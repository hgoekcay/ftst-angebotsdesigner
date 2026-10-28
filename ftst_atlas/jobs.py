"""Owner-scoped durable work queue. Only explicitly submitted work is executed.

Running work is never replayed after restart: an external paid request may have
completed even when its response was lost. SQLite contains the local inputs and
results; callers must protect the database and validate the requested action.
"""
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone


class JobError(Exception):
    """A deliberately public, credential-free error supplied by trusted code."""


def _now():
    return datetime.now(timezone.utc).isoformat()


class JobQueue:
    def __init__(self, db_factory, execute_callable):
        self.db = db_factory
        self.execute = execute_callable
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lifecycle = threading.Lock()
        self._thread = None
        # A finished external call may outlive a temporary local DB outage.
        # Keep its bounded completion in memory and retry only the local write.
        self._pending_completion = None
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS atlas_jobs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload TEXT NOT NULL, title TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                finished_at TEXT, result TEXT, error TEXT)''')
            db.execute('CREATE INDEX IF NOT EXISTS atlas_jobs_owner ON atlas_jobs(user_id, created_at)')

    @staticmethod
    def _user(user_id):
        if not isinstance(user_id, str) or not user_id or len(user_id) > 128:
            raise JobError('Benutzerkennung fehlt oder ist ungültig.')

    @staticmethod
    def _public(row):
        if row is None:
            return None
        # Avoid dependence on a caller-specific row_factory.
        ident, status, created, finished, result, error, title = tuple(row)
        return {'id': ident, 'status': status, 'created_at': created,
                'finished_at': finished, 'result': json.loads(result) if result else None,
                'error': error, 'title': title}

    @staticmethod
    def _cleanup(db):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        db.execute("DELETE FROM atlas_jobs WHERE status IN ('completed','failed') AND finished_at < ?", (cutoff,))

    def submit(self, user_id, payload):
        self._user(user_id)
        if not isinstance(payload, dict):
            raise JobError('Auftrag muss ein Objekt sein.')
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, OverflowError):
            raise JobError('Auftrag enthält ungültige Daten.') from None
        if len(encoded.encode('utf-8')) > 32768:
            raise JobError('Auftrag ist zu groß.')
        message = payload.get('message')
        title = message[:120] if isinstance(message, str) and message.strip() else 'ATLAS-Auftrag'
        ident, stamp = secrets.token_urlsafe(24), _now()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self._cleanup(db)
            if db.execute("SELECT 1 FROM atlas_jobs WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone():
                raise JobError('Ein Auftrag läuft bereits. Bitte das Ergebnis abwarten.')
            if db.execute("SELECT COUNT(*) FROM atlas_jobs WHERE status='queued'").fetchone()[0] >= 10:
                raise JobError('Die Warteschlange ist voll. Bitte später erneut versuchen.')
            db.execute('INSERT INTO atlas_jobs(id,user_id,payload,status,created_at,title) VALUES (?,?,?,?,?,?)',
                       (ident, user_id, encoded, 'queued', stamp, title))
        self._wake.set()
        return {'id': ident, 'status': 'queued', 'created_at': stamp,
                'finished_at': None, 'result': None, 'error': None, 'title': title}

    def get(self, user_id, ident):
        self._user(user_id)
        if not isinstance(ident, str) or len(ident) > 100:
            return None
        with self.db() as db:
            row = db.execute('''SELECT id,status,created_at,finished_at,result,error,title
                FROM atlas_jobs WHERE id=? AND user_id=?''', (ident, user_id)).fetchone()
        return self._public(row)

    def list(self, user_id):
        self._user(user_id)
        with self.db() as db:
            self._cleanup(db)
            rows = db.execute('''SELECT id,status,created_at,finished_at,result,error,title
                FROM atlas_jobs WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT 20''', (user_id,)).fetchall()
        return [self._public(row) for row in rows]

    def start(self):
        with self._lifecycle:
            if self._thread is not None and self._thread.is_alive():
                return
            with self.db() as db:
                db.execute("""UPDATE atlas_jobs SET status='failed',finished_at=?,payload='{}',
                    error=? WHERE status='running' AND id<>?""", (_now(),
                    'ATLAS wurde neu gestartet. Der begonnene Auftrag wird nicht automatisch wiederholt.',
                    self._pending_completion[-1] if self._pending_completion else ''))
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='atlas-jobs', daemon=True)
            self._thread.start()

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _process_one(self):
        if self._pending_completion is not None:
            self._finalize_pending()
            return True
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id,user_id,payload FROM atlas_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if row is None:
                return False
            ident, user_id, payload = tuple(row)
            db.execute("UPDATE atlas_jobs SET status='running' WHERE id=?", (ident,))
        result, error, status = None, None, 'completed'
        try:
            result = self.execute(user_id, json.loads(payload))
            if not isinstance(result, dict):
                raise ValueError('Result must be an object')
            result = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(result.encode('utf-8')) > 65536:
                raise ValueError('Result too large')
        except JobError as exc:
            result, status = None, 'failed'
            error = str(exc)[:500] or 'Auftrag konnte nicht abgeschlossen werden.'
        except Exception:
            result, status = None, 'failed'
            error = 'Auftrag konnte nicht abgeschlossen werden. Keine automatische Wiederholung.'
        self._pending_completion = (status, _now(), result, error, ident)
        self._finalize_pending()
        return True

    def _finalize_pending(self):
        completion = self._pending_completion
        if completion is None:
            return
        with self.db() as db:
            # Inputs are no longer required after execution. Retain only output.
            db.execute("UPDATE atlas_jobs SET status=?,finished_at=?,result=?,error=?,payload='{}' WHERE id=? AND status='running'",
                       completion)
        # Clear only after the transaction context committed successfully. A
        # retry after an uncertain commit is harmless because this UPDATE is
        # conditional and never executes the original external operation.
        self._pending_completion = None

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._process_one():
                    continue
            except sqlite3.Error:
                # Fixed, interruptible backoff even when submissions keep the
                # wake event set. Never retry an already-claimed external call.
                self._stop.wait(1)
                continue
            self._wake.wait(1)
            self._wake.clear()
