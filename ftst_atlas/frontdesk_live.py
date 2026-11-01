"""Owner-scoped GPT-Live setup; credentials and session prompts stay server-side.

WebRTC audio goes directly to OpenAI. Both frontend graceful close and a server
sideband watchdog send session.close. Finalization is confirmed only when the
provider emits session.closed; network failures remain explicitly unconfirmed.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import http.client
import json
import re
import secrets
import ssl
import time
import threading


class LiveError(Exception):
    pass


MAX_RESPONSE = 128 * 1024
TIMEOUT = 25
FAILURE = 'GPT-Live konnte nicht verbunden werden. API-Zugang, Modellfreigabe und Guthaben prüfen. Kein automatischer Wiederholungsversuch.'


def _request(key, payload):
    connection = http.client.HTTPSConnection('api.openai.com', 443, timeout=TIMEOUT,
                                             context=ssl.create_default_context())
    try:
        connection.request('POST', '/v1/live/sessions', body=json.dumps(payload).encode(),
                           headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                                    'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 201:
            raise ValueError('Provider rejected session')
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ValueError('Response is not JSON')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > MAX_RESPONSE):
            raise ValueError('Response too large')
        deadline = time.monotonic() + TIMEOUT
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Response deadline')
            if connection.sock:
                connection.sock.settimeout(min(10, remaining))
            chunk = response.read1(min(16384, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError('Response too large')
            chunks.append(chunk)
        if length is not None and size != int(length):
            raise ValueError('Truncated response')
        return json.loads(b''.join(chunks))
    except Exception:
        # Never return provider bodies or exception strings (may contain a key).
        raise LiveError(FAILURE) from None
    finally:
        connection.close()


def _close_remote(key, session_id):
    """Verified Live sideband path; never use SIP-only REST hangup for WebRTC."""
    connection = None
    try:
        import websocket
        connection = websocket.create_connection(
            'wss://api.openai.com/v1/live/sessions/' + session_id + '/attach',
            header={'Authorization': 'Bearer ' + key}, timeout=10,
            redirect_limit=0, http_no_proxy=['api.openai.com'])
        # Attached sidebands already belong to a running session; no start event.
        connection.send(json.dumps({'type': 'session.close'}))
        deadline = time.monotonic() + 15
        for _ in range(1000):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            connection.settimeout(min(5, remaining))
            message = connection.recv()
            if not message or len(message) > 1024 * 1024:
                return False
            event = json.loads(message)
            if event.get('type') == 'session.closed':
                return True
        return False
    except Exception:
        return False
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def function(name, description, properties):
    return {'type': 'function', 'name': name, 'description': description,
            'strict': True, 'parameters': {'type': 'object', 'properties': properties,
                                         'required': list(properties), 'additionalProperties': False}}


TOOLS = [
    function('check_availability', 'Freie Zeiten im lokalen Demo-Kalender prüfen. Datum YYYY-MM-DD oder leer für alle nächsten 14 Tage.',
             {'date': {'type': 'string'}}),
    function('propose_appointment', 'Einen unbestätigten Terminvorschlag anzeigen. Speichert KEINE Buchung; ersetzt einen alten Vorschlag.',
             {'slot_id': {'type': 'string'}, 'name': {'type': 'string'}}),
    function('cancel_proposal', 'Einen noch unbestätigten Vorschlag verwerfen.',
             {'proposal_id': {'type': 'string'}}),
    function('end_conversation', 'Auf ausdrücklichen Wunsch das Gespräch beenden (fertig, auf Wiedersehen, Gespräch beenden).', {}),
    function('list_bookings', 'Bereits durch den Benutzer bestätigte Demo-Buchungen lesen.', {}),
]


def session_config():
    today = datetime.now(ZoneInfo('Europe/Berlin')).date().isoformat()
    return {
        'model': 'gpt-live-1',
        'instructions': (
            'Du bist ATLAS, die freundliche deutschsprachige Terminassistenz von FT Sicherheitstechnik. '
            'Dies ist ausdrücklich ein Demo-Kalender, keine echte Firmen-Terminbuchung. Begrüße kurz. '
            'Höre auch während deiner Antworten zu, berücksichtige Unterbrechungen und neue Wünsche. '
            'Für Verfügbarkeiten, Terminvorschläge, Änderungen und Buchungsstatus: Generate <|SpawnThinking|>. '
            'Erfinde keine freien Termine. Halte die Unterhaltung während der Prüfung natürlich. '
            'Lies am Ende Datum, Uhrzeit, Zeitzone, Dienstleistung und Name vor. '
            'Erkläre, dass erst der Bestätigen-Knopf auf der aktuellen Karte die Demo-Buchung speichert. '
            'Ein gesprochenes Ja allein speichert nicht. Behaupte Bestätigung nur nach verifiziertem Ergebnis. '
            'Wenn sich Wünsche ändern, lasse den alten Vorschlag verwerfen und einen neuen prüfen. '
            'Wenn der Benutzer fertig ist oder das Gespräch beenden möchte, Generate <|SpawnThinking|> für end_conversation. Heute ist ' + today + ', Zeitzone Europe/Berlin.'
        ),
        'client': {'data_channel': {
            # Do not let browser event messages change models or add costly tools.
            'allowed_client_events': ['session.close', 'response.item.create', 'response.create',
                                      'session.instructions.append', 'session.commentary.append'],
            'allowed_server_events': 'all',
        }},
        'delegation': {'type': 'responses', 'responses': {
            'model': 'gpt-6-luna', 'parallel_tool_calls': False, 'max_output_tokens': 1200,
            'instructions': (
                'Verwalte ausschließlich den lokalen FT Sicherheitstechnik Demo-Kalender. '
                'Heute ' + today + ', Europe/Berlin. Dienstleistung: Sicherheitsberatung, 60 Minuten. '
                'Verwende check_availability für jede Verfügbarkeitsauskunft; nutze nur exakte zurückgegebene slot_id. '
                'Frage fehlenden Namen oder Terminwunsch nach. Nach Auswahl propose_appointment aufrufen. '
                'Vorschläge sind unbestätigt. Die Oberfläche zeigt die endgültigen Details und verlangt einen Klick '
                'auf Bestätigen; kein Tool kann buchen. Bei geänderten Wünschen einen vorhandenen Vorschlag '
                'mit cancel_proposal verwerfen, danach neu prüfen. Beachte die jüngsten Korrekturen auch bei '
                'Unterbrechungen. Keine echten Kunden, Kalender, E-Mails oder Firmendaten sind verbunden. '
                'Nur list_bookings oder das bestätigte UI-Ergebnis belegt eine gespeicherte Demo-Buchung. '
                'Wenn der Benutzer ausdrücklich fertig ist oder sich verabschiedet, end_conversation aufrufen. Berichte Fehler ehrlich und knapp. Unverfügbare Zeiten nicht anbieten.'
            ),
            'tools': TOOLS,
        }},
    }


class FrontDeskLive:
    def __init__(self, options, db_factory):
        self.db = db_factory
        self.enabled = options.get('live_enabled') is True
        self.owner = options.get('online_ha_user_id') or ''
        self._key = options.get('openai_api_key') or ''
        self.limit = options.get('live_daily_limit', 10)
        self.max_seconds = options.get('live_max_seconds', 600)
        self.configured = (
            isinstance(self.owner, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.owner))
            and isinstance(self._key, str) and bool(re.fullmatch(r'sk-[A-Za-z0-9_-]{20,500}', self._key))
            and type(self.limit) is int and 1 <= self.limit <= 100
            and type(self.max_seconds) is int and 60 <= self.max_seconds <= 600
        )
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            self.limit = 10
        if type(self.max_seconds) is not int or not 60 <= self.max_seconds <= 600:
            self.max_seconds = 600
        self._timers = {}
        self._timer_lock = threading.Lock()
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS atlas_live_sessions (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL, day TEXT NOT NULL,
                session_id TEXT, expires_at REAL NOT NULL, state TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS atlas_live_owner_day ON atlas_live_sessions(user_id, day)')
            db.execute("UPDATE atlas_live_sessions SET state='close_unconfirmed' WHERE state='closing'")
            pending = db.execute("SELECT user_id,session_id,expires_at FROM atlas_live_sessions WHERE session_id IS NOT NULL AND state IN ('active','closing','close_unconfirmed','client_closed')").fetchall()
        for user, session_id, expires_at in pending:
            self._schedule_close(user, session_id, max(0, expires_at - time.time()))

    def enabled_for(self, user):
        return bool(self.enabled and self.configured and user == self.owner)

    def status(self, user):
        used = 0
        if user == self.owner:
            with self.db() as db:
                used = db.execute('SELECT count(*) FROM atlas_live_sessions WHERE user_id=? AND day=?',
                                  (user, datetime.now(timezone.utc).date().isoformat())).fetchone()[0]
        reason = ('Bereit' if self.enabled_for(user) else 'GPT-Live ist deaktiviert oder für diesen Benutzer nicht eingerichtet.')
        return {'enabled': self.enabled_for(user), 'reason': reason, 'used': used, 'limit': self.limit,
                'model': 'gpt-live-1', 'backend_model': 'gpt-6-luna', 'max_seconds': self.max_seconds,
                'duration_limit_enforcement': 'server_sideband_and_browser', 'demo': True}

    def create(self, user, sdp):
        if not self.enabled_for(user):
            raise LiveError('GPT-Live ist für diesen Benutzer nicht freigegeben.')
        if not isinstance(sdp, str) or not sdp.startswith('v=0') or not 10 <= len(sdp) <= 24000 or '\x00' in sdp:
            raise ValueError('Ungültiges Verbindungsangebot.')
        stamp = time.time()
        token = secrets.token_urlsafe(24)
        day = datetime.now(timezone.utc).date().isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM atlas_live_sessions WHERE user_id=? AND state IN ('creating','active','closing','close_unconfirmed') AND expires_at>?",
                          (user, stamp)).fetchone():
                raise LiveError('Es läuft bereits ein GPT-Live-Gespräch. Bitte zuerst beenden.')
            used = db.execute('SELECT count(*) FROM atlas_live_sessions WHERE user_id=? AND day=?', (user, day)).fetchone()[0]
            if used >= self.limit:
                raise LiveError('Das tägliche GPT-Live-Startlimit ist erreicht (UTC).')
            db.execute('INSERT INTO atlas_live_sessions VALUES (?,?,?,?,?,?)',
                       (token, user, day, None, stamp + self.max_seconds, 'creating'))
        # Reserve before network call, including failed or ambiguous attempts.
        session_id = None
        try:
            raw = _request(self._key, {'session': session_config(), 'transport': {'type': 'webrtc', 'sdp': sdp}})
            session_id = raw['session']['id']
            answer = raw['transport']['sdp']
            if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', session_id):
                raise ValueError('Invalid session identifier')
            if not isinstance(answer, str) or not answer.startswith('v=0') or not 10 <= len(answer) <= 32000 or '\x00' in answer:
                raise ValueError('Invalid SDP')
        except Exception:
            if isinstance(session_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,256}', session_id):
                with self.db() as db:
                    db.execute("UPDATE atlas_live_sessions SET session_id=?, state='active' WHERE token=?", (session_id, token))
                self._schedule_close(user, session_id, 0)
            # A timeout may still have created a remote session. Keep the lease
            # until expiry and count the attempt; never automatically retry it.
            raise LiveError(FAILURE) from None
        with self.db() as db:
            db.execute("UPDATE atlas_live_sessions SET session_id=?, state='active' WHERE token=?", (session_id, token))
        self._schedule_close(user, session_id, max(0, stamp + self.max_seconds - time.time()))
        return {'session': {'id': session_id}, 'transport': {'sdp': answer}, 'max_seconds': self.max_seconds}

    def active_for(self, user, session_id):
        if not self.enabled_for(user) or not isinstance(session_id, str):
            return False
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM atlas_live_sessions WHERE user_id=? AND session_id=? AND state='active' AND expires_at>?",
                                   (user, session_id, time.time())).fetchone())

    owns_session = active_for

    def _schedule_close(self, user, session_id, delay, attempt=0):
        def watchdog():
            try:
                result = self.close(user, session_id)
                if result['provider_finalization'] != 'confirmed' and attempt == 0:
                    self._schedule_close(user, session_id, 5, attempt=1)
            except Exception:
                # No provider/private exception output from a daemon thread.
                pass
        timer = threading.Timer(delay, watchdog)
        timer.daemon = True
        with self._timer_lock:
            previous = self._timers.get(session_id)
            if previous:
                previous.cancel()
            self._timers[session_id] = timer
        timer.start()

    def close(self, user, session_id, client_closed=False):
        """Try server-side finalization; never certify a lost connection as closed."""
        if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', session_id):
            raise ValueError('Ungültige Sitzung.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT token,state FROM atlas_live_sessions WHERE user_id=? AND session_id=?', (user, session_id)).fetchone()
            if not row:
                raise LiveError('Sitzung nicht gefunden oder nicht freigegeben.')
            if row[1] == 'finalized':
                return {'released': True, 'provider_finalization': 'confirmed'}
            if client_closed is True:
                db.execute("UPDATE atlas_live_sessions SET state='client_closed' WHERE token=?", (row[0],))
                return {'released': True, 'provider_finalization': 'unconfirmed', 'client_reported_closed': True}
            if row[1] == 'closing':
                return {'released': False, 'provider_finalization': 'unconfirmed'}
            db.execute("UPDATE atlas_live_sessions SET state='closing' WHERE token=?", (row[0],))
        finalized = _close_remote(self._key, session_id)
        with self.db() as db:
            db.execute('UPDATE atlas_live_sessions SET state=? WHERE token=?',
                       ('finalized' if finalized else ('client_closed' if row[1] == 'client_closed' else 'close_unconfirmed'), row[0]))
        if finalized:
            with self._timer_lock:
                timer = self._timers.pop(session_id, None)
            if timer:
                timer.cancel()
        return {'released': finalized or row[1] == 'client_closed', 'provider_finalization': 'confirmed' if finalized else 'unconfirmed'}
