"""Synthetic connection tests: no production access or credentials."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ftst_angebotsdesigner'))
from connect_service import Connection, create_mcp, prepare_app
from connect_http import HTTPSettings, build_http_app, SCOPE


@pytest.fixture
def connection(tmp_path):
    return Connection('example', 'synthetic-key', tmp_path, client=Mock())


def test_disabled_does_not_open_store_or_require_credentials():
    assert prepare_app({}) is None


@pytest.mark.parametrize('collection,record,page', [
    ('../users', '', 1), ('offers', '../clients', 1), ('offers', '1?api_key=x', 1),
    ('offers', '', 0), ('clients', '', 1001), ('articles', '', True)])
def test_invalid_parameters_never_call_upstream(connection, collection, record, page):
    with pytest.raises(ValueError):
        connection.read_billomat(collection, record, page)
    connection.client._offer_request.assert_not_called()


def test_bounded_get(connection):
    connection.read_billomat('offers', '123', 2)
    connection.client._offer_request.assert_called_once_with(
        'GET', '/offers/123', params={'page': 2, 'per_page': 30})


def test_project_account_and_field_isolation(connection):
    connection.store.put_record('other', 'project', 'p1', {'title': 'secret'})
    with pytest.raises(ValueError):
        connection.read_project('p1')
    connection.store.put_record('example', 'project', 'p1',
                                {'title': 'Example', 'notes': 'Plan', 'internal_path': '/secret'})
    assert connection.read_project('p1') == {'title': 'Example', 'notes': 'Plan'}


def test_tools_are_read_only(connection):
    tools = asyncio.run(create_mcp(connection).list_tools())
    assert {t.name for t in tools} == {'connection_status', 'read_billomat', 'read_designer_project'}
    assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools)


def test_oauth_requires_auth_and_exact_host(connection, tmp_path):
    async def run():
        settings = HTTPSettings('https://connect.example.test', 'x' * 32, tmp_path / 'oauth')
        app = build_http_app(settings, create_mcp(connection))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                    base_url=settings.public_url) as client:
            metadata = await client.get('/.well-known/oauth-authorization-server')
            assert metadata.status_code == 200
            assert metadata.json()['scopes_supported'] == [SCOPE]
            assert 'refresh_token' in metadata.json()['grant_types_supported']
            response = await client.post('/mcp', json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
            assert response.status_code == 401
            wrong = await client.get('/.well-known/oauth-authorization-server', headers={'Host': 'attacker.test'})
            assert wrong.status_code == 421
    asyncio.run(run())


def test_invalid_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        prepare_app({'FTST_CONNECT_ENABLED': 'true', 'FTST_DATA_DIR': str(tmp_path),
                     'FTST_CONNECT_PUBLIC_URL': 'http://bad.test', 'FTST_CONNECT_PASSWORD': 'x'*32})


def test_refresh_survives_restart_rotates_and_revokes_family(tmp_path):
    from connect_http import LocalOAuthProvider, opaque
    import time
    from types import SimpleNamespace
    async def run():
        settings = HTTPSettings('https://connect.example.test', 'x' * 32, tmp_path / 'oauth')
        provider = LocalOAuthProvider(settings)
        with provider.store.connect() as db:
            token = provider.issue(db, 'test-client', [SCOPE], opaque(), int(time.time()) + 3600)
        restarted = LocalOAuthProvider(settings)
        assert await restarted.load_access_token(token.access_token)
        client = SimpleNamespace(client_id='test-client')
        refresh = await restarted.load_refresh_token(client, token.refresh_token)
        rotated = await restarted.exchange_refresh_token(client, refresh, [SCOPE])
        assert await restarted.load_access_token(token.access_token) is None
        assert await restarted.load_access_token(rotated.access_token)
        assert await restarted.load_refresh_token(client, token.refresh_token) is None
        assert await restarted.load_access_token(rotated.access_token) is None
        raw = (tmp_path / 'oauth' / 'oauth.sqlite').read_bytes()
        assert token.access_token.encode() not in raw
        assert token.refresh_token.encode() not in raw
    asyncio.run(run())
