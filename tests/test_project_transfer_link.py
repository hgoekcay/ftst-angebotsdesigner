from copy import deepcopy

import pytest

import app as module
from storage import OfferStore
from test_persistence import isolated_storage


@pytest.fixture
def project(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'one')
    client = module.app.test_client()
    response = client.post('/projects', data={'title': 'Übertragenes Projekt', 'notes': 'Ursprüngliche Notizen'})
    url = response.headers['Location']
    key = url.rsplit('/', 1)[-1]
    return client, module.offer_store(), key, url


def completed(store, key, account='one', offer_id='501'):
    store.put_record(account, 'quote_transfer', key, {'status': 'created', 'offer_id': offer_id})
    value = store.record(account, 'project', key)
    store.put_record(account, 'project', key, dict(value, offer_id=offer_id))


@pytest.mark.parametrize('submitted', ['', '501', None])
def test_stale_empty_or_same_id_form_preserves_completed_offer_link(project, submitted):
    client, store, key, url = project
    completed(store, key)
    form = {'notes': 'Neue Notizen'}
    if submitted is not None:
        form['offer_id'] = submitted
    assert client.post(url, data=form).status_code == 302
    result = store.record('one', 'project', key)
    assert result['offer_id'] == '501' and result['notes'] == 'Neue Notizen'
    assert 'Billomat-Angebot öffnen' in client.get(url).text


def test_different_offer_id_after_completed_transfer_returns_clear_conflict_without_saving(project):
    client, store, key, url = project
    completed(store, key)
    before = deepcopy(store.record('one', 'project', key))
    response = client.post(url, data={'notes': 'Darf nicht gespeichert werden', 'offer_id': '999'})
    assert response.status_code == 409
    assert '501' in response.text and 'verknüpft' in response.text
    assert store.record('one', 'project', key) == before


def test_finish_between_form_read_and_transaction_cannot_be_overwritten(project, monkeypatch):
    client, store, key, url = project
    original = OfferStore.transact_record
    intercepted = []

    def finish_before_save(self, identity, kind, record_key, change):
        if identity == 'one' and kind == 'project' and record_key == key:
            intercepted.append(record_key)
            completed(store, key)
            # Unrelated newer fields should also survive the stale form.
            value = store.record('one', 'project', key)
            store.put_record('one', 'project', key, dict(value, recovered_metadata='newer value'))
        return original(self, identity, kind, record_key, change)

    monkeypatch.setattr(OfferStore, 'transact_record', finish_before_save)
    assert client.post(url, data={'notes': 'Notizen aus altem Formular', 'offer_id': ''}).status_code == 302
    assert intercepted == [key]
    result = store.record('one', 'project', key)
    assert result['offer_id'] == '501'
    assert result['notes'] == 'Notizen aus altem Formular'
    assert result['recovered_metadata'] == 'newer value'


def test_conflicting_form_is_rejected_if_transfer_finishes_before_transaction(project, monkeypatch):
    client, store, key, url = project
    original = OfferStore.transact_record

    def finish_before_save(self, identity, kind, record_key, change):
        if identity == 'one' and kind == 'project' and record_key == key:
            completed(store, key)
        return original(self, identity, kind, record_key, change)

    monkeypatch.setattr(OfferStore, 'transact_record', finish_before_save)
    assert client.post(url, data={'notes': 'Neue Notizen', 'offer_id': '999'}).status_code == 409
    assert store.record('one', 'project', key)['offer_id'] == '501'
    assert store.record('one', 'project', key)['notes'] == 'Ursprüngliche Notizen'


def test_transfer_link_check_is_account_scoped(project):
    client, store, key, url = project
    store.put_record('two', 'quote_transfer', key, {'status': 'created', 'offer_id': '999'})
    assert client.post(url, data={'notes': 'Eigene Notizen', 'offer_id': '123'}).status_code == 302
    assert store.record('one', 'project', key)['offer_id'] == '123'
    assert store.record('two', 'quote_transfer', key)['offer_id'] == '999'


@pytest.mark.parametrize('status', ['sending', 'unknown', 'review'])
def test_only_completed_transfer_forces_the_offer_link(project, status):
    client, store, key, url = project
    store.put_record('one', 'quote_transfer', key, {'status': status, 'offer_id': '501'})
    assert client.post(url, data={'notes': 'Geprüfte Notizen', 'offer_id': '123'}).status_code == 302
    assert store.record('one', 'project', key)['offer_id'] == '123'
