"""Explicit, bounded Billomat capability check; never stores or displays receipt values."""
import json
import os
import re
import secrets
import threading
import time

import requests
from flask import abort, make_response, request, session

MAX_BYTES = 256 * 1024
PAGE_SIZE = 5
_busy = threading.Lock()
RESOURCES = (
    ('incomings', 'incoming', 'Eingangsrechnungen'),
    ('inbox-documents', 'inbox-document', 'Beleg-Inbox'),
)
# Never echo arbitrary server-supplied property names: they can themselves contain secrets.
FIELDS = frozenset(('id', 'supplier_id', 'created', 'number', 'status', 'date', 'due_date',
                    'address', 'note', 'total_gross', 'total_net', 'paid_amount', 'open_amount',
                    'currency_code', 'quote', 'expense_account_number', 'label', 'client_number',
                    'category', 'user_id', 'filename', 'mimetype', 'filesize', 'file_url',
                    'base64file', 'metadata', 'document_type'))
MESSAGES = {
    'configuration': 'Billomat-Zugang fehlt oder die Konfiguration ist ungültig.',
    'redirect': 'Weiterleitung abgelehnt. Es wurden keine Zugangsdaten weitergereicht.',
    'access': 'Zugriff abgelehnt. Billomat-Berechtigungen und Zugang prüfen.',
    'limited': 'Billomat-Aufruflimit erreicht. Später erneut prüfen.',
    'http': 'Billomat hat die Lesprüfung nicht erfolgreich beantwortet.',
    'transport': 'Billomat derzeit nicht sicher erreichbar oder Zeitlimit überschritten.',
    'large': 'Antwort überschreitet das sichere Größenlimit.',
    'invalid': 'Antwortformat konnte nicht sicher geprüft werden.',
    'busy': 'Eine Belegprüfung läuft bereits. Bitte später erneut versuchen.',
}


class ReceiptCheckError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def _configuration():
    account = os.getenv('BILLOMAT_ID', '').strip()
    key = os.getenv('BILLOMAT_API_KEY', '').strip()
    if (not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', account)
            or not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise ReceiptCheckError('configuration')
    return 'https://' + account + '.billomat.net/api', {
        'X-BillomatApiKey': key, 'Accept': 'application/json',
        'User-Agent': 'FTST-Beleg-Lespruefung',
    }


def _read(http, base, headers, resource):
    """Do not reuse the legacy client's raw-error logging or redirect behavior."""
    started = time.monotonic()
    try:
        with http.get(base + '/' + resource, headers=headers,
                      params={'format': 'json', 'per_page': PAGE_SIZE, 'page': 1},
                      timeout=(5, 10), allow_redirects=False, verify=True, stream=True) as response:
            status = response.status_code
            if 300 <= status < 400:
                raise ReceiptCheckError('redirect')
            if status in (401, 403):
                raise ReceiptCheckError('access')
            if status == 429:
                raise ReceiptCheckError('limited')
            if status != 200:
                raise ReceiptCheckError('http')
            length = response.headers.get('Content-Length')
            if length is not None:
                if not length.isascii() or not length.isdigit():
                    raise ReceiptCheckError('invalid')
                if len(length) > 12 or int(length) > MAX_BYTES:
                    raise ReceiptCheckError('large')
            data = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if time.monotonic() - started > 20:
                    raise ReceiptCheckError('transport')
                if len(data) + len(chunk) > MAX_BYTES:
                    raise ReceiptCheckError('large')
                data.extend(chunk)
            return json.loads(data.decode('utf-8-sig'))
    except ReceiptCheckError:
        raise
    except requests.RequestException:
        raise ReceiptCheckError('transport') from None
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise ReceiptCheckError('invalid') from None


def _summary(payload, plural, singular):
    if not isinstance(payload, dict) or plural not in payload:
        raise ReceiptCheckError('invalid')
    wrapper = payload[plural]
    if not isinstance(wrapper, dict):
        raise ReceiptCheckError('invalid')
    rows = wrapper.get(singular, [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE or any(not isinstance(row, dict) for row in rows):
        raise ReceiptCheckError('invalid')
    total = wrapper.get('@total', wrapper.get('total'))
    if total is not None:
        if isinstance(total, bool) or not re.fullmatch(r'[0-9]{1,12}', str(total)) or int(total) < len(rows):
            raise ReceiptCheckError('invalid')
        total = int(total)
    if singular not in wrapper and total != 0:
        raise ReceiptCheckError('invalid')
    names = sorted({name for row in rows for name in row if name in FIELDS})
    return {'reachable': True, 'total': total, 'fields': names}


def check_receipts():
    """At most two GETs to fixed first-page resources. No file URLs, bank data or writes."""
    base, headers = _configuration()
    if not _busy.acquire(blocking=False):
        raise ReceiptCheckError('busy')
    try:
        results = []
        with requests.Session() as http:
            http.trust_env = False
            for plural, singular, title in RESOURCES:
                try:
                    summary = _summary(_read(http, base, headers, plural), plural, singular)
                    results.append(dict(resource=plural, title=title, **summary))
                except ReceiptCheckError as exc:
                    results.append(dict(resource=plural, title=title, reachable=False, error=exc.code))
                    if exc.code in ('limited', 'access', 'redirect'):
                        break
        return results
    finally:
        _busy.release()


def register(app, base, ingress, escape):
    @app.route('/billomat/receipts-check', methods=['GET', 'POST'])
    def billomat_receipts_check():
        session.setdefault('receipts_csrf', secrets.token_urlsafe(32))
        output = ''
        if request.method == 'POST':
            token = request.form.get('csrf', '')
            if not token.isascii() or not secrets.compare_digest(token, session['receipts_csrf']):
                abort(400)
            try:
                results = check_receipts()
                for result in results:
                    output += '<div class="card"><h2>' + result['title'] + '</h2>'
                    if result['reachable']:
                        total = str(result['total']) if result['total'] is not None else 'Nicht geliefert'
                        output += ('<p>Lesend erreichbar. Gesamtzahl laut Billomat: ' + total + '</p><p>Erkannte Feldnamen: '
                                   + escape(', '.join(result['fields']) or 'Keine in dieser Stichprobe') + '</p>')
                    else:
                        output += '<p role="alert">' + MESSAGES[result['error']] + '</p>'
                    output += '</div>'
                if len(results) < len(RESOURCES):
                    output += '<p>Weitere Ressourcen wurden nach diesem Ergebnis nicht abgefragt.</p>'
            except ReceiptCheckError as exc:
                output = '<p role="alert">' + MESSAGES[exc.code] + '</p>'
        page = base('Billomat-Belegprüfung', '<div class="card"><h1>Billomat-Belege: Verbindung prüfen</h1>'
                    '<p>Bewusste Lesprüfung der ersten Seite von Eingangsrechnungen und Beleg-Inbox, jeweils höchstens fünf Einträge. '
                    'Es werden nur Erreichbarkeit, Gesamtzahl und bekannte Feldnamen angezeigt, keine Belegwerte.</p>'
                    '<p>Keine Datei wird separat heruntergeladen. Keine Anlage, Buchung, Zahlung oder Bankabfrage. '
                    'Die Stichprobe bestätigt weder Vollständigkeit noch Banking-Aktivierung oder Zahlungsabgleich.</p>'
                    '<form method="post"><input type="hidden" name="csrf" value="' + escape(session['receipts_csrf']) + '">'
                    '<button class="btn">Billomat jetzt lesend prüfen</button></form><p><a href="' + ingress('billomat')
                    + '">Zur Billomat-Übersicht</a></p></div>' + output)
        response = make_response(page)
        response.headers['Cache-Control'] = 'no-store'
        return response
