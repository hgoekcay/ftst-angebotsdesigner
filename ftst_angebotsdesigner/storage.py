"""Durable presentation overrides; Billomat remains the source of commercial data."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


class StorageError(RuntimeError):
    pass


def data_directory():
    configured = os.environ.get('FTST_DATA_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name != 'nt' and Path('/data').is_dir():
        return Path('/data/ftst_angebotsdesigner')
    # Predictable local fallback, never a temporary or in-memory database.
    return Path(__file__).resolve().parent / 'instance'


class OfferStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'offers.sqlite3'

    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 2:
                raise StorageError('Neuere Datenbankversion. Bitte die passende App-Version verwenden.')
            if version == 0:
                db.execute('CREATE TABLE IF NOT EXISTS presentations ('
                           'account TEXT NOT NULL, offer_id TEXT NOT NULL, payload TEXT NOT NULL, '
                           'updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, '
                           'PRIMARY KEY(account, offer_id))')
                db.execute('PRAGMA user_version=1')
            if version < 2:
                db.execute('CREATE TABLE IF NOT EXISTS records ('
                           'account TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, '
                           'payload TEXT NOT NULL, PRIMARY KEY(account,kind,id))')
                db.execute('PRAGMA user_version=2')
            db.commit()
            return db
        except Exception:
            db.close()
            raise

    def load(self, account, offer_id, legacy=None):
        try:
            with closing(self._connect()) as db, db:
                if isinstance(legacy, dict) and legacy:
                    # Older browser cookies must never overwrite a newer database edit.
                    db.execute('INSERT OR IGNORE INTO presentations(account,offer_id,payload) VALUES(?,?,?)',
                               (account, str(offer_id), json.dumps(legacy, ensure_ascii=False)))
                row = db.execute('SELECT payload FROM presentations WHERE account=? AND offer_id=?',
                                 (account, str(offer_id))).fetchone()
                result = json.loads(row[0]) if row else {}
                if not isinstance(result, dict):
                    raise ValueError('Invalid presentation data')
                return result
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise StorageError('Gespeicherte Angebotsdaten sind derzeit nicht verfügbar. Bitte erneut versuchen; die Datenbank bleibt erhalten.') from exc

    def save(self, account, offer_id, source):
        try:
            with closing(self._connect()) as db, db:
                db.execute('INSERT INTO presentations(account,offer_id,payload) VALUES(?,?,?) '
                           'ON CONFLICT(account,offer_id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP',
                           (account, str(offer_id), json.dumps(source, ensure_ascii=False)))
        except (sqlite3.Error, OSError) as exc:
            raise StorageError('Änderungen konnten nicht dauerhaft gespeichert werden. Bitte Eingaben sichern und erneut versuchen.') from exc

    def check(self):
        try:
            with closing(self._connect()) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise StorageError('Datenbankprüfung fehlgeschlagen.')
        except (sqlite3.Error, OSError) as exc:
            raise StorageError('Datenbank nicht verfügbar.') from exc

    def records(self, account, kind):
        try:
            with closing(self._connect()) as db:
                rows = db.execute('SELECT id,payload FROM records WHERE account=? AND kind=? ORDER BY rowid DESC', (account, kind)).fetchall()
                return {key: json.loads(value) for key, value in rows}
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise StorageError('Projektdaten sind derzeit nicht verfügbar.') from exc

    def put_record(self, account, kind, key, value):
        try:
            with closing(self._connect()) as db, db:
                db.execute('INSERT INTO records(account,kind,id,payload) VALUES(?,?,?,?) '
                           'ON CONFLICT(account,kind,id) DO UPDATE SET payload=excluded.payload',
                           (account, kind, key, json.dumps(value, ensure_ascii=False)))
        except (sqlite3.Error, OSError) as exc:
            raise StorageError('Projektdaten konnten nicht gespeichert werden.') from exc
