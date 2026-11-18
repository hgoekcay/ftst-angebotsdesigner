"""Isolated draft reservations, NOT payments or a production reconciliation API.

The service must authenticate actor and authorize snapshot provisioning. Snapshot
freshness cannot be guaranteed across the separate Bookkeeping database. Never
expose provisioning directly to form input. All lifecycle writes are atomic in
this staging DB; invoice/payment records are never changed.
"""
import json
from contextlib import closing
from datetime import datetime, timezone

from bank_statements import StatementStore
from bank_validation import BankValidationError, _id, _cents, _money, preview_allocation


class AllocationConflict(BankValidationError):
    pass


def _scope(actor, owner, account):
    actor, owner, account = _id(actor), _id(owner), _id(account)
    if actor != owner:
        raise AllocationConflict('Zugriff nicht erlaubt.')
    return owner, account


class DraftAllocations(StatementStore):
    def __init__(self, path):
        super().__init__(path)
        with closing(self._connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bank_draft_accounts_v1 (
                    owner TEXT NOT NULL, account TEXT NOT NULL, PRIMARY KEY(owner,account));
                CREATE TABLE IF NOT EXISTS bank_draft_invoices_v1 (
                    owner TEXT NOT NULL, invoice TEXT NOT NULL, revision TEXT NOT NULL,
                    open_cents INTEGER NOT NULL, direction TEXT NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(owner,invoice));
                CREATE TABLE IF NOT EXISTS bank_draft_batches_v1 (
                    owner TEXT NOT NULL, request_key TEXT NOT NULL, account TEXT NOT NULL,
                    transaction_id TEXT NOT NULL, request_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('reserved_unconfirmed','reversed')),
                    actor TEXT NOT NULL, created_at TEXT NOT NULL,
                    reversed_by TEXT, reversed_at TEXT,
                    PRIMARY KEY(owner,request_key));
                CREATE TABLE IF NOT EXISTS bank_draft_lines_v1 (
                    owner TEXT NOT NULL, request_key TEXT NOT NULL, invoice TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents>0), revision TEXT NOT NULL,
                    PRIMARY KEY(owner,request_key,invoice),
                    FOREIGN KEY(owner,request_key) REFERENCES bank_draft_batches_v1(owner,request_key),
                    FOREIGN KEY(owner,invoice) REFERENCES bank_draft_invoices_v1(owner,invoice));
            ''')

    def provision_account(self, *, actor, owner, account):
        """Trusted setup only; actor must come from authenticated service context."""
        owner, account = _scope(actor, owner, account)
        with closing(self._connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO bank_draft_accounts_v1 VALUES (?,?)', (owner, account))

    def _account(self, db, owner, account):
        if not db.execute('SELECT 1 FROM bank_draft_accounts_v1 WHERE owner=? AND account=?', (owner, account)).fetchone():
            raise AllocationConflict('Konto nicht freigegeben.')

    def freeze_invoice(self, *, actor, owner, invoice, revision, open_amount, direction, expected_revision=None):
        """Trusted reviewed-source adapter only; freeze baseline, not a live balance.

        Refuse changes while active reservations exist: new source open amounts
        may already reflect payments, so subtracting old reservations is unsafe.
        """
        _scope(actor, owner, 'unused')
        invoice, revision = _id(invoice), _id(revision)
        cents = _cents(open_amount)
        if cents < 0 or direction not in ('incoming', 'outgoing'):
            raise AllocationConflict('Rechnungsbasis ungültig.')
        conflict = False
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT revision,open_cents,direction,blocked FROM bank_draft_invoices_v1 WHERE owner=? AND invoice=?', (owner, invoice)).fetchone()
            new = (revision, cents, direction)
            if prior and prior[:3] == new:
                if prior[3]:
                    raise AllocationConflict('Rechnungsbasis wartet auf erneute Prüfung.')
                return
            if (prior[0] if prior else None) != expected_revision:
                raise AllocationConflict('Rechnungsbasis inzwischen geändert; erneut laden.')
            if (prior and prior[0] == revision) or self._invoice_used(db, owner, invoice):
                db.execute('UPDATE bank_draft_invoices_v1 SET blocked=1 WHERE owner=? AND invoice=?', (owner, invoice))
                conflict = True
            else:
                db.execute('INSERT INTO bank_draft_invoices_v1 VALUES (?,?,?,?,?,0) ON CONFLICT(owner,invoice) DO UPDATE SET revision=excluded.revision,open_cents=excluded.open_cents,direction=excluded.direction,blocked=0', (owner, invoice, *new))
        if conflict:
            raise AllocationConflict('Quellstand geändert; aktive Entwürfe zuerst prüfen und zurücknehmen.')

    def get_invoice_basis(self, *, actor, owner, invoice):
        _scope(actor, owner, 'unused')
        invoice = _id(invoice)
        with closing(self._connect()) as db:
            row = db.execute('SELECT revision,open_cents,direction,blocked FROM bank_draft_invoices_v1 WHERE owner=? AND invoice=?', (owner, invoice)).fetchone()
        if row is None:
            return None
        return {'revision': row[0], 'open_amount': _money(row[1]),
                'direction': row[2], 'blocked': bool(row[3]), 'state': 'unconfirmed_source_basis'}

    def invalidate_invoice(self, *, actor, owner, invoice):
        """Trusted adapter must call this on canceled/unusable/unknown source state."""
        _scope(actor, owner, 'unused')
        invoice = _id(invoice)
        with closing(self._connect()) as db, db:
            result = db.execute('UPDATE bank_draft_invoices_v1 SET blocked=1 WHERE owner=? AND invoice=?', (owner, invoice))
            if not result.rowcount:
                raise AllocationConflict('Rechnungsbasis nicht verfügbar.')

    def _invoice_used(self, db, owner, invoice):
        return db.execute("SELECT COALESCE(SUM(l.amount_cents),0) FROM bank_draft_lines_v1 l JOIN bank_draft_batches_v1 b USING(owner,request_key) WHERE l.owner=? AND l.invoice=? AND b.state='reserved_unconfirmed'", (owner, invoice)).fetchone()[0]

    def reserve(self, *, actor, owner, account, transaction_id, request_key, selections):
        owner, account = _scope(actor, owner, account)
        transaction_id, request_key = _id(transaction_id), _id(request_key)
        if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
            raise AllocationConflict('Auswahl fehlt oder überschreitet das Limit.')
        normalized = []
        for item in selections:
            if not isinstance(item, dict) or set(item) != {'invoice_id', 'revision', 'amount'}:
                raise AllocationConflict('Auswahlfelder ungültig.')
            normalized.append(dict(invoice_id=_id(item['invoice_id']), revision=_id(item['revision']), amount=_money(_cents(item['amount']))))
        normalized.sort(key=lambda row: row['invoice_id'])
        request = json.dumps(dict(account=account, transaction_id=transaction_id, selections=normalized), sort_keys=True)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._account(db, owner, account)
            previous = db.execute('SELECT request_json,state FROM bank_draft_batches_v1 WHERE owner=? AND request_key=?', (owner, request_key)).fetchone()
            if previous:
                if previous[0] != request:
                    raise AllocationConflict('Wiederholungsschlüssel bereits anders verwendet.')
                return {'request_key': request_key, 'state': previous[1], 'replayed': True}
            tx = db.execute('SELECT payload FROM bank_transactions_v1 WHERE owner=? AND account=? AND transaction_id=?', (owner, account, transaction_id)).fetchone()
            if tx is None:
                raise AllocationConflict('Bankbewegung nicht verfügbar.')
            amount = _cents(json.loads(tx[0])['amount'])
            used = db.execute("SELECT COALESCE(SUM(l.amount_cents),0) FROM bank_draft_lines_v1 l JOIN bank_draft_batches_v1 b USING(owner,request_key) WHERE b.owner=? AND b.account=? AND b.transaction_id=? AND b.state='reserved_unconfirmed'", (owner, account, transaction_id)).fetchone()[0]
            remaining = abs(amount) - used
            if remaining <= 0:
                raise AllocationConflict('Bankbewegung vollständig reserviert.')
            rows = []
            direction = 'outgoing' if amount > 0 else 'incoming'
            for item in normalized:
                inv = db.execute('SELECT revision,open_cents,direction,blocked FROM bank_draft_invoices_v1 WHERE owner=? AND invoice=?', (owner, item['invoice_id'])).fetchone()
                if inv is None or inv[3] or inv[0] != item['revision']:
                    raise AllocationConflict('Rechnungsbasis fehlt oder Revision ist veraltet.')
                rows.append(dict(invoice_id=item['invoice_id'], amount=item['amount'], currency='EUR', direction=inv[2], open_amount=_money(inv[1] - self._invoice_used(db, owner, item['invoice_id']))))
            preview_allocation(available_amount=_money(remaining if amount > 0 else -remaining), direction=direction, allocations=rows)
            db.execute('INSERT INTO bank_draft_batches_v1 VALUES (?,?,?,?,?,?,?,?,?,?)', (owner, request_key, account, transaction_id, request, 'reserved_unconfirmed', actor, datetime.now(timezone.utc).isoformat(), None, None))
            for item in normalized:
                db.execute('INSERT INTO bank_draft_lines_v1 VALUES (?,?,?,?,?)', (owner, request_key, item['invoice_id'], _cents(item['amount']), item['revision']))
        return {'request_key': request_key, 'state': 'reserved_unconfirmed', 'replayed': False}

    def reverse(self, *, actor, owner, account, request_key):
        owner, account = _scope(actor, owner, account)
        request_key = _id(request_key)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._account(db, owner, account)
            row = db.execute('SELECT state FROM bank_draft_batches_v1 WHERE owner=? AND account=? AND request_key=?', (owner, account, request_key)).fetchone()
            if row is None:
                raise AllocationConflict('Entwurf nicht verfügbar.')
            if row[0] == 'reversed':
                return {'request_key': request_key, 'state': 'reversed', 'replayed': True}
            db.execute("UPDATE bank_draft_batches_v1 SET state='reversed',reversed_by=?,reversed_at=? WHERE owner=? AND account=? AND request_key=?", (actor, datetime.now(timezone.utc).isoformat(), owner, account, request_key))
        return {'request_key': request_key, 'state': 'reversed', 'replayed': False}
