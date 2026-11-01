"""Confirmed appointment intents backed by a Home Assistant calendar.

A durable intent precedes every external write. Ambiguous writes are reconciled
by reading their unique marker, never automatically sent again. The provider
cannot atomically reserve against other calendar clients; conflicts are checked
immediately before sending, not guaranteed impossible.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
import secrets
import sqlite3

from appointments import Appointments, AppointmentError, PROPOSAL_TTL, _now, _text

SERVICE = 'Sicherheitstechnik-Erstberatung'
UNKNOWN = 'Buchungsstatus unklar. ATLAS sendet den Termin nicht erneut. Bitte Buchungsstatus prüfen.'


class CalendarAppointments(Appointments):
    def __init__(self, db_factory, provider):
        self.db_factory = db_factory
        self.provider = provider
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS calendar_proposals (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, scope TEXT NOT NULL,
                    revision INTEGER NOT NULL, slot_id TEXT NOT NULL,
                    name TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    UNIQUE(user_id, scope, revision)
                );
                CREATE TABLE IF NOT EXISTS calendar_bookings (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, scope TEXT NOT NULL,
                    proposal_id TEXT NOT NULL UNIQUE, slot_id TEXT NOT NULL,
                    name TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(scope, slot_id)
                );
            ''')

    @contextmanager
    def _db(self):
        db = self.db_factory()
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _access(self, user):
        user = self._user(user)
        status = self.provider.status(user)
        if status.get('enabled') is not True:
            raise AppointmentError('Firmenkalender ist für diesen Benutzer nicht freigegeben oder nicht eingerichtet.')
        scope = status.get('calendar_entity_id')
        if not isinstance(scope, str) or not scope:
            raise AppointmentError('Firmenkalender ist nicht eindeutig konfiguriert.')
        return user, scope, status

    def _slot(self, slot_id):
        slot = super()._slot(slot_id)
        slot.update(service=SERVICE, demo=False)
        return slot

    def _available_real(self, user, scope, selected=None):
        slots = self._slots(selected)
        if not slots:
            return []
        busy = self.provider.busy(user, slots[0]['start'], slots[-1]['end'])
        intervals = [(datetime.fromisoformat(item['start']), datetime.fromisoformat(item['end'])) for item in busy]
        if any(start.tzinfo is None or end.tzinfo is None or end <= start for start, end in intervals):
            raise AppointmentError('Kalenderbelegung konnte nicht verlässlich geprüft werden.')
        with self._db() as db:
            held = {row['slot_id'] for row in db.execute(
                'SELECT slot_id FROM calendar_bookings WHERE scope=?', (scope,))}
        return [slot for slot in slots if slot['slot_id'] not in held and not any(
            datetime.fromisoformat(slot['start']) < end and datetime.fromisoformat(slot['end']) > start
            for start, end in intervals)]

    def availability(self, user, date=None):
        user, scope, _ = self._access(user)
        try:
            return self._available_real(user, scope, date)
        except AppointmentError:
            raise
        except Exception:
            raise AppointmentError('Kalender nicht erreichbar. Es werden keine freien Zeiten angenommen.') from None

    def _proposal(self, row):
        result = super()._proposal(row)
        if result:
            result.update(service=SERVICE, demo=False)
        return result

    def _booking(self, row):
        result = super()._booking(row)
        result.update(service=SERVICE, demo=False, status=row['status'])
        if row['status'] != 'confirmed':
            result['notice'] = UNKNOWN
        return result

    def propose(self, user, slot_id, name):
        user, scope, _ = self._access(user)
        slot_id = _text(slot_id, 'Zeitfenster', 40)
        name = _text(name, 'Name', 100)
        if slot_id not in {s['slot_id'] for s in self.availability(user)}:
            raise AppointmentError('Dieses Zeitfenster ist nicht mehr verfügbar. Bitte erneut prüfen.')
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM calendar_proposals WHERE user_id=? AND scope=?', (user, scope)).fetchone()[0]
            current = _now()
            proposal_id = secrets.token_hex(24)
            db.execute("UPDATE calendar_proposals SET status='superseded' WHERE user_id=? AND scope=? AND status='pending'", (user, scope))
            db.execute('INSERT INTO calendar_proposals VALUES(?,?,?,?,?,?,?,?,?)',
                       (proposal_id, user, scope, revision, slot_id, name, 'pending', current.isoformat(), (current + PROPOSAL_TTL).isoformat()))
            return self._proposal(db.execute('SELECT * FROM calendar_proposals WHERE id=?', (proposal_id,)).fetchone())

    def _existing(self, user, scope, proposal_id):
        with self._db() as db:
            row = db.execute('SELECT * FROM calendar_bookings WHERE user_id=? AND scope=? AND proposal_id=?', (user, scope, proposal_id)).fetchone()
            return self._booking(row) if row else None

    def reconcile(self, user, proposal_id):
        user, scope, _ = self._access(user)
        proposal_id = _text(proposal_id, 'Terminvorschlag', 100)
        booking = self._existing(user, scope, proposal_id)
        if not booking:
            raise AppointmentError('Buchungsauftrag nicht gefunden.')
        if booking['status'] == 'confirmed':
            return booking
        try:
            found = self.provider.find_booking(user, booking['id'], booking['start'], booking['end'])
            verified = (isinstance(found, dict) and found.get('verified') is True
                        and found.get('booking_id') == booking['id']
                        and datetime.fromisoformat(found['start']) == datetime.fromisoformat(booking['start'])
                        and datetime.fromisoformat(found['end']) == datetime.fromisoformat(booking['end']))
        except Exception:
            verified = False
        with self._db() as db:
            # A late inconclusive read must never undo another request's verification.
            if verified:
                db.execute("UPDATE calendar_bookings SET status='confirmed' WHERE id=?", (booking['id'],))
                db.execute("UPDATE calendar_proposals SET status='booked' WHERE id=?", (proposal_id,))
            else:
                db.execute("UPDATE calendar_bookings SET status='unknown' WHERE id=? AND status!='confirmed'", (booking['id'],))
            row = db.execute('SELECT * FROM calendar_bookings WHERE id=?', (booking['id'],)).fetchone()
            return self._booking(row)

    def confirm(self, user, proposal_id):
        user, scope, _ = self._access(user)
        proposal_id = _text(proposal_id, 'Terminvorschlag', 100)
        existing = self._existing(user, scope, proposal_id)
        if existing:
            return self.reconcile(user, proposal_id)
        # Network read before local reservation. The unique constraint and proposal
        # status recheck arbitrate concurrent confirmations after this read.
        available = {s['slot_id'] for s in self.availability(user)}
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM calendar_bookings WHERE user_id=? AND scope=? AND proposal_id=?', (user, scope, proposal_id)).fetchone()
            if existing:
                return self._booking(existing)
            proposal = self._proposal(db.execute('SELECT * FROM calendar_proposals WHERE user_id=? AND scope=? AND id=?', (user, scope, proposal_id)).fetchone())
            if not proposal or proposal['status'] != 'pending':
                raise AppointmentError('Terminvorschlag abgelaufen, geändert oder nicht gefunden. Bitte erneut auswählen.')
            if proposal['slot_id'] not in available:
                raise AppointmentError('Dieses Zeitfenster ist nicht mehr verfügbar. Bitte erneut prüfen.')
            booking_id = secrets.token_hex(24)
            try:
                db.execute('INSERT INTO calendar_bookings VALUES(?,?,?,?,?,?,?,?)',
                           (booking_id, user, scope, proposal_id, proposal['slot_id'], proposal['name'], 'saving', _now().isoformat()))
            except sqlite3.IntegrityError:
                raise AppointmentError('Für dieses Zeitfenster besteht bereits ein Buchungsauftrag.') from None
            db.execute("UPDATE calendar_proposals SET status='saving' WHERE id=?", (proposal_id,))
        # From this point, ANY error is ambiguous. Persisted intent is retained and
        # no call, restart or repeated click is allowed to issue this write again.
        try:
            self.provider.create(user, booking_id, proposal['start'], proposal['end'], proposal['name'])
        except Exception:
            pass
        return self.reconcile(user, proposal_id)

    def cancel_proposal(self, user, proposal_id):
        user, scope, _ = self._access(user)
        proposal_id = _text(proposal_id, 'Terminvorschlag', 100)
        with self._db() as db:
            row = db.execute('SELECT * FROM calendar_proposals WHERE user_id=? AND scope=? AND id=?', (user, scope, proposal_id)).fetchone()
            if row is None:
                raise AppointmentError('Terminvorschlag nicht gefunden.')
            if row['status'] not in ('pending', 'cancelled'):
                raise AppointmentError('Buchung wurde bereits gestartet; der Kalendereintrag wird nicht gelöscht.')
            db.execute("UPDATE calendar_proposals SET status='cancelled' WHERE id=?", (proposal_id,))
        return {'cancelled': True, 'demo': False}

    def bookings(self, user):
        user, scope, _ = self._access(user)
        with self._db() as db:
            return [self._booking(row) for row in db.execute(
                'SELECT * FROM calendar_bookings WHERE user_id=? AND scope=? ORDER BY slot_id DESC LIMIT 100', (user, scope))]

    def state(self, user):
        user, scope, status = self._access(user)
        error = None
        try:
            available = self.availability(user)
        except AppointmentError as exc:
            available, error = [], str(exc)
        with self._db() as db:
            proposal = self._proposal(db.execute(
                "SELECT * FROM calendar_proposals WHERE user_id=? AND scope=? AND status='pending' ORDER BY revision DESC LIMIT 1", (user, scope)).fetchone())
        return {'business': 'FT Sicherheitstechnik', 'demo': False,
                'timezone': 'Europe/Berlin', 'service': SERVICE,
                'notice': error or 'Firmenkalender: Buchung erst nach Bestätigung und geprüftem Kalendereintrag. Änderungen anderer Kalendernutzer können gleichzeitig erfolgen.',
                'provider_status': {**status, 'availability_verified': error is None},
                'available': available, 'bookings': self.bookings(user),
                'proposal': proposal if proposal and proposal['status'] == 'pending' else None,
                'busy': []}
