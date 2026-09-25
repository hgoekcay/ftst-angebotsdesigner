import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import chat_release
import pytest
from storage import OfferStore


@pytest.fixture
def setup(tmp_path):
    store = OfferStore(tmp_path)
    payload = dict(client_id='7', label='reference', currency_code='EUR', net_gross='NET',
                   title='Sicherheit', intro='Für Sie', note='', reduction='0%',
                   **{'offer-items': {'offer-item': []}})
    transfer = {'status': 'created', 'offer_id': '42', 'payload': payload,
                    'calculation': {'total': {'net': '0', 'gross': '0'}, 'lines': []}}
    store.put_record('a', 'quote_transfer', 'p', transfer)

    class API:
        def __init__(self):
            self.offer = dict(payload, id='42', status='DRAFT', items=[], total_net='0', total_gross='0')
            self.calls = []
            self.fail = False
            self.read_fail = False
            self.barrier = None

        def get_offer_for_verification(self, oid):
            if self.read_fail:
                raise RuntimeError('secret-password')
            result = deepcopy(self.offer)
            if self.barrier and result['status'] == 'DRAFT':
                self.barrier.wait(timeout=5)
            return result

        def _offer_request(self, method, path, payload):
            self.calls.append((method, path, payload))
            self.offer.update(status='OPEN', offer_number='26-100')
            if self.fail:
                raise RuntimeError('secret-password')

    return store, API()


def test_completes_once_and_never_sends(setup):
    store, api = setup
    result = chat_release.complete(store, 'a', 'p', api)
    assert result['status'] == 'open' and result['offer_number'] == '26-100'
    assert chat_release.complete(store, 'a', 'p', api) == result
    assert api.calls == [('PUT', '/offers/42/complete', {'complete': {}})]


def test_concurrent_claim_is_durable(setup):
    store, api = setup
    api.barrier = threading.Barrier(2)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: chat_release.complete(store, 'a', 'p', api), range(2)))
    assert len(api.calls) == 1
    assert any(r['status'] == 'open' for r in results)


@pytest.mark.parametrize('change', [{'id': '43'}, {'client_id': '8'}, {'total_net': '1'},
                                  {'title': 'Changed'}, {'status': 'OPEN'}])
def test_changed_or_mismatched_draft_blocked(setup, change):
    store, api = setup
    api.offer.update(change)
    with pytest.raises(ValueError):
        chat_release.complete(store, 'a', 'p', api)
    assert not api.calls


def test_ambiguous_write_reconciles_without_retry(setup):
    store, api = setup
    api.fail = True
    result = chat_release.complete(store, 'a', 'p', api)
    assert result['status'] == 'uncertain' and 'secret-password' not in str(result)
    assert chat_release.complete(store, 'a', 'p', api)['status'] == 'uncertain'
    assert chat_release.reconcile(store, 'a', 'p', api)['status'] == 'open'
    assert len(api.calls) == 1


@pytest.mark.parametrize('change', [{'id': '43'}, {'total_gross': '1'}, {'offer_number': ''}])
def test_readback_must_match(setup, change):
    store, api = setup
    api.fail = True
    chat_release.complete(store, 'a', 'p', api)
    api.offer.update(change)
    assert chat_release.reconcile(store, 'a', 'p', api)['status'] == 'uncertain'
    assert len(api.calls) == 1


def test_read_errors_do_not_leak_or_write(setup):
    store, api = setup
    api.read_fail = True
    with pytest.raises(ValueError) as caught:
        chat_release.complete(store, 'a', 'p', api)
    assert 'secret-password' not in str(caught.value) and not api.calls


def test_account_isolation(setup):
    store, api = setup
    with pytest.raises(ValueError):
        chat_release.complete(store, 'other', 'p', api)
    with pytest.raises(ValueError):
        chat_release.reconcile(store, 'other', 'p', api)
    assert not api.calls


def test_crashed_claim_cannot_retry(setup):
    store, api = setup
    transfer = store.record('a', 'quote_transfer', 'p')
    store.put_record('a', 'chat_release', 'p', {'token': 'crash', 'status': 'completing',
                     'offer_id': '42', 'offer_number': '', 'transfer': transfer})
    assert chat_release.complete(store, 'a', 'p', api)['status'] == 'completing'
    assert chat_release.reconcile(store, 'a', 'p', api)['status'] == 'uncertain'
    assert not api.calls

