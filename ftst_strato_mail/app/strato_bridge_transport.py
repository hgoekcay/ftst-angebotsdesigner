"""Bounded, read-only STRATO intake. No SMTP, flag mutations or cursor persistence."""
import imaplib
import os
import re
import ssl
import time
from datetime import date

HOST = 'imap.strato.de'
USER = 'info@ftst.eu'  # Compatibility default for standalone transport tests.


def _user():
    return os.environ.get('STRATO_EMAIL', USER)


def _folder():
    return os.environ.get('STRATO_BRIDGE_FOLDER', 'INBOX')


def _quoted_folder():
    from strato_mail import quoted
    folder = _folder()
    return 'INBOX' if folder == 'INBOX' else quoted(folder)

MAX_MESSAGE = 8 * 1024 * 1024
MAX_BATCH = 20 * 1024 * 1024
MAX_MESSAGES = 10
TIMEOUT = 15
MAX_SECONDS = 60
MAX_LINE = 65536
MAX_WIRE = MAX_BATCH + MAX_MESSAGE + 1024 * 1024
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


class ImapFetchError(RuntimeError):
    """Only fixed messages may cross the transport boundary."""


class UIDValidityChanged(ImapFetchError):
    pass


class ImapLimitError(ImapFetchError):
    pass


class _BoundedIMAP(imaplib.IMAP4_SSL):
    def __init__(self):
        self._deadline = time.monotonic() + MAX_SECONDS
        self._wire = 0
        self._pending = b''
        super().__init__(HOST, 993, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
        self.debug = 0

    def _mode_ascii(self):
        # IMAP4.__init__ copies the module debug flag before connecting. Override
        # this initialization hook so even greetings/authentication stay quiet.
        super()._mode_ascii()
        self.debug = 0

    def _budget(self, size):
        if time.monotonic() >= self._deadline:
            raise ImapFetchError('Zeitlimit beim Postfachabruf erreicht. Kein Cursor wurde bestätigt.')
        if size < 0 or self._wire + size > MAX_WIRE:
            raise ImapLimitError('Antwortlimit beim Postfachabruf erreicht. Kein Teilabruf bestätigt.')

    def read(self, size):
        if size > MAX_MESSAGE + 1:
            raise ImapLimitError('Die Mailantwort überschreitet 8 MiB. Abruf nicht übernommen.')
        self._budget(size)
        pending = getattr(self, '_pending', b'')
        first = pending[:size]
        self._pending = pending[size:]
        chunks, remaining = [first], size - len(first)
        while remaining:
            self._budget(remaining)
            # read1 returns after at most one underlying read, so a trickling
            # peer cannot hide indefinitely inside BufferedReader.read(size).
            chunk = self.file.read1(min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            self._wire += len(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def readline(self):
        value = bytearray(getattr(self, '_pending', b''))
        self._pending = b''
        while True:
            self._budget(0)
            newline = value.find(b'\n')
            if newline >= 0:
                if newline + 1 > MAX_LINE:
                    raise ImapLimitError('IMAP-Antwortzeile zu groß. Bitte Postfachabruf prüfen.')
                self._pending = bytes(value[newline + 1:])
                return bytes(value[:newline + 1])
            if len(value) > MAX_LINE:
                raise ImapLimitError('IMAP-Antwortzeile zu groß. Bitte Postfachabruf prüfen.')
            size = min(4096, MAX_LINE + 1 - len(value))
            self._budget(size)
            chunk = self.file.read1(size)
            self._wire += len(chunk)
            if not chunk:
                return bytes(value)
            value.extend(chunk)


def _integer(value, *, zero=False):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,10}', str(value)):
        raise ImapFetchError('Ungültige IMAP-Kennung.')
    result = int(value)
    if result < (0 if zero else 1) or result > 4294967295:
        raise ImapFetchError('Ungültige IMAP-Kennung.')
    return result


def _ok(result):
    if not isinstance(result, tuple) or len(result) != 2 or result[0] != 'OK':
        raise ImapFetchError('Postfachabfrage nicht bestätigt. Bitte Verbindung und Berechtigung prüfen.')
    return result[1]


def _response_number(client, name):
    kind, values = client.response(name)
    if kind != name or not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], bytes):
        raise ImapFetchError('Postfach liefert keine sichere Synchronisationskennung.')
    try:
        return _integer(values[0].decode('ascii'))
    except UnicodeError:
        raise ImapFetchError('Postfach liefert keine sichere Synchronisationskennung.') from None


def _status_validity(client):
    values = _ok(client.status(_quoted_folder(), '(UIDVALIDITY)'))
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], bytes):
        raise ImapFetchError('Postfachkennung konnte nicht abschließend geprüft werden.')
    folder = _folder().encode('ascii')
    quoted_folder = b'"' + folder.replace(b'\\', b'\\\\').replace(b'"', b'\\"') + b'"'
    names = b'(?:' + re.escape(folder) + b'|' + re.escape(quoted_folder) + b')'
    match = re.fullmatch(names + rb' \(UIDVALIDITY ([0-9]+)\)', values[0], re.I if folder == b'INBOX' else 0)
    if not match:
        raise ImapFetchError('Postfachkennung konnte nicht abschließend geprüft werden.')
    return _integer(match[1].decode('ascii'))


def _same_validity(client, expected):
    if _status_validity(client) != expected:
        raise UIDValidityChanged('Postfachkennung geändert. Zeitraum erneut abgleichen; kein Cursor bestätigt.')


def _open(password):
    if not isinstance(password, str) or not password or len(password) > 4096 or any(c in password for c in '\r\n\x00'):
        raise ImapFetchError('Postfachpasswort fehlt oder ist ungültig.')
    client = _BoundedIMAP()
    try:
        client.debug = 0
        if password.isascii():
            _ok(client.login(_user(), password))
        else:
            capabilities = {c.decode('ascii') if isinstance(c, bytes) else c for c in client.capabilities}
            if 'AUTH=PLAIN' not in capabilities:
                raise ImapFetchError('Sichere Passwortübermittlung nicht unterstützt.')
            payload = b'\x00' + _user().encode('ascii') + b'\x00' + password.encode('utf-8')
            _ok(client.authenticate('PLAIN', lambda challenge: payload if not challenge else None))
        _ok(client.select(_quoted_folder(), readonly=True))
        return client
    except BaseException:
        _disconnect(client)
        raise


def _disconnect(client):
    # Close only the network transport. IMAP CLOSE could expunge messages.
    try:
        client.shutdown()
    except Exception:
        pass


def _run(password, operation):
    client = None
    try:
        client = _open(password)
        return operation(client)
    except ImapFetchError:
        raise
    except Exception:
        # imaplib/server errors may contain credentials or original mail text.
        raise ImapFetchError('Postfachabruf fehlgeschlagen. Zugang, TLS-Verbindung und Server prüfen; kein Cursor bestätigt.') from None
    finally:
        if client is not None:
            _disconnect(client)


def activation_checkpoint(password):
    """Baseline only: UIDNEXT-1 excludes all messages already present at activation."""
    def checkpoint(client):
        validity = _response_number(client, 'UIDVALIDITY')
        next_uid = _response_number(client, 'UIDNEXT')
        _same_validity(client, validity)
        return {'uidvalidity': validity, 'after_uid': next_uid - 1}
    return _run(password, checkpoint)


def _fetch(client, uid, *, body=False):
    query = '(UID RFC822.SIZE' + (f' BODY.PEEK[]<0.{MAX_MESSAGE + 1}>' if body else '') + ')'
    parts = _ok(client.uid('FETCH', str(uid), query))
    if not isinstance(parts, list) or len(parts) > 10:
        raise ImapFetchError('Unvollständige Mailantwort. Kein Teilabruf bestätigt.')
    metadata, bodies = [], []
    for part in parts:
        if isinstance(part, tuple) and len(part) == 2 and all(isinstance(x, bytes) for x in part):
            metadata.append(part[0])
            bodies.append(part[1])
        elif isinstance(part, bytes):
            metadata.append(part)
        else:
            raise ImapFetchError('Unvollständige Mailantwort. Kein Teilabruf bestätigt.')
    info = b' '.join(metadata)
    uids = re.findall(rb'\bUID ([0-9]+)\b', info, re.I)
    sizes = re.findall(rb'\bRFC822\.SIZE ([0-9]+)\b', info, re.I)
    if len(uids) != 1 or int(uids[0]) != uid or len(sizes) != 1:
        raise ImapFetchError('Mailkennung oder Größe unklar. Kein Teilabruf bestätigt.')
    size = int(sizes[0])
    if size > MAX_MESSAGE:
        raise ImapLimitError('Eine Mail überschreitet 8 MiB. Abruf angehalten; Mail nicht übersprungen.')
    if size <= 0 or (not body and bodies):
        raise ImapFetchError('Mailgröße oder Antwortformat ungültig.')
    if body:
        markers = re.findall(rb'BODY\[\](?:<([0-9]+)>)?\s+\{([0-9]+)\}', info, re.I)
        if (len(bodies) != 1 or len(markers) != 1 or markers[0][0] not in (b'', b'0')
                or int(markers[0][1]) != size or len(bodies[0]) != size):
            raise ImapFetchError('Mailinhalt unvollständig oder abgeschnitten. Kein Teilabruf bestätigt.')
        return size, bodies[0]
    return size, None


def fetch_batch(password, since_date, uidvalidity=None, after_uid=0):
    """Return a complete verified batch. Caller persists cursor atomically with originals."""
    try:
        since = date.fromisoformat(since_date) if isinstance(since_date, str) else since_date
        if type(since) is not date:
            raise ValueError
    except (ValueError, TypeError):
        raise ImapFetchError('Ungültiges Aktivierungsdatum.') from None
    cursor = _integer(after_uid, zero=True)
    expected = _integer(uidvalidity) if uidvalidity is not None else None

    def batch(client):
        validity = _response_number(client, 'UIDVALIDITY')
        if expected is not None and expected != validity:
            raise UIDValidityChanged('Postfachkennung geändert. Zeitraum erneut abgleichen; kein Cursor bestätigt.')
        _same_validity(client, validity)
        if cursor == 4294967295:
            _same_validity(client, validity)
            return {'uidvalidity': validity, 'messages': [], 'pending': False}
        stamp = f'{since.day:02d}-{MONTHS[since.month - 1]}-{since.year:04d}'
        found = _ok(client.uid('SEARCH', None, 'SINCE', stamp, 'UID', f'{cursor + 1}:*'))
        if not isinstance(found, list) or len(found) != 1 or not isinstance(found[0], bytes) or len(found[0]) > MAX_LINE:
            raise ImapLimitError('Suchantwort überschreitet das sichere Format oder Größenlimit.')
        tokens = found[0].split()
        if any(not re.fullmatch(rb'[0-9]{1,10}', token) for token in tokens):
            raise ImapFetchError('Ungültige Mailkennungen in Suchantwort.')
        candidates = sorted({_integer(token.decode('ascii')) for token in tokens})
        # In IMAP, start:* can include the greatest existing UID even below start.
        candidates = [uid for uid in candidates if uid > cursor]
        messages, total = [], 0
        for uid in candidates[:MAX_MESSAGES]:
            size, _ = _fetch(client, uid)
            if total + size > MAX_BATCH:
                break
            actual_size, raw = _fetch(client, uid, body=True)
            if actual_size != size:
                raise ImapFetchError('Mailgröße änderte sich während des Abrufs. Kein Teilabruf bestätigt.')
            messages.append((uid, raw))
            total += size
        _same_validity(client, validity)
        return {'uidvalidity': validity, 'messages': messages, 'pending': len(candidates) > len(messages)}
    return _run(password, batch)


def _configured_password():
    import os
    from strato_mail import credentials
    address, password = credentials()
    from strato_mail import quoted
    quoted(_folder())
    return password


def bridge_checkpoint():
    return activation_checkpoint(_configured_password())


def bridge_batch(uidvalidity, after_uid, since):
    import base64
    result = fetch_batch(_configured_password(), since, uidvalidity, after_uid)
    result['messages'] = [{'uid': uid, 'raw_base64': base64.b64encode(raw).decode('ascii')}
                          for uid, raw in result['messages']]
    return result
