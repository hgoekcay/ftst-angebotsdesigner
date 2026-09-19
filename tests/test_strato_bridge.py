import base64
import io
import json
import pytest
from unittest.mock import Mock
import strato_bridge as bridge

TOKEN = 'test_token_' + 'a' * 32


class Response:
    status = 200
    def __init__(self, value):
        self.data = io.BytesIO(json.dumps(value).encode())
        self.headers = {'Content-Type': 'application/json'}
    def getheader(self, key, default=None):
        return self.headers.get(key, default)
    def read1(self, amount):
        return self.data.read(amount)


@pytest.fixture
def connection(monkeypatch):
    class Connection:
        def __init__(self, host, port, timeout):
            assert host == 'local-ftst-strato-mail' and port == 8098 and timeout == 15
            self.response = Response({'uidvalidity': 7, 'after_uid': 20})
            self.closed = False
            self.sock = Mock()
        def request(self, method, path, body=None, headers=None):
            self.requested = (method, path, body, headers)
        def getresponse(self):
            return self.response
        def close(self):
            self.closed = True
    instance = Connection(bridge.HOST, bridge.PORT, bridge.TIMEOUT)
    monkeypatch.setattr(bridge.http.client, 'HTTPConnection', lambda *a, **k: instance)
    return instance


def batch():
    return {'uidvalidity': 7, 'messages': [{'uid': 21, 'raw_base64': base64.b64encode(b'From: x@example.test\r\n\r\nhello').decode()}], 'pending': False}


def test_fixed_destination_auth_and_request(connection):
    assert bridge.activation_checkpoint(TOKEN) == {'uidvalidity': 7, 'after_uid': 20}
    method, path, body, headers = connection.requested
    assert (method, path) == ('POST', '/internal/mail/checkpoint')
    assert json.loads(body) == {'account_id': 'primary'}
    assert headers['Authorization'] == 'Bearer ' + TOKEN
    connection.response = Response(batch())
    result = bridge.fetch_batch(TOKEN, '2026-09-19', 7, 20)
    assert result['messages'][0][0] == 21
    assert json.loads(connection.requested[2]) == {'uidvalidity': 7, 'after_uid': 20, 'since': '2026-09-19', 'account_id': 'primary'}
    assert connection.closed
    timeouts = [call.args[0] for call in connection.sock.settimeout.call_args_list]
    assert timeouts[0] == 85 and timeouts[1] == 15
    assert all(0 < value <= 85 for value in timeouts)


@pytest.mark.parametrize('status', [301, 302, 401, 403, 500, 502])
def test_no_redirects_or_secret_leak(connection, status):
    connection.response.status = status
    with pytest.raises(bridge.ImapFetchError) as error:
        bridge.activation_checkpoint(TOKEN)
    assert TOKEN not in str(error.value) and connection.closed


def test_epoch_conflict(connection):
    connection.response = Response({'error': 'uidvalidity_changed'})
    connection.response.status = 409
    with pytest.raises(bridge.UIDValidityChanged):
        bridge.fetch_batch(TOKEN, '2026-09-19', 7, 20)


@pytest.mark.parametrize('mutate', [
    lambda b: b.update(uidvalidity=True),
    lambda b: b.update(pending='false'),
    lambda b: b.update(messages=[{'uid': 20, 'raw_base64': 'eA=='}]),
    lambda b: b['messages'].append(b['messages'][0]),
    lambda b: b['messages'][0].update(raw_base64='!!'),
    lambda b: b['messages'][0].update(raw_base64=''),
    lambda b: b.update(messages=[], pending=True),
    lambda b: b.update(messages=b['messages'] * 11),
    lambda b: b.update(unexpected='anything'),
])
def test_invalid_batch_fails_closed(connection, mutate):
    value = batch(); mutate(value); connection.response = Response(value)
    with pytest.raises(bridge.ImapFetchError):
        bridge.fetch_batch(TOKEN, '2026-09-19', 7, 20)


def test_changed_epoch_in_success_body(connection):
    value = batch(); value['uidvalidity'] = 8; connection.response = Response(value)
    with pytest.raises(bridge.UIDValidityChanged):
        bridge.fetch_batch(TOKEN, '2026-09-19', 7, 20)


def test_length_type_deadline_and_duplicate_keys(connection, monkeypatch):
    connection.response.headers['Content-Length'] = str(bridge.MAX_RESPONSE + 1)
    with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(TOKEN)
    connection.response = Response({})
    connection.response.data = io.BytesIO(b'{"uidvalidity":7,"uidvalidity":8,"after_uid":20}')
    with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(TOKEN)
    connection.response = Response({})
    connection.response.headers['Content-Type'] = 'text/html'
    with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(TOKEN)
    connection.response = Response({})
    monkeypatch.setattr(bridge, 'MAX_SECONDS', -1)
    with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(TOKEN)


def test_token_header_injection_and_bad_cursor_never_request(connection):
    for token in ('', TOKEN + '\r\nHost: external', 'short', 'a' * 42, 'a' * 129):
        with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(token)
    with pytest.raises(bridge.ImapFetchError): bridge.fetch_batch(TOKEN, '2026-09-19', True, 20)
    assert not hasattr(connection, 'requested')


def test_message_and_response_limit(connection, monkeypatch):
    connection.response = Response(batch())
    monkeypatch.setattr(bridge, 'MAX_MESSAGE', 3)
    with pytest.raises(bridge.ImapFetchError): bridge.fetch_batch(TOKEN, '2026-09-19', 7, 20)
    monkeypatch.setattr(bridge, 'MAX_RESPONSE', 4)
    with pytest.raises(bridge.ImapFetchError): bridge.activation_checkpoint(TOKEN)


def test_account_list_and_explicit_account_payload(connection):
    connection.response = Response({'accounts':[{'id':'service','email':'service@example.test','folder':'INBOX'}]})
    assert bridge.list_accounts(TOKEN)[0]['id'] == 'service'
    assert connection.requested[1] == '/internal/mail/accounts'
    connection.response = Response({'uidvalidity':7,'after_uid':20})
    bridge.activation_checkpoint(TOKEN, account_id='service')
    assert json.loads(connection.requested[2]) == {'account_id':'service'}
    connection.response = Response(batch())
    bridge.fetch_batch(TOKEN,'2026-09-19',7,20,account_id='service')
    assert json.loads(connection.requested[2])['account_id'] == 'service'


@pytest.mark.parametrize('accounts', [
    [{'id':'bad/id','email':'x','folder':'INBOX'}],
    [{'id':'primary','email':'x','folder':'INBOX'}]*2,
    [{'id':'primary','email':'x\r\n','folder':'INBOX'}],
    [{'id':'primary','email':'x','folder':'INBOX','password':'secret'}],
])
def test_bad_account_metadata_rejected(connection, accounts):
    connection.response = Response({'accounts':accounts})
    with pytest.raises(bridge.ImapFetchError): bridge.list_accounts(TOKEN)


def test_source_expectations_sent_and_server_mismatch_rejected(connection):
    source = {'email':'service@example.test','folder':'INBOX'}
    bridge.activation_checkpoint(TOKEN,account_id='service',expected_source=source)
    assert json.loads(connection.requested[2]) == {'account_id':'service','expected_email':source['email'],'expected_folder':'INBOX'}
    connection.response = Response(batch())
    bridge.fetch_batch(TOKEN,'2026-09-19',7,20,account_id='service',expected_source=source)
    assert json.loads(connection.requested[2])['expected_email'] == source['email']
    connection.response = Response({'error':'source_changed'})
    connection.response.status = 409
    with pytest.raises(bridge.ImapFetchError, match='Postfachquelle geändert'):
        bridge.fetch_batch(TOKEN,'2026-09-19',7,20,expected_source=source)
