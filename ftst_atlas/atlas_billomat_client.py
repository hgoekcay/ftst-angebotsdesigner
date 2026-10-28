"""Owner-scoped Billomat invoice reads; no creation, booking, payment or sending.

Contracts verified against https://www.billomat.com/api/rechnungen/ and
https://www.billomat.com/en/api/basics/read-data/ (2026-10-28).
Lists are live page-based reads, not immutable snapshots or certified ledgers.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode


class BillomatError(Exception):
    pass


PAGE_SIZE = 25
MAX_JSON = 2 * 1024 * 1024
MAX_PDF = 8 * 1024 * 1024
STATUSES = frozenset(('DRAFT', 'OPEN', 'OVERDUE', 'PAID', 'CANCELED'))


def _identifier(value):
    if type(value) not in (str, int) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(value)):
        raise BillomatError('Ungültige Rechnungskennung.')
    return str(value)


def _day(value, optional=False):
    if optional and value in (None, ''):
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        date.fromisoformat(value)
    except ValueError:
        raise BillomatError('Ungültiges Rechnungsdatum oder Zeitfenster.') from None
    return value


def _decimal(value, optional=False):
    if optional and value in (None, ''):
        return None
    # JSON fractional values are decoded to Decimal before reaching this function.
    if type(value) not in (str, int, Decimal):
        raise BillomatError('Ungültiger Rechnungsbetrag.')
    raw = str(value)
    if len(raw) > 60 or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,3})?', raw):
        raise BillomatError('Ungültiger Rechnungsbetrag.')
    try:
        number = Decimal(raw)
        if not number.is_finite() or abs(number) >= Decimal('1e15') or number.as_tuple().exponent < -12:
            raise ValueError()
        return format(number, 'f')
    except (InvalidOperation, ValueError):
        raise BillomatError('Ungültiger Rechnungsbetrag.') from None


def _text(value, maximum=500):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise BillomatError('Ungültiges Rechnungsfeld.')
    return value


def _invoice(row):
    if not isinstance(row, dict):
        raise BillomatError('Ungültiges Rechnungsformat.')
    status = row.get('status')
    if not isinstance(status, str) or status not in STATUSES:
        raise BillomatError('Unbekannter Rechnungsstatus. Keine Übernahme.')
    currency = row.get('currency_code')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
        raise BillomatError('Rechnungswährung fehlt oder ist ungültig.')
    result = {'id': _identifier(row.get('id')), 'invoice_number': _text(row.get('invoice_number'), 200),
              'status': status, 'date': _day(row.get('date')), 'due_date': _day(row.get('due_date'), optional=True),
              'currency_code': currency, 'label': _text(row.get('label'), 1000),
              'total_net': _decimal(row.get('total_net')), 'total_gross': _decimal(row.get('total_gross')),
              'paid_amount': _decimal(row.get('paid_amount'), optional=True),
              'open_amount': _decimal(row.get('open_amount'), optional=True),
              'client_id': _identifier(row['client_id']) if row.get('client_id') not in (None, '') else None,
              'source': 'Billomat', 'taxes': [], 'warnings': []}
    if not result['invoice_number'] and status != 'DRAFT':
        raise BillomatError('Abgeschlossene Rechnung ohne Rechnungsnummer.')
    if result['paid_amount'] is None or result['open_amount'] is None:
        result['warnings'].append('Zahlungsbeträge fehlen teilweise; kein Zahlungsabgleich möglich.')
    taxes = row.get('taxes')
    if taxes is not None:
        if isinstance(taxes, dict):
            taxes = taxes.get('tax', [])
        if isinstance(taxes, dict):
            taxes = [taxes]
        if not isinstance(taxes, list) or len(taxes) > 30:
            raise BillomatError('Ungültige Steueraufstellung.')
        for tax in taxes:
            if not isinstance(tax, dict):
                raise BillomatError('Ungültige Steueraufstellung.')
            result['taxes'].append({'name': _text(tax.get('name'), 200),
                                    'rate': _decimal(tax.get('rate')), 'amount': _decimal(tax.get('amount'))})
    else:
        result['warnings'].append('Keine gesonderte Steueraufstellung im Abruf enthalten.')
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate key')
        result[key] = value
    return result


def _read(host, key, path, params, pdf=False):
    """Fixed Billomat host, GET only, verified TLS, no redirect or arbitrary file URL."""
    if (not isinstance(host, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.billomat\.net', host)
            or not re.fullmatch(r'/api/invoices(?:/[1-9][0-9]{0,19}(?:/pdf)?)?', path)
            or not isinstance(key, str) or not key or len(key) > 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise BillomatError('Billomat-Lesezugang ist ungültig konfiguriert.')
    connection = http.client.HTTPSConnection(host, 443, timeout=15, context=ssl.create_default_context())
    deadline = time.monotonic() + 45
    maximum = MAX_PDF if pdf else MAX_JSON
    try:
        query = dict(params, format='pdf' if pdf else 'json')
        connection.request('GET', path + '?' + urlencode(query), headers={
            'X-BillomatApiKey': key, 'Accept': 'application/pdf' if pdf else 'application/json',
            'User-Agent': 'FTST-ATLAS-ReadOnly'})
        socket = connection.sock
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('HTTP failure')
        expected = 'application/pdf' if pdf else 'application/json'
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != expected:
            raise ValueError('Invalid MIME')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 12 or int(length) > maximum):
            raise ValueError('Invalid size')
        chunks, total = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Timeout')
            socket.settimeout(min(15, remaining))
            chunk = response.read1(min(65536, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError('Too large')
            chunks.append(chunk)
        if length is not None and total != int(length):
            raise ValueError('Truncated')
        raw = b''.join(chunks)
        if pdf:
            if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-4096:]:
                raise ValueError('Invalid PDF')
            return raw
        return json.loads(raw.decode('utf-8-sig'), parse_float=Decimal, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()),
                          object_pairs_hook=_unique_object)
    except Exception:
        raise BillomatError('Billomat-Abruf fehlgeschlagen oder unvollständig. Zugang, Berechtigungen und Zeitfenster prüfen; nichts wurde verändert.') from None
    finally:
        connection.close()


class BillomatClient:
    def __init__(self, options):
        self.enabled = options.get('billomat_enabled') is True
        self.owner = options.get('billomat_ha_user_id') or ''
        subdomain = options.get('billomat_subdomain') or ''
        self._key = options.get('billomat_api_key') or ''
        self.configured = (isinstance(self.owner, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.owner))
                           and isinstance(subdomain, str) and bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', subdomain))
                           and isinstance(self._key, str) and bool(self._key) and len(self._key) <= 4096
                           and not any(ord(c) < 33 or ord(c) > 126 for c in self._key))
        self.host = subdomain.lower() + '.billomat.net' if self.configured else ''

    def enabled_for(self, user_id):
        return bool(self.enabled and self.configured and isinstance(user_id, str) and user_id == self.owner)

    def status(self, user_id):
        return {'enabled': self.enabled_for(user_id),
                'configured': bool(self.configured and user_id == self.owner),
                'read_only': True, 'provider': 'Billomat'}

    def _authorize(self, user_id):
        if not self.enabled_for(user_id):
            raise BillomatError('Billomat-Lesezugriff ist für diesen Benutzer nicht eingerichtet oder freigegeben.')

    def list_invoices(self, user_id, date_from, date_to, page=1, status=''):
        self._authorize(user_id)
        first, last = _day(date_from), _day(date_to)
        if first > last or (date.fromisoformat(last) - date.fromisoformat(first)).days > 366:
            raise BillomatError('Zeitfenster muss geordnet sein und höchstens 367 Kalendertage umfassen.')
        if type(page) is not int or not 1 <= page <= 10000 or not isinstance(status, str) or (status and status not in STATUSES):
            raise BillomatError('Ungültige Seite oder Statusauswahl.')
        params = {'from': first, 'to': last, 'per_page': PAGE_SIZE, 'page': page, 'order_by': 'date ASC,id ASC'}
        if status:
            params['status'] = status
        payload = _read(self.host, self._key, '/api/invoices', params)
        if not isinstance(payload, dict) or not isinstance(payload.get('invoices'), dict):
            raise BillomatError('Ungültige Billomat-Rechnungsliste.')
        wrapper = payload['invoices']
        total = wrapper.get('@total', wrapper.get('total'))
        if type(total) not in (str, int) or not re.fullmatch(r'[0-9]{1,9}', str(total)):
            raise BillomatError('Gesamtzahl fehlt. Vollständigkeit nicht prüfbar.')
        total = int(total)
        for key, expected in [('page', page), ('per_page', PAGE_SIZE)]:
            actual = wrapper.get('@' + key, wrapper.get(key))
            if actual is not None and (type(actual) not in (str, int) or str(actual) != str(expected)):
                raise BillomatError('Billomat lieferte eine andere Seite als angefordert.')
        rows = wrapper.get('invoice', [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
            raise BillomatError('Ungültige Billomat-Rechnungsliste.')
        offset = (page - 1) * PAGE_SIZE
        if (len(rows) != min(PAGE_SIZE, max(0, total - offset)) or (not rows and page > 1 and offset >= total)):
            raise BillomatError('Rechnungsseite unvollständig oder nicht mehr verfügbar. Abruf neu starten.')
        invoices = [_invoice(row) for row in rows]
        ids = [row['id'] for row in invoices]
        if len(set(ids)) != len(ids):
            raise BillomatError('Doppelte Rechnungskennungen im Abruf.')
        ordering = [(row['date'], int(row['id'])) for row in invoices]
        if ordering != sorted(ordering) or any(not first <= row['date'] <= last or (status and row['status'] != status) for row in invoices):
            raise BillomatError('Rechnungsfilter oder Sortierung wurde nicht bestätigt.')
        pending = offset + len(invoices) < total
        return {'invoices': invoices, 'page': page, 'per_page': PAGE_SIZE, 'total': total,
                'pending': pending, 'next_page': page + 1 if pending else None,
                'date_from': first, 'date_to': last, 'status': status,
                'read_only': True, 'snapshot': False, 'source': 'Billomat',
                'scope': 'Ausgangsrechnungen nach Rechnungsdatum; laufender Seitenabruf, kein unveränderlicher Buchhaltungsabschluss.'}

    def get_invoice(self, user_id, invoice_id):
        self._authorize(user_id)
        ident = _identifier(invoice_id)
        payload = _read(self.host, self._key, '/api/invoices/' + ident, {})
        if not isinstance(payload, dict):
            raise BillomatError('Ungültige Billomat-Rechnung.')
        invoice = _invoice(payload.get('invoice'))
        if invoice['id'] != ident:
            raise BillomatError('Billomat lieferte eine andere Rechnungskennung.')
        return invoice

    def get_pdf(self, user_id, invoice_id):
        self._authorize(user_id)
        ident = _identifier(invoice_id)
        return _read(self.host, self._key, '/api/invoices/' + ident + '/pdf', {}, pdf=True)
