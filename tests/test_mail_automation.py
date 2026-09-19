import uuid

import mail_assistant
import strato_views
from mail_automation import MailAutomation
from storage import OfferStore


def setup(tmp_path, monkeypatch, analyzer=None):
    store = OfferStore(tmp_path)
    monkeypatch.setattr(strato_views, 'configured', lambda: True)
    monkeypatch.setattr(strato_views, 'list_mailboxes', lambda: [{'id': 'primary', 'email': 'info@ftst.eu', 'folder': 'INBOX'}], raising=False)
    monkeypatch.setattr(strato_views, 'sync_key', lambda account_id: 'strato' if account_id == 'primary' else 'strato:' + account_id, raising=False)
    monkeypatch.setattr(mail_assistant, 'model_digest', lambda: 'synthetic-model')
    worker = MailAutomation(lambda: store, 'test', analyze=analyzer)
    return store, worker


def mail(store, key='m', **extra):
    value = dict(source='Vier Kameras in Mannheim.', title='Test', reply='', revision=uuid.uuid4().hex,
                 categories=['general'], status='new', mail_origin={'uid': 1}, warnings=[])
    value.update(extra)
    store.put_record('test', 'mail', key, value)
    return value


def result(source):
    return {'excerpts': [source], 'missing': ['timing'], 'categories': ['enquiry']}


def test_automatic_proposal_never_adopts_or_sends(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch, result)
    original = mail(store)
    assert worker.analyze_one()
    saved = store.record('test', 'mail', 'm')
    assert saved['automation']['state'] == 'ready'
    assert saved['proposal']
    assert saved['reply'] == ''
    assert saved['categories'] == original['categories']
    assert saved['status'] == 'new'
    assert not worker.analyze_one()


def test_concurrent_user_edit_wins(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch)
    mail(store)
    def edit_during_analysis(source):
        value = store.record('test', 'mail', 'm')
        value.update(reply='Meine Antwort', revision='user-edit')
        store.put_record('test', 'mail', 'm', value)
        return result(source)
    worker.analyze = edit_during_analysis
    worker.analyze_one()
    saved = store.record('test', 'mail', 'm')
    assert saved['reply'] == 'Meine Antwort'
    assert 'proposal' not in saved
    assert saved['revision'] == 'user-edit'


def test_failed_analysis_is_not_retried_after_restart(tmp_path, monkeypatch):
    def fail(source):
        raise ValueError('untrusted customer text must not be persisted as error')
    store, worker = setup(tmp_path, monkeypatch, fail)
    mail(store)
    worker.analyze_one()
    saved = store.record('test', 'mail', 'm')
    assert saved['automation']['state'] == 'failed'
    assert 'error' not in saved
    new_worker = MailAutomation(lambda: store, 'test', analyze=lambda s: (_ for _ in ()).throw(AssertionError()))
    assert not new_worker.analyze_one()


def test_original_warnings_and_long_bodies_require_manual_review(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch, lambda s: (_ for _ in ()).throw(AssertionError()))
    mail(store, warnings=['Unvollständige MIME-Daten'])
    worker.analyze_one()
    assert store.record('test', 'mail', 'm')['automation']['state'] == 'skipped'
    mail(store, key='long', source='X' * 4001)
    worker.analyze_one()
    assert store.record('test', 'mail', 'long')['automation']['state'] == 'skipped'


def test_no_automatic_activation_and_poll_interval(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch)
    calls = []
    worker.sync = lambda *args, **kw: calls.append(True)
    monkeypatch.setenv('STRATO_AUTO_IMPORT', 'true')
    monkeypatch.setenv('STRATO_AUTO_AI', 'false')
    monkeypatch.setenv('STRATO_POLL_SECONDS', '300')
    worker.tick(0)
    assert calls == []
    assert store.record('test', 'mail_automation', 'state')['state'] == 'waiting'
    store.put_record('test', 'mail_sync', 'strato', {'revision': '1'})
    worker.tick(1)
    worker.tick(200)
    assert calls == [True]
    worker.tick(301)
    assert calls == [True, True]


def test_disabled_options_do_not_process_existing_mail(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch, result)
    monkeypatch.setenv('STRATO_AUTO_IMPORT', 'false')
    monkeypatch.setenv('STRATO_AUTO_AI', 'false')
    store.put_record('test', 'mail_sync', 'strato', {'revision': '1'})
    mail(store)
    worker.sync = lambda *args: (_ for _ in ()).throw(AssertionError())
    worker.tick(0)
    assert 'automation' not in store.record('test', 'mail', 'm')


def test_failure_backoff_preserves_checkpoint(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch)
    monkeypatch.setenv('STRATO_AUTO_IMPORT', 'true')
    store.put_record('test', 'mail_sync', 'strato', {'revision': '1'})
    calls = []
    def fail(*args, **kw):
        calls.append(True)
        raise ValueError('remote error')
    worker.sync = fail
    worker.tick(0)
    worker.tick(300)
    assert calls == [True]
    assert store.record('test', 'mail_sync', 'strato') == {'revision': '1'}
    assert store.record('test', 'mail_automation', 'state')['state'] == 'degraded'


def test_bad_mailbox_does_not_block_others_and_pause_is_independent(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch)
    monkeypatch.setenv('STRATO_AUTO_IMPORT', 'true')
    monkeypatch.setenv('STRATO_AUTO_AI', 'false')
    monkeypatch.setattr(strato_views, 'list_mailboxes', lambda: [
        {'id': key, 'email': key + '@example.invalid', 'folder': 'INBOX'} for key in ['primary', 'office', 'paused']])
    for key in ['primary', 'office', 'paused']:
        store.put_record('test', 'mail_sync', strato_views.sync_key(key), {'revision': '1', 'paused': key == 'paused'})
    calls = []
    def sync(store, identity, account_id):
        calls.append(account_id)
        if account_id == 'primary':
            raise ValueError()
    worker.sync = sync
    worker.tick(0)
    assert calls == ['primary', 'office']
    statuses = store.record('test', 'mail_automation', 'state')['accounts']
    assert statuses['primary']['state'] == 'degraded'
    assert statuses['office']['state'] == 'healthy'
    assert statuses['paused']['state'] == 'paused'
    worker.tick(300)
    assert calls == ['primary', 'office', 'office']


def test_ai_round_robin_and_disabled_accounts(tmp_path, monkeypatch):
    store, worker = setup(tmp_path, monkeypatch, result)
    mail(store, 'a1', mail_origin={'account_id': 'primary', 'uid': 1})
    mail(store, 'a2', mail_origin={'account_id': 'primary', 'uid': 2})
    mail(store, 'b1', mail_origin={'account_id': 'office', 'uid': 1})
    mail(store, 'c1', mail_origin={'account_id': 'disabled', 'uid': 1})
    worker.analyze_one({'primary', 'office'})
    worker.analyze_one({'primary', 'office'})
    assert store.record('test', 'mail', 'a1')['automation']['state'] == 'ready'
    assert store.record('test', 'mail', 'b1')['automation']['state'] == 'ready'
    assert 'automation' not in store.record('test', 'mail', 'a2')
    assert 'automation' not in store.record('test', 'mail', 'c1')
