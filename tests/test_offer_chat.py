"""Chat integration uses only fake extraction/catalogs; no external writes."""
from copy import deepcopy
from io import BytesIO

import app as module
import offer_chat
import offer_chat_ai
import pytest
from pypdf import PdfReader
from test_persistence import isolated_storage  # noqa: F401
from test_quote_drafts import catalog  # noqa: F401


@pytest.fixture
def chat(monkeypatch, catalog):  # noqa: F811 - imported pytest fixture
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test-only')
    monkeypatch.setattr(offer_chat, 'start_thread', lambda target: target())
    monkeypatch.setattr(offer_chat, 'load_catalog', lambda *a, **kw: {'data': deepcopy(catalog), 'at': '2026-09-25'})
    state = deepcopy(offer_chat_ai.EMPTY)
    state.update(name='Testkunde', title='Sicherheit', rows=[{'description': 'Hub', 'quantity': 1, 'evidence': '1 Hub'}])
    monkeypatch.setattr(offer_chat_ai, 'extract', lambda *args: deepcopy(state))
    client = module.app.test_client()
    client.get('/chat')
    with client.session_transaction() as cookie:
        csrf = cookie['offer_chat_csrf']
    result = client.post('/chat', data={'csrf': csrf, 'account': 'test'})
    assert result.status_code == 303
    key = result.location.rsplit('/', 1)[-1]
    return client, key, csrf, state


def send(chat, action='message', **extra):
    client, key, csrf, _ = chat
    store = module.offer_store()
    current = store.record('test', 'offer_chat', key)
    draft = store.record('test', 'quote', key) or {}
    data = {'csrf': csrf, 'account': 'test', 'revision': current['revision'],
            'draft_revision': draft.get('revision', ''), 'action': action, 'message': '1 Hub für Testkunde'}
    data.update(extra)
    return client.post('/chat/' + key, data=data)


def test_csrf_and_account_isolation(chat, monkeypatch):
    client, key, _, _ = chat
    assert send(chat, csrf='wrong').status_code == 400
    assert send(chat, account='other').status_code == 400
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    assert client.get('/chat/' + key).status_code == 404
    assert client.get('/chat/' + key + '/status').status_code == 404
    assert client.get('/chat/' + key + '/pdf').status_code == 404


def test_stale_revision_and_busy_job_rejected(chat, monkeypatch):
    assert send(chat, revision='old').status_code == 409
    queued = []
    monkeypatch.setattr(offer_chat, 'start_thread', queued.append)
    assert send(chat).status_code == 303
    assert send(chat).status_code == 409
    assert len(queued) == 1
    queued[0]()


def test_exact_article_and_customer_selection_and_corrections(chat):
    _, key, _, state = chat
    assert send(chat).status_code == 303
    draft = module.offer_store().record('test', 'quote', key)
    assert draft['client_id'] == '3' and draft['rows'][0]['article_id'] == '1'
    assert draft['rows'][0]['quantity'] == '1' and not draft['reviewed']
    state['rows'][0].update(quantity=8, evidence='8 Hub')
    send(chat, message='Statt 1 jetzt 8 Hub')
    draft = module.offer_store().record('test', 'quote', key)
    assert len(draft['rows']) == 1 and draft['rows'][0]['quantity'] == '8'


def test_fuzzy_article_never_selected_automatically(chat):
    _, key, _, state = chat
    state['rows'][0]['description'] = 'FireProtect'
    send(chat)
    assert module.offer_store().record('test', 'quote', key)['rows'][0]['article_id'] == ''


def test_natural_language_send_does_not_call_external_api(chat, monkeypatch):
    def forbidden():
        pytest.fail('Natural language must not execute external operations')
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', forbidden)
    assert send(chat, message='Ja passt, erstelle und schicke an kunde@example.org').status_code == 303
    _, key, _, _ = chat
    assert module.offer_store().record('test', 'quote_transfer', key) is None


def test_review_create_requires_separate_explicit_confirmation(chat, monkeypatch):
    _, key, _, _ = chat
    send(chat)
    send(chat, 'review')
    assert not module.offer_store().record('test', 'quote', key)['reviewed']
    send(chat, 'review', confirm='yes')
    assert module.offer_store().record('test', 'quote', key)['reviewed']
    calls = []
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', lambda: calls.append('external'))
    send(chat, 'create')
    assert not calls


def test_external_edit_after_claim_cannot_be_created(chat, monkeypatch):
    _, key, _, _ = chat
    send(chat)
    send(chat, 'review', confirm='yes')
    queued, calls = [], []
    monkeypatch.setattr(offer_chat, 'start_thread', queued.append)
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', lambda: object())
    def prepare(store, identity, project_id, *_):
        calls.append('prepare')
        return {'draft': store.record(identity, 'quote', project_id),
                'project': store.record(identity, 'project', project_id), 'token': 'fake'}
    monkeypatch.setattr(offer_chat.quote_transfer, 'prepare', prepare)
    monkeypatch.setattr(offer_chat.quote_transfer, 'submit', lambda *args: calls.append('WRITE') or {'status': 'created'})
    assert send(chat, 'create', confirm='yes').status_code == 303
    store = module.offer_store()
    draft = store.record('test', 'quote', key)
    draft['rows'][0]['quantity'] = '999'
    draft['revision'] = 'external-edit'
    store.put_record('test', 'quote', key, draft)
    queued[0]()
    assert 'WRITE' not in calls


def test_parallel_edit_during_extraction_preserved(chat, monkeypatch):
    _, key, _, state = chat
    send(chat)
    def extract(*args):
        store = module.offer_store()
        draft = store.record('test', 'quote', key)
        draft['rows'][0]['quantity'] = '99'
        store.put_record('test', 'quote', key, draft)
        return deepcopy(state)
    monkeypatch.setattr(offer_chat_ai, 'extract', extract)
    send(chat)
    assert module.offer_store().record('test', 'quote', key)['rows'][0]['quantity'] == '99'


def test_voice_requires_text_review_before_extraction(chat, monkeypatch):
    import chat_voice
    monkeypatch.setattr(chat_voice, 'transcribe', lambda *args: '8 Bewegungsmelder')
    monkeypatch.setattr(offer_chat_ai, 'extract', lambda *args: pytest.fail('Voice must await text confirmation'))
    assert send(chat, 'voice', audio=(BytesIO(b'fake'), 'voice.webm')).status_code == 303
    client, key, _, _ = chat
    saved = module.offer_store().record('test', 'offer_chat', key)
    assert saved['transcript'] == '8 Bewegungsmelder'
    assert not any(m['role'] == 'user' for m in saved['messages'])
    assert module.offer_store().record('test', 'quote', key) is None
    assert '8 Bewegungsmelder' in client.get('/chat/' + key).text


def test_pdf_current_snapshot_and_stale_revision(chat):
    client, key, _, _ = chat
    send(chat)
    saved = module.offer_store().record('test', 'offer_chat', key)
    assert client.get('/chat/' + key + '/pdf?revision=old').status_code == 409
    result = client.get('/chat/' + key + '/pdf?revision=' + saved['revision'])
    assert result.status_code == 200 and result.mimetype == 'application/pdf'
    assert 'Testkunde' in ''.join(page.extract_text() for page in PdfReader(BytesIO(result.data)).pages)


def test_german_decimal_quantity_selection(chat):
    _, key, _, _ = chat
    send(chat)
    send(chat, 'select', article_id='1', quantity='1,5', client_id='3')
    draft = module.offer_store().record('test', 'quote', key)
    assert offer_chat.quotes.number(draft['rows'][0]['quantity']) == offer_chat.quotes.number('1.5')
    assert module.offer_store().record('test', 'offer_chat', key)['state']['rows'][0]['quantity'] == 1.5


def test_ja_passt_reviews_only(chat, monkeypatch):
    _, key, _, _ = chat
    send(chat)
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', lambda: pytest.fail('Approval must not send or create'))
    send(chat, message='Ja, passt so!')
    assert module.offer_store().record('test', 'quote', key)['reviewed']
    assert module.offer_store().record('test', 'quote_transfer', key) is None


def test_external_project_edit_after_claim_cannot_be_created(chat, monkeypatch):
    _, key, _, _ = chat
    send(chat)
    send(chat, 'review', confirm='yes')
    queued = []
    monkeypatch.setattr(offer_chat, 'start_thread', queued.append)
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', lambda: pytest.fail('Changed project must block before API'))
    send(chat, 'create', confirm='yes')
    store = module.offer_store()
    project = store.record('test', 'project', key)
    project['notes'] = 'Different installation scope'
    store.put_record('test', 'project', key, project)
    queued[0]()
    assert store.record('test', 'quote_transfer', key) is None


@pytest.mark.parametrize('change', [{'recipient': 'invented@example.org'}, {'name': 'Erfundener Kunde'},
                                  {'rows': [{'description': 'Hub', 'quantity': 8, 'evidence': '1 Hub'}]},
                                  {'send': True}])
def test_model_unproven_data_and_actions_rejected(monkeypatch, change):
    value = deepcopy(offer_chat_ai.EMPTY)
    value.update(rows=[{'description': 'Hub', 'quantity': 1, 'evidence': '1 Hub'}])
    value.update(change)
    monkeypatch.setattr(offer_chat_ai, 'request_local', lambda context, prompt, schema, check, **kwargs: check(value, context))
    with pytest.raises(ValueError):
        offer_chat_ai.extract(deepcopy(offer_chat_ai.EMPTY), [{'role': 'user', 'text': '1 Hub'}])

