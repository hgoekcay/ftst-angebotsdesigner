"""Revocable upload-only employee invitations; no public bookkeeping read access."""
import base64
import hashlib
import re
import secrets
from datetime import datetime, timezone

MAX_FILE = 8 * 1024 * 1024
MAX_ENCODED = ((MAX_FILE + 2) // 3) * 4
MAX_DAILY = 20
MAX_OWNER_DAILY = 200
MAX_TOKEN_TOTAL = 500
MAX_ACTIVE_ACCESS = 20
MIMES = frozenset({'application/pdf', 'application/xml', 'text/xml', 'image/jpeg', 'image/png', 'image/tiff'})


class SubmissionError(ValueError):
    """Fixed, safe message; never expose document fields or storage exceptions."""


SubmissionsError = SubmissionError


def _now():
    return datetime.now(timezone.utc).isoformat()


def _owner(owner):
    if not isinstance(owner, str) or not owner or len(owner) > 128:
        raise SubmissionError('Benutzerkennung ungültig.')
    return owner


def _text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise SubmissionError('Angabe fehlt oder ist zu lang.')
    value = ' '.join(value.split())
    if (required and not value) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SubmissionError('Angabe fehlt oder ist ungültig.')
    if '://' in value or re.search(r'(?i)(bearer\s|password=|token=|api[_-]?key=)', value):
        raise SubmissionError('Bitte keine Zugangsdaten oder Links in die Angaben eintragen.')
    return value


def _token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class Submissions:
    def __init__(self, db_factory, bookkeeping, owner_enabled=None):
        self.db_factory, self.bookkeeping = db_factory, bookkeeping
        self.owner_enabled = (lambda owner: True) if owner_enabled is None else owner_enabled
        with self.db_factory() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS atlas_submission_access (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT);
                CREATE INDEX IF NOT EXISTS atlas_submission_access_owner
                    ON atlas_submission_access(owner);
                CREATE TABLE IF NOT EXISTS atlas_submissions (
                    receipt TEXT PRIMARY KEY, access_id TEXT NOT NULL, owner TEXT NOT NULL,
                    created_at TEXT NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL,
                    project TEXT NOT NULL, note TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS atlas_submissions_quota
                    ON atlas_submissions(access_id, day);
                CREATE INDEX IF NOT EXISTS atlas_submissions_owner_quota
                    ON atlas_submissions(owner, day);
            ''')

    def list_access(self, owner):
        owner = _owner(owner)
        with self.db_factory() as db:
            rows = db.execute('''SELECT a.id,a.label,a.created_at,a.revoked_at,
                (SELECT COUNT(*) FROM atlas_submissions s WHERE s.access_id=a.id AND s.status='accepted')
                FROM atlas_submission_access a WHERE owner=? ORDER BY created_at DESC LIMIT 200''', (owner,)).fetchall()
        return [{'id': row[0], 'label': row[1], 'created_at': row[2], 'revoked': row[3] is not None,
                 'submission_count': row[4]} for row in rows]

    def create_access(self, owner, label):
        owner, label = _owner(owner), _text(label, 80, required=True)
        token, ident = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
        with self.db_factory() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM atlas_submission_access WHERE owner=? AND revoked_at IS NULL', (owner,)).fetchone()[0] >= MAX_ACTIVE_ACCESS:
                raise SubmissionError('Höchstens 20 aktive Upload-Zugänge. Bitte zuerst einen Zugang sperren.')
            if db.execute('SELECT COUNT(*) FROM atlas_submission_access WHERE owner=?', (owner,)).fetchone()[0] >= 200:
                raise SubmissionError('Limit für Upload-Zugänge erreicht.')
            db.execute('INSERT INTO atlas_submission_access(id,owner,token_hash,label,created_at) VALUES (?,?,?,?,?)',
                       (ident, owner, _token_hash(token), label, _now()))
        # Only this response ever contains the bearer token. It is not recoverable.
        return {'id': ident, 'token': token, 'label': label}

    def revoke_access(self, owner, ident):
        owner = _owner(owner)
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{22}', ident):
            raise SubmissionError('Upload-Zugang nicht gefunden.')
        with self.db_factory() as db:
            row = db.execute('SELECT id FROM atlas_submission_access WHERE id=? AND owner=?', (ident, owner)).fetchone()
            if not row:
                raise SubmissionError('Upload-Zugang nicht gefunden.')
            db.execute('UPDATE atlas_submission_access SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND owner=?', (_now(), ident, owner))
        return {'ok': True}

    def validate_access(self, token):
        digest = _token_hash(token)
        if digest is None:
            return {'valid': False, 'label': ''}
        with self.db_factory() as db:
            row = db.execute('SELECT label,owner FROM atlas_submission_access WHERE token_hash=? AND revoked_at IS NULL', (digest,)).fetchone()
        valid = row is not None and self.owner_enabled(row[1]) is True
        return {'valid': valid, 'label': row[0] if valid else ''}

    def _reserve(self, token, project, note):
        digest = _token_hash(token)
        if digest is None:
            raise SubmissionError('Upload-Link ungültig oder gesperrt.')
        stamp, receipt = _now(), secrets.token_urlsafe(18)
        with self.db_factory() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id,owner,label FROM atlas_submission_access WHERE token_hash=? AND revoked_at IS NULL', (digest,)).fetchone()
            if not row:
                raise SubmissionError('Upload-Link ungültig oder gesperrt.')
            ident, owner, label = row
            if self.owner_enabled(owner) is not True:
                raise SubmissionError('Upload-Link ungültig oder gesperrt.')
            daily, total = db.execute('SELECT COALESCE(SUM(day=?),0),COUNT(*) FROM atlas_submissions WHERE access_id=?', (stamp[:10], ident)).fetchone()
            owner_daily = db.execute('SELECT COUNT(*) FROM atlas_submissions WHERE owner=? AND day=?', (owner, stamp[:10])).fetchone()[0]
            if daily >= MAX_DAILY or total >= MAX_TOKEN_TOTAL or owner_daily >= MAX_OWNER_DAILY:
                raise SubmissionError('Upload-Limit erreicht. Bitte später erneut versuchen oder den Betrieb kontaktieren.')
            db.execute('INSERT INTO atlas_submissions VALUES (?,?,?,?,?,?,?,?)',
                       (receipt, ident, owner, stamp, stamp[:10], 'reserved', project, note))
        return receipt, ident, owner, label

    def submit(self, token, filename, mime, data_base64, project='', note=''):
        project, note = _text(project, 120), _text(note, 500)
        receipt, ident, owner, label = self._reserve(token, project, note)
        # Reservation counts failed/aborted attempts too, including across restarts.
        try:
            if (not isinstance(filename, str) or not filename or len(filename) > 250
                    or any(ord(char) < 32 for char in filename)
                    or not isinstance(mime, str) or mime not in MIMES
                    or not isinstance(data_base64, str) or not 0 < len(data_base64) <= MAX_ENCODED):
                raise ValueError()
            data = base64.b64decode(data_base64, validate=True)
            if not data or len(data) > MAX_FILE:
                raise ValueError()
            source = {'provider': 'employee', 'reference': receipt, 'access_id': ident, 'label': label}
            if project:
                source['project'] = project
            if note:
                source['note'] = note
            # The caller's token selects owner; no owner/record selector is accepted.
            self.bookkeeping.ingest_document(owner, data, filename, mime, source)
        except Exception:
            with self.db_factory() as db:
                db.execute("UPDATE atlas_submissions SET status='failed' WHERE receipt=?", (receipt,))
            raise SubmissionError('Beleg konnte nicht übernommen werden. Dateityp, Inhalt und Größe prüfen.') from None
        with self.db_factory() as db:
            db.execute("UPDATE atlas_submissions SET status='accepted' WHERE receipt=?", (receipt,))
        return {'accepted': True, 'receipt': receipt,
                'message': 'Beleg eingegangen. Der Betrieb prüft die Angaben. Es wurde nichts gebucht oder bezahlt.'}
