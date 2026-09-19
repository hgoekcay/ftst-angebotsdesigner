import pytest
import app as module
import strato_views as views
from storage import RecordConflict
from test_strato_views import browser, raw_mail
from test_persistence import isolated_storage


@pytest.fixture
def multi(browser, monkeypatch):
    boxes = [{'id':'primary','email':'info@ftst.eu','folder':'INBOX'}, {'id':'service','email':'service@example.test','folder':'INBOX'}]
    monkeypatch.setenv('STRATO_PROVIDER','bridge')
    monkeypatch.setenv('STRATO_BRIDGE_TOKEN','a'*43)
    monkeypatch.setattr(views.strato_bridge,'list_accounts',lambda token:boxes)
    monkeypatch.setattr(views.strato_bridge,'activation_checkpoint',lambda token,account_id='primary',**kwargs:{'uidvalidity':7,'after_uid':20})
    monkeypatch.setattr(views.strato_bridge,'fetch_batch',lambda token,since,epoch,cursor,account_id='primary',**kwargs:{'uidvalidity':7,'messages':[(cursor+1,raw_mail())],'pending':False})
    return browser, boxes, module.offer_store()


def test_same_uid_same_original_independent_workitems(multi):
    _, boxes, store = multi
    for item in boxes:
        views.activate(store,'test',account_id=item['id'])
        views.sync_once(store,'test',account_id=item['id'])
    records = store.records('test','mail')
    assert len(records) == 2
    assert {value['mail_origin']['account_id'] for value in records.values()} == {'primary','service'}
    assert len({value['original_hash'] for value in records.values()}) == 1
    assert len(store.records('test','mail_imap_source')) == 2
    assert set(store.records('test','mail_sync')) == {'strato','strato:service'}
    assert views.sync_once(store,'test',account_id='service')['added'] == 0
    assert len(store.records('test','mail')) == 2


def test_account_email_change_epoch_change_and_removal_do_not_advance(multi, monkeypatch):
    _, boxes, store = multi
    views.activate(store,'test',account_id='service')
    before = store.record('test','mail_sync','strato:service')
    boxes[1]['email'] = 'other@example.test'
    with pytest.raises(RecordConflict): views.sync_once(store,'test',account_id='service')
    boxes[1]['email'] = 'service@example.test'
    def changed(*args, **kwargs): raise views.strato_imap.UIDValidityChanged('changed')
    monkeypatch.setattr(views.strato_bridge,'fetch_batch',changed)
    with pytest.raises(views.strato_imap.UIDValidityChanged): views.sync_once(store,'test',account_id='service')
    boxes.pop()
    with pytest.raises(RecordConflict): views.sync_once(store,'test',account_id='service')
    assert store.record('test','mail_sync','strato:service') == before


def test_ui_accounts_and_independent_pause(multi):
    browser, boxes, store = multi
    client, csrf = browser
    assert 'service@example.test' in client.get('/mail/strato').text
    def post(action, account_id, revision=''):
        return client.post('/mail/strato',data={'csrf':csrf,'action':action,'account_id':account_id,'revision':revision})
    assert post('activate','service').status_code == 200
    before = store.record('test','mail_sync','strato:service')
    assert post('pause','service',before['revision']).status_code == 200
    paused = store.record('test','mail_sync','strato:service')
    assert paused['paused'] and paused['after_uid'] == before['after_uid']
    with pytest.raises(RecordConflict): views.sync_once(store,'test',account_id='service')
    assert store.record('test','mail_sync','strato') is None
    assert post('resume','service',paused['revision']).status_code == 200
    assert not store.record('test','mail_sync','strato:service')['paused']
    assert post('activate','unknown').status_code == 409


def test_source_race_no_checkpoint_or_cursor_committed(multi, monkeypatch):
    _, boxes, store = multi
    def check(token, account_id, expected_source):
        assert expected_source == {'email':'service@example.test','folder':'INBOX'}
        raise views.strato_imap.ImapFetchError('Postfachquelle geändert')
    monkeypatch.setattr(views.strato_bridge,'activation_checkpoint',check)
    with pytest.raises(views.strato_imap.ImapFetchError): views.activate(store,'test',account_id='service')
    assert store.record('test','mail_sync','strato:service') is None
    monkeypatch.setattr(views.strato_bridge,'activation_checkpoint',lambda *a,**k:{'uidvalidity':7,'after_uid':20})
    views.activate(store,'test',account_id='service')
    before = store.record('test','mail_sync','strato:service')
    def fetch(token,since,epoch,cursor,account_id,expected_source):
        assert expected_source == {'email':'service@example.test','folder':'INBOX'}
        raise views.strato_imap.ImapFetchError('Postfachquelle geändert')
    monkeypatch.setattr(views.strato_bridge,'fetch_batch',fetch)
    with pytest.raises(views.strato_imap.ImapFetchError): views.sync_once(store,'test',account_id='service')
    assert store.record('test','mail_sync','strato:service') == before
    assert store.records('test','mail') == {}
