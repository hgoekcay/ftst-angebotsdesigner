import html
import json
from unittest.mock import MagicMock

import pytest
import requests
from flask import Flask

import billomat_receipts as receipts

SENTINEL = 'DO-NOT-EXPOSE-secret-123'


def test_integrated_entry_has_no_implicit_account_read(monkeypatch, tmp_path):
    import app as module
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(tmp_path))
    check = MagicMock(return_value=[])
    monkeypatch.setattr(receipts, 'check_receipts', check)
    client = module.app.test_client()
    assert 'Beleg-Verbindung prüfen' in client.get('/billomat').text
    page = client.get('/billomat/receipts-check')
    assert page.status_code == 200 and 'Billomat jetzt lesend prüfen' in page.text
    check.assert_not_called()


def response(payload=None, *, status=200, raw=None, headers=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.headers = headers or {}
    content = raw if raw is not None else json.dumps(payload).encode()
    result.iter_content.return_value = [content]
    return result


@pytest.fixture
def http(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test-account')
    monkeypatch.setenv('BILLOMAT_API_KEY', SENTINEL)
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(receipts.requests, 'Session', lambda: client)
    return client


def test_only_fixed_first_pages_and_redacted_summary(http, caplog):
    http.get.side_effect = [
        response({'incomings': {'@total': '10', 'incoming': [
            {'id': 9, 'number': SENTINEL, 'note': SENTINEL, SENTINEL: 'value'}]}}),
        response({'inbox-documents': {'total': 1, 'inbox-document': {
            'id': 3, 'file_url': 'https://secret.invalid/' + SENTINEL,
            'base64file': SENTINEL, 'metadata': {'secret': SENTINEL}}}}),
    ]
    result = receipts.check_receipts()
    assert result[0] == {'resource': 'incomings', 'title': 'Eingangsrechnungen',
                         'reachable': True, 'total': 10, 'fields': ['id', 'note', 'number']}
    assert result[1]['total'] == 1
    assert SENTINEL not in repr(result) + caplog.text
    assert http.trust_env is False
    assert http.get.call_count == 2
    for call, resource in zip(http.get.call_args_list, ['incomings', 'inbox-documents']):
        assert call.args == ('https://test-account.billomat.net/api/' + resource,)
        assert call.kwargs['params'] == {'format': 'json', 'per_page': 5, 'page': 1}
        assert call.kwargs['allow_redirects'] is False
        assert call.kwargs['verify'] is True and call.kwargs['stream'] is True
        assert call.kwargs['timeout'] == (5, 10)
    http.post.assert_not_called()


@pytest.mark.parametrize('status,code', [(301, 'redirect'), (302, 'redirect'),
                                       (401, 'access'), (403, 'access'), (429, 'limited')])
def test_terminal_errors_do_not_follow_retry_or_read_body(http, caplog, status, code):
    reply = response(status=status, raw=SENTINEL.encode(), headers={'Location': 'https://evil.invalid'})
    http.get.return_value = reply
    result = receipts.check_receipts()
    assert result[0]['error'] == code and http.get.call_count == 1
    reply.iter_content.assert_not_called()
    assert SENTINEL not in repr(result) + caplog.text


@pytest.mark.parametrize('error', [requests.Timeout(SENTINEL), requests.exceptions.SSLError(SENTINEL),
                                 requests.ConnectionError(SENTINEL)])
def test_transport_exceptions_are_redacted_and_lock_released(http, caplog, error):
    http.get.side_effect = error
    result = receipts.check_receipts()
    assert all(row['error'] == 'transport' for row in result)
    assert SENTINEL not in repr(result) + caplog.text
    assert receipts._busy.acquire(blocking=False)
    receipts._busy.release()


@pytest.mark.parametrize('raw', [b'<html>secret</html>', b'{', b'[]', b'{"incomings":{}}',
                              b'{"incomings":{"incoming":[1]}}', b'\xff'])
def test_invalid_json_shapes_are_not_success(http, raw):
    http.get.return_value = response(raw=raw)
    assert receipts.check_receipts()[0]['error'] == 'invalid'


def test_size_limit_uses_stream_bytes_even_without_length(http):
    reply = response(raw=b'x' * (receipts.MAX_BYTES + 1))
    http.get.return_value = reply
    assert receipts.check_receipts()[0]['error'] == 'large'
    assert reply.__exit__.call_count == 2


def test_content_length_limit_does_not_read_body(http):
    reply = response(raw=SENTINEL.encode(), headers={'Content-Length': str(receipts.MAX_BYTES + 1)})
    http.get.return_value = reply
    assert receipts.check_receipts()[0]['error'] == 'large'
    reply.iter_content.assert_not_called()


def test_elapsed_limit(http, monkeypatch):
    http.get.return_value = response({'incomings': {'@total': '0'}})
    times = iter([0, 21, 22, 43])
    monkeypatch.setattr(receipts.time, 'monotonic', lambda: next(times))
    assert all(x['error'] == 'transport' for x in receipts.check_receipts())


@pytest.mark.parametrize('total', [-1, True, 'NaN', SENTINEL, '999999999999999', 0])
def test_invalid_totals_never_echo_values(total):
    with pytest.raises(receipts.ReceiptCheckError) as exc:
        receipts._summary({'incomings': {'total': total, 'incoming': [{'id': 1}]}}, 'incomings', 'incoming')
    assert SENTINEL not in str(exc.value)


def test_empty_collection_and_missing_total_are_distinguished():
    assert receipts._summary({'incomings': {'@total': '0'}}, 'incomings', 'incoming')['total'] == 0
    assert receipts._summary({'incomings': {'incoming': [{'id': 1}]}}, 'incomings', 'incoming')['total'] is None
    with pytest.raises(receipts.ReceiptCheckError):
        receipts._summary({'incomings': {'incoming': [{'id': n} for n in range(6)]}}, 'incomings', 'incoming')


@pytest.mark.parametrize('account', ['', 'evil.invalid/path', 'evil@host', 'x:443', '-bad', 'bad.', SENTINEL + '/'])
def test_invalid_account_never_sends_credentials(http, monkeypatch, account):
    monkeypatch.setenv('BILLOMAT_ID', account)
    with pytest.raises(receipts.ReceiptCheckError, match='Konfiguration'):
        receipts.check_receipts()
    http.get.assert_not_called()


def test_busy_does_not_start_second_read(http):
    with receipts._busy:
        with pytest.raises(receipts.ReceiptCheckError, match='bereits'):
            receipts.check_receipts()
    http.get.assert_not_called()


def test_route_requires_csrf_and_never_displays_receipt_values(http):
    app = Flask(__name__)
    app.secret_key = 'test-only'
    receipts.register(app, lambda title, body: body, lambda path: '/' + path, html.escape)
    client = app.test_client()
    page = client.get('/billomat/receipts-check')
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    http.get.assert_not_called()
    assert client.post('/billomat/receipts-check').status_code == 400
    assert client.post('/billomat/receipts-check', data={'csrf': 'ä'}).status_code == 400
    http.get.assert_not_called()
    with client.session_transaction() as state:
        csrf = state['receipts_csrf']
    http.get.side_effect = [response({'incomings': {'incoming': [{'note': SENTINEL}], '@total': '1'}}),
                            response({'inbox-documents': {'@total': '0'}})]
    page = client.post('/billomat/receipts-check', data={'csrf': csrf})
    assert page.status_code == 200 and 'Lesend erreichbar' in page.text
    assert SENTINEL not in page.text
    assert page.headers['Cache-Control'] == 'no-store'
