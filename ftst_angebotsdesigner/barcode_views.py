"""Barcode selection never books. Confirmed issues use the existing ledger."""
from flask import abort, jsonify, redirect, request

from inventory import InventoryError, fmt, load, open_need, quantity, reserved
from inventory_barcodes import code_value, issue_payload, resolve
from materials import account
from storage import RecordConflict


def register(app, ingress, escape, get_store, fields, protect, page, error, actor_field, run):
    def outcome(state, event):
        payload = event['payload']
        article = state['articles'][payload['article']]
        return dict(found=True, operation=event['id'], article=article['title'], order=payload['order'],
                    quantity=fmt(quantity(payload['quantity'], article['unit'])), unit=article['unit'],
                    stock=fmt(article['stock']), warehouse='Hauptlager')

    @app.get('/inventory/scan/operations/<operation>')
    def barcode_operation(operation):
        state = load(get_store(), account())
        event = next((e for e in state['events'] if e['id'] == operation and e['action'] == 'issue'
                      and 'barcode' in e['payload']), None)
        result = outcome(state, event) if event else dict(found=False, operation=operation)
        if request.accept_mimetypes.best == 'application/json':
            response = jsonify(result)
            response.headers['Cache-Control'] = 'no-store'
            return response
        message = (f'Bestätigt: {escape(result["quantity"])} {escape(result["unit"])} {escape(result["article"])} entnommen. Aktueller Bestand: {escape(result["stock"])}.'
                   if event else 'Noch keine bestätigte Buchung für diesen Vorgang gefunden. Bei unklarer Übertragung nur denselben Vorgang erneut senden, keine neue Entnahme anlegen.')
        return page('Buchungsstatus', f'<div class="card"><h1>Buchungsstatus</h1><p>{message}</p><p>Vorgang {escape(operation)}</p><a href="{ingress("inventory/scan")}">Zur Scanansicht</a></div>')

    @app.route('/inventory/barcodes', methods=['GET', 'POST'])
    def barcode_mappings():
        state = load(get_store(), account())
        if request.method == 'POST':
            protect()
            try:
                action = request.form.get('action')
                if action not in ('barcode_assign', 'barcode_remove'):
                    raise InventoryError('Unbekannte Barcodeaktion.')
                payload = {k: request.form.get(k, '') for k in ('code', 'article', 'kind', 'factor', 'confirmed', 'note')}
                run(action, payload)
            except RecordConflict as exc:
                return error(exc, 409)
            except InventoryError as exc:
                return error(exc)
            return redirect(ingress('inventory/barcodes') + '?saved=1')
        opts = ''.join(f'<option value="{escape(aid)}">{escape(a["title"])} · {escape(aid)} · {a["unit"]}</option>' for aid, a in state['articles'].items())
        rows = ''.join(f'<details><summary>{escape(m["code"])} → {escape(state["articles"][m["article"]]["title"])} · {fmt(m["factor"])} {state["articles"][m["article"]]["unit"]} je {"Packung" if m["kind"] == "pack" else "Einheit"}</summary><form method="post">{fields(state)}<input type="hidden" name="action" value="barcode_remove"><input type="hidden" name="code" value="{escape(m["code"])}"><label>Grund<input name="note" required maxlength="300"></label>{actor_field()}<button class="btn light">Zuordnung aufheben</button></form></details>' for m in state['barcodes'].values())
        return page('Barcodes', f'''<div class="card"><h1>Produktbarcodes zuordnen</h1><p>Keine Lagerbuchung. Ein Code gehört eindeutig zu einem Lagerartikel. Billomat-Artikelnummern werden nicht automatisch als Herstellerbarcode behandelt.</p>
<p>Keine individuellen Seriennummern, SSCC, GS1-Verbundcodes oder QR-Links. Ein einfacher Code allein verrät seinen Zweck nicht: Etikett und Verpackungsinhalt selbst prüfen.</p>
<form method="post">{fields(state)}<input type="hidden" name="action" value="barcode_assign"><label>Code (führende Nullen behalten)<input name="code" maxlength="100" required value="{escape(request.args.get('code', '')[:100])}" autocomplete="off" autocapitalize="off"></label>
<label>Lagerartikel<select name="article" required><option value="">Auswählen</option>{opts}</select></label><label>Code gehört zu<select name="kind"><option value="single">Einzelartikel / eine Lagereinheit</option><option value="pack">Verpackung</option></select></label>
<label>Lagereinheiten je Code / Verpackung<input name="factor" value="1" inputmode="decimal" required></label>{actor_field()}<label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required> Produktcode, Artikel, Lagereinheit und Verpackungsinhalt geprüft; keine individuelle Seriennummer.</label><button class="btn">Zuordnung bestätigen</button></form></div><div class="card"><h2>Bestehende Zuordnungen</h2>{rows or '<p>Noch keine Zuordnungen.</p>'}<a href="{ingress('inventory/scan')}">Zur Scanansicht</a></div>''')

    @app.route('/inventory/scan', methods=['GET', 'POST'])
    def barcode_scan():
        state = load(get_store(), account())
        if request.method == 'POST':
            protect()
            try:
                if request.form.get('confirmed') != 'yes':
                    raise InventoryError('Entnahme ausdrücklich bestätigen.')
                # A lost-response retry must still work after a later mapping change.
                event = next((e for e in state['events'] if e['id'] == request.form.get('operation')), None)
                if event:
                    p = event['payload']
                    same = (event['action'] == 'issue' and p.get('barcode') == code_value(request.form.get('code'))
                            and p.get('order') == request.form.get('order')
                            and str(p.get('mapping_revision')) == request.form.get('mapping_revision')
                            and p.get('scan_quantity') == request.form.get('scan_quantity', '').strip()
                            and p.get('note') == request.form.get('note', '')[:300]
                            and event['actor'] == request.form.get('actor', '').strip())
                    if not same:
                        raise RecordConflict('Vorgangs-ID bereits für andere Eingaben benutzt.')
                    payload = p
                else:
                    payload = issue_payload(state, request.form)
                updated = run('issue', payload)
                event = next(e for e in updated['events'] if e['id'] == request.form['operation'])
                if request.accept_mimetypes.best == 'application/json':
                    return jsonify(outcome(updated, event))
                return redirect(ingress('inventory/scan/operations/' + event['id']))
            except (RecordConflict, InventoryError) as exc:
                # A conflicting operation may already have committed, including in a
                # concurrent request after our initial read. Never claim it did not.
                recorded = any(e['id'] == request.form.get('operation')
                               for e in load(get_store(), account())['events'])
                if request.accept_mimetypes.best == 'application/json':
                    return jsonify(error=str(exc), rejected=not recorded, already_recorded=recorded), 409 if isinstance(exc, RecordConflict) else 400
                if recorded:
                    return page('Vorgang prüfen', f'<div class="card"><h1>Vorgangs-ID bereits gebucht</h1><p>{escape(exc)}</p><p>Originalbuchung im Lagerjournal prüfen. Keine neue Entnahme anlegen.</p></div>', 409)
                return error(exc, 409 if isinstance(exc, RecordConflict) else 400)
        oid = request.args.get('order', '')
        raw = request.args.get('code', '')
        orders = ''.join(f'<option value="{escape(key)}" {"selected" if key == oid else ""}>{escape(o["title"])}</option>' for key, o in state['orders'].items() if o['active'])
        selection = ''
        if raw:
            try:
                mapping = resolve(state, raw)
                order = state['orders'].get(oid)
                if not order or not order['active']:
                    raise InventoryError('Zuerst einen aktiven Auftrag auswählen.')
                article = state['articles'][mapping['article']]
                available = fmt(max(0, article['stock'] - reserved(state, mapping['article'], oid))) if article['known'] else 'Unbekannt – zuerst zählen'
                unit = 'Packungen (ganze Anzahl)' if mapping['kind'] == 'pack' else article['unit']
                selection = f'''<div class="card" id="barcode-selection"><h2>{escape(article['title'])}</h2><p>Auftrag: {escape(order['title'])} · Hauptlager</p><p>Für diesen Auftrag verfügbar (einschließlich eigener Reservierung): {available} {article['unit']} · offener Bedarf: {fmt(open_need(order, mapping['article']))} {article['unit']}</p><p>Code {escape(mapping['code'])}: {fmt(mapping['factor'])} {article['unit']} je {"Packung" if mapping['kind'] == "pack" else "Lagereinheit"}.</p>
<form method="post" id="barcode-issue" data-factor="{mapping['factor']}" data-unit="{article['unit']}">{fields(state)}<input type="hidden" name="code" value="{escape(mapping['code'])}"><input type="hidden" name="mapping_revision" value="{mapping['revision']}"><input type="hidden" name="order" value="{escape(oid)}"><label>Menge in {unit}<input name="scan_quantity" inputmode="decimal" required autocomplete="off"></label><p id="barcode-total" aria-live="polite">Menge eingeben; der Scan allein bucht nichts.</p><label>Beleg / Notiz<input name="note" maxlength="300"></label>{actor_field()}<label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required> Artikel, Auftrag, Menge und Verpackungsinhalt geprüft. Aus dem Hauptlager entnehmen.</label><button class="btn">Entnahme bestätigen</button></form></div>'''
            except InventoryError as exc:
                selection = f'<div class="card"><p role="alert">{escape(exc)}</p><a href="{ingress("inventory/barcodes")}">Produktzuordnung prüfen</a></div>'
        return page('Für Auftrag scannen', f'''<style>#barcode-screen [hidden]{{display:none!important}}#barcode-screen{{overflow-wrap:anywhere}}#barcode-screen button{{max-width:100%;white-space:normal}}</style><div id="barcode-screen" data-status-base="{ingress('inventory/scan/operations/')}" data-storage-key="ftst-barcode-{escape(account())}"><div class="card"><h1>Für Auftrag scannen</h1><p>Hauptlager · Scan wählt nur den Artikel. Keine Fahrzeugumbuchung.</p><div id="barcode-pending" hidden role="status"></div><form method="get" id="barcode-lookup"><label>Aktiver Auftrag<select name="order" required><option value="">Auftrag auswählen</option>{orders}</select></label><label>Barcode / Scannereingabe<input name="code" required maxlength="100" value="{escape(raw)}" autocomplete="off" autocapitalize="off" spellcheck="false"></label><button class="btn light">Artikel anzeigen</button><button class="btn light" type="button" id="barcode-start">Kamera starten / nächsten Code scannen</button><button class="btn light" style="min-height:44px" type="button" id="barcode-stop" hidden>Kamera stoppen</button></form><video id="barcode-video" playsinline muted hidden style="width:100%;max-width:480px"></video><p id="barcode-camera-status" role="status">Kamera startet erst nach Klick. Kameraaufnahmen bleiben auf diesem Gerät. Alternativ Hardware-Scanner oder Code eintippen.</p><a href="{ingress('inventory/barcodes')}">Barcodes zuordnen</a></div>{selection}</div><script defer src="{ingress('static/vendor/zxing-browser-0.2.1.min.js')}"></script><script defer src="{ingress('static/barcode-scan.js')}"></script>''')
