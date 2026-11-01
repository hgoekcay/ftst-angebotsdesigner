"""Direct Google OAuth, isolated from Home Assistant's Google integration.

Only begin/finish/disconnect may be exposed through authenticated owner+CSRF routes.
The public callback consumes an unguessable state and stages credentials; only the
owner's subsequent explicit finish activates them. Never return access_token()
from an HTTP route. Backups of the private data directory contain credentials.
"""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
from urllib.parse import urlencode, urlsplit

SCOPES = frozenset(('https://www.googleapis.com/auth/calendar.events',
                    'https://www.googleapis.com/auth/calendar.calendarlist.readonly'))
TTL = 600
MAX_BYTES = 128 * 1024
TIMEOUT = 20


class GoogleOAuthError(ValueError):
    pass


def _exchange(payload):
    connection = http.client.HTTPSConnection('oauth2.googleapis.com', 443,
                                             timeout=TIMEOUT, context=ssl.create_default_context())
    try:
        connection.request('POST', '/token', body=urlencode(payload).encode(),
                           headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError()
        deadline, chunks, size = time.monotonic() + TIMEOUT, [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError()
            if connection.sock:
                connection.sock.settimeout(min(5, remaining))
            chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError()
            chunks.append(chunk)
        raw = json.loads(b''.join(chunks))
        if not isinstance(raw, dict):
            raise ValueError()
        return raw
    except Exception:
        raise GoogleOAuthError('Google-Anmeldung konnte nicht abgeschlossen werden. Client-ID, Client-Geheimnis und Freigabe prüfen; neu verbinden.') from None
    finally:
        connection.close()


def _secret(value, limit=8192):
    return isinstance(value, str) and 1 <= len(value) <= limit and not any(ord(c) <= 32 or ord(c) == 127 for c in value)


class GoogleOAuth:
    def __init__(self, options, data_dir):
        self.owner = options.get('calendar_ha_user_id') or ''
        self.client_id = options.get('google_client_id') or ''
        self.client_secret = options.get('google_client_secret') or ''
        self.redirect_uri = options.get('google_redirect_uri') or ''
        self.enabled = options.get('calendar_enabled') is True and options.get('calendar_provider') == 'google'
        self._lock = threading.RLock()
        self._path = Path(data_dir) / 'google-oauth.json'
        try:
            uri = urlsplit(self.redirect_uri)
            redirect_ok = (uri.scheme == 'https' and bool(uri.hostname) and not uri.username and not uri.password
                           and uri.path == '/oauth/google/callback' and not uri.query and not uri.fragment
                           and uri.port in (None, 443) and not any(c.isspace() for c in self.redirect_uri))
        except (TypeError, ValueError):
            redirect_ok = False
        self.configured = bool(self.enabled and isinstance(self.owner, str)
                               and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.owner)
                               and isinstance(self.client_id, str)
                               and re.fullmatch(r'[A-Za-z0-9_-]{10,250}\.apps\.googleusercontent\.com', self.client_id)
                               and _secret(self.client_secret, 512) and redirect_ok)
        self._binding = hashlib.sha256(json.dumps([self.owner, self.client_id, self.redirect_uri]).encode()).hexdigest()
        self._data = self._load()

    def _load(self):
        if not self._path.exists():
            return {}
        try:
            if self._path.is_symlink() or self._path.stat().st_size > MAX_BYTES:
                raise ValueError()
            os.chmod(self._path, 0o600)
            data = json.loads(self._path.read_text())
            if not isinstance(data, dict) or data.get('binding') != self._binding:
                return {}
            return data
        except Exception:
            raise GoogleOAuthError('Geschützter Google-Zugangsspeicher ist nicht lesbar.') from None

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump({**self._data, 'binding': self._binding}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _check(self, user):
        if not self.configured or user != self.owner:
            raise GoogleOAuthError('Google-Kalender ist für diesen Benutzer nicht eingerichtet.')

    def status(self, user):
        with self._lock:
            allowed = self.configured and user == self.owner
            connected = bool(allowed and self._data.get('grant', {}).get('refresh_token'))
            pending = bool(allowed and self._data.get('pending', {}).get('expires_at', 0) > time.time())
            return {'configured': bool(allowed), 'connected': connected, 'pending': pending,
                    'connection_id': self._data.get('connection_id', '') if connected else '',
                    'reason': ('Google-Zugang gespeichert; Kalender auswählen und prüfen.' if connected else
                               'Google-Freigabe wartet auf Bestätigung in ATLAS.' if pending else
                               'Google verbinden.' if allowed else 'Google OAuth-Zugang und HTTPS-Rückleitung noch nicht eingerichtet.'),
                    **({'redirect_uri': self.redirect_uri} if allowed else {})}

    def begin(self, user):
        self._check(user)
        with self._lock:
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            self._data.pop('pending', None)
            self._data['flow'] = {'state_hash': hashlib.sha256(state.encode()).hexdigest(),
                                  'verifier': verifier, 'expires_at': time.time() + TTL}
            self._save()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            return {'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
                'client_id': self.client_id, 'redirect_uri': self.redirect_uri, 'response_type': 'code',
                'scope': ' '.join(sorted(SCOPES)), 'state': state, 'code_challenge': challenge,
                'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent'}), 'expires_in': TTL}

    def _tokens(self, raw, refresh=None, scope=None):
        access, expires = raw.get('access_token'), raw.get('expires_in')
        refresh = raw.get('refresh_token') or refresh
        granted = raw.get('scope', scope)
        if (not _secret(access) or not _secret(refresh) or raw.get('token_type', '').lower() != 'bearer'
                or type(expires) not in (int, float) or not 0 < expires <= 86400
                or not isinstance(granted, str) or not SCOPES.issubset(set(granted.split()))):
            raise GoogleOAuthError('Google hat den erforderlichen Kalenderzugriff nicht vollständig freigegeben. Bitte neu verbinden.')
        return {'access_token': access, 'refresh_token': refresh, 'expires_at': time.time() + expires,
                'scope': granted}

    def callback(self, query):
        if not self.configured or not isinstance(query, dict):
            raise GoogleOAuthError('Ungültige Google-Rückleitung.')
        state = query.get('state')
        if not _secret(state, 128):
            raise GoogleOAuthError('Google-Rückleitung ist ungültig oder abgelaufen.')
        with self._lock:
            flow = self._data.get('flow', {})
            if (flow.get('expires_at', 0) <= time.time() or not secrets.compare_digest(
                    hashlib.sha256(state.encode()).hexdigest(), flow.get('state_hash', ''))):
                raise GoogleOAuthError('Google-Rückleitung ist ungültig oder abgelaufen.')
            self._data.pop('flow', None)
            self._save()  # One attempt: a lost token exchange must start a new flow.
            if query.get('error'):
                raise GoogleOAuthError('Google-Freigabe wurde nicht erteilt. In ATLAS erneut verbinden.')
            code = query.get('code')
            if not _secret(code, 4096):
                raise GoogleOAuthError('Google-Rückleitung enthält keinen gültigen Code.')
            tokens = self._tokens(_exchange({'client_id': self.client_id, 'client_secret': self.client_secret,
                'code': code, 'code_verifier': flow['verifier'], 'redirect_uri': self.redirect_uri,
                'grant_type': 'authorization_code'}))
            self._data['pending'] = {'tokens': tokens, 'expires_at': time.time() + TTL}
            self._save()
            return {'pending': True}

    def finish(self, user):
        self._check(user)
        with self._lock:
            pending = self._data.get('pending', {})
            if pending.get('expires_at', 0) <= time.time():
                raise GoogleOAuthError('Keine gültige Google-Freigabe vorhanden. Bitte neu verbinden.')
            self._data['grant'] = pending['tokens']
            self._data['connection_id'] = secrets.token_hex(24)
            self._data.pop('pending', None)
            self._save()
            return self.status(user)

    def access_token(self, user):
        self._check(user)
        with self._lock:
            grant = self._data.get('grant', {})
            if not _secret(grant.get('refresh_token')):
                raise GoogleOAuthError('Google ist noch nicht verbunden.')
            if grant.get('expires_at', 0) > time.time() + 60 and _secret(grant.get('access_token')):
                return grant['access_token']
            tokens = self._tokens(_exchange({'client_id': self.client_id, 'client_secret': self.client_secret,
                'refresh_token': grant['refresh_token'], 'grant_type': 'refresh_token'}),
                refresh=grant['refresh_token'], scope=grant.get('scope'))
            self._data['grant'] = tokens
            self._save()
            return tokens['access_token']

    def disconnect(self, user):
        self._check(user)
        with self._lock:
            self._data.clear()
            self._save()
            return self.status(user)
