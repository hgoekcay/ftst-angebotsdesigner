"""Owner-scoped direct Google Calendar API adapter. No HA calendar dependency.

Google credentials stay inside OAuth helper. This adapter never follows redirects,
retries a write, sends invitations, or returns existing event descriptions.
"""
from datetime import date, datetime, time, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import threading
from time import monotonic
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from ha_calendar import CalendarError, CalendarWriteUnknown, _range, _instant, BOOKING

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 20
MAX_PAGES = 20


def _request(token, path, payload=None, missing=False):
    conn = http.client.HTTPSConnection('www.googleapis.com', 443, timeout=TIMEOUT,
                                      context=ssl.create_default_context())
    writing = payload is not None
    try:
        conn.request('POST' if writing else 'GET', '/calendar/v3/' + path,
                     body=json.dumps(payload).encode() if writing else None,
                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        response = conn.getresponse()
        if response.status == 404 and missing and not writing:
            return None
        if response.status not in (200, 201):
            raise ValueError('Rejected')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
            raise ValueError('Invalid length')
        deadline, chunks, size = monotonic() + TIMEOUT, [], 0
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ValueError('Deadline')
            if conn.sock:
                conn.sock.settimeout(min(5, remaining))
            chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Too large')
            chunks.append(chunk)
        if length is not None and size != int(length):
            raise ValueError('Truncated')
        data = json.loads(b''.join(chunks))
        if not isinstance(data, dict):
            raise ValueError('Invalid response')
        return data
    except Exception:
        if writing:
            raise CalendarWriteUnknown('Google-Buchung nicht sicher bestätigt. Buchungsstatus prüfen; nicht erneut senden.') from None
        raise CalendarError('Google Kalender nicht erreichbar oder Zugriff verweigert. Verbindung prüfen.') from None
    finally:
        conn.close()


def _valid_id(value):
    return isinstance(value, str) and 1 <= len(value) <= 1024 and not any(ord(c) < 32 for c in value)


def _event_time(value, zone):
    if not isinstance(value, dict):
        raise CalendarError('Google-Kalenderzeit ist ungültig.')
    if 'dateTime' in value:
        return _instant(value['dateTime'])
    try:
        day = date.fromisoformat(value['date'])
        return datetime.combine(day, time(), ZoneInfo(zone)).astimezone(timezone.utc)
    except Exception:
        raise CalendarError('Google-Kalenderdatum ist ungültig.') from None


class GoogleCalendar:
    def __init__(self, options, oauth, data_dir=None):
        self.oauth = oauth
        self.owner = options.get('calendar_ha_user_id', '')
        self.enabled = options.get('calendar_enabled') is True and options.get('calendar_provider') == 'google'
        self.path = Path(data_dir) / 'google_calendar_selection.json' if data_dir is not None else None
        self.lock = threading.RLock()
        self.selection = None
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 8192:
                    raise ValueError()
                self.selection = json.loads(self.path.read_text())
            except Exception:
                self.selection = None

    def _connection(self, user):
        if not self.enabled or not isinstance(user, str) or not user or user != self.owner:
            raise CalendarError('Google Kalender ist für diesen Benutzer nicht freigegeben.')
        status = self.oauth.status(user)
        if status.get('connected') is not True:
            raise CalendarError('Google Kalender noch nicht verbunden.')
        connection = status.get('connection_id')
        if not isinstance(connection, str) or not connection:
            raise CalendarError('Google-Verbindung ist nicht eindeutig bestätigt.')
        return connection

    def _selected(self, user):
        connection = self._connection(user)
        selection = self.selection
        if isinstance(selection, dict) and selection.get('owner') == user and selection.get('connection') == connection:
            calendar = selection.get('id')
        else:
            calendar = None
        if not _valid_id(calendar) or calendar == 'primary':
            raise CalendarError('Bitte einen konkreten Firmenkalender auswählen.')
        return connection, calendar

    def selected_id(self, user):
        with self.lock:
            try:
                return self._selected(user)[1]
            except CalendarError:
                return None

    def status(self, user):
        with self.lock:
            try:
                connection, calendar = self._selected(user)
            except CalendarError:
                return {'enabled': False, 'configured': False, 'provider': 'google', 'state': 'not_configured'}
            scope = hashlib.sha256((connection + '\0' + calendar).encode()).hexdigest()
            return {'enabled': True, 'configured': True, 'provider': 'google', 'state': 'configured_unverified',
                    'calendar_entity_id': 'google:' + scope, 'timezone': 'Europe/Berlin'}

    def list_calendars(self, user):
        with self.lock:
            self._connection(user)
            token, page, seen, result = self.oauth.access_token(user), None, set(), []
            for _ in range(MAX_PAGES):
                query = {'maxResults': 250, 'minAccessRole': 'writer'}
                if page:
                    query['pageToken'] = page
                raw = _request(token, 'users/me/calendarList?' + urlencode(query))
                items = raw.get('items')
                if not isinstance(items, list):
                    raise CalendarError('Google-Kalenderliste ist unvollständig.')
                for item in items:
                    if not isinstance(item, dict) or not _valid_id(item.get('id')):
                        raise CalendarError('Google-Kalenderliste ist ungültig.')
                    if item.get('accessRole') in ('writer', 'owner') and not item.get('deleted'):
                        result.append({'id': item['id'], 'name': str(item.get('summary', 'Kalender'))[:300], 'access_role': item['accessRole']})
                page = raw.get('nextPageToken')
                if not page:
                    return result
                if not isinstance(page, str) or len(page) > 4096 or page in seen:
                    break
                seen.add(page)
            raise CalendarError('Google-Kalenderliste überschreitet die sichere Abfragegrenze.')

    def _metadata(self, user, calendar):
        raw = _request(self.oauth.access_token(user), 'users/me/calendarList/' + quote(calendar, safe=''))
        if raw.get('id') != calendar or raw.get('accessRole') not in ('writer', 'owner') or raw.get('deleted'):
            raise CalendarError('Der ausgewählte Kalender ist nicht zum Schreiben freigegeben.')
        zone = raw.get('timeZone')
        try:
            ZoneInfo(zone)
        except Exception:
            raise CalendarError('Google-Kalenderzeitzone fehlt oder ist ungültig.') from None
        return raw

    def select_calendar(self, user, calendar_id):
        with self.lock:
            connection = self._connection(user)
            if not _valid_id(calendar_id) or calendar_id == 'primary':
                raise CalendarError('Konkrete Kalender-ID erforderlich.')
            self._metadata(user, calendar_id)
            value = {'owner': user, 'connection': connection, 'id': calendar_id}
            if self.path:
                temporary = self.path.with_name(self.path.name + '.' + secrets.token_hex(8) + '.tmp')
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w') as stream:
                        json.dump(value, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            self.selection = value
            return self.status(user)

    def _events(self, user, start, end):
        _, calendar = self._selected(user)
        start, end = _range(start, end)
        metadata = self._metadata(user, calendar)
        token, page, seen, result = self.oauth.access_token(user), None, set(), []
        for _ in range(MAX_PAGES):
            query = {'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'singleEvents': 'true',
                     'showDeleted': 'false', 'maxResults': 250, 'timeZone': metadata['timeZone']}
            if page:
                query['pageToken'] = page
            raw = _request(token, 'calendars/' + quote(calendar, safe='') + '/events?' + urlencode(query))
            items = raw.get('items')
            if not isinstance(items, list):
                raise CalendarError('Google-Kalenderantwort ist unvollständig.')
            for event in items:
                if not isinstance(event, dict):
                    raise CalendarError('Google-Kalendereintrag ist ungültig.')
                if event.get('status') == 'cancelled':
                    continue
                a, b = _event_time(event.get('start'), metadata['timeZone']), _event_time(event.get('end'), metadata['timeZone'])
                if b <= a:
                    raise CalendarError('Google-Kalenderzeitraum ist ungültig.')
                if a < end and b > start and event.get('transparency') != 'transparent':
                    result.append({'start': a.isoformat(), 'end': b.isoformat()})
            page = raw.get('nextPageToken')
            if not page:
                return result
            if not isinstance(page, str) or len(page) > 4096 or page in seen:
                break
            seen.add(page)
        raise CalendarError('Google-Kalenderantwort überschreitet die sichere Abfragegrenze.')

    def busy(self, user, start, end):
        with self.lock:
            return self._events(user, start, end)

    def _event_id(self, calendar, bookingid):
        if not isinstance(bookingid, str) or not BOOKING.fullmatch(bookingid):
            raise CalendarError('Buchungskennung ist ungültig.')
        return hashlib.sha256((calendar + '\0' + bookingid).encode()).hexdigest()

    def create(self, user, bookingid, start, end, name):
        with self.lock:
            _, calendar = self._selected(user)
            event_id = self._event_id(calendar, bookingid)
            start, end = _range(start, end)
            if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
                raise CalendarError('Name ist ungültig.')
            self._metadata(user, calendar)
            raw = _request(self.oauth.access_token(user), 'calendars/' + quote(calendar, safe='') + '/events?sendUpdates=none', {
                'id': event_id, 'summary': 'FTST Beratung – ' + name.strip(),
                'start': {'dateTime': start.isoformat()}, 'end': {'dateTime': end.isoformat()},
                'extendedProperties': {'private': {'atlas_booking_id': bookingid}},
            })
            if raw.get('id') != event_id:
                raise CalendarWriteUnknown('Google-Buchung nicht sicher bestätigt. Buchungsstatus prüfen.')
            return {'accepted': True, 'verified': False, 'booking_id': bookingid}

    def find_booking(self, user, bookingid, start, end):
        with self.lock:
            _, calendar = self._selected(user)
            event_id = self._event_id(calendar, bookingid)
            start, end = _range(start, end)
            raw = _request(self.oauth.access_token(user), 'calendars/' + quote(calendar, safe='') + '/events/' + event_id, missing=True)
            if raw is None or raw.get('status') == 'cancelled':
                return None
            if (raw.get('id') != event_id or raw.get('extendedProperties', {}).get('private', {}).get('atlas_booking_id') != bookingid
                    or _event_time(raw.get('start'), 'Europe/Berlin') != start
                    or _event_time(raw.get('end'), 'Europe/Berlin') != end):
                raise CalendarError('Google-Kalendereintrag stimmt nicht mit dem Buchungsauftrag überein.')
            return {'booking_id': bookingid, 'start': start.isoformat(), 'end': end.isoformat(), 'verified': True}
