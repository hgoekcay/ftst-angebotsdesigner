"""Bounded, owner-authorized read-only imports. No model calls or mail mutations.

A source cursor is committed only after every document in its batch is durable.
Retries rely on bookkeeping content/source deduplication. Live Billomat pagination
is checked for changes, but is not an immutable accounting snapshot.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import threading

from mail_client import UIDValidityChanged


class SyncError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _bounded(value, default, minimum, maximum):
    return value if type(value) is int and minimum <= value <= maximum else default


class BookkeepingSync:
    def __init__(self, options, db_factory, bookkeeping, mail, billomat):
        self.db, self.bookkeeping, self.mail, self.billomat = db_factory, bookkeeping, mail, billomat
        self.owner = options.get('bookkeeping_ha_user_id') or ''
        self.enabled = options.get('bookkeeping_enabled') is True and isinstance(self.owner, str) and 0 < len(self.owner) <= 128
        self.auto = options.get('bookkeeping_auto_sync') is True
        self.interval = _bounded(options.get('bookkeeping_interval_seconds'), 3600, 900, 86400)
        self.days = _bounded(options.get('bookkeeping_lookback_days'), 30, 1, 365)
        self.account_ids = options.get('mail_account_ids') or [options.get('mail_account_id') or 'primary']
        if not isinstance(self.account_ids, list) or len(self.account_ids) > 21 or any(not isinstance(x, str) or not 1 <= len(x) <= 40 for x in self.account_ids):
            self.account_ids = []
        self._lock, self._lifecycle = threading.Lock(), threading.Lock()
        self._stop, self._thread = threading.Event(), None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS atlas_bookkeeping_sync (owner TEXT, source TEXT, state TEXT NOT NULL, PRIMARY KEY(owner,source))')
            db.execute('CREATE TABLE IF NOT EXISTS atlas_bookkeeping_refresh (owner TEXT, invoice_id TEXT, checked_at TEXT NOT NULL DEFAULT \'\', attempted_at TEXT NOT NULL DEFAULT \'\', PRIMARY KEY(owner,invoice_id))')
            db.execute('CREATE TABLE IF NOT EXISTS atlas_bookkeeping_pdfs (owner TEXT, invoice_id TEXT, record_id TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,invoice_id))')

    def enabled_for(self, user):
        return bool(self.enabled and isinstance(user, str) and user == self.owner)

    def _get(self, key):
        with self.db() as db:
            row = db.execute('SELECT state FROM atlas_bookkeeping_sync WHERE owner=? AND source=?', (self.owner, key)).fetchone()
        return json.loads(row[0]) if row else {}

    def _put(self, key, state):
        raw = json.dumps(state, ensure_ascii=False, allow_nan=False)
        if len(raw.encode()) > 16384:
            raise SyncError('Importstatus überschreitet das Größenlimit.')
        with self.db() as db:
            db.execute('INSERT INTO atlas_bookkeeping_sync VALUES(?,?,?) ON CONFLICT(owner,source) DO UPDATE SET state=excluded.state', (self.owner, key, raw))

    def status(self, user):
        if not self.enabled_for(user):
            return {'enabled': False, 'auto_sync': False, 'running': False}
        result = self._get('summary')
        with self.db() as db:
            pending = db.execute('SELECT COUNT(*) FROM atlas_bookkeeping_pdfs WHERE owner=? AND done=0', (self.owner,)).fetchone()[0]
        return dict(result, enabled=True, auto_sync=self.auto, running=self._lock.locked(), interval_seconds=self.interval,
                    pending_pdfs=pending, pending=bool(result.get('pending') or pending))

    def sync(self, user):
        if not self.enabled_for(user):
            raise SyncError('Belegimport ist für diesen Benutzer nicht freigegeben.')
        if not self._lock.acquire(blocking=False):
            raise SyncError('Ein Belegimport läuft bereits.')
        summary = {'last_run': _now(), 'last_finished': None, 'counts': {'mail_messages': 0, 'documents': 0, 'billomat_invoices': 0, 'pdfs': 0},
                   'errors': [], 'sources': [], 'pending': False}
        try:
            self._put('summary', summary)
            if self.mail.enabled_for(user):
                try:
                    accounts = self.mail.accounts(user)
                    for account_id in self.account_ids[:21]:
                        if self._stop.is_set():
                            summary['pending'] = True
                            break
                        selected = [a for a in accounts if a['id'] == account_id]
                        if len(selected) != 1:
                            summary['sources'].append({'id': account_id, 'type': 'mail', 'pending': True, 'error': 'Freigegebenes Postfach nicht verfügbar.', 'warnings': 0})
                        else:
                            summary['sources'].append(self._mail(user, selected[0], summary['counts']))
                except Exception:
                    summary['errors'].append('Postfachliste konnte nicht sicher abgerufen werden.')
                    summary['pending'] = True
            if self.billomat.enabled_for(user) and not self._stop.is_set():
                summary['sources'].append(self._billomat(user, summary['counts']))
                if not summary['sources'][-1].get('binding_changed'):
                    summary['sources'].append(self._refresh_open_invoices(user, summary['counts']))
                    self._pdfs(user, summary)
            if not summary['sources'] and not summary['errors']:
                summary['errors'].append('Keine freigegebene Importquelle eingerichtet.')
            summary['pending'] = bool(summary['pending'] or summary['errors'] or any(s.get('pending') for s in summary['sources']))
            summary['last_finished'] = _now()
            self._put('summary', summary)
            result = self.status(user)
            result['running'] = False
            result['reply'] = ('Belegimport beendet. ' + str(summary['counts']['documents']) + ' Mail-Belege und ' + str(summary['counts']['billomat_invoices']) + ' Billomat-Snapshots verarbeitet. '
                               + ('Weitere Belege oder Prüfungen sind offen.' if result['pending'] else 'Belege bleiben bis zur Prüfung unbestätigt.'))
            return result
        finally:
            self._lock.release()

    def _mail(self, user, account, counts):
        key = 'mail:' + account['id']
        state = self._get(key)
        binding = hashlib.sha256(json.dumps([account['email'], account['folder']], ensure_ascii=False).encode()).hexdigest()
        if state.get('binding') != binding:
            changed = bool(state)
            state = {'binding': binding, 'since': (date.today() - timedelta(days=self.days - 1)).isoformat(), 'after_uid': 0, 'uidvalidity': None,
                     'warnings': 1 if changed else 0}
        state.update(id=account['id'], type='mail', pending=True, error='', last_run=_now())
        try:
            for _ in range(3):
                if self._stop.is_set():
                    break
                try:
                    batch = self.mail.invoice_batch(user, account['id'], self.days, after_uid=state['after_uid'], uidvalidity=state['uidvalidity'], since=state['since'])
                except UIDValidityChanged:
                    state.update(after_uid=0, uidvalidity=None, pending=True, warnings=min(999999, state.get('warnings', 0) + 1))
                    self._put(key, state)
                    break
                source = batch['source']
                if (source['account_id'], source['mailbox'], source['folder']) != (account['id'], account['email'], account['folder']):
                    raise SyncError('Quelle geändert.')
                warnings = 0
                for message in batch['messages']:
                    for attachment in message['attachments']:
                        provenance = {'provider': 'mail', 'account_id': account['id'], 'message_uid': str(batch['uidvalidity']) + ':' + str(message['uid']),
                                      'attachment_id': str(attachment['source']['part_index']), 'reference': binding}
                        self.bookkeeping.ingest_document(user, attachment['data'], attachment['name'], attachment['content_type'], provenance)
                        counts['documents'] += 1
                    warnings += len(message.get('warnings', []))
                # Cursor and accumulated warning marker commit together, after all ingests.
                state.update(after_uid=batch['after_uid'], uidvalidity=batch['uidvalidity'], pending=batch['pending'], warnings=min(999999, state.get('warnings', 0) + warnings))
                self._put(key, state)
                counts['mail_messages'] += len(batch['messages'])
                if not batch['pending']:
                    break
        except Exception:
            state.update(error='Postfachimport unvollständig; nicht bestätigte Nachrichten werden erneut geprüft.', pending=True)
        self._put(key, state)
        return {k: state.get(k) for k in ('id', 'type', 'pending', 'error', 'warnings', 'after_uid', 'last_run')} | {'pending': bool(state['pending'] or state.get('warnings'))}

    @staticmethod
    def _normalize(row):
        status = row['status']
        payment = 'paid' if status == 'PAID' else 'unknown'
        if status in ('OPEN', 'OVERDUE') and row.get('paid_amount') is not None:
            try:
                paid = Decimal(row['paid_amount'])
                outstanding = Decimal(row.get('open_amount') or 'NaN')
                if paid.is_finite() and paid == 0:
                    payment = 'unpaid'
                elif paid.is_finite() and outstanding.is_finite() and paid > 0 and outstanding > 0:
                    payment = 'partial'
            except (InvalidOperation, TypeError, ValueError):
                pass
        return {'id': row['id'], 'invoice_number': row['invoice_number'], 'invoice_date': row['date'], 'currency': row['currency_code'],
                'net': row['total_net'], 'gross': row['total_gross'], 'tax': '', 'supplier': '', 'payment_status': payment, 'direction': 'outgoing', 'source_status': status, 'source_open_amount': row.get('open_amount') or '', 'source_due_date': row.get('due_date') or ''}

    def _billomat(self, user, counts):
        key = 'billomat'
        state = self._get(key)
        binding = getattr(self.billomat, 'host', '')
        if state and state.get('binding') != binding:
            return {'id': 'billomat', 'type': 'billomat', 'pending': True, 'warnings': 1, 'binding_changed': True, 'error': 'Billomat-Konto geändert; Quellenzuordnung muss vor weiteren Importen geprüft werden.'}
        if not state or not state.get('pending'):
            state = {'binding': binding, 'date_from': (date.today() - timedelta(days=self.days - 1)).isoformat(), 'date_to': date.today().isoformat(), 'page': 1, 'pending': True, 'warnings': 0}
        state.update(id='billomat', type='billomat', error='', last_run=_now())
        try:
            for _ in range(3):
                if self._stop.is_set():
                    break
                page = self.billomat.list_invoices(user, state['date_from'], state['date_to'], page=state['page'])
                if state['page'] > 1 and state.get('total') != page['total']:
                    state.update(page=1, total=page['total'], pending=True)
                    state.pop('last_order', None)
                    raise SyncError('Live-Liste geändert.')
                ordering = [(r['date'], int(r['id'])) for r in page['invoices']]
                if ordering and state.get('last_order') and ordering[0] <= tuple(state['last_order']):
                    state.update(page=1, pending=True)
                    state.pop('last_order', None)
                    raise SyncError('Live-Reihenfolge geändert.')
                for row in page['invoices']:
                    if row['status'] in ('DRAFT', 'CANCELED'):
                        state['warnings'] = min(999999, state.get('warnings', 0) + 1)
                    if row['status'] == 'DRAFT':
                        continue
                    record = self.bookkeeping.ingest_billomat(user, self._normalize(row))
                    with self.db() as db:
                        db.execute('INSERT OR IGNORE INTO atlas_bookkeeping_pdfs(owner,invoice_id,record_id) VALUES(?,?,?)', (user, row['id'], record['id']))
                    counts['billomat_invoices'] += 1
                state.update(page=page['next_page'] or 1, total=page['total'], pending=page['pending'])
                if ordering:
                    state['last_order'] = list(ordering[-1])
                self._put(key, state)
                if not page['pending']:
                    break
        except Exception:
            state.update(error='Billomat-Import unvollständig; Abruf oder geänderte Seitenfolge muss erneut geprüft werden.', pending=True)
        self._put(key, state)
        return {k: state.get(k) for k in ('id', 'type', 'pending', 'error', 'warnings', 'page', 'last_run')} | {'pending': bool(state['pending'] or state.get('warnings'))}

    def _refresh_open_invoices(self, user, counts):
        """Recheck unresolved IDs independently of the invoice discovery window.

        A durable cycle and oldest-attempt ordering bound each run to 25 reads
        without starving later IDs when an earlier invoice cannot be fetched.
        """
        key = 'billomat_op'
        state = self._get(key)
        if not state.get('pending') or state.get('cycle_attempted'):
            state = {'started_at': datetime.now(timezone.utc).isoformat(), 'pending': True}
        state.update(id=key, type='billomat', error='', last_run=_now(), refreshed=0)
        query = """FROM atlas_bookkeeping b
                   LEFT JOIN atlas_bookkeeping_refresh r
                     ON r.owner=b.user_id AND r.invoice_id=json_extract(b.source_json,'$.invoice_id')
                   WHERE b.user_id=? AND json_extract(b.source_json,'$.provider')='billomat'
                     AND COALESCE(json_extract(b.fields_json,'$.source_status'),'') NOT IN ('PAID','CANCELED','DRAFT')
                     AND COALESCE(r.checked_at,'') < ?"""
        try:
            with self.db() as db:
                rows = db.execute("SELECT json_extract(b.source_json,'$.invoice_id') " + query +
                                  " ORDER BY COALESCE(r.attempted_at,''),b.id LIMIT 25",
                                  (user, state['started_at'])).fetchall()
            for (invoice_id,) in rows:
                if self._stop.is_set():
                    break
                attempted = datetime.now(timezone.utc).isoformat()
                # Mark attempts before network access; failed IDs rotate but stay pending.
                with self.db() as db:
                    db.execute("INSERT INTO atlas_bookkeeping_refresh(owner,invoice_id,attempted_at) VALUES(?,?,?) "
                               "ON CONFLICT(owner,invoice_id) DO UPDATE SET attempted_at=excluded.attempted_at",
                               (user, invoice_id, attempted))
                try:
                    row = self.billomat.get_invoice(user, invoice_id)
                    if row['id'] != invoice_id or row['status'] == 'DRAFT':
                        raise SyncError('Rechnungskennung oder Status ungeklärt.')
                    self.bookkeeping.ingest_billomat(user, self._normalize(row))
                    with self.db() as db:
                        db.execute('UPDATE atlas_bookkeeping_refresh SET checked_at=? WHERE owner=? AND invoice_id=?',
                                   (attempted, user, invoice_id))
                    state['refreshed'] += 1
                    counts['billomat_invoices'] += 1
                except Exception:
                    state['error'] = 'Zahlungsstände bestehender Rechnungen konnten nicht vollständig aktualisiert werden.'
            with self.db() as db:
                state['remaining'] = db.execute('SELECT COUNT(*) ' + query, (user, state['started_at'])).fetchone()[0]
                # Completion of attempts advances the next cycle even if an ID keeps
                # failing. Successful OPEN invoices must not remain frozen behind it.
                unattempted = db.execute('SELECT COUNT(*) ' + query + " AND COALESCE(r.attempted_at,'') < ?",
                                         (user, state['started_at'], state['started_at'])).fetchone()[0]
                state['cycle_attempted'] = unattempted == 0
            state['pending'] = bool(state['remaining'])
            if not state['pending']:
                state['last_finished'] = _now()
        except Exception:
            state.update(pending=True, error='Abdeckung der bestehenden offenen Rechnungen konnte nicht geprüft werden.')
        self._put(key, state)
        return dict(state)

    def _pdfs(self, user, summary):
        with self.db() as db:
            rows = db.execute('SELECT invoice_id,record_id FROM atlas_bookkeeping_pdfs WHERE owner=? AND done=0 ORDER BY rowid LIMIT 5', (user,)).fetchall()
        for invoice, record in rows:
            if self._stop.is_set():
                break
            try:
                raw = self.billomat.get_pdf(user, invoice)
                self.bookkeeping.attach_original(user, record, raw, 'billomat-' + invoice + '.pdf', 'application/pdf')
                with self.db() as db:
                    db.execute('UPDATE atlas_bookkeeping_pdfs SET done=1 WHERE owner=? AND invoice_id=?', (user, invoice))
                summary['counts']['pdfs'] += 1
            except Exception:
                summary['errors'].append('Billomat-Original noch nicht verfügbar; PDF-Übernahme bleibt offen.')
                # Rotate unsuccessful items to avoid starving later invoices.
                with self.db() as db:
                    db.execute('DELETE FROM atlas_bookkeeping_pdfs WHERE owner=? AND invoice_id=?', (user, invoice))
                    db.execute('INSERT INTO atlas_bookkeeping_pdfs(owner,invoice_id,record_id) VALUES(?,?,?)', (user, invoice, record))

    def start(self):
        with self._lifecycle:
            if not (self.enabled and self.auto) or self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='atlas-bookkeeping', daemon=True)
            self._thread.start()

    def stop(self, timeout=2):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.sync(self.owner)
            except Exception:
                pass  # Never leak document contents, credentials or remote error text.
            if self._stop.wait(self.interval):
                break
