"""Restricted calendar access through Home Assistant's internal Core proxy.

The Google OAuth connection belongs to Home Assistant. SUPERVISOR_TOKEN never
leaves the fixed internal host. Callers must durably record a write attempt before
create(): the HA service does not provide an idempotency key or atomic booking.
An ambiguous write must be reconciled with find_booking(), never blindly retried.
"""
from datetime import date, datetime, time, timedelta, timezone
import http.client
import json
import os
import re
from time import monotonic
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Berlin')
MAX_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 5000
TIMEOUT = 20
ENTITY = re.compile(r'calendar\.[a-z0-9_]{1,100}\Z')
BOOKING = re.compile(r'[A-Za-z0-9_-]{8,100}\Z')


class CalendarError(ValueError):
    pass


class CalendarWriteUnknown(CalendarError):
    """A write may have reached the provider; only read reconciliation is safe."""


def _instant(value):
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise CalendarError('Kalenderzeit muss eine gültige Zeitzone enthalten.') from None


def _range(start, end):
    start, end = _instant(start), _instant(end)
    if not timedelta(0) < end - start <= timedelta(days=31):
        raise CalendarError('Kalenderabfrage muss zwischen 0 und 31 Tagen umfassen.')
    return start, end


def _event_time(value):
    # HA REST uses date/dateTime objects; service responses may use ISO strings.
    if isinstance(value, dict):
        value = value.get('dateTime') or value.get('date')
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return datetime.combine(date.fromisoformat(value), time(), TZ).astimezone(timezone.utc)
        except ValueError:
            raise CalendarError('Kalender enthält ein ungültiges Datum.') from None
    return _instant(value)


def _request(token, path, payload=None):
    """One bounded call. No proxy, redirects, retries, or provider error bodies."""
    conn = http.client.HTTPConnection('supervisor', 80, timeout=TIMEOUT)
    writing = payload is not None
    try:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if writing else None
        conn.request('POST' if writing else 'GET', '/core/api/' + path, body=body,
                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        response = conn.getresponse()
        if response.status != 200:
            raise CalendarError('Kalender-Schnittstelle hat die Anfrage nicht bestätigt.')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
            raise CalendarError('Kalenderantwort ist zu groß oder ungültig.')
        deadline = monotonic() + TIMEOUT
        chunks, size = [], 0
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise CalendarError('Kalenderantwort hat zu lange gedauert.')
            if conn.sock:
                conn.sock.settimeout(min(5, remaining))
            chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise CalendarError('Kalenderantwort ist zu groß; Zeitraum verkleinern.')
            chunks.append(chunk)
        if length is not None and size != int(length):
            raise CalendarError('Kalenderantwort ist unvollständig.')
        return json.loads(b''.join(chunks))
    except Exception:
        if writing:
            raise CalendarWriteUnknown('Kalenderbuchung nicht sicher bestätigt. Nicht erneut buchen; Ergebnis prüfen.') from None
        raise CalendarError('Kalender ist nicht lesbar. Verbindung und Freigabe in Home Assistant prüfen.') from None
    finally:
        conn.close()


class HACalendar:
    def __init__(self, options):
        self.enabled = options.get('calendar_enabled') is True
        self.owner = options.get('calendar_ha_user_id', '')
        self.entity = options.get('calendar_entity_id', '')
        self.token = os.environ.get('SUPERVISOR_TOKEN', '')

    def status(self, user):
        authorized = isinstance(user, str) and bool(user) and user == self.owner
        configured = bool(self.enabled and authorized and isinstance(self.entity, str)
                          and ENTITY.fullmatch(self.entity) and self.token)
        result = {'enabled': configured, 'configured': configured,
                'state': 'configured_unverified' if configured else 'not_configured',
                'provider': 'home_assistant', 'timezone': 'Europe/Berlin'}
        if configured:
            result['calendar_entity_id'] = self.entity
        return result

    def _check(self, user):
        if not self.status(user)['enabled']:
            raise CalendarError('Kalender ist für diesen Benutzer nicht freigegeben oder unvollständig eingerichtet.')

    def _events(self, user, start, end):
        self._check(user)
        start, end = _range(start, end)
        state = _request(self.token, 'states/' + self.entity)
        if (not isinstance(state, dict) or state.get('entity_id') != self.entity
                or state.get('state') not in ('on', 'off')):
            raise CalendarError('Kalender ist in Home Assistant nicht verfügbar.')
        data = _request(self.token, 'calendars/' + self.entity + '?' + urlencode(
            {'start': start.isoformat(), 'end': end.isoformat()}))
        if not isinstance(data, list) or len(data) > MAX_EVENTS:
            raise CalendarError('Kalenderantwort ist unvollständig oder ungültig.')
        result = []
        for event in data:
            if not isinstance(event, dict):
                raise CalendarError('Kalender enthält einen ungültigen Eintrag.')
            if event.get('status') == 'cancelled':
                continue
            event_start, event_end = _event_time(event.get('start')), _event_time(event.get('end'))
            if event_end <= event_start:
                raise CalendarError('Kalender enthält einen ungültigen Zeitraum.')
            if event_start < end and event_end > start:
                result.append((event, event_start, event_end))
        return result

    def busy(self, user, start, end):
        """All overlapping blocks, with exclusive ends and no private event text."""
        return [{'start': a.isoformat(), 'end': b.isoformat()}
                for event, a, b in self._events(user, start, end)
                if event.get('transparency') != 'transparent']

    def _marker(self, bookingid):
        if not isinstance(bookingid, str) or not BOOKING.fullmatch(bookingid):
            raise CalendarError('Buchungskennung ist ungültig.')
        return 'ATLAS-Buchung: ' + bookingid

    def find_booking(self, user, bookingid, start, end):
        """Read-only reconciliation. None does NOT prove a prior write failed."""
        self._check(user)
        marker = self._marker(bookingid)
        start, end = _range(start, end)
        matches = []
        for event, a, b in self._events(user, start, end):
            description = event.get('description', '')
            if isinstance(description, str) and marker in description.splitlines() and a == start and b == end:
                matches.append({'booking_id': bookingid, 'start': a.isoformat(),
                                'end': b.isoformat(), 'verified': True})
        if len(matches) > 1:
            raise CalendarError('Mehrere passende Kalenderbuchungen gefunden. Bitte manuell prüfen.')
        return matches[0] if matches else None

    def create(self, user, bookingid, start, end, name):
        """Single write attempt. Caller requires explicit human confirmation first."""
        self._check(user)
        marker = self._marker(bookingid)
        start, end = _range(start, end)
        if (not isinstance(name, str) or not name.strip() or len(name) > 100
                or any(ord(c) < 32 for c in name)):
            raise CalendarError('Name ist ungültig.')
        result = _request(self.token, 'services/calendar/create_event', {
            'entity_id': self.entity,
            'summary': 'FTST Beratung – ' + name.strip(),
            'description': marker,
            'start_date_time': start.isoformat(), 'end_date_time': end.isoformat(),
        })
        if not isinstance(result, list):
            raise CalendarWriteUnknown('Kalenderbuchung nicht sicher bestätigt. Ergebnis prüfen.')
        return {'accepted': True, 'verified': False, 'booking_id': bookingid}
