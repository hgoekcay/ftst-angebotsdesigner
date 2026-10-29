"""Read-only Billomat documents and explicit device sharing, never issue/send."""
import io
import json
import re
import time

import requests
from flask import abort, request, send_file

from billomat_receipts import _configuration, ReceiptCheckError

KINDS = {
    'invoices': ('invoice', 'Rechnung', 'Rechnungen', 'invoice_number', {'OPEN', 'OVERDUE', 'PAID'}),
    'delivery-notes': ('delivery-note', 'Lieferschein', 'Lieferscheine', 'delivery_note_number', {'CREATED'}),
}
STATUS_LABELS = {'OPEN': 'Offen', 'OVERDUE': 'Überfällig', 'PAID': 'Bezahlt', 'CREATED': 'Erstellt'}


class DocumentError(RuntimeError):
    pass


def read(path, params=None, pdf=False):
    """Fixed callers only. Credentials stay on the configured Billomat host."""
    try:
        base, headers = _configuration()
        headers['Accept'] = 'application/pdf' if pdf else 'application/json'
        started = time.monotonic()
        limit = 15 * 1024 * 1024 if pdf else 2 * 1024 * 1024
        with requests.Session() as http:
            http.trust_env = False
            with http.get(base + '/' + path, headers=headers,
                          params=dict(params or {}, format='pdf' if pdf else 'json'),
                          timeout=(5, 25), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise DocumentError('Billomat-Dokument nicht verfügbar. Zugang, Berechtigung und Dokumentstatus prüfen.')
                data = bytearray()
                for chunk in response.iter_content(65536):
                    if len(data) + len(chunk) > limit or time.monotonic() - started > 45:
                        raise DocumentError('Dokument ist zu groß oder der Abruf dauert zu lange.')
                    data.extend(chunk)
                if pdf:
                    if not data.startswith(b'%PDF-') or 'application/pdf' not in response.headers.get('Content-Type', '').lower():
                        raise DocumentError('Billomat hat keine gültige PDF geliefert.')
                    return bytes(data)
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
    except (requests.RequestException, ValueError, ReceiptCheckError):
        raise DocumentError('Billomat konnte nicht gelesen werden. Verbindung und Konfiguration prüfen.') from None


def document(kind, oid):
    if kind not in KINDS or not re.fullmatch(r'[1-9][0-9]{0,19}', oid):
        abort(404)
    row = read(kind + '/' + oid).get(KINDS[kind][0])
    if not isinstance(row, dict) or str(row.get('id')) != oid:
        raise DocumentError('Dokument konnte nicht eindeutig zugeordnet werden.')
    return row


def register(app, base, ingress, escape):
    @app.after_request
    def document_private(response):
        if request.path == '/documents' or request.path.startswith('/documents/'):
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(DocumentError)
    def document_error(error):
        return base('Dokument nicht verfügbar', '<section class="card"><h1>Dokument nicht verfügbar</h1><p>'
                    + escape(str(error)) + '</p><a class="btn" href="' + ingress('documents')
                    + '">Zur Dokumentübersicht</a></section>'), 502

    @app.get('/documents')
    def documents():
        kind = request.args.get('kind', 'invoices')
        if kind not in KINDS:
            abort(400)
        page = request.args.get('page', '1')
        if not re.fullmatch(r'[1-9][0-9]{0,4}', page):
            abort(400)
        singular, title, plural, number, statuses = KINDS[kind]
        selected_status = request.args.get('status', '')
        if selected_status and selected_status not in statuses:
            abort(400)
        query = request.args.get('q', '').strip()[:100]
        params = {'page': int(page), 'per_page': 30, 'order_by': 'id', 'order': 'desc',
                  'status': selected_status or ','.join(sorted(statuses))}
        if query:
            params[number] = query
        payload = read(kind, params).get(kind)
        if not isinstance(payload, dict):
            raise DocumentError('Dokumentliste konnte nicht gelesen werden.')
        rows = payload.get(singular, [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or len(rows) > 30 or any(not isinstance(r, dict) for r in rows):
            raise DocumentError('Unerwartete Dokumentliste.')
        body = '<section class="card"><h1>Rechnungen und Lieferscheine</h1><p>Originale aus Billomat prüfen und als PDF über WhatsApp oder Ihre E-Mail-App teilen.</p>'
        for key, spec in KINDS.items():
            body += '<a class="btn light" href="' + ingress('documents?kind=' + key) + '">' + spec[2] + '</a>'
        body += '<h2>' + plural + '</h2><form method="get"><input type="hidden" name="kind" value="' + kind + '"><label for="document-search">Dokumentnummer suchen</label><input id="document-search" name="q" maxlength="100" value="' + escape(query) + '"><button class="btn">Suchen / aktualisieren</button></form><p>Bis zu 30 Dokumente pro Seite. Entwürfe und stornierte Rechnungen sind vom Teilen ausgeschlossen.</p></section>'
        options = '<option value="">Alle freigegebenen Dokumente</option>'
        for status in sorted(statuses):
            options += '<option value="' + status + '"' + (' selected' if status == selected_status else '') + '>' + STATUS_LABELS[status] + '</option>'
        body = body.replace('<button class="btn">Suchen / aktualisieren</button>', '<div class="field"><label for="document-status">Status</label><select id="document-status" name="status">' + options + '</select></div><button class="btn">Suchen / aktualisieren</button>', 1)
        shown = 0
        for row in rows:
            oid = str(row.get('id', ''))
            if not re.fullmatch(r'[1-9][0-9]{0,19}', oid) or row.get('status') not in statuses:
                continue
            if selected_status and row.get('status') != selected_status:
                continue
            shown += 1
            body += '<section class="card"><h2>' + escape(str(row.get(number) or oid)) + '</h2><p style="white-space:pre-line;overflow-wrap:anywhere">' + escape(str(row.get('address') or '')) + '</p><p>' + escape(str(row.get('date', ''))) + ' · ' + STATUS_LABELS[row['status']] + '</p><a class="btn" href="' + ingress('documents/' + kind + '/' + oid) + '">Prüfen und teilen</a></section>'
        if not shown:
            body += '<section class="card">Keine passenden freigegebenen Dokumente auf dieser Seite.</section>'
        from urllib.parse import urlencode
        for label, target in [('Vorherige Seite', int(page)-1), ('Weitere Dokumente', int(page)+1)]:
            if target > 0 and (target < int(page) or len(rows) == 30):
                body += '<a class="btn light" href="' + ingress('documents?' + urlencode({'kind':kind, 'page':target, 'q':query, 'status':selected_status})) + '">' + label + '</a>'
        return base(plural, body)

    @app.get('/documents/<kind>/<oid>')
    def document_detail(kind, oid):
        row = document(kind, oid)
        _, title, _, number, statuses = KINDS[kind]
        if row.get('status') not in statuses:
            abort(409, description='Dieses Dokument ist nicht zum Teilen freigegeben.')
        client = {}
        contact_notice = ''
        cid = str(row.get('client_id', ''))
        if re.fullmatch(r'[1-9][0-9]{0,19}', cid) and str(row.get('contact_id') or '') in ('', '0'):
            try:
                client = read('clients/' + cid).get('client', {})
            except DocumentError:
                contact_notice = 'Kundenkontaktdaten konnten nicht geladen werden. Empfänger bitte manuell eintragen und prüfen.'
        elif str(row.get('contact_id') or '') not in ('', '0'):
            contact_notice = 'Das Dokument hat einen abweichenden Ansprechpartner. Dessen Empfänger bitte manuell eintragen und prüfen.'
        if not isinstance(client, dict):
            client = {}
            contact_notice = 'Kundenkontaktdaten konnten nicht geladen werden. Empfänger bitte manuell eintragen und prüfen.'
        e = lambda value: escape(str(value or ''))
        subject = title + ' ' + str(row.get(number) or oid) + ' - FT Sicherheitstechnik'
        message = 'Guten Tag, anbei erhalten Sie das Dokument ' + str(row.get(number) or oid) + ' (' + title + ') als PDF. Bei Fragen melden Sie sich gerne. Viele Grüße, FT Sicherheitstechnik'
        filename = 'FTST-' + title + '-' + oid + '.pdf'
        pdfurl = ingress('documents/' + kind + '/' + oid + '/pdf')
        body = '<section class="card"><a href="' + ingress('documents?kind=' + kind) + '">Zur Dokumentübersicht</a><h1>' + e(subject) + '</h1><p style="white-space:pre-line">' + e(row.get('address')) + '</p><p>Status: ' + e(row.get('status')) + '</p><a class="btn light" data-pdf="' + e(filename) + '" href="' + pdfurl + '">Original-PDF prüfen / speichern</a></section>'
        body += '<section class="card" data-offer-delivery data-pdf-url="' + pdfurl + '" data-filename="' + e(filename) + '"><h2>Dokument teilen</h2><p>Empfänger und Anhang vor dem Senden in WhatsApp oder Ihrer E-Mail-App prüfen.</p>'
        if contact_notice:
            body += '<p role="status">' + e(contact_notice) + '</p>'
        for name, label, typ, value in [('email','E-Mail des Kunden','email',client.get('email')), ('phone','WhatsApp-Nummer mit Ländervorwahl','tel',client.get('mobile') or client.get('phone')), ('subject','Betreff','text',subject)]:
            body += '<div class="field"><label for="delivery-' + name + '">' + label + '</label><input id="delivery-' + name + '" type="' + typ + '" value="' + e(value) + '"></div>'
        for name,label in [('email','E-Mail-Text'),('whatsapp','WhatsApp-Text')]:
            body += '<div class="field"><label for="delivery-' + name + '-text">' + label + '</label><textarea id="delivery-' + name + '-text" maxlength="2000">' + e(message) + '</textarea></div>'
        body += '<button class="btn" type="button" data-deliver="whatsapp">PDF für WhatsApp vorbereiten</button><button class="btn light" type="button" data-deliver="email">PDF für E-Mail vorbereiten</button><p>Die App übergibt die Datei an das Teilen-Menü. Empfänger dort auswählen; es wird kein automatischer Versand und keine Zustellung bestätigt.</p><div data-delivery-result aria-live="polite"></div></section>'
        body += '<script defer src="' + ingress('ui-assets/' + app.config['CHAT_ASSET_VERSION'] + '/offer-delivery.js') + '"></script>'
        return base(title, body)

    @app.get('/documents/<kind>/<oid>/pdf')
    def document_pdf(kind, oid):
        row = document(kind, oid)
        if row.get('status') not in KINDS[kind][4]:
            abort(409)
        pdf = read(kind + '/' + oid + '/pdf', pdf=True)
        return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                         download_name='FTST-' + KINDS[kind][1] + '-' + oid + '.pdf')
