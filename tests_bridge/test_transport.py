import io
import ssl
import time
from datetime import date
from unittest.mock import Mock

import pytest

import strato_bridge_transport as transport

SECRET = 'synthetic-test-secret-not-a-password'


class FakeIMAP:
    def __init__(self):
        self.debug = 9
        self.calls = []
        self.search = b'1 2'
        self.validities = [7, 7]
        self.next_uid = b'3'
        self.messages = {1: b'From: a@example.test\r\n\r\nOne', 2: b'From: b@example.test\r\n\r\nTwo'}
        self.closed = False

    def login(self, user, password):
        assert self.debug == 0 and user == 'info@ftst.eu' and password == SECRET
        self.calls.append(('LOGIN',))
        return 'OK', [b'logged in']

    def select(self, mailbox, readonly=False):
        self.calls.append(('SELECT', mailbox, readonly))
        return 'OK', [b'2']

    def response(self, key):
        return key, [b'7' if key == 'UIDVALIDITY' else self.next_uid]

    def status(self, mailbox, query):
        self.calls.append(('STATUS', mailbox, query))
        value = self.validities.pop(0)
        return 'OK', [f'INBOX (UIDVALIDITY {value})'.encode()]

    def uid(self, action, *args):
        self.calls.append((action,) + args)
        if action == 'SEARCH':
            return 'OK', [self.search]
        uid = int(args[0])
        raw = self.messages[uid]
        info = f'1 (UID {uid} RFC822.SIZE {len(raw)}'.encode()
        if 'BODY.PEEK' in args[1]:
            return 'OK', [(info + f' BODY[]<0> {{{len(raw)}}}'.encode(), raw), b')']
        return 'OK', [info + b')']

    def shutdown(self):
        self.closed = True


@pytest.fixture
def server(monkeypatch):
    client = FakeIMAP()
    monkeypatch.setattr(transport, '_BoundedIMAP', lambda: client)
    return client


def test_checkpoint_requires_uidnext_without_message_fetch(server):
    assert transport.activation_checkpoint(SECRET) == {'uidvalidity': 7, 'after_uid': 2}
    assert server.closed
    assert ('SELECT', 'INBOX', True) in server.calls
    assert not any(c[0] in ('FETCH', 'SEARCH') for c in server.calls)


@pytest.mark.parametrize('bad', [None, b'', b'zero', b'0', b'4294967296'])
def test_checkpoint_missing_or_invalid_uidnext_fails_closed(server, bad):
    server.next_uid = bad
    with pytest.raises(transport.ImapFetchError):
        transport.activation_checkpoint(SECRET)
    assert server.closed


def test_checkpoint_validity_change_rejected(server):
    server.validities = [8]
    with pytest.raises(transport.UIDValidityChanged):
        transport.activation_checkpoint(SECRET)


def test_readonly_peek_and_local_uid_filter(server):
    result = transport.fetch_batch(SECRET, '2026-09-18', uidvalidity='7', after_uid=1)
    assert result == {'uidvalidity': 7, 'messages': [(2, server.messages[2])], 'pending': False}
    assert ('SEARCH', None, 'SINCE', '18-Sep-2026', 'UID', '2:*') in server.calls
    assert ('FETCH', '2', f'(UID RFC822.SIZE BODY.PEEK[]<0.{transport.MAX_MESSAGE + 1}>)') in server.calls
    assert not any(c[0] in ('STORE', 'CLOSE', 'EXPUNGE', 'LOGOUT') for c in server.calls)
    assert server.closed


def test_star_range_can_return_old_uid_without_fetch(server):
    server.search = b'2'
    result = transport.fetch_batch(SECRET, date(2026, 9, 18), 7, 100)
    assert result['messages'] == [] and not result['pending']
    assert not any(c[0] == 'FETCH' for c in server.calls)


@pytest.mark.parametrize('expected,end', [(8, 7), (7, 8)])
def test_validity_change_before_or_after_discards_batch(server, expected, end):
    server.validities = [7, end]
    with pytest.raises(transport.UIDValidityChanged):
        transport.fetch_batch(SECRET, '2026-09-18', expected)
    assert server.closed


def test_ten_messages_limit_and_pending(server):
    server.messages = {n: b'x' for n in range(1, 13)}
    server.search = b' '.join(str(n).encode() for n in server.messages)
    result = transport.fetch_batch(SECRET, '2026-09-18')
    assert len(result['messages']) == 10 and result['pending']
    assert result['messages'][-1][0] == 10


def test_batch_byte_limit_stops_before_body_without_skipping(server, monkeypatch):
    monkeypatch.setattr(transport, 'MAX_BATCH', 5)
    server.messages = {1: b'123', 2: b'456'}
    result = transport.fetch_batch(SECRET, '2026-09-18')
    assert result['messages'] == [(1, b'123')] and result['pending']
    assert not any(c[0] == 'FETCH' and c[1] == '2' and 'BODY' in c[2] for c in server.calls)


def test_oversize_metadata_discards_earlier_message(server, monkeypatch):
    monkeypatch.setattr(transport, 'MAX_MESSAGE', 3)
    server.messages = {1: b'123', 2: b'4567'}
    with pytest.raises(transport.ImapLimitError):
        transport.fetch_batch(SECRET, '2026-09-18')
    assert server.closed


@pytest.mark.parametrize('reply', [
    ('NO', [SECRET.encode()]),
    ('OK', [(b'1 (UID 999 RFC822.SIZE 3 BODY[]<0> {3}', b'abc'), b')']),
    ('OK', [(b'1 (UID 1 RFC822.SIZE 3 BODY[]<1> {3}', b'abc'), b')']),
    ('OK', [(b'1 (UID 1 RFC822.SIZE 3 BODY[]<0> {3}', b'ab'), b')']),
    ('OK', [(b'1 (UID 1 RFC822.SIZE 3 BODY[]<0> {4}', b'abc'), b')']),
    ('OK', [None]),
])
def test_unconfirmed_uid_size_or_literal_rejected(server, reply):
    server.uid = Mock(return_value=reply)
    with pytest.raises(transport.ImapFetchError):
        transport._fetch(server, 1, body=True)


def test_uid_after_literal_is_supported(server):
    server.uid = Mock(return_value=('OK', [(b'1 (BODY[]<0> {3}', b'abc'), b' UID 1 RFC822.SIZE 3)']))
    assert transport._fetch(server, 1, body=True) == (3, b'abc')


def test_server_timeout_and_credentials_are_redacted(server, caplog):
    server.login = Mock(side_effect=TimeoutError(SECRET))
    with pytest.raises(transport.ImapFetchError) as exc:
        transport.fetch_batch(SECRET, '2026-09-18')
    assert SECRET not in str(exc.value) + caplog.text
    assert exc.value.__suppress_context__ and server.closed


def test_invalid_dates_and_cursors_never_connect(server):
    for kwargs in [{'since_date': 'garbage'}, {'since_date': '2026-09-18', 'after_uid': -1},
                   {'since_date': '2026-09-18', 'uidvalidity': True}]:
        with pytest.raises(transport.ImapFetchError):
            transport.fetch_batch(SECRET, **kwargs)
    assert not server.calls


def test_fixed_tls_endpoint_and_verification(monkeypatch):
    called = {}
    def fake_init(self, host, port, **kwargs):
        called.update(host=host, port=port, **kwargs)
    monkeypatch.setattr(transport.imaplib.IMAP4_SSL, '__init__', fake_init)
    client = transport._BoundedIMAP()
    assert called['host'] == 'imap.strato.de' and called['port'] == 993
    assert called['ssl_context'].verify_mode == ssl.CERT_REQUIRED
    assert called['ssl_context'].check_hostname is True
    assert called['timeout'] == transport.TIMEOUT and client.debug == 0


def bare_client():
    client = object.__new__(transport._BoundedIMAP)
    client._deadline = time.monotonic() + 10
    client._wire = 0
    client.file = io.BytesIO(b'abc\r\n')
    return client


def test_huge_literal_rejected_before_allocating_or_reading():
    client = bare_client()
    with pytest.raises(transport.ImapLimitError):
        client.read(10**12)
    assert client.file.tell() == 0


def test_bounded_line_wire_budget_deadline():
    client = bare_client()
    client.file = io.BytesIO(b'x' * (transport.MAX_LINE + 1))
    with pytest.raises(transport.ImapLimitError):
        client.readline()
    client = bare_client()
    client._wire = transport.MAX_WIRE
    with pytest.raises(transport.ImapLimitError):
        client.read(3)
    client = bare_client()
    client._deadline = 0
    with pytest.raises(transport.ImapFetchError):
        client.read(3)


def test_normal_bounded_read_and_no_debug_in_initialization():
    client = bare_client()
    assert client.read(3) == b'abc' and client._wire == 3
    client.debug = 9
    client._mode_ascii()
    assert client.debug == 0


def test_line_read_ahead_keeps_literal_and_next_line_intact():
    client = bare_client()
    client.file = io.BytesIO(b'header {3}\r\nabc)\r\n')
    assert client.readline() == b'header {3}\r\n'
    assert client.read(3) == b'abc'
    assert client.readline() == b')\r\n'
    assert client._wire == len(b'header {3}\r\nabc)\r\n')
