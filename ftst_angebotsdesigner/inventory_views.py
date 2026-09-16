"""Internal pilot inventory and operations screens. No supplier/calendar writes."""
import csv
import io
import json
import secrets
import uuid
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from flask import abort, redirect, request, session, Response
from materials import account
from inventory import InventoryError, execute, load, fmt, reserved, open_need, procurement
from operations_planning import suggestions
from quote_drafts import fingerprint, calculate
from storage import RecordConflict


def register(app, base, ingress, escape, get_store):
    def fields(state):
        if 'inventory_csrf' not in session:
            session['inventory_csrf'] = secrets.token_urlsafe(32)
        return (f'<input type="hidden" name="csrf" value="{escape(session["inventory_csrf"])}">'
                f'<input type="hidden" name="revision" value="{state["revision"]}">'
                f'<input type="hidden" name="operation" value="{uuid.uuid4().hex}">')

    def protect():
        if not secrets.compare_digest(request.form.get('csrf', ''), session.get('inventory_csrf', '-') or '-'):
            abort(400, 'Formular abgelaufen. Bitte die Seite neu laden.')

    def page(title, body, status=200):
        return base(title, f'<div class="back"><a href="{ingress("inventory")}">Lager</a> · <a href="{ingress("projects")}">Projekte</a></div>{body}'), status

    def error(exc, status=400):
        return page('Eingaben prüfen', f'<div class="card"><h1>Eingaben prüfen</h1><p>{escape(exc)}</p><p>Es wurde nichts gebucht. Über Zurück bleiben Ihre Eingaben erreichbar.</p></div>', status)

    def catalog(store):
        shared = store.record(account(), 'catalog', 'shared') or {}
        result = {str(a['id']): a for a in shared.get('data', {}).get('articles', [])}
        for draft in store.records(account(), 'quote').values():
            for article in draft.get('catalog', {}).get('articles', []):
                result.setdefault(str(article['id']), article)
        return result

    def actor_field():
        return '<label>Erfasst von (Name)<input name="actor" required maxlength="100"></label>'

    def run(action, payload, verify=None):
        return execute(get_store(), account(), action, payload, request.form.get('operation'),
                       request.form.get('actor'), request.form.get('revision'), verify)

    def csv_response(filename, rows):
        out = io.StringIO()
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r')) else value
        writer = csv.writer(out, delimiter=';')
        for row in rows:
            writer.writerow([safe(v) for v in row])
        return Response('\ufeff' + out.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})

    @app.route('/inventory', methods=['GET', 'POST'])
    def inventory_home():
        store = get_store()
        state = load(store, account())
        if request.method == 'POST':
            protect()
            try:
                action = request.form.get('action')
                if action == 'article':
                    aid = request.form.get('article', '')
                    article = catalog(store).get(aid)
                    if not article:
                        raise InventoryError('Artikel muss aus einem gespeicherten Billomat-Katalog stammen.')
                    payload = dict(id=aid, title=article.get('title'), unit=request.form.get('unit'))
                elif action == 'reverse':
                    payload = dict(event=request.form.get('event'), note=request.form.get('note'))
                elif action in ('opening', 'receive', 'issue', 'return', 'count'):
                    payload = {k: request.form.get(k, '').strip() for k in ('article', 'quantity', 'order', 'note', 'usable')}
                else:
                    raise InventoryError('Unbekannte Lageraktion.')
                run(action, payload)
            except RecordConflict as exc:
                return error(exc, 409)
            except InventoryError as exc:
                return error(exc)
            return redirect(ingress('inventory') + '?saved=1')
        query = request.args.get('q', '').strip()[:100]
        visible_articles = {k: a for k, a in state['articles'].items() if query.casefold() in (a['title'] + ' ' + k).casefold()}
        saved = '<p class="success">Buchung dauerhaft gespeichert.</p>' if request.args.get('saved') else ''
        rows = ''.join(f'<tr><td>{escape(a["title"])}<br><small>Billomat-ID {escape(aid)}</small></td><td>{a["unit"]}</td><td>{fmt(a["stock"]) if a["known"] else "Noch nicht gezählt"}</td><td>{fmt(reserved(state, aid))}</td><td>{fmt(a["stock"]-reserved(state, aid)) if a["known"] else "Unbekannt"}</td></tr>' for aid, a in visible_articles.items())
        article_options = ''.join(f'<option value="{escape(aid)}">{escape(a["title"])} ({a["unit"]})</option>' for aid, a in state['articles'].items())
        catalog_options = ''.join(f'<option value="{escape(aid)}">{escape(a.get("title"))} · {escape(a.get("article_number") or aid)}</option>' for aid, a in catalog(store).items() if aid not in state['articles'])
        orders = ''.join(f'<option value="{escape(oid)}">{escape(o["title"])}{" (storniert, nur Rückgabe)" if not o["active"] else ""}</option>' for oid, o in state['orders'].items())
        labels = dict(article='Artikel aufgenommen', order='Auftrag erfasst', opening='Anfangszählung', receive='Wareneingang', issue='Entnahme', return_='Rückgabe', count='Zählkorrektur', reserve='Reservierung', release='Reservierung freigegeben', cancel='Auftrag storniert', need='Bedarf geändert', reverse='Gegenbuchung', purchase='Externe Bestellung erfasst', purchase_cancel='Externe Reststornierung erfasst')
        labels['return'] = labels.pop('return_')
        def event_details(event):
            p = event['payload']
            aid = p.get('article', p.get('id', ''))
            title = state['articles'].get(aid, {}).get('title', p.get('title', ''))
            details = [title]
            if 'quantity' in p:
                details.append('Menge: ' + str(p['quantity']) + ' ' + state['articles'].get(aid, {}).get('unit', ''))
            oid = p.get('order')
            if oid:
                details.append('Auftrag: ' + state['orders'].get(oid, {}).get('title', oid))
            if p.get('lines'):
                details.extend(str(r['quantity']) + ' × ' + state['articles'].get(str(r['article_id']), {}).get('title', str(r['article_id'])) for r in p['lines'])
            if p.get('event'):
                details.append('Gegenbuchung zu ' + p['event'])
            if p.get('purchase'):
                purchase = state['purchases'].get(p['purchase'], {})
                details.append('Bestellung: ' + str(purchase.get('reference', p['purchase'])))
            details.extend(str(p[k]) for k in ('supplier', 'reference', 'delivery', 'note') if p.get(k))
            return '<br>'.join(escape(d) for d in details if d)
        history = ''.join(f'<tr><td>{datetime.fromisoformat(e["at"]).astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")}<br><small>Vorgang {escape(e["id"])}</small></td><td>{escape(e["actor"])}</td><td>{escape(labels.get(e["action"], e["action"]))}</td><td>{event_details(e)}</td></tr>' for e in reversed(state['events'][-100:]))
        actions = ''.join(f'<option value="{key}">{label}</option>' for key, label in [('opening','Anfangsbestand gezählt'),('receive','Ware erhalten'),('issue','Für Auftrag entnehmen'),('return','Verwendbare Ware zurückgeben'),('count','Gezählten Bestand korrigieren')])
        order_links = ''.join(f'<p><a href="{ingress("projects/"+oid+"/operations")}">{escape(o["title"])}</a> · {"beauftragt" if o["active"] else "storniert"}</p>' for oid, o in state['orders'].items())
        return page('Lager', f'''<div class="card"><div class="eyebrow">Hauptlager · Pilot</div><h1>Material im Blick</h1>{saved}<form method="get"><label>Artikel suchen<input name="q" value="{escape(query)}" placeholder="Bezeichnung oder Artikel-ID"></label><button class="btn light">Suchen</button></form><p>Erst zählen, dann buchen. Ungezählte Artikel haben keinen bestätigten Bestand. Reservierte Mengen gehören bereits zu einem Auftrag.</p><table><tr><th>Artikel</th><th>Einheit</th><th>Vorhanden</th><th>Reserviert</th><th>Frei</th></tr>{rows}</table></div>
<div class="grid"><div class="card"><h2>Lagerbuchung</h2><form method="post">{fields(state)}<label>Aktion<select name="action">{actions}</select></label><label>Artikel<select name="article" required>{article_options}</select></label><label>Menge / neuer Zählbestand<input name="quantity" inputmode="decimal" required></label><label>Auftrag (bei Entnahme/Rückgabe)<select name="order"><option value="">Bitte auswählen</option>{orders}</select></label><label>Beleg / Begründung<input name="note" maxlength="300"></label><label>Rückgabe geprüft und verwendbar?<select name="usable"><option value="">Keine Rückgabe</option><option value="yes">Ja, geprüft und verwendbar</option></select></label>{actor_field()}<p>Eine Zählkorrektur benötigt eine Begründung. Defekte Ware hier nicht als verfügbar buchen.</p><button class="btn">Buchung bestätigen</button></form></div>
<div class="card"><h2>Artikel aufnehmen</h2><p>Aus dem geladenen Billomat-Katalog. <a href="{ingress("billomat")}">Artikel und Kunden aus Billomat laden</a>. Nur tatsächlich lagerfähiges Material auswählen; Dienstleistungen auslassen.</p><form method="post">{fields(state)}<input type="hidden" name="action" value="article"><label>Billomat-Artikel<select name="article" required>{catalog_options}</select></label><label>Lagereinheit verbindlich zuordnen<select name="unit"><option value="Stück">Stück (ganze Mengen)</option><option value="m">Meter (bis 3 Nachkommastellen)</option></select></label>{actor_field()}<button class="btn light">Mit unbekanntem Bestand aufnehmen</button></form></div></div>
<div class="card"><h2>Aufträge & Materialplanung</h2>{order_links or '<p>Noch keine beauftragten Projekte. In einem geprüften Projekt die Materialplanung öffnen.</p>'}</div>
<div class="card"><h2>Fehlbuchung korrigieren</h2><p>Eingang, Entnahme oder Rückgabe durch eine nachvollziehbare Gegenbuchung aufheben. Die ursprüngliche Buchung bleibt erhalten. Reservierungen werden dabei nicht automatisch wiederhergestellt.</p><form method="post">{fields(state)}<input type="hidden" name="action" value="reverse"><label>Vorgangs-ID aus dem Journal<input name="event" required></label><label>Begründung<input name="note" required maxlength="300"></label>{actor_field()}<button class="btn light">Gegenbuchung bestätigen</button></form></div><div class="card"><h2>Buchungsjournal</h2><p>Letzte 100 Vorgänge · Namen werden vom Buchenden eingetragen.</p><a class="btn light" href="{ingress('inventory/journal.csv')}">Vollständiges Journal als CSV</a><table><tr><th>Zeit (Berlin)</th><th>Erfasst von</th><th>Aktion</th><th>Details</th></tr>{history}</table></div>''')

    @app.get('/inventory/journal.csv')
    def inventory_journal():
        events = load(get_store(), account())['events']
        return csv_response('FTST-Lagerjournal.csv', [['Vorgang', 'Zeit UTC', 'Erfasst von', 'Aktion', 'Details']] + [[e['id'], e['at'], e['actor'], e['action'], json.dumps(e['payload'], ensure_ascii=False)] for e in events])

    @app.route('/projects/<key>/operations', methods=['GET', 'POST'])
    def operations(key):
        store = get_store()
        identity = account()
        project = store.record(identity, 'project', key)
        if project is None:
            abort(404)
        state = load(store, identity)
        draft = store.record(identity, 'quote', key)
        order = state['orders'].get(key)
        plan = None
        if request.method == 'POST':
            protect()
            try:
                action = request.form.get('action')
                if action == 'order':
                    if not draft or request.form.get('quote_revision') != draft.get('revision') or not draft.get('reviewed') or draft.get('source') != fingerprint(project) or calculate(draft).get('total') is None:
                        raise RecordConflict('Zuerst aktuellen Angebotsentwurf vollständig prüfen und speichern.')
                    if request.form.get('confirmed') != 'yes':
                        raise InventoryError('Tatsächliche Beauftragung bestätigen.')
                    selected = set(request.form.getlist('material'))
                    lines = [r for i, r in enumerate(draft['rows']) if str(i) in selected]
                    payload = dict(id=key, title=project['title'], reference=request.form.get('reference'),
                                   quote_revision=draft['revision'], lines=lines)
                    def verify(db):
                        for kind, expected in [('quote', draft), ('project', project)]:
                            row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?', (identity, kind, key)).fetchone()
                            if not row or json.loads(row[0]) != expected:
                                raise RecordConflict('Projekt oder Entwurf wurde geändert. Bitte neu laden.')
                    run(action, payload, verify)
                elif action in ('reserve', 'release', 'cancel', 'need'):
                    run(action, dict(order=key, article=request.form.get('article'), quantity=request.form.get('quantity'), note=request.form.get('note')))
                elif action == 'purchase':
                    payload = {k: request.form.get(k, '').strip() for k in ('article', 'quantity', 'supplier', 'reference', 'delivery', 'confirmed', 'ordered', 'note')}
                    payload.update(id=request.form.get('operation'), order=key)
                    run(action, payload)
                elif action in ('purchase_receive', 'purchase_cancel'):
                    pid = request.form.get('purchase', '')
                    purchase = state['purchases'].get(pid)
                    if not purchase or purchase['order'] != key:
                        raise InventoryError('Bestellung gehört nicht zu diesem Auftrag.')
                    payload = dict(purchase=pid, note=request.form.get('note', ''), confirmed=request.form.get('confirmed'))
                    if action == 'purchase_receive':
                        payload.update(article=purchase['article'], quantity=request.form.get('quantity'), order=key)
                    run('receive' if action == 'purchase_receive' else 'purchase_cancel', payload)
                elif action == 'plan':
                    if not order:
                        raise InventoryError('Zuerst Beauftragung dokumentieren.')
                    if str(state['revision']) != request.form.get('revision'):
                        raise RecordConflict('Lagerstand hat sich geändert. Bitte neu prüfen.')
                    plan = suggestions(state, key, request.form.get('availability', ''), request.form.get('minutes'),
                                       request.form.get('crew'), request.form.get('skills', ''),
                                       request.form.get('buffer'), request.form.get('checked_at'))
                else:
                    raise InventoryError('Unbekannte Aktion.')
            except RecordConflict as exc:
                return error(exc, 409)
            except InventoryError as exc:
                return error(exc)
            if plan is None:
                return redirect(ingress('projects/'+key+'/operations') + '?saved=1')
        title = f'<div class="card"><h1>Materialplanung · {escape(project["title"])}</h1><p>Interne Planung. Billomat bleibt für Angebote/Rechnungen zuständig; Craftnote und Google Kalender werden hier nicht verändert.</p></div>'
        if not order:
            if not draft:
                return page('Materialplanung', title + f'<div class="card"><a class="btn" href="{ingress("projects/"+key+"/quote")}">Angebotsentwurf vorbereiten</a></div>')
            materials = ''.join(f'<label><input style="width:auto" type="checkbox" name="material" value="{i}"> {escape(r.get("quantity"))} × {escape(r.get("description"))} · Artikel {escape(r.get("article_id"))}</label>' for i, r in enumerate(draft.get('rows', [])))
            return page('Beauftragung', title + f'<div class="card"><h2>Beauftragung dokumentieren</h2><p>Nur tatsächlich beauftragte Materialpositionen markieren. Vorher deren Billomat-Artikel im Lager aufnehmen. Dienstleistungen nicht reservieren.</p><form method="post">{fields(state)}<input type="hidden" name="action" value="order"><input type="hidden" name="quote_revision" value="{escape(draft.get("revision"))}">{materials}<label>Auftragsnachweis / Billomat- oder Craftnote-Referenz<input name="reference" required maxlength="300"></label>{actor_field()}<label><input type="checkbox" style="width:auto" name="confirmed" value="yes" required> Beauftragung liegt vor; Materialauswahl und Lagereinheiten stimmen mit dem geprüften Entwurf überein.</label><button class="btn">Auftrag erfassen und verfügbares Material reservieren</button></form></div>')
        rows = ''.join(f'<tr><td>{escape(state["articles"][aid]["title"])} ({state["articles"][aid]["unit"]})</td><td>{fmt(n)}</td><td>{fmt(order["issued"].get(aid,0))}</td><td>{fmt(order["reserved"].get(aid,0))}</td><td>{fmt(max(0,open_need(order,aid)-order["reserved"].get(aid,0)))}</td></tr>' for aid, n in order['needs'].items())
        missing = procurement(state, key)
        missing_rows = ''.join(f'<tr><td>{escape(r["title"])}</td><td>{fmt(r["quantity"])} {r["unit"]}</td><td>{fmt(r["incoming"])}</td><td>{fmt(r["to_buy"])}</td><td>{r["status"]}</td></tr>' for r in missing)
        options = ''.join(f'<option value="{escape(aid)}">{escape(a["title"])}</option>' for aid, a in state['articles'].items())
        controls = ''
        if order['active']:
            controls = f'''<form method="post">{fields(state)}{actor_field()}<button class="btn" name="action" value="reserve">Freies Material erneut zuordnen</button><button class="btn light" name="action" value="cancel">Auftrag stornieren und Reservierungen freigeben</button></form>
<details><summary>Reservierungen freigeben</summary><form method="post">{fields(state)}<input type="hidden" name="action" value="release"><label>Begründung<input name="note" required maxlength="300"></label>{actor_field()}<button class="btn light">Alle offenen Reservierungen dieses Auftrags freigeben</button></form></details><details><summary>Materialbedarf begründet ändern</summary><form method="post">{fields(state)}<input name="action" type="hidden" value="need"><label>Artikel<select name="article">{options}</select></label><label>Gesamter neuer Bedarf<input name="quantity" inputmode="decimal" required></label><label>Begründung<input name="note" required maxlength="300"></label>{actor_field()}<button class="btn light">Bedarf ändern</button></form></details>'''
        result = ''
        def show_time(value):
            return datetime.fromisoformat(value).strftime('%d.%m.%Y %H:%M')
        if plan:
            result = '<div class="card"><h2>Interne Terminvorschläge</h2><p>' + escape(plan['reason']) + '</p>' + ''.join(f'<p>{show_time(s["start"])} bis {show_time(s["end"])} (Berlin) · {escape(", ".join(s["team"]))}</p>' for s in plan['slots']) + '</div>'
        if request.args.get('saved'):
            title += '<p class="success">Auftragsänderung dauerhaft gespeichert.</p>'
        if not missing and order['active']:
            missing_rows = '<tr><td colspan="5">Materialbedarf durch Reservierungen und Entnahmen gedeckt.</td></tr>'
        return page('Materialplanung', title + f'''<div class="card"><h2>{'Beauftragtes Material' if order['active'] else 'Stornierter Auftrag'}</h2><p>Nachweis: {escape(order['reference'])} · Angebotsstand {escape(order['quote_revision'])}</p><table><tr><th>Artikel</th><th>Bedarf</th><th>Netto entnommen</th><th>Reserviert</th><th>Offen</th></tr>{rows}</table>{controls}</div>
<div class="card"><h2>Einkauf vorbereiten</h2><p>Unbestellter Vorschlag. Erfasste offene Bestellungen sind berücksichtigt. Lieferant, Preis und weitere extern bestellte Mengen vor einer neuen Bestellung abgleichen. Unbekannter Bestand bedeutet zuerst zählen. Bestellte Ware ist erst nach Wareneingang verfügbar.</p><table><tr><th>Artikel</th><th>Physisch ungedeckt</th><th>Offen bestellt</th><th>Noch zu beschaffen</th><th>Nächster Schritt</th></tr>{missing_rows}</table><a class="btn light" href="{ingress('projects/'+key+'/procurement.csv')}">Prüfliste als CSV</a></div>{purchase_section(state, key)}
{result}<div class="card"><h2>Vorläufige Termine ermitteln</h2><p>Freie Zeiten jedes Mitarbeiters nach Kalenderprüfung eintragen. Alle benötigten Personen müssen gleichzeitig verfügbar und für die angegebenen Fähigkeiten geeignet sein. Fahrt-/Rüstpuffer ist in der Gesamtbelegung enthalten. Keine Kalenderanbindung oder Buchung.</p><form method="post">{fields(state)}<input type="hidden" name="action" value="plan"><div class="grid"><label>Montagedauer (Minuten)<input name="minutes" type="number" min="1" max="720" required></label><label>Teamgröße<input name="crew" type="number" min="1" max="3" required></label><label>Fahrt und Rüsten insgesamt (Minuten)<input name="buffer" type="number" min="0" max="240" required></label></div><label>Benötigte Fähigkeiten (kommagetrennt)<input name="skills" required></label><label>Kalender zuletzt geprüft (Europe/Berlin)<input name="checked_at" type="datetime-local" required></label><label>Freie Zeitfenster, eine Zeile je Person und Zeitraum<textarea name="availability" placeholder="Name; Fähigkeiten; JJJJ-MM-TTTHH:MM; JJJJ-MM-TTTHH:MM" required></textarea></label><button class="btn">Interne Vorschläge prüfen</button></form></div>''')

    @app.get('/projects/<key>/procurement.csv')
    def procurement_export(key):
        state = load(get_store(), account())
        if key not in state['orders']:
            abort(404)
        rows = [['Status', 'Auftrag', 'Artikel-ID', 'Artikel', 'Physisch ungedeckt', 'Einheit', 'Bestandsprüfung', 'Offen bestellt', 'Noch zu beschaffen', 'Lieferant', 'Einkaufspreis', 'Weitere externe Bestellungen', 'Stand UTC']]
        now = datetime.now(timezone.utc).isoformat()
        for r in procurement(state, key):
            rows.append(['Unbestellter Prüfvorschlag', state['orders'][key]['title'], r['article'], r['title'], fmt(r['quantity']), r['unit'], r['status'], fmt(r['incoming']), fmt(r['to_buy']), 'Prüfen', 'Offen', 'Manuell abgleichen', now])
        return csv_response('FTST-Einkaufspruefliste.csv', rows)

    def purchase_section(state, key):
        order = state['orders'][key]
        cards = ''
        for pid, purchase in state['purchases'].items():
            if purchase['order'] != key:
                continue
            a = state['articles'][purchase['article']]
            remaining = purchase['quantity'] - purchase['received'] - purchase['cancelled']
            delivery = escape(purchase['delivery']) or 'Unbekannt'
            delivery += ' · Lieferant bestätigt' if purchase['confirmed'] and purchase['delivery'] else ' · keine bestätigte Zusage'
            warning = '<p class="success">Auftrag storniert: Diese Bestellung ist weiterhin extern zu prüfen.</p>' if remaining and not order['active'] else ''
            if remaining and purchase['delivery'] and purchase['delivery'] < datetime.now(ZoneInfo('Europe/Berlin')).date().isoformat():
                warning += '<p><strong>Lieferdatum überschritten:</strong> Offene Lieferung beim Lieferanten prüfen.</p>'
            if remaining > max(0, open_need(order, purchase['article']) - order['reserved'].get(purchase['article'], 0)):
                warning += '<p><strong>Bedarf prüfen:</strong> Die offene Bestellmenge übersteigt den noch ungedeckten Auftragsbedarf.</p>'
            receive = ''
            if remaining:
                receive = f'''<form method="post">{fields(state)}<input type="hidden" name="action" value="purchase_receive"><input type="hidden" name="purchase" value="{escape(pid)}"><label>Tatsächlich geprüfte Liefermenge ({a['unit']})<input name="quantity" required inputmode="decimal"></label><label>Lieferschein / Notiz<input name="note" maxlength="300"></label>{actor_field()}<button class="btn">Wareneingang buchen</button></form>
<details><summary>Extern bestätigte Reststornierung erfassen</summary><form method="post">{fields(state)}<input type="hidden" name="action" value="purchase_cancel"><input type="hidden" name="purchase" value="{escape(pid)}"><label>Stornonachweis<input name="note" required maxlength="300"></label>{actor_field()}<label><input style="width:auto" type="checkbox" name="confirmed" value="yes" required> Lieferant hat die Stornierung der offenen Restmenge bestätigt.</label><button class="btn light">Bestätigte Reststornierung dokumentieren</button></form></details>'''
            cards += f'''<div class="card"><h3>{escape(a['title'])} · {escape(purchase['supplier'])}</h3><p>Bestellnachweis: {escape(purchase['reference'])}</p><p>Bestellt: {fmt(purchase['quantity'])} · Eingegangen: {fmt(purchase['received'])} · Storniert: {fmt(purchase['cancelled'])} · Noch offen: <strong>{fmt(remaining)} {a['unit']}</strong></p><p>Lieferdatum: {delivery}</p>{warning}{receive}</div>'''
        if order['active']:
            options = ''.join(f'<option value="{escape(aid)}">{escape(state["articles"][aid]["title"])} ({state["articles"][aid]["unit"]})</option>' for aid, n in order['needs'].items() if n)
            cards += f'''<div class="card"><h2>Bestehende Bestellung erfassen</h2><p>Eine bereits außerhalb der App aufgegebene Bestellung dokumentieren. Dieses Formular sendet keine Bestellung an einen Lieferanten.</p><form method="post">{fields(state)}<input type="hidden" name="action" value="purchase"><label>Artikel<select name="article">{options}</select></label><label>Bestellte Menge<input name="quantity" required inputmode="decimal"></label><label>Lieferant<input name="supplier" required maxlength="300"></label><label>Eindeutige Bestellnummer / Teilposition<input name="reference" required maxlength="300"></label><label>Lieferdatum, falls bekannt<input type="date" name="delivery"></label><label><input type="checkbox" style="width:auto" name="confirmed" value="yes"> Lieferdatum vom Lieferanten bestätigt</label><label>Notiz<input name="note" maxlength="300"></label>{actor_field()}<label><input type="checkbox" style="width:auto" name="ordered" value="yes" required> Diese Menge wurde tatsächlich extern bestellt und hier noch nicht erfasst.</label><button class="btn light">Bestehende Bestellung dokumentieren</button></form></div>'''
        return cards
