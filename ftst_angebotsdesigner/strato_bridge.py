"""Read-only HA mail bridge; destination fixed, no redirects/proxy or IMAP fallback."""
import base64
import binascii
from datetime import date
import http.client
import json
import re
import time
from strato_imap import ImapFetchError, UIDValidityChanged, MAX_MESSAGE, MAX_BATCH, MAX_MESSAGES

HOST = 'local-ftst-strato-mail'
PORT = 8098
MAX_RESPONSE = ((MAX_BATCH + 2) // 3) * 4 + 65536
TIMEOUT = 15
RESPONSE_TIMEOUT = 85
MAX_SECONDS = 130


def _number(value, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 4294967295:
        raise ImapFetchError('Ungültige Kennung der lokalen Mail-App. Kein Abruf übernommen.')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _request(token, path, payload=None):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ImapFetchError('Verbindungsschlüssel der lokalen Mail-App fehlt oder ist ungültig.')
    connection = http.client.HTTPConnection(HOST, PORT, timeout=TIMEOUT)
    deadline = time.monotonic() + MAX_SECONDS
    try:
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        connection.request('GET' if body is None else 'POST', path, body=body, headers=headers)
        # Upstream mail worker may need 75 seconds before sending headers.
        # Keep a reference: HTTPConnection can detach a Connection: close socket.
        response_socket = connection.sock
        response_socket.settimeout(RESPONSE_TIMEOUT)
        response = connection.getresponse()
        response_socket.settimeout(TIMEOUT)
        if response.status not in (200, 409):
            raise ValueError('HTTP failure')
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ValueError('not JSON')
        limit = MAX_RESPONSE if response.status == 200 else 4096
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > limit):
            raise ValueError('response too large')
        chunks, total = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('deadline')
            response_socket.settimeout(min(TIMEOUT, remaining))
            block = response.read1(min(65536, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > limit:
                raise ValueError('response too large')
        if length is not None and total != int(length):
            raise ValueError('truncated response')
        value = json.loads(b''.join(chunks), object_pairs_hook=_unique_object)
        if type(value) is not dict:
            raise ValueError('invalid object')
        if response.status == 409:
            if value.get('error') == 'source_changed':
                raise ImapFetchError('Postfachquelle geändert. Abruf unverändert angehalten; technischer Abgleich erforderlich.')
            if value.get('error') == 'uidvalidity_changed':
                raise UIDValidityChanged('Postfachkennung geändert. Abruf unverändert angehalten.')
            raise ValueError('conflict')
        return value
    except ImapFetchError:
        raise
    except Exception:
        raise ImapFetchError('Lokale Mail-App nicht sicher erreichbar oder Antwort ungültig. Kein Abruf übernommen.') from None
    finally:
        connection.close()


def validate_account_id(value):
    if type(value) is not str or not re.fullmatch(r'[a-z0-9_-]{1,40}', value):
        raise ImapFetchError('Ungültige Postfach-ID.')
    return value


def list_accounts(token):
    value = _request(token, '/internal/mail/accounts')
    if set(value) != {'accounts'} or type(value['accounts']) is not list or len(value['accounts']) > 21:
        raise ImapFetchError('Ungültige Postfachliste.')
    seen = set()
    for item in value['accounts']:
        if type(item) is not dict or set(item) != {'id', 'email', 'folder'}:
            raise ImapFetchError('Ungültiges Postfachformat.')
        key = validate_account_id(item['id'])
        if key in seen or any(type(item[k]) is not str or not item[k] or len(item[k]) > 320 or any(ord(c) < 32 for c in item[k]) for k in ('email', 'folder')):
            raise ImapFetchError('Ungültige oder doppelte Postfachkennung.')
        seen.add(key)
    return value['accounts']


def _source_expectations(expected_source):
    if expected_source is None:
        return {}
    if type(expected_source) is not dict or set(expected_source) != {'email', 'folder'} or any(type(value) is not str or not value or len(value) > 320 or any(ord(c) < 32 for c in value) for value in expected_source.values()):
        raise ImapFetchError('Ungültige erwartete Postfachquelle.')
    return {'expected_email': expected_source['email'], 'expected_folder': expected_source['folder']}


def activation_checkpoint(token, account_id='primary', expected_source=None):
    validate_account_id(account_id)
    value = _request(token, '/internal/mail/checkpoint', {'account_id': account_id, **_source_expectations(expected_source)})
    if set(value) != {'uidvalidity', 'after_uid'}:
        raise ImapFetchError('Ungültiger Startpunkt der lokalen Mail-App.')
    return {'uidvalidity': _number(value['uidvalidity']), 'after_uid': _number(value['after_uid'], True)}


def fetch_batch(token, since_date, uidvalidity, after_uid, account_id='primary', expected_source=None):
    validate_account_id(account_id)
    epoch, cursor = _number(uidvalidity), _number(after_uid, True)
    try:
        since = date.fromisoformat(since_date) if isinstance(since_date, str) else since_date
        if type(since) is not date:
            raise ValueError
    except (ValueError, TypeError):
        raise ImapFetchError('Ungültiges Aktivierungsdatum.') from None
    value = _request(token, '/internal/mail/batch', {'uidvalidity': epoch, 'after_uid': cursor, 'since': since.isoformat(), 'account_id': account_id, **_source_expectations(expected_source)})
    if set(value) != {'uidvalidity', 'messages', 'pending'} or type(value['messages']) is not list or type(value['pending']) is not bool:
        raise ImapFetchError('Ungültiger Abruf der lokalen Mail-App.')
    if _number(value['uidvalidity']) != epoch:
        raise UIDValidityChanged('Postfachkennung geändert. Abruf unverändert angehalten.')
    if len(value['messages']) > MAX_MESSAGES:
        raise ImapFetchError('Zu viele Nachrichten in einem Abruf.')
    messages, total, last = [], 0, cursor
    for item in value['messages']:
        if type(item) is not dict or set(item) != {'uid', 'raw_base64'}:
            raise ImapFetchError('Ungültiges Nachrichtenformat.')
        uid = _number(item['uid'])
        encoded = item['raw_base64']
        if uid <= last or type(encoded) is not str or len(encoded) > ((MAX_MESSAGE + 2) // 3) * 4:
            raise ImapFetchError('Nachrichtenfolge oder Größe ungültig. Kein Abruf übernommen.')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ImapFetchError('Nachricht konnte nicht vollständig gelesen werden.') from None
        total += len(raw)
        if not raw or len(raw) > MAX_MESSAGE or total > MAX_BATCH:
            raise ImapFetchError('Nachricht oder Abruf überschreitet das Größenlimit.')
        messages.append((uid, raw))
        last = uid
    if value['pending'] and not messages:
        raise ImapFetchError('Mail-App meldet ausstehende Nachrichten ohne Fortschritt.')
    return {'uidvalidity': epoch, 'messages': messages, 'pending': value['pending']}
