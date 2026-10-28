"""Read-only HA mail bridge; destination fixed, no redirects/proxy or IMAP fallback."""
import base64
import binascii
import hashlib
from datetime import date
import http.client
import json
import re
import time
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from html.parser import HTMLParser
from urllib.parse import urlsplit
class MailError(Exception):
    pass


class MailAccessError(MailError):
    pass


class UIDValidityChanged(MailError):
    pass


ImapFetchError = MailError
MAX_MESSAGE = 32 * 1024 * 1024
MAX_BATCH = 40 * 1024 * 1024
MAX_MESSAGES = 10

HOST = 'local-ftst-strato-mail'
PORT = 8098
MAX_RESPONSE = ((MAX_BATCH + 2) // 3) * 4 + 65536
TIMEOUT = 15
RESPONSE_TIMEOUT = 85
MAX_SECONDS = 130
MAX_MIME_PARTS = 100
MAX_MIME_DEPTH = 12
MAX_ATTACHMENTS = 20
MAX_ATTACHMENT = 8 * 1024 * 1024
ATTACHMENT_TYPES = {'application/pdf': '.pdf', 'application/xml': '.xml',
                    'text/xml': '.xml', 'image/png': '.png', 'image/jpeg': '.jpg',
                    'image/tiff': '.tiff'}


def _parse_message(raw):
    count = 0
    def factory(**kwargs):
        nonlocal count
        count += 1
        if count > MAX_MIME_PARTS:
            raise MailError('MIME-Struktur überschreitet das Limit.')
        return EmailMessage(**kwargs)
    return BytesParser(_class=factory, policy=policy.default).parsebytes(raw)


def _attachment_type(part, name, data):
    declared = part.get_content_type()
    if declared == 'application/octet-stream':
        extension = name.lower().rsplit('.', 1)[-1]
        declared = {'pdf': 'application/pdf', 'xml': 'application/xml',
                    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'tif': 'image/tiff', 'tiff': 'image/tiff'}.get(extension)
    if declared not in ATTACHMENT_TYPES:
        return None
    stripped = data.lstrip(b'\xef\xbb\xbf \t\r\n')
    valid = ((declared == 'application/pdf' and stripped.startswith(b'%PDF-'))
             or (declared in ('application/xml', 'text/xml') and stripped.startswith(b'<')
                 and b'\x00' not in data and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper())
             or (declared == 'image/png' and data.startswith(b'\x89PNG\r\n\x1a\n'))
             or (declared == 'image/jpeg' and data.startswith(b'\xff\xd8\xff'))
             or (declared == 'image/tiff' and data.startswith((b'II*\x00', b'MM\x00*'))))
    return declared if valid else None


def _safe_filename(name, index, content_type):
    # A display name only: storage must use its own opaque/hash key, never this name.
    basename = re.split(r'[/\\]', name)[-1]
    stem = basename.rsplit('.', 1)[0] if '.' in basename else basename
    stem = re.sub(r'[^A-Za-z0-9_-]', '_', stem)[:80].strip('_-')
    return (stem or 'attachment-' + str(index)) + ATTACHMENT_TYPES[content_type]


def _invoice_message(raw, source, epoch, uid):
    """Collect inert candidate bytes; never declare a document to be an invoice."""
    reference = dict(source, uidvalidity=epoch, uid=uid)
    result = {'source': reference, 'uid': uid, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
              'subject': '', 'from': '', 'date': '', 'message_id': '',
              'attachments': [], 'warnings': []}
    try:
        message = _parse_message(raw)
        for key, header in [('subject', 'subject'), ('from', 'from'), ('date', 'date'), ('message_id', 'message-id')]:
            result[key] = str(message.get(header, ''))[:1000]
        pending, count, attachments = [(message, 0)], 0, []
        while pending:
            part, depth = pending.pop()
            count += 1
            if count > MAX_MIME_PARTS or depth > MAX_MIME_DEPTH:
                result['warnings'].append('MIME-Struktur überschreitet das Limit; keine Anhänge dieser Nachricht übernommen.')
                result['attachments'] = []
                return result
            if part.get_content_type() == 'message/rfc822':
                result['warnings'].append('Eingebettete E-Mail nicht ausgewertet.')
                continue
            if part.is_multipart():
                children = part.get_payload()
                if not isinstance(children, list) or len(children) + count > MAX_MIME_PARTS:
                    result['warnings'].append('MIME-Struktur überschreitet das Limit; keine Anhänge dieser Nachricht übernommen.')
                    return result
                pending.extend((child, depth + 1) for child in reversed(children))
                continue
            filename = part.get_filename() or ''
            disposition = part.get_content_disposition()
            if disposition == 'inline' or (disposition != 'attachment' and not filename):
                continue
            if len(attachments) >= MAX_ATTACHMENTS:
                result['warnings'].append('Weitere Anhänge wegen Mengenlimit nicht übernommen.')
                break
            if part.get_content_type() not in (*ATTACHMENT_TYPES, 'application/octet-stream'):
                result['warnings'].append('Nicht unterstützter Anhang nicht übernommen.')
                continue
            data = part.get_payload(decode=True)
            if part.defects or not isinstance(data, bytes) or not data or len(data) > MAX_ATTACHMENT:
                result['warnings'].append('Fehlerhafter, leerer oder zu großer Anhang nicht übernommen.')
                continue
            content_type = _attachment_type(part, filename, data)
            if content_type is None:
                result['warnings'].append('Dateityp oder Dateisignatur nicht unterstützt; Anhang nicht übernommen.')
                continue
            attachments.append({'name': _safe_filename(filename, count, content_type),
                'content_type': content_type, 'data': data, 'size': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
                'source': dict(reference, part_index=count), 'candidate_only': True})
        result['attachments'] = attachments
        if message.defects:
            result['warnings'].append('Nachrichtenformat weist Fehler auf; Anhänge bitte prüfen.')
    except Exception:
        # A bad message must not keep every subsequent document permanently blocked.
        result['attachments'] = []
        result['warnings'].append('Nachrichtenformat nicht lesbar; Anhänge dieser Nachricht nicht übernommen.')
    return result


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        elif tag in ('p', 'br', 'div', 'li') and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _message(raw, source, epoch, uid):
    message = _parse_message(raw)
    body = message.get_body(preferencelist=('plain', 'html'))
    text = ''
    warnings = []
    if body is not None:
        try:
            text = body.get_content()
            if not isinstance(text, str):
                raise ValueError()
            if body.get_content_type() == 'text/html':
                parser = _PlainHTML()
                parser.feed(text)
                text = ''.join(parser.parts)
        except (LookupError, UnicodeError, ValueError):
            warnings.append('Nachrichtentext konnte nicht vollständig gelesen werden.')
            text = ''
    if not text.strip():
        warnings.append('Kein lesbarer Nachrichtentext; Anhänge werden nicht ausgewertet.')
    if len(text) > 12000:
        warnings.append('Nachrichtentext auf 12000 Zeichen gekürzt.')
    if message.defects:
        warnings.append('Nachrichtenformat weist Fehler auf.')
    return {'source': dict(source, uidvalidity=epoch, uid=uid), 'uid': uid,
            'subject': str(message.get('subject', ''))[:1000],
            'from': str(message.get('from', ''))[:1000],
            'to': str(message.get('to', ''))[:1000],
            'date': str(message.get('date', ''))[:200],
            'message_id': str(message.get('message-id', ''))[:1000],
            'body': text[:12000], 'body_truncated': len(text) > 12000, 'warnings': warnings,
            'attachments_present': any(p.get_content_disposition() == 'attachment' for p in message.walk())}


class MailClient:
    """Explicit, per-owner preview; no state changes, persistent cache or sending."""
    def __init__(self, options):
        self.enabled = options.get('mail_enabled') is True
        self.owner = options.get('mail_ha_user_id') or ''
        self.token = options.get('mail_bridge_token') or ''
        self.account_id = options.get('mail_account_id') or 'primary'
        self.account_ids = options.get('mail_account_ids', [self.account_id])
        if self.account_ids == []:
            self.account_ids = [self.account_id]
        self.host = '76b650ab-ftst-strato-mail'
        if not self.enabled:
            return
        try:
            parsed = urlsplit(options.get('mail_bridge_url') or 'http://76b650ab-ftst-strato-mail:8098')
            if (parsed.scheme != 'http' or parsed.hostname not in ('76b650ab-ftst-strato-mail', 'local-ftst-strato-mail')
                    or parsed.port != PORT or parsed.path or parsed.query or parsed.fragment
                    or parsed.username or parsed.password):
                raise ValueError()
            if (not isinstance(self.owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.owner)
                    or not isinstance(self.token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', self.token)):
                raise ValueError()
            validate_account_id(self.account_id)
            if (not isinstance(self.account_ids, list) or not 1 <= len(self.account_ids) <= 21
                    or any(not isinstance(account, str) for account in self.account_ids)
                    or len(set(self.account_ids)) != len(self.account_ids)):
                raise ValueError()
            for account in self.account_ids:
                validate_account_id(account)
            if self.account_id not in self.account_ids:
                self.account_id = self.account_ids[0]
            self.account_ids = tuple(self.account_ids)
            self.host = parsed.hostname
        except (ValueError, TypeError, MailError):
            raise MailError('Mail-Anbindung unvollständig oder ungültig konfiguriert.') from None

    def enabled_for(self, user_id):
        return self.enabled and bool(self.owner) and isinstance(user_id, str) and user_id == self.owner

    def accounts(self, user_id):
        if not self.enabled_for(user_id):
            raise MailAccessError('Mail-Zugriff für diesen Benutzer nicht freigegeben.')
        return [account for account in list_accounts(self.token, host=self.host)
                if account['id'] in self.account_ids]

    def _batch(self, user_id, days, account_id, after_uid=0, uidvalidity=None, since=None, max_days=30):
        if not self.enabled_for(user_id):
            raise MailAccessError('Mail-Zugriff für diesen Benutzer nicht freigegeben.')
        if type(days) is not int or not 1 <= days <= max_days:
            raise MailError('Zeitraum überschreitet das erlaubte Limit.')
        if since is None:
            since = (date.today() - timedelta(days=days - 1)).isoformat()
        else:
            try:
                if not isinstance(since, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
                    raise ValueError()
                start_date = date.fromisoformat(since)
                if not 0 <= (date.today() - start_date).days < max_days:
                    raise ValueError()
            except ValueError:
                raise MailError('Startdatum fehlt oder überschreitet das erlaubte Limit.') from None
        account_id = self.account_id if account_id is None else validate_account_id(account_id)
        if account_id not in self.account_ids:
            raise MailAccessError('Postfach nicht für ATLAS freigegeben.')
        after_uid = _number(after_uid, zero=True)
        if after_uid and uidvalidity is None:
            raise MailError('Fortsetzen erfordert die unveränderte Postfachgeneration.')
        if uidvalidity is not None:
            uidvalidity = _number(uidvalidity)
        selected = [a for a in self.accounts(user_id) if a['id'] == account_id]
        if len(selected) != 1:
            raise MailError('Freigegebenes Postfach nicht verfügbar.')
        account = selected[0]
        expected = {k: account[k] for k in ('email', 'folder')}
        if uidvalidity is None:
            uidvalidity = activation_checkpoint(self.token, account_id, expected, host=self.host)['uidvalidity']
        batch = fetch_batch(self.token, since, uidvalidity, after_uid,
                            account_id, expected, host=self.host)
        source = {'account_id': account_id, 'mailbox': account['email'], 'folder': account['folder']}
        return source, since, batch

    def preview(self, user_id, days=7, account_id=None):
        source, since, batch = self._batch(user_id, days, account_id)
        try:
            messages = [_message(raw, source, batch['uidvalidity'], uid) for uid, raw in batch['messages']]
        except Exception:
            raise MailError('Nachrichtenformat konnte nicht sicher gelesen werden.') from None
        return {'source': source, 'uidvalidity': batch['uidvalidity'], 'since': since,
                'messages': messages, 'pending': batch['pending'], 'order': 'oldest_first',
                'read_only': True, 'scope': 'Bis zu 10 Nachrichten im Zeitraum; keine vollständige oder ungelesene Postfachliste.'}

    def invoice_batch(self, user_id, account_id, days, after_uid=0, uidvalidity=None, since=None):
        """Caller commits candidate documents before advancing this returned cursor.

        This returns bytes and is not a JSON/HTTP response. Non-invoice, malformed
        and skipped messages still advance the cursor and carry explicit warnings.
        No mail is mutated. Original MIME is hashed but not retained by this client.
        """
        source, since, batch = self._batch(user_id, days, account_id, after_uid, uidvalidity,
                                          since=since, max_days=365)
        messages, total = [], 0
        for uid, raw in batch['messages']:
            message = _invoice_message(raw, source, batch['uidvalidity'], uid)
            accepted = []
            for attachment in message['attachments']:
                if total + attachment['size'] > MAX_BATCH:
                    message['warnings'].append('Anhang wegen Gesamtgrößenlimit nicht übernommen.')
                    continue
                total += attachment['size']
                accepted.append(attachment)
            message['attachments'] = accepted
            messages.append(message)
        return {'source': source, 'uidvalidity': batch['uidvalidity'], 'since': since,
                'after_uid': max([after_uid] + [message['uid'] for message in messages]),
                'pending': batch['pending'], 'messages': messages, 'read_only': True}


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


def _request(token, path, payload=None, host=HOST):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ImapFetchError('Verbindungsschlüssel der lokalen Mail-App fehlt oder ist ungültig.')
    connection = http.client.HTTPConnection(host, PORT, timeout=TIMEOUT)
    deadline = time.monotonic() + MAX_SECONDS
    try:
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Host': 'local-ftst-strato-mail:8098'}
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
        if response.status not in (200, 409, 502):
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
        if response.status == 502:
            messages = {
                'mail_auth_failed': 'STRATO hat die Anmeldung abgelehnt. Zugangsdaten in der Mail-App prüfen. Kein Abruf übernommen.',
                'mail_message_too_large': 'Eine E-Mail überschreitet 32 MiB. Abruf angehalten; keine Nachricht übersprungen.',
                'mail_limit_exceeded': 'Eine Sicherheitsgrenze beim Mailabruf wurde erreicht. Abruf angehalten; keine Nachricht übersprungen.',
            }
            if value.get('error') in messages:
                raise ImapFetchError(messages[value['error']])
            raise ValueError('upstream failure')
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


def list_accounts(token, host=HOST):
    value = _request(token, '/internal/mail/accounts', host=host)
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


def activation_checkpoint(token, account_id='primary', expected_source=None, host=HOST):
    validate_account_id(account_id)
    value = _request(token, '/internal/mail/checkpoint', {'account_id': account_id, **_source_expectations(expected_source)}, host=host)
    if set(value) != {'uidvalidity', 'after_uid'}:
        raise ImapFetchError('Ungültiger Startpunkt der lokalen Mail-App.')
    return {'uidvalidity': _number(value['uidvalidity']), 'after_uid': _number(value['after_uid'], True)}


def fetch_batch(token, since_date, uidvalidity, after_uid, account_id='primary', expected_source=None, host=HOST):
    validate_account_id(account_id)
    epoch, cursor = _number(uidvalidity), _number(after_uid, True)
    try:
        since = date.fromisoformat(since_date) if isinstance(since_date, str) else since_date
        if type(since) is not date:
            raise ValueError
    except (ValueError, TypeError):
        raise ImapFetchError('Ungültiges Aktivierungsdatum.') from None
    value = _request(token, '/internal/mail/batch', {'uidvalidity': epoch, 'after_uid': cursor, 'since': since.isoformat(), 'account_id': account_id, **_source_expectations(expected_source)}, host=host)
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
