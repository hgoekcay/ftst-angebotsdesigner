import asyncio
import base64
import json
import os
from unittest.mock import Mock, patch

import httpx
import pytest

from strato_internal_bridge import InternalBridge
from strato_service import Settings
from strato_worker import select_bridge_account
import strato_bridge_transport as transport

OPTIONS = {'email':'info@ftst.eu','password':'primary-secret','public_url':'https://mail.example.test',
           'login_password':'long-separate-connection-secret','bridge_token':'a'*43}
EXTRA = {'id':'sales', 'email':'sales@example.test','password':'sales-secret'}


def test_account_config_validation_and_default_preservation():
    settings = Settings.parse({**OPTIONS,'accounts':[EXTRA]})
    assert settings.email == 'info@ftst.eu' and settings.password == 'primary-secret'
    assert settings.accounts[0] == {**EXTRA,'enabled':True,'folder':'INBOX'}
    for accounts in [[EXTRA]*2, [{**EXTRA,'id':'primary'}], [{**EXTRA,'id':'../bad'}],
                     [{**EXTRA,'email':'info@ftst.eu','folder':'inbox'}],
                     [{**EXTRA,'enabled':'yes'}], [EXTRA]*21,
                     [{**EXTRA,'folder':'INBOX\r\nBAD'}]]:
        with pytest.raises(ValueError): Settings.parse({**OPTIONS,'accounts':accounts})


def test_accounts_route_filters_secrets_and_selects_only_enabled_ids():
    accounts = [{'id':'primary','email':'info@ftst.eu','folder':'INBOX','password':'must-not-leak'},
                {'id':'sales','email':'sales@example.test','folder':'INBOX'}]
    runner = Mock(return_value={'uidvalidity':7,'after_uid':3})
    async def fallback(scope, receive, send): raise AssertionError()
    async def run():
        app = InternalBridge(fallback, 'a'*43, runner, accounts=lambda:accounts)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://local-ftst-strato-mail:8098',
                                     headers={'Authorization':'Bearer '+'a'*43}) as client:
            result = await client.get('/internal/mail/accounts')
            assert result.status_code == 200 and 'password' not in result.text and 'must-not-leak' not in result.text
            result = await client.post('/internal/mail/checkpoint',json={'account_id':'sales'})
            assert result.status_code == 200
            runner.assert_called_once_with('bridge_checkpoint',{'account_id':'sales'})
            result = await client.post('/internal/mail/checkpoint',json={'account_id':'disabled'})
            assert result.status_code == 404 and result.json() == {'error':'account_not_found'}
            result = await client.post('/internal/mail/batch',json={'account_id':'sales','uidvalidity':7,'after_uid':3,'since':'2026-09-19'})
            assert result.status_code == 200
            assert runner.call_args.args[1]['account_id'] == 'sales'
    asyncio.run(run())


def test_child_credentials_are_isolated_and_disabled_account_rejected():
    accounts = [{'id':'primary','email':'info@ftst.eu','password':'one','folder':'INBOX','enabled':True},
                {'id':'sales','email':'sales@example.test','password':'two','folder':'Requests','enabled':True},
                {'id':'disabled','email':'disabled@example.test','password':'three','folder':'INBOX','enabled':False}]
    outer_email = os.environ.get('STRATO_EMAIL')
    for account in accounts[:2]:
        with patch.dict(os.environ, {'STRATO_ACCOUNTS_JSON':json.dumps(accounts)}):
            select_bridge_account(account['id'])
            assert os.environ['STRATO_EMAIL'] == account['email']
            assert os.environ['STRATO_PASSWORD'] == account['password']
            assert os.environ['STRATO_BRIDGE_FOLDER'] == account['folder']
            assert 'STRATO_ACCOUNTS_JSON' not in os.environ
        assert os.environ.get('STRATO_EMAIL') == outer_email
    with patch.dict(os.environ, {'STRATO_ACCOUNTS_JSON':json.dumps(accounts)}):
        with pytest.raises(ValueError): select_bridge_account('disabled')
        with pytest.raises(ValueError): select_bridge_account('missing')


def test_same_uid_in_two_accounts_fetches_separate_content():
    class Fake:
        def __init__(self): self.user = None
        def login(self,user,password):
            self.user = user
            assert password == {'one@example.test':'one-secret','two@example.test':'two-secret'}[user]
            return 'OK',[]
        def select(self,folder,readonly):
            assert readonly is True and folder == 'INBOX'
            return 'OK',[]
        def response(self,name): return name,[b'7']
        def status(self,*args): return 'OK',[b'INBOX (UIDVALIDITY 7)']
        def uid(self,action,*args):
            if action == 'SEARCH': return 'OK',[b'1']
            raw = ('From: '+self.user+'\r\n\r\nPrivate body').encode()
            meta = f'1 (UID 1 RFC822.SIZE {len(raw)}'.encode()
            if 'BODY.PEEK' in args[1]: return 'OK',[(meta+f' BODY[]<0> {{{len(raw)}}}'.encode(),raw),b')']
            return 'OK',[meta+b')']
        def shutdown(self): pass
    results=[]
    for name in ['one','two']:
        with patch.dict(os.environ,{'STRATO_EMAIL':name+'@example.test','STRATO_PASSWORD':name+'-secret','STRATO_BRIDGE_FOLDER':'INBOX'}),patch.object(transport,'_BoundedIMAP',Fake):
            result = transport.bridge_batch(7,0,'2026-09-19')
            assert result['messages'][0]['uid'] == 1
            results.append(base64.b64decode(result['messages'][0]['raw_base64']))
    assert results[0] != results[1]


def test_folder_status_must_match_configured_mailbox():
    with patch.dict(os.environ,{'STRATO_BRIDGE_FOLDER':'Customer Requests'}):
        client = Mock()
        client.status.return_value = 'OK',[b'"Customer Requests" (UIDVALIDITY 7)']
        assert transport._status_validity(client) == 7
        client.status.assert_called_once_with('"Customer Requests"','(UIDVALIDITY)')
        client.status.return_value = 'OK',[b'INBOX (UIDVALIDITY 7)']
        with pytest.raises(transport.ImapFetchError): transport._status_validity(client)


def test_expected_source_rejects_reassigned_mailbox_before_worker():
    accounts = [{'id':'sales','email':'new@example.test','folder':'INBOX'}]
    runner = Mock(return_value={'uidvalidity':7,'after_uid':3})
    async def fallback(scope, receive, send): raise AssertionError()
    async def run():
        app = InternalBridge(fallback, 'a'*43, runner, accounts=lambda:accounts)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://local-ftst-strato-mail:8098',
                                     headers={'Authorization':'Bearer '+'a'*43}) as client:
            for path, payload in [('/internal/mail/checkpoint',{'account_id':'sales'}),
                                  ('/internal/mail/batch',{'account_id':'sales','uidvalidity':7,'after_uid':3,'since':'2026-09-19'})]:
                response = await client.post(path,json={**payload,'expected_email':'old@example.test','expected_folder':'INBOX'})
                assert response.status_code == 409 and response.json() == {'error':'source_changed'}
                runner.assert_not_called()
            response = await client.post('/internal/mail/checkpoint',json={'account_id':'sales','expected_email':'new@example.test'})
            assert response.status_code == 400
            runner.assert_not_called()
            response = await client.post('/internal/mail/checkpoint',json={'account_id':'sales','expected_email':'new@example.test','expected_folder':'INBOX'})
            assert response.status_code == 200
            runner.assert_called_once_with('bridge_checkpoint',{'account_id':'sales'})
    asyncio.run(run())
