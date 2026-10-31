"""Owner-scoped invoice preparation, not accounting, tax advice or DATEV filing.

Original bytes and source snapshots are append-only through this API. Review is
explicit, amounts use Decimal, and exports preserve unresolved items visibly.
"""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
from functools import wraps
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree
from bookkeeping_export import documents_v1

MAX_FILE = 12 * 1024 * 1024
MAX_RECORDS = 2000
MAX_EXPORT_FILES = MAX_RECORDS
MAX_EXPORT_BYTES = 100 * 1024 * 1024
FIELDS = {'supplier', 'invoice_number', 'invoice_date', 'currency', 'net', 'tax', 'gross', 'payment_status', 'direction', 'source_status', 'source_open_amount', 'source_due_date', 'source_currency'}
SOURCE_KEYS = {'type', 'provider', 'reference', 'account_id', 'message_uid', 'attachment_id', 'invoice_id', 'access_id', 'label', 'project', 'note'}
MIMES = {'application/pdf': '.pdf', 'application/xml': '.xml', 'text/xml': '.xml', 'image/jpeg': '.jpg', 'image/png': '.png', 'image/tiff': '.tiff'}


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class BookkeepingError(ValueError):
    """Safe error for user display; never includes raw document content."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _user(user):
    if not isinstance(user, str) or not user or len(user) > 128:
        raise BookkeepingError('Benutzerkennung ungültig.')


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError, OverflowError):
        raise BookkeepingError('Ungültige Daten.') from None


def _amount(value):
    if value in (None, ''):
        return ''
    if isinstance(value, (float, bool)) or not isinstance(value, (str, int, Decimal)):
        raise BookkeepingError('Beträge müssen exakte Dezimaltexte sein.')
    text = str(value).strip()
    # Manual/API amounts are canonical decimals. Locale parsing belongs to extraction.
    if not re.fullmatch(r'-?\d{1,12}(?:\.\d{1,2})?', text):
        raise BookkeepingError('Betrag ungültig; Format beispielsweise 1234.56.')
    try:
        return format(Decimal(text).quantize(Decimal('.01')), 'f')
    except InvalidOperation:
        raise BookkeepingError('Betrag ungültig.') from None


def _fields(values):
    if not isinstance(values, dict) or set(values) - FIELDS:
        raise BookkeepingError('Unbekannte Belegfelder.')
    out = {'supplier': '', 'invoice_number': '', 'invoice_date': '', 'currency': '', 'net': '', 'tax': '', 'gross': '', 'payment_status': 'unknown', 'direction': 'incoming', 'source_status': '', 'source_open_amount': '', 'source_due_date': '', 'source_currency': ''}
    for key, value in values.items():
        if key in ('net', 'tax', 'gross', 'source_open_amount'):
            out[key] = _amount(value)
        elif not isinstance(value, str) or len(value) > (300 if key == 'supplier' else 100):
            raise BookkeepingError('Belegfeld ungültig oder zu lang.')
        else:
            out[key] = value.strip()
    if out['source_status'] not in ('', 'DRAFT', 'OPEN', 'PAID', 'OVERDUE', 'CANCELED'):
        raise BookkeepingError('Quellstatus ungültig.')
    if out['payment_status'] not in ('unknown', 'paid', 'unpaid', 'partial'):
        raise BookkeepingError('Zahlungsstatus ungültig.')
    if out['direction'] not in ('incoming', 'outgoing'):
        raise BookkeepingError('Belegrichtung ungültig.')
    for key in ('currency', 'source_currency'):
        if out[key] and not re.fullmatch(r'[A-Z]{3}', out[key]):
            raise BookkeepingError('Währung benötigt drei Großbuchstaben.')
    for key in ('invoice_date', 'source_due_date'):
        if out[key]:
            try:
                if date.fromisoformat(out[key]).isoformat() != out[key]:
                    raise ValueError()
            except ValueError:
                raise BookkeepingError('Datum benötigt YYYY-MM-DD.') from None
    return out


def _issues(fields):
    issues = []
    if fields.get('source_status') == 'CANCELED':
        issues.append('Quelle meldet Storno; nicht als offene Forderung oder gültige Rechnung übernehmen.')
    if fields.get('source_status') == 'DRAFT':
        issues.append('Quelle meldet Entwurf; nicht als ausgestellte Rechnung übernehmen.')
    for key in ('supplier', 'invoice_number', 'invoice_date', 'currency', 'net', 'tax', 'gross'):
        if not fields[key]:
            issues.append('Feld fehlt: ' + key)
    if all(fields[k] for k in ('net', 'tax', 'gross')):
        if Decimal(fields['net']) + Decimal(fields['tax']) != Decimal(fields['gross']):
            issues.append('Netto + Steuer stimmt nicht mit Brutto überein.')
        signs = {Decimal(fields[k]).is_signed() for k in ('net', 'tax', 'gross') if Decimal(fields[k]) != 0}
        if len(signs) > 1:
            issues.append('Vorzeichen der Beträge prüfen.')
    return issues


def _source(value):
    if not isinstance(value, dict) or set(value) - SOURCE_KEYS:
        raise BookkeepingError('Quelle enthält unbekannte oder sensible Felder.')
    value = dict(value)
    if 'type' in value:
        if 'provider' in value and value['provider'] != value['type']:
            raise BookkeepingError('Widersprüchliche Quelle.')
        value['provider'] = value.pop('type')
    out = {}
    for key, val in value.items():
        if not isinstance(val, str) or not val.strip() or len(val) > {'label':80, 'project':120, 'note':500}.get(key, 300) or any(ord(c) < 32 for c in val):
            raise BookkeepingError('Quellenangabe ungültig.')
        # No URLs with query tokens or userinfo in source references.
        if '://' in val or re.search(r'(?i)(bearer\s|password=|token=|api[_-]?key=)', val):
            raise BookkeepingError('Quelle darf keine Zugangsdaten oder URLs enthalten.')
        out[key] = val
    if out.get('provider') not in ('upload', 'mail', 'billomat', 'employee'):
        raise BookkeepingError('Quellanbieter fehlt oder ist ungültig.')
    return out


def _filename(value, ext):
    if not isinstance(value, str) or len(value) > 250:
        raise BookkeepingError('Dateiname ungültig.')
    name = Path(value.replace('\\', '/')).name
    name = re.sub(r'[^\w.() -]', '_', name).strip(' .')[:150] or 'beleg'
    return name if name.lower().endswith(ext) else name + ext


def _date(text):
    text = text.strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y%m%d'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


def _locale_amount(text):
    text = text.strip().replace(' ', '').replace('\u00a0', '')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    return _amount(text)


def _extract_text(text):
    """Conservative labeled fields only; missing supplier/currency stay unknown."""
    # PDF text often puts the two explicit header labels on one row. Split only
    # a complete, recognized number/date pair; do not split arbitrary prose.
    number = r'(?:Rechnungs(?:nummer|[ -]?Nr\.?)|Invoice[ \t]*(?:number|no\.?))[ \t]*[:#]?[ \t]*[A-Za-z0-9][A-Za-z0-9_./-]{1,80}'
    stamp = r'(?:Rechnungsdatum|Invoice[ \t]*date)[ \t]*:?[ \t]*(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})'
    for first, second in ((number, stamp), (stamp, number)):
        text = re.sub(r'(?im)^[ \t]*(' + first + r')[ \t]{2,}(' + second + r')[ \t]*$', r'\1\n\2', text)
    result = {}
    patterns = {
        'invoice_number': r'(?im)^\s*(?:Rechnungs(?:nummer|[ -]?Nr\.?)|Invoice\s*(?:number|no\.?))\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_./-]{1,80})\s*$',
        'invoice_date': r'(?im)^\s*(?:Rechnungsdatum|Invoice\s*date)\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})\s*$',
        'supplier': r'(?im)^\s*(?:Lieferant|Supplier|Rechnungssteller)\s*:\s*([^\n]{2,200})$',
        'currency': r'(?im)^\s*(?:Währung|Currency)\s*:\s*([A-Z]{3})\s*$',
        'net': r'(?im)^\s*(?:Nettobetrag|Netto(?:summe)?|Net\s*total)\s*:?\s*(?:(?:EUR|€)[ \t]*)?(-?[\d., \u00a0]+)[ \t]*(?:EUR|€)?\s*$',
        'tax': r'(?im)^\s*(?:Steuerbetrag|Umsatzsteuer|MwSt\.?|VAT\s*total)\s*:?\s*(?:(?:EUR|€)[ \t]*)?(-?[\d., \u00a0]+)[ \t]*(?:EUR|€)?\s*$',
        'gross': r'(?im)^\s*(?:Bruttobetrag|Bruttosumme|Gesamtbetrag|Gross\s*total)\s*:?\s*(?:(?:EUR|€)[ \t]*)?(-?[\d., \u00a0]+)[ \t]*(?:EUR|€)?\s*$'
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if key == 'invoice_number':
            # Repeated page headers are one identifier; conflicting IDs stay unknown.
            matches = list(dict.fromkeys(value.strip() for value in matches))
        if len(matches) != 1:
            continue
        try:
            result[key] = _locale_amount(matches[0]) if key in ('net', 'tax', 'gross') else _date(matches[0]) if key == 'invoice_date' else matches[0].strip()
        except BookkeepingError:
            continue
    return result


def _extract_xml(data):
    if len(data) > 2 * 1024 * 1024:
        raise BookkeepingError('XML-Beleg ist zu groß.')
    try:
        text = data.decode('utf-8-sig')
        if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I):
            raise BookkeepingError('DTD und XML-Entitäten sind nicht erlaubt.')
        root = ElementTree.fromstring(text)
    except (UnicodeDecodeError, ElementTree.ParseError):
        raise BookkeepingError('XML muss gültiges UTF-8 ohne externe Entitäten sein.') from None
    def local(tag): return tag.rsplit('}', 1)[-1]
    def child(node, name): return next((x for x in node if local(x.tag) == name), None) if node is not None else None
    def path(node, *names):
        for name in names: node = child(node, name)
        return node
    def val(node): return (node.text or '').strip() if node is not None else ''
    result = {}
    if local(root.tag) == 'Invoice':
        result.update(invoice_number=val(child(root, 'ID')), invoice_date=_date(val(child(root, 'IssueDate'))), currency=val(child(root, 'DocumentCurrencyCode')))
        party = path(root, 'AccountingSupplierParty', 'Party')
        result['supplier'] = val(path(party, 'PartyLegalEntity', 'RegistrationName')) or val(path(party, 'PartyName', 'Name'))
        monetary = child(root, 'LegalMonetaryTotal')
        amounts = {'net': val(child(monetary, 'TaxExclusiveAmount')), 'gross': val(child(monetary, 'TaxInclusiveAmount'))}
        totals = [val(child(x, 'TaxAmount')) for x in root if local(x.tag) == 'TaxTotal']
        # Multiple TaxTotal nodes may include accounting-currency totals; never sum blindly.
        if len(totals) == 1: amounts['tax'] = totals[0]
    elif local(root.tag) == 'CrossIndustryInvoice':
        doc = child(root, 'ExchangedDocument')
        txn = child(root, 'SupplyChainTradeTransaction')
        agreement = child(txn, 'ApplicableHeaderTradeAgreement')
        settlement = child(txn, 'ApplicableHeaderTradeSettlement')
        result.update(invoice_number=val(child(doc, 'ID')), invoice_date=_date(val(path(doc, 'IssueDateTime', 'DateTimeString'))), supplier=val(path(agreement, 'SellerTradeParty', 'Name')), currency=val(child(settlement, 'InvoiceCurrencyCode')))
        monetary = child(settlement, 'SpecifiedTradeSettlementHeaderMonetarySummation')
        amounts = {'net': val(child(monetary, 'TaxBasisTotalAmount')), 'gross': val(child(monetary, 'GrandTotalAmount'))}
        taxes = [val(x) for x in monetary if local(x.tag) == 'TaxTotalAmount' and x.attrib.get('currencyID', result['currency']) == result['currency']] if monetary is not None else []
        if len(taxes) == 1: amounts['tax'] = taxes[0]
    else:
        return {}, ['XML-Format nicht erkannt; Angaben manuell prüfen.']
    for key, value in amounts.items():
        if value:
            try: result[key] = _amount(value)
            except BookkeepingError: pass
    try:
        result = _fields(result)
    except BookkeepingError:
        return {}, ['XML-Felder konnten nicht eindeutig normalisiert werden.']
    return result, ['XML-Werte extrahiert; Original und Steuerbehandlung manuell prüfen.']


_PDF_SCRIPT = r'''
import json, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024,512*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU, (10,10))
from pypdf import PdfReader
reader=PdfReader(sys.argv[1])
if reader.is_encrypted: raise ValueError('encrypted')
if len(reader.pages)>30: raise ValueError('pages')
chunks=[]
remaining=100000
for page in reader.pages:
    text=(page.extract_text() or '')[:remaining]
    chunks.append(text)
    remaining-=len(text)
    if remaining<=0: break
print(json.dumps({'text':'\n'.join(chunks)}, ensure_ascii=True))
'''


def _extract_pdf(path):
    try:
        run = subprocess.run([sys.executable, '-I', '-c', _PDF_SCRIPT, str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
        if run.returncode != 0 or len(run.stdout) > 650000:
            return {}, ['PDF-Texterkennung nicht verfügbar; Original manuell prüfen.']
        text = json.loads(run.stdout)['text']
        if not text.strip():
            return {}, ['PDF enthält keinen lesbaren Text; OCR oder manuelle Eingabe nötig.']
        return _extract_text(text), ['PDF-Felder sind Vorschläge und müssen am Original geprüft werden.']
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return {}, ['PDF-Texterkennung fehlgeschlagen; Original manuell prüfen.']


class Bookkeeping:
    def __init__(self, db_factory, data_dir):
        self.db = db_factory
        self._lock = threading.RLock()
        self.root = Path(data_dir) / 'bookkeeping'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS atlas_bookkeeping (
              id TEXT PRIMARY KEY,user_id TEXT NOT NULL,sha256 TEXT NOT NULL,
              filename TEXT NOT NULL,mime TEXT NOT NULL,original_path TEXT NOT NULL,
              source_json TEXT NOT NULL,fields_json TEXT NOT NULL,notes_json TEXT NOT NULL,
              reviewed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,
              UNIQUE(user_id,sha256));
            CREATE TABLE IF NOT EXISTS atlas_bookkeeping_snapshots (
              user_id TEXT NOT NULL,record_id TEXT NOT NULL,sha256 TEXT NOT NULL,
              original_path TEXT NOT NULL,created_at TEXT NOT NULL,
              UNIQUE(user_id,record_id,sha256));
            CREATE TABLE IF NOT EXISTS atlas_bookkeeping_documents (
              user_id TEXT NOT NULL,record_id TEXT NOT NULL,sha256 TEXT NOT NULL,
              filename TEXT NOT NULL,mime TEXT NOT NULL,original_path TEXT NOT NULL,
              created_at TEXT NOT NULL,UNIQUE(user_id,record_id));
            CREATE TABLE IF NOT EXISTS atlas_bookkeeping_sources (
              user_id TEXT NOT NULL,record_id TEXT NOT NULL,source_json TEXT NOT NULL,
              created_at TEXT NOT NULL,UNIQUE(user_id,record_id,source_json));
            CREATE TABLE IF NOT EXISTS atlas_bookkeeping_audit (
              id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,record_id TEXT NOT NULL,
              action TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS atlas_bookkeeping_owner ON atlas_bookkeeping(user_id,created_at);
            ''')

    def _record(self, row):
        if row is None: return None
        ident, sha, filename, mime, source, fields, notes, reviewed, created = tuple(row)
        fields = json.loads(fields)
        issues = _issues(fields)
        source = json.loads(source)
        source['type'] = source['provider']
        return {'canceled': fields.get('source_status') == 'CANCELED', 'source_status':fields.get('source_status', ''), 'source_open_amount':fields.get('source_open_amount', ''), 'source_due_date':fields.get('source_due_date', ''), 'source_currency':fields.get('source_currency', ''), 'direction': fields['direction'], 'id': ident, 'sha256': sha, 'filename': filename, 'mime': mime, 'source': source, 'fields': fields, 'extraction_notes': json.loads(notes), 'issues': issues, 'reviewed': bool(reviewed), 'status': 'canceled' if fields.get('source_status') == 'CANCELED' else 'reviewed' if reviewed and not issues else 'needs_review', 'created_at': created}

    def list(self, user):
        _user(user)
        with self.db() as db:
            rows = db.execute('SELECT id,sha256,filename,mime,source_json,fields_json,notes_json,reviewed,created_at FROM atlas_bookkeeping WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?', (user, MAX_RECORDS)).fetchall()
        return [self._record(row) for row in rows]

    def get(self, user, ident):
        _user(user)
        if not isinstance(ident, str) or len(ident) > 100: return None
        with self.db() as db:
            row = db.execute('SELECT id,sha256,filename,mime,source_json,fields_json,notes_json,reviewed,created_at FROM atlas_bookkeeping WHERE user_id=? AND id=?', (user, ident)).fetchone()
            result = self._record(row)
            if result:
                result['audit'] = [{'action': r[0], 'before': json.loads(r[1]) if r[1] else None, 'after': json.loads(r[2]), 'created_at': r[3]} for r in db.execute('SELECT action,before_json,after_json,created_at FROM atlas_bookkeeping_audit WHERE user_id=? AND record_id=? ORDER BY id', (user, ident))]
                result['snapshots'] = [{'sha256':r[0], 'created_at':r[1]} for r in db.execute('SELECT sha256,created_at FROM atlas_bookkeeping_snapshots WHERE user_id=? AND record_id=? ORDER BY created_at', (user,ident))]
                result['documents'] = [{'sha256':r[0], 'filename':r[1], 'mime':r[2]} for r in db.execute('SELECT sha256,filename,mime FROM atlas_bookkeeping_documents WHERE user_id=? AND record_id=?', (user, ident))]
                result['sources'] = [json.loads(r[0]) for r in db.execute('SELECT source_json FROM atlas_bookkeeping_sources WHERE user_id=? AND record_id=? ORDER BY created_at', (user, ident))]
        return result

    def _store(self, user, data, filename, mime, source, fields, notes):
        _user(user)
        if not isinstance(data, bytes) or not data or len(data) > MAX_FILE:
            raise BookkeepingError('Beleg muss 1 Byte bis 12 MiB groß sein.')
        source = _source(source)
        fields = _fields(fields)
        sha = hashlib.sha256(data).hexdigest()
        owner = hashlib.sha256(user.encode()).hexdigest()
        folder = self.root / owner
        folder.mkdir(mode=0o700, exist_ok=True)
        file = folder / sha
        ident, stamp = secrets.token_urlsafe(20), _now()
        was_duplicate = False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            duplicate = db.execute('SELECT id FROM atlas_bookkeeping WHERE user_id=? AND sha256=?', (user, sha)).fetchone()
            if duplicate:
                was_duplicate = True
                ident = duplicate[0]
                db.execute('INSERT OR IGNORE INTO atlas_bookkeeping_sources VALUES (?,?,?,?)', (user, ident, _json(source), stamp))
            else:
                if len(source) > 1 and db.execute('SELECT 1 FROM atlas_bookkeeping_sources WHERE user_id=? AND source_json=?', (user, _json(source))).fetchone():
                    raise BookkeepingError('Diese Quelle hat bereits einen anderen unveränderlichen Datenstand. Änderung manuell prüfen.')
                if db.execute('SELECT COUNT(*) FROM atlas_bookkeeping WHERE user_id=?', (user,)).fetchone()[0] >= MAX_RECORDS:
                    raise BookkeepingError('Beleglimit erreicht.')
                try:
                    with file.open('xb') as handle:
                        os.chmod(file, 0o600)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                        raise BookkeepingError('Originaldatei ist beschädigt.') from None
                db.execute('INSERT INTO atlas_bookkeeping VALUES (?,?,?,?,?,?,?,?,?,?,?)', (ident, user, sha, filename, mime, str(file.relative_to(self.root)), _json(source), _json(fields), _json(notes), 0, stamp))
                db.execute('INSERT INTO atlas_bookkeeping_sources VALUES (?,?,?,?)', (user, ident, _json(source), stamp))
                if source['provider'] == 'billomat':
                    db.execute('INSERT INTO atlas_bookkeeping_snapshots VALUES (?,?,?,?,?)', (user,ident,sha,str(file.relative_to(self.root)),stamp))
                db.execute('INSERT INTO atlas_bookkeeping_audit(user_id,record_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)', (user, ident, 'ingest', None, _json({'fields': fields, 'reviewed': False, 'sha256': sha}), stamp))
        result = self.get(user, ident)
        result['duplicate'] = was_duplicate
        return result

    @_locked
    def ingest_document(self, user, data, filename, mime, source):
        _user(user)
        if mime not in MIMES or not isinstance(data, bytes) or not 0 < len(data) <= MAX_FILE:
            raise BookkeepingError('Erlaubt sind PDF, XML, JPEG, PNG und TIFF bis 12 MiB.')
        _source(source)
        filename = _filename(filename, MIMES[mime])
        fields, notes = {}, []
        if mime == 'application/pdf':
            if not data.startswith(b'%PDF-'): raise BookkeepingError('PDF-Kennung fehlt.')
            # Persist the original before optional extraction; no mail/network side effects.
            record = self._store(user, data, filename, mime, source, fields, ['PDF-Auswertung ausstehend.'])
            if len(record['audit']) > 1 or record['extraction_notes'] != ['PDF-Auswertung ausstehend.']:
                return record
            with self.db() as db:
                row = db.execute('SELECT original_path FROM atlas_bookkeeping WHERE id=? AND user_id=?', (record['id'], user)).fetchone()
            fields, notes = _extract_pdf(self.root / row[0])
            with self.db() as db:
                # Never overwrite a human review racing with extraction.
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT reviewed,fields_json FROM atlas_bookkeeping WHERE id=? AND user_id=?', (record['id'], user)).fetchone()
                audit_count = db.execute('SELECT COUNT(*) FROM atlas_bookkeeping_audit WHERE user_id=? AND record_id=?', (user,record['id'])).fetchone()[0]
                if current and not current[0] and audit_count == 1:
                    db.execute('UPDATE atlas_bookkeeping SET fields_json=?,notes_json=? WHERE id=? AND user_id=? AND reviewed=0', (_json(_fields(fields)), _json(notes), record['id'], user))
                    db.execute('INSERT INTO atlas_bookkeeping_audit(user_id,record_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)', (user, record['id'], 'extract', _json(record['fields']), _json(_fields(fields)), _now()))
            result = self.get(user, record['id'])
            result['duplicate'] = record['duplicate']
            return result
        if mime.endswith('xml'):
            fields, notes = _extract_xml(data)
        elif mime == 'image/jpeg':
            if not data.startswith(b'\xff\xd8\xff'): raise BookkeepingError('JPEG-Kennung fehlt.')
            notes = ['Bildbeleg: OCR noch nicht verfügbar; Angaben manuell erfassen.']
        elif mime == 'image/tiff':
            if not data.startswith((b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')): raise BookkeepingError('TIFF-Kennung fehlt.')
            notes = ['Bildbeleg: OCR noch nicht verfügbar; Angaben manuell erfassen.']
        elif mime == 'image/png':
            if not data.startswith(b'\x89PNG\r\n\x1a\n'): raise BookkeepingError('PNG-Kennung fehlt.')
            notes = ['Bildbeleg: OCR noch nicht verfügbar; Angaben manuell erfassen.']
        return self._store(user, data, filename, mime, source, fields, notes)

    @_locked
    def ingest_billomat(self, user, invoice):
        _user(user)
        if not isinstance(invoice, dict) or set(invoice) - (FIELDS | {'id', 'invoice_id'}):
            raise BookkeepingError('Billomat benötigt normalisierte Belegfelder ohne Zugangsdaten.')
        ident = invoice.get('invoice_id', invoice.get('id'))
        if not isinstance(ident, (str, int)) or isinstance(ident, bool) or not str(ident) or len(str(ident)) > 100:
            raise BookkeepingError('Billomat-Belegkennung fehlt.')
        fields = _fields({key: value for key, value in invoice.items() if key in FIELDS})
        fields['direction'] = invoice.get('direction', 'outgoing')
        fields['source_currency'] = fields['currency']
        snapshot = {'invoice_id': str(ident), 'fields': fields}
        data = _json(snapshot).encode()
        source = {'provider': 'billomat', 'invoice_id': str(ident)}
        sha = hashlib.sha256(data).hexdigest()
        notes = ['Unveränderter normalisierter Billomat-Datenstand; Rechnungs-PDF separat, falls verfügbar. Zahlungsstatus stammt nur aus expliziten Quelldaten.']
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id,sha256,fields_json,reviewed FROM atlas_bookkeeping WHERE user_id=? AND source_json=?', (user,_json(source))).fetchone()
            if prior and prior[1] != sha:
                record_id = prior[0]
                folder = self.root / hashlib.sha256(user.encode()).hexdigest()
                file = folder / sha
                try:
                    with file.open('xb') as handle:
                        os.chmod(file, 0o600)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                        raise BookkeepingError('Datenstand ist beschädigt.') from None
                stamp = _now()
                before = {'fields':json.loads(prior[2]), 'reviewed':bool(prior[3]), 'sha256':prior[1]}
                # Preserve manual completion when the source still has no value;
                # explicit source values and source-status always win, with a new review.
                refreshed = dict(before['fields'])
                for key, value in fields.items():
                    if value != '' or key.startswith('source_'):
                        refreshed[key] = value
                refreshed = _fields(refreshed)
                after = {'fields':refreshed, 'reviewed':False, 'sha256':sha}
                db.execute('UPDATE atlas_bookkeeping SET sha256=?,original_path=?,fields_json=?,notes_json=?,reviewed=0 WHERE user_id=? AND id=?', (sha,str(file.relative_to(self.root)),_json(refreshed),_json(notes),user,record_id))
                db.execute('INSERT OR IGNORE INTO atlas_bookkeeping_snapshots VALUES (?,?,?,?,?)', (user,record_id,sha,str(file.relative_to(self.root)),stamp))
                db.execute('INSERT INTO atlas_bookkeeping_audit(user_id,record_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)', (user,record_id,'source_refresh',_json(before),_json(after),stamp))
            elif prior:
                record_id = prior[0]
            else:
                record_id = None
        if record_id:
            result = self.get(user,record_id)
            result['duplicate'] = prior[1] == sha
            return result
        return self._store(user, data, _filename('billomat-' + str(ident), '.json'), 'application/json', source, fields, notes)


    @_locked
    def review(self, user, ident, fields):
        _user(user)
        if not isinstance(fields, dict) or set(fields) - ((FIELDS - {'source_status', 'source_open_amount', 'source_due_date', 'source_currency'}) | {'reviewed'}):
            raise BookkeepingError('Prüffelder ungültig.')
        reviewed = fields.get('reviewed', False)
        if not isinstance(reviewed, bool): raise BookkeepingError('Prüfbestätigung muss wahr oder falsch sein.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fields_json,reviewed FROM atlas_bookkeeping WHERE user_id=? AND id=?', (user, ident)).fetchone()
            if row is None: raise BookkeepingError('Beleg nicht gefunden.')
            before = {'fields': json.loads(row[0]), 'reviewed': bool(row[1])}
            merged = dict(before['fields'])
            merged.update({key: value for key, value in fields.items() if key != 'reviewed'})
            merged = _fields(merged)
            if reviewed and _issues(merged):
                raise BookkeepingError('Pflichtfelder und Betragsprüfung zuerst vervollständigen.')
            after = {'fields': merged, 'reviewed': reviewed}
            db.execute('UPDATE atlas_bookkeeping SET fields_json=?,reviewed=? WHERE user_id=? AND id=?', (_json(merged), int(reviewed), user, ident))
            db.execute('INSERT INTO atlas_bookkeeping_audit(user_id,record_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)', (user, ident, 'review', _json(before), _json(after), _now()))
        return self.get(user, ident)

    @_locked
    def attach_original(self, user, ident, data, filename, mime='application/pdf'):
        _user(user)
        if mime != 'application/pdf' or not isinstance(data, bytes) or not 0 < len(data) <= MAX_FILE or not data.startswith(b'%PDF-'):
            raise BookkeepingError('Rechnungsoriginal muss PDF bis 12 MiB sein.')
        filename = _filename(filename, '.pdf')
        sha = hashlib.sha256(data).hexdigest()
        owner = hashlib.sha256(user.encode()).hexdigest()
        folder = self.root / owner
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT source_json FROM atlas_bookkeeping WHERE user_id=? AND id=?', (user, ident)).fetchone()
            if row is None or json.loads(row[0])['provider'] != 'billomat':
                raise BookkeepingError('Billomat-Beleg nicht gefunden.')
            prior = db.execute('SELECT sha256 FROM atlas_bookkeeping_documents WHERE user_id=? AND record_id=?', (user, ident)).fetchone()
            if prior and prior[0] != sha:
                raise BookkeepingError('Ein abweichendes Original ist bereits vorhanden.')
            if not prior:
                file = folder / sha
                try:
                    with file.open('xb') as handle:
                        os.chmod(file, 0o600)
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                except FileExistsError:
                    if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                        raise BookkeepingError('Originaldatei ist beschädigt.') from None
                stamp = _now()
                db.execute('INSERT INTO atlas_bookkeeping_documents VALUES (?,?,?,?,?,?,?)', (user, ident, sha, filename, mime, str(file.relative_to(self.root)), stamp))
                db.execute('INSERT INTO atlas_bookkeeping_audit(user_id,record_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)', (user, ident, 'attach_original', None, _json({'sha256':sha, 'filename':filename}), stamp))
        return self.get(user, ident)

    def get_document(self, user, ident):
        _user(user)
        with self.db() as db:
            row = db.execute('SELECT original_path,filename,mime,sha256 FROM atlas_bookkeeping_documents WHERE user_id=? AND record_id=?', (user, ident)).fetchone()
            if row is None:
                row = db.execute('SELECT original_path,filename,mime,sha256 FROM atlas_bookkeeping WHERE user_id=? AND id=?', (user, ident)).fetchone()
        if row is None: return None
        path = (self.root / row[0]).resolve()
        if not path.is_relative_to(self.root.resolve()): raise BookkeepingError('Originalpfad ungültig.')
        try:
            if path.stat().st_size > MAX_FILE: raise BookkeepingError('Originaldatei ist zu groß.')
            data = path.read_bytes()
        except OSError:
            raise BookkeepingError('Originaldatei nicht verfügbar.') from None
        if hashlib.sha256(data).hexdigest() != row[3]: raise BookkeepingError('Originaldatei ist beschädigt.')
        return data, row[1], row[2]

    @_locked
    def export(self, user, month):
        _user(user)
        if not isinstance(month, str) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])', month):
            raise BookkeepingError('Monat benötigt YYYY-MM.')
        # Filter the complete owner's dataset before applying the explicit export
        # budget. The UI list limit must never hide an older month's documents.
        with self.db() as db:
            rows = db.execute('''SELECT id,sha256,filename,mime,source_json,fields_json,notes_json,reviewed,created_at
                FROM atlas_bookkeeping WHERE user_id=? AND
                (json_extract(fields_json, '$.invoice_date') LIKE ? OR COALESCE(json_extract(fields_json, '$.invoice_date'),'')='')
                ORDER BY created_at DESC,rowid DESC LIMIT ?''', (user, month + '-%', MAX_EXPORT_FILES + 1)).fetchall()
        if len(rows) > MAX_EXPORT_FILES: raise BookkeepingError('Export enthält mehr als 2000 Belege; Auswahl eingrenzen.')
        records = [self._record(row) for row in rows]
        output, csv_out = io.BytesIO(), io.StringIO(newline='')
        writer = csv.writer(csv_out, delimiter=';')
        columns = ['id','status','direction','supplier','invoice_number','invoice_date','currency','net','tax','gross','payment_status','sha256','original']
        writer.writerow(columns)
        manifest = {'format': 'ATLAS Belegvorbereitung 1', 'month': month, 'created_at': _now(), 'notice': 'Vorbereitung für Prüfung; kein DATEV-Import und keine Buchung. Undatierte Belege sind als ungeklärt enthalten. Zahlungsstatus unknown bedeutet nicht bezahlt oder unbezahlt. ai-bookkeeping.documents.json folgt documents/1; enthaltene Belege bleiben prüfpflichtig, ausgelassene Fälle sind dort in notes dokumentiert.', 'records': []}
        unresolved, total, manifest_bytes = [], 0, 0
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                data, name, mime = self.get_document(user, record['id'])
                total += len(data)
                if total > MAX_EXPORT_BYTES: raise BookkeepingError('Export überschreitet 100 MiB.')
                original = 'originale/' + record['id'] + '-' + name
                archive.writestr(original, data)
                values = {**record['fields'], 'id':record['id'], 'status':record['status'], 'sha256':hashlib.sha256(data).hexdigest(), 'original':original}
                # Protect spreadsheets, even whitespace-prefixed formula text and negative amounts.
                writer.writerow([("'" + str(values[key])) if str(values[key]).lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else str(values[key]) for key in columns])
                full = self.get(user, record['id'])
                with self.db() as db:
                    snapshots = db.execute('SELECT sha256,original_path FROM atlas_bookkeeping_snapshots WHERE user_id=? AND record_id=? ORDER BY created_at', (user,record['id'])).fetchall()
                full['snapshot_files'] = []
                for snapshot_sha, snapshot_path in snapshots:
                    snapshot_file = (self.root / snapshot_path).resolve()
                    if not snapshot_file.is_relative_to(self.root.resolve()) or snapshot_file.stat().st_size > MAX_FILE:
                        raise BookkeepingError('Billomat-Datenstand ist ungültig.')
                    snapshot = snapshot_file.read_bytes()
                    if hashlib.sha256(snapshot).hexdigest() != snapshot_sha:
                        raise BookkeepingError('Billomat-Datenstand ist beschädigt.')
                    total += len(snapshot)
                    if total > MAX_EXPORT_BYTES: raise BookkeepingError('Export überschreitet 100 MiB.')
                    snapshot_name = 'datenstaende/' + record['id'] + '-' + snapshot_sha[:16] + '.json'
                    archive.writestr(snapshot_name, snapshot)
                    full['snapshot_files'].append({'file':snapshot_name,'sha256':snapshot_sha})
                manifest_record = {**full, 'original':original, 'original_sha256':hashlib.sha256(data).hexdigest()}
                # Bound accumulation across many small documents before keeping
                # another full history in memory. The exact final check below
                # also includes bridge, CSV, unresolved items and wrapper bytes.
                manifest_bytes += len(_json(manifest_record).encode('utf-8'))
                if total + manifest_bytes > MAX_EXPORT_BYTES:
                    raise BookkeepingError('Export einschließlich Prüfdaten überschreitet 100 MiB.')
                manifest['records'].append(manifest_record)
                if record['status'] != 'reviewed' or record['fields']['payment_status'] == 'unknown':
                    unresolved.append({'id':record['id'], 'filename':name, 'issues':record['issues'], 'manual_review_required':record['status'] != 'reviewed', 'payment_unknown':record['fields']['payment_status'] == 'unknown'})
            bridge = documents_v1(manifest['records'])
            metadata_size = len(_json(manifest).encode()) + len(_json(bridge).encode()) + len(csv_out.getvalue().encode()) + len(_json(unresolved).encode())
            if total + metadata_size > MAX_EXPORT_BYTES:
                raise BookkeepingError('Export einschließlich Prüfdaten überschreitet 100 MiB.')
            archive.writestr('ai-bookkeeping.documents.json', _json(bridge))
            archive.writestr('belege.csv', '\ufeff' + csv_out.getvalue())
            archive.writestr('manifest.json', _json(manifest))
            archive.writestr('ungeklaert.json', _json(unresolved))
            archive.writestr('HINWEIS.txt', manifest['notice'])
        return output.getvalue()
