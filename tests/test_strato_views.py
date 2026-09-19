from copy import deepcopy
from email.message import EmailMessage
import sqlite3
import pytest
import app as module
import strato_views as views
from storage import StorageError, RecordConflict
from mail_workflow import parse_eml
from test_persistence import isolated_storage


def raw_mail(text='Fiktive Anfrage'):
    msg = EmailMessage()
    msg['From'] = 'test@example.invalid'
    msg['Subject'] = 'IMAP Funktionstest'
    msg.set_content(text)
    return msg.as_bytes()


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('STRATO_IMAP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_IMAP_PASSWORD', 'synthetic-secret')
    client = module.app.test_client()
    client.get('/mail/strato')
    with client.session_transaction() as session:
        token = session['strato_csrf']
    monkeypatch.setattr(views.strato_imap, 'activation_checkpoint', lambda password: {'uidvalidity': 12, 'after_uid': 20})
    return client, token


def post(browser, action, revision=''):
    client, token = browser
    return client.post('/mail/strato', data={'csrf':token,'action':action,'revision':revision})


def state():
    return module.offer_store().record('test','mail_sync','strato')


def test_missing_configuration_and_no_secrets(browser, monkeypatch):
    c, token = browser
    monkeypatch.delenv('STRATO_IMAP_PASSWORD')
    monkeypatch.setattr(views.strato_imap,'activation_checkpoint',lambda p:pytest.fail('network'))
    assert 'Nicht eingerichtet' in c.get('/mail/strato').text
    assert post(browser,'activate').status_code == 400
    assert state() is None
    monkeypatch.setenv('STRATO_IMAP_PASSWORD','synthetic-secret')
    page=c.get('/mail/strato')
    assert 'synthetic-secret' not in page.text
    assert 'no-store' in page.headers['Cache-Control']
    assert c.post('/mail/strato',data={'action':'activate'}).status_code == 400


def test_activation_read_batch_original_and_replay_preserve_edits(browser, monkeypatch):
    assert post(browser,'activate').status_code == 200
    initial=state()
    assert 'Startpunkt erfolgreich bestätigt' in browser[0].get('/mail/strato').text
    assert initial['after_uid']==20
    assert module.offer_store().records('test','mail')=={}
    raw=raw_mail(); calls=[]
    def fetch(password,since,epoch,cursor):
        calls.append((epoch,cursor))
        return {'uidvalidity':12,'messages':[(cursor+1,raw)],'pending':False}
    monkeypatch.setattr(views.strato_imap,'fetch_batch',fetch)
    assert post(browser,'sync',initial['revision']).status_code==200
    store=module.offer_store(); key,value,blobs=parse_eml(raw)
    assert store.mail_blob('test',value['original_hash'])==raw
    stored=store.record('test','mail',key);stored['reply']='Manuell geprüft';store.put_record('test','mail',key,stored)
    current=state()
    assert 'lesender Abruf wurde erfolgreich abgeschlossen' in browser[0].get('/mail/strato').text
    assert post(browser,'sync',initial['revision']).status_code==409
    assert len(calls)==1
    assert post(browser,'sync',current['revision']).status_code==200
    assert len(store.records('test','mail'))==1
    assert len(store.records('test','mail_imap_source'))==2
    assert store.record('test','mail',key)['reply']=='Manuell geprüft'


def test_bad_second_mail_rolls_back_entire_batch(browser,monkeypatch):
    post(browser,'activate'); before=state()
    monkeypatch.setattr(views.strato_imap,'fetch_batch',lambda *a:{'uidvalidity':12,'messages':[(21,raw_mail()),(22,b'broken')],'pending':False})
    assert post(browser,'sync',before['revision']).status_code==400
    assert state()==before
    assert module.offer_store().records('test','mail')=={}


def test_connection_failure_or_epoch_change_does_not_advance(browser,monkeypatch):
    post(browser,'activate'); before=state()
    def fail(*a):
        raise views.strato_imap.UIDValidityChanged('Postfachkennung geändert; Prüfung erforderlich.')
    monkeypatch.setattr(views.strato_imap,'fetch_batch',fail)
    assert post(browser,'sync',before['revision']).status_code==409
    assert state()==before


def test_transaction_failure_rolls_back_original_and_cursor(browser):
    store=module.offer_store();raw=raw_mail();key,value,blobs=parse_eml(raw)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON records WHEN NEW.kind='mail_sync' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(StorageError):
        store.commit_mail_batch('test','',{'revision':'one','uidvalidity':12},[(21,key,value,blobs)])
    assert store.records('test','mail')=={}
    assert store.mail_blob('test',value['original_hash']) is None
    assert state() is None


def test_checkpoint_cas_and_uid_identity_collision(browser):
    store=module.offer_store();key,value,blobs=parse_eml(raw_mail())
    checkpoint={'revision':'one','uidvalidity':12}
    store.commit_mail_batch('test','',checkpoint,[(21,key,value,blobs)])
    with pytest.raises(RecordConflict):
        store.commit_mail_batch('test','',dict(checkpoint,revision='two'),[])
    other_key,other_value,other_blobs=parse_eml(raw_mail('Andere Bytes'))
    with pytest.raises(StorageError):
        store.commit_mail_batch('test','one',dict(checkpoint,revision='two'),[(21,other_key,other_value,other_blobs)])
    assert state()==checkpoint
    assert len(store.records('test','mail'))==1
