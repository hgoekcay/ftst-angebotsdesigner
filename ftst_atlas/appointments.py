"""Owner-isolated demo calendar; no connection to a real business calendar.

Proposals never reserve or save a booking. Only an authenticated, explicitly
confirmed call to confirm() may create a booking; model tools must not call it.
"""
from contextlib import contextmanager
from datetime import date as Date, datetime, time, timedelta, timezone
import secrets
import sqlite3
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Berlin')
SERVICE = 'Sicherheitstechnik-Erstberatung (Demo)'
PROPOSAL_TTL = timedelta(minutes=10)


class AppointmentError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise AppointmentError(label + ' ist ungültig.')
    return value.strip()


class Appointments:
    def __init__(self, db_factory):
        self.db_factory = db_factory
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS appointment_proposals (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, slot_id TEXT NOT NULL,
                    name TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    UNIQUE(user_id, revision)
                );
                CREATE TABLE IF NOT EXISTS appointment_bookings (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL UNIQUE,
                    slot_id TEXT NOT NULL, name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, slot_id)
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

    def _user(self, user):
        return _text(user, 'Benutzer', 200)

    def _days(self, selected=None):
        today = _now().astimezone(TZ).date()
        if selected is not None:
            try:
                if not isinstance(selected, str) or len(selected) != 10:
                    raise ValueError()
                day = Date.fromisoformat(selected)
                if day.isoformat() != selected or not today <= day < today + timedelta(days=14):
                    raise ValueError()
            except ValueError:
                raise AppointmentError('Datum muss innerhalb der nächsten 14 Tage liegen.') from None
            return [day]
        return [today + timedelta(days=n) for n in range(14)]

    def _slots(self, selected=None):
        current = _now()
        return [self._slot(datetime.combine(day, time(hour), TZ).isoformat())
                for day in self._days(selected) if day.weekday() < 5
                for hour in range(9, 17)
                if datetime.combine(day, time(hour), TZ) > current]

    def _slot(self, slot_id):
        start = datetime.fromisoformat(slot_id)
        return {'id': slot_id, 'slot_id': slot_id, 'start': start.isoformat(),
                'end': (start + timedelta(hours=1)).isoformat(),
                'service': SERVICE, 'demo': True, 'timezone': 'Europe/Berlin'}

    def _busy(self, slot):
        # Deterministic example blocks: lunch daily and a sample Monday meeting.
        start = datetime.fromisoformat(slot['start'])
        return start.hour == 12 or (start.weekday() == 0 and start.hour == 10)

    def _available(self, db, user, selected=None):
        booked = {row['slot_id'] for row in db.execute(
            'SELECT slot_id FROM appointment_bookings WHERE user_id=?', (user,))}
        return [slot for slot in self._slots(selected)
                if not self._busy(slot) and slot['slot_id'] not in booked]

    def availability(self, user, date=None):
        user = self._user(user)
        with self._db() as db:
            return self._available(db, user, date)

    def _proposal(self, row):
        if row is None:
            return None
        result = {key: row[key] for key in ('id', 'revision', 'slot_id', 'name', 'status', 'created_at', 'expires_at')}
        slot = self._slot(row['slot_id'])
        result.update({key: slot[key] for key in ('start', 'end', 'service', 'demo', 'timezone')})
        if result['status'] == 'pending' and datetime.fromisoformat(result['expires_at']) <= _now():
            result['status'] = 'expired'
        return result

    def _booking(self, row):
        result = {key: row[key] for key in ('id', 'proposal_id', 'slot_id', 'name', 'created_at')}
        slot = self._slot(row['slot_id'])
        result.update({key: slot[key] for key in ('start', 'end', 'service', 'demo', 'timezone')})
        result['status'] = 'confirmed'
        return result

    def propose(self, user, slot_id, name):
        user = self._user(user)
        slot_id = _text(slot_id, 'Zeitfenster', 40)
        name = _text(name, 'Name', 100)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if slot_id not in {s['slot_id'] for s in self._available(db, user)}:
                raise AppointmentError('Dieses Zeitfenster ist nicht mehr verfügbar. Bitte erneut prüfen.')
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM appointment_proposals WHERE user_id=?', (user,)).fetchone()[0]
            current = _now()
            proposal_id = secrets.token_urlsafe(24)
            db.execute("UPDATE appointment_proposals SET status='superseded' WHERE user_id=? AND status='pending'", (user,))
            db.execute('INSERT INTO appointment_proposals VALUES(?,?,?,?,?,?,?,?)',
                       (proposal_id, user, revision, slot_id, name, 'pending', current.isoformat(), (current + PROPOSAL_TTL).isoformat()))
            return self._proposal(db.execute('SELECT * FROM appointment_proposals WHERE id=?', (proposal_id,)).fetchone())

    def confirm(self, user, proposal_id):
        user = self._user(user)
        proposal_id = _text(proposal_id, 'Terminvorschlag', 100)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM appointment_bookings WHERE user_id=? AND proposal_id=?', (user, proposal_id)).fetchone()
            if existing:
                return self._booking(existing)
            proposal = self._proposal(db.execute('SELECT * FROM appointment_proposals WHERE user_id=? AND id=?', (user, proposal_id)).fetchone())
            if not proposal or proposal['status'] != 'pending':
                raise AppointmentError('Terminvorschlag abgelaufen, geändert oder nicht gefunden. Bitte erneut auswählen.')
            if proposal['slot_id'] not in {s['slot_id'] for s in self._available(db, user)}:
                raise AppointmentError('Dieses Zeitfenster ist nicht mehr verfügbar. Bitte erneut prüfen.')
            booking_id = secrets.token_urlsafe(24)
            db.execute('INSERT INTO appointment_bookings VALUES(?,?,?,?,?,?)',
                       (booking_id, user, proposal_id, proposal['slot_id'], proposal['name'], _now().isoformat()))
            db.execute("UPDATE appointment_proposals SET status='booked' WHERE id=? AND user_id=?", (proposal_id, user))
            return self._booking(db.execute('SELECT * FROM appointment_bookings WHERE id=?', (booking_id,)).fetchone())

    def cancel_proposal(self, user, proposal_id):
        user = self._user(user)
        proposal_id = _text(proposal_id, 'Terminvorschlag', 100)
        with self._db() as db:
            row = db.execute('SELECT * FROM appointment_proposals WHERE user_id=? AND id=?', (user, proposal_id)).fetchone()
            if row is None:
                raise AppointmentError('Terminvorschlag nicht gefunden.')
            db.execute("UPDATE appointment_proposals SET status='cancelled' WHERE user_id=? AND id=? AND status='pending'", (user, proposal_id))
        return {'cancelled': row['status'] in ('pending', 'cancelled'), 'demo': True}

    def bookings(self, user):
        user = self._user(user)
        with self._db() as db:
            return [self._booking(row) for row in db.execute(
                'SELECT * FROM appointment_bookings WHERE user_id=? ORDER BY slot_id', (user,))]

    def state(self, user):
        user = self._user(user)
        with self._db() as db:
            proposal = self._proposal(db.execute(
                "SELECT * FROM appointment_proposals WHERE user_id=? AND status='pending' ORDER BY revision DESC LIMIT 1", (user,)).fetchone())
            return {'business': 'FT Sicherheitstechnik – Demo-Empfang',
                    'demo': True, 'timezone': 'Europe/Berlin', 'service': SERVICE,
                    'notice': 'Demo-Kalender: keine echten Kundentermine und keine externen Einladungen.',
                    'available': self._available(db, user),
                    'bookings': [self._booking(row) for row in db.execute('SELECT * FROM appointment_bookings WHERE user_id=? ORDER BY slot_id', (user,))],
                    'proposal': proposal if proposal and proposal['status'] == 'pending' else None,
                    'busy': [dict(slot, reason='Beispielbelegung (Demo)') for slot in self._slots() if self._busy(slot)]}
