import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest
from starlette.responses import JSONResponse

from strato_internal_bridge import InternalBridge
from strato_worker import BridgeUIDValidityChanged

TOKEN = 'a' * 43
BASE = 'http://local-ftst-strato-mail:8098'


async def fallback(scope, receive, send):
    await JSONResponse({'public': True})(scope, receive, send)


def call(path='/internal/mail/checkpoint', *, token=TOKEN, host=BASE, method='GET', headers=None, content=None, runner=None):
    app = InternalBridge(fallback, TOKEN, runner or Mock(return_value={'uidvalidity': 7, 'after_uid': 2}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=host) as client:
            h = {'Authorization': 'Bearer ' + token, **(headers or {})}
            return await client.request(method, path, headers=h, content=content)
    return asyncio.run(run())


def test_checkpoint_auth_and_public_path_unchanged():
    assert call().json() == {'uidvalidity': 7, 'after_uid': 2}
    assert call(token='wrong').status_code == 401
    assert call(host='https://mail-assistent.ftsicherheit.org').status_code == 404
    assert call(headers={'Origin': 'null'}).status_code == 404
    assert call('/mcp', host='https://mail-assistent.ftsicherheit.org').json() == {'public': True}


def test_disabled_bridge():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(InternalBridge(fallback, '', Mock())), base_url=BASE) as c:
            return await c.get('/internal/mail/checkpoint')
    assert asyncio.run(run()).status_code == 404


def batch(payload, runner=None):
    return call('/internal/mail/batch', method='POST', headers={'Content-Type': 'application/json'}, content=json.dumps(payload), runner=runner)


def test_batch_validation_and_forwarding():
    payload = {'uidvalidity': 7, 'after_uid': 2, 'since': '2026-09-20'}
    runner = Mock(return_value={'uidvalidity': 7, 'messages': [], 'pending': False})
    assert batch(payload, runner).status_code == 200
    runner.assert_called_once_with('bridge_batch', payload)
    for invalid in [dict(payload, uidvalidity=True), dict(payload, after_uid=-1), dict(payload, since='2026-02-30'), dict(payload, folder='Sent')]:
        assert batch(invalid).status_code == 400
    assert batch({'x': 'a'*4096}).status_code == 413


def test_no_partial_error_or_secret_leaks():
    payload = {'uidvalidity': 7, 'after_uid': 2, 'since': '2026-09-20'}
    response = batch(payload, Mock(side_effect=BridgeUIDValidityChanged('private')))
    assert response.status_code == 409
    assert response.json() == {'error': 'uidvalidity_changed'}
    response = batch(payload, Mock(side_effect=ValueError('private-secret')))
    assert response.status_code == 502
    assert 'private' not in response.text


def test_duplicate_host_and_auth_rejected():
    async def run(headers):
        app = InternalBridge(fallback, TOKEN, Mock())
        events = []
        async def send(event): events.append(event)
        async def receive(): return {'type': 'http.request', 'body': b''}
        await app({'type':'http','path':'/internal/mail/checkpoint','method':'GET','headers':headers}, receive, send)
        return events[0]['status']
    auth = (b'authorization', ('Bearer '+TOKEN).encode())
    host = (b'host', b'local-ftst-strato-mail:8098')
    assert asyncio.run(run([host, host, auth])) == 404
    assert asyncio.run(run([host, auth, auth])) == 401


def test_configuration_requires_separate_token():
    from strato_service import Settings
    options = {'email':'info@ftst.eu', 'password':'mail-secret',
               'public_url':'https://mail.example.test', 'login_password':'separate-login-password-long-enough',
               'bridge_token':TOKEN}
    assert Settings.parse(options).bridge_token == TOKEN
    for changed in [{'bridge_token':'short'}, {'bridge_token':'!'*43}, {'password':TOKEN}]:
        with pytest.raises(ValueError):
            Settings.parse({**options, **changed})
    assert Settings.parse({**options, 'bridge_token':'', 'email':'other@example.test'}).bridge_token == ''


def test_worker_uidvalidity_failure_survives_process_boundary():
    from unittest.mock import patch
    from types import SimpleNamespace
    from strato_worker import run_mail_operation
    result = SimpleNamespace(returncode=0, stdout=json.dumps({'ok':False,'error_code':'UIDVALIDITY_CHANGED'}))
    with patch('strato_worker.subprocess.run', return_value=result):
        with pytest.raises(BridgeUIDValidityChanged):
            run_mail_operation('bridge_batch', {'uidvalidity':7,'after_uid':2,'since':'2026-09-20'})
