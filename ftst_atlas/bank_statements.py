"""Isolated canonical-statement staging; no routes, payment writes or default DB.

Caller must resolve authenticated owner and an account they own. IDs supplied to
this repository provide data scoping, not authentication. Explicit path only.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from bank_validation import BankValidationError, _id, validate_csv


class StatementConflict(BankValidationError):
    """Safe conflict without bank/customer data."""


class StatementStore:
    def __init__(self, path):
        if not isinstance(path, (str, os.PathLike)):
            raise ValueError('Explicit persistent staging path required.')
        self.path = os.fspath(path)
        if not self.path or self.path == ':memory:':
            raise ValueError('Explicit persistent staging path required.')
        with closing(self._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bank_statements_v1 (
                    owner TEXT NOT NULL, account TEXT NOT NULL, digest TEXT NOT NULL,
                    source BLOB NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, account, digest)
                );
                CREATE TABLE IF NOT EXISTS bank_transactions_v1 (
                    owner TEXT NOT NULL, account TEXT NOT NULL, transaction_id TEXT NOT NULL,
                    digest TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (owner, account, transaction_id),
                    FOREIGN KEY (owner, account, digest)
                        REFERENCES bank_statements_v1 (owner, account, digest)
                );
            ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def import_csv(self, owner, account, data, *, opening_balance, closing_balance,
                   start_date, end_date):
        """Atomic immutable staging. Same bytes/metadata replay; overlaps reject all.

        Transaction IDs must be stable within this account across files. No
        automatic deduplication by date/amount, and no financial settlement claim.
        """
        owner, account = _id(owner), _id(account)
        preview = validate_csv(data, opening_balance=opening_balance,
                               closing_balance=closing_balance, start_date=start_date,
                               end_date=end_date)
        metadata = json.dumps(dict(opening_balance=preview['opening_balance'],
                                   closing_balance=preview['closing_balance'],
                                   start_date=start_date, end_date=end_date), sort_keys=True)
        digest = hashlib.sha256(data).hexdigest()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT metadata FROM bank_statements_v1 WHERE owner=? AND account=? AND digest=?',
                                  (owner, account, digest)).fetchone()
            if existing:
                if existing[0] != metadata:
                    raise StatementConflict('Identische Quelldatei mit widersprüchlichen Auszugsangaben.')
                return {'digest': digest, 'status': 'already_staged',
                        'transaction_count': len(preview['transactions'])}
            try:
                db.execute('INSERT INTO bank_statements_v1 VALUES (?,?,?,?,?,?)',
                           (owner, account, digest, data, metadata, datetime.now(timezone.utc).isoformat()))
                for row in preview['transactions']:
                    db.execute('INSERT INTO bank_transactions_v1 VALUES (?,?,?,?,?)',
                               (owner, account, row['transaction_id'], digest,
                                json.dumps(row, sort_keys=True)))
            except sqlite3.IntegrityError:
                raise StatementConflict('Transaktionsreferenz bereits vorhanden; Auszug vollständig abgelehnt.') from None
        return {'digest': digest, 'status': 'staged_unreconciled',
                'transaction_count': len(preview['transactions'])}

    def get_statement(self, owner, account, digest):
        owner, account = _id(owner), _id(account)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise BankValidationError('Quellreferenz ungültig.')
        with closing(self._connect()) as db:
            row = db.execute('SELECT source, metadata, created_at FROM bank_statements_v1 WHERE owner=? AND account=? AND digest=?',
                             (owner, account, digest)).fetchone()
        if row is None:
            return None
        return {'digest': digest, 'source': row[0], 'metadata': json.loads(row[1]),
                'created_at': row[2], 'status': 'staged_unreconciled'}
