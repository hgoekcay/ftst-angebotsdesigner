import threading
import time
from unittest.mock import Mock

import app as module
import offer_cache
from billomat_client import BillomatClient
from storage import OfferStore


def test_client_requests_only_one_page(monkeypatch):
    client = BillomatClient('test', 'secret')
    get = Mock(return_value={'offers': {'offer': {'id': '4', 'date': '2026-09-19'}}})
    monkeypatch.setattr(client, '_get', get)
    assert len(client.list_offers('26-', page=2)) == 1
    assert get.call_args.args[1] == {'format': 'json', 'per_page': 30, 'page': 2,
                                    'order_by': 'date DESC, id DESC', 'offer_number': '26-'}


def test_persistent_snapshot_and_failed_refresh(tmp_path):
    client = Mock()
    client.list_offers.return_value = [{'id': '42', 'title': 'Gespeichert', 'secret_extra': 'omit'}]
    cache = offer_cache.OfferCache(OfferStore(tmp_path), 'one', client)
    first = cache.refresh()
    assert 'secret_extra' not in first['rows'][0]
    assert offer_cache.OfferCache(OfferStore(tmp_path), 'one', client).snapshot() == first
    assert offer_cache.OfferCache(OfferStore(tmp_path), 'two', client).snapshot() == {}
    client.list_offers.side_effect = RuntimeError('secret exception')
    failed = cache.refresh()
    assert failed['rows'] == first['rows'] and failed['updated_at'] == first['updated_at']
    assert failed['error'] and 'secret exception' not in str(failed)


def test_start_does_not_wait_for_api_or_spawn_duplicates(tmp_path):
    entered, release = threading.Event(), threading.Event()
    client = Mock()
    def slow():
        entered.set()
        release.wait(5)
        return []
    client.list_offers.side_effect = slow
    cache = offer_cache.OfferCache(OfferStore(tmp_path), 'test', client)
    try:
        cache.start()
        assert entered.wait(2)
        original = cache.thread
        for _ in range(5):
            cache.start()
        assert cache.thread is original and client.list_offers.call_count == 1
    finally:
        cache.stop.set()
        release.set()
        cache.thread.join(3)


def test_cached_route_never_waits_for_billomat(tmp_path, monkeypatch):
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test')
    monkeypatch.setattr(offer_cache.OfferCache, 'start', lambda self: None)
    rows = [{'id': str(i), 'date': '2026-09-19', 'title': 'Angebot', 'total_gross': '10'} for i in range(30)]
    OfferStore(tmp_path).put_record('test', 'offer_list', 'recent', {'rows': rows, 'updated_at': '2026-09-19', 'checked': time.time()})
    api = Mock(side_effect=AssertionError('must not request API'))
    monkeypatch.setattr(BillomatClient, 'list_offers', api)
    client = module.app.test_client()
    result = client.get('/offers', headers={'X-Ingress-Path': '/ingress/test'})
    assert result.status_code == 200 and 'Weitere 30 Angebote' in result.text
    assert '/ingress/test/offers?page=2' in result.text
    assert result.headers['Cache-Control'] == 'no-store'
    api.assert_not_called()
    assert client.get('/offers?page=bad').status_code == 400
    api.side_effect = None
    api.return_value = []
    assert client.get('/offers?page=2&search=26-').status_code == 200
    api.assert_called_once_with('26-', page=2)


def test_valid_empty_result_replaces_old_snapshot(tmp_path):
    client = Mock()
    cache = offer_cache.OfferCache(OfferStore(tmp_path), 'one', client)
    client.list_offers.return_value = [{'id': '42'}]
    cache.refresh()
    client.list_offers.return_value = []
    assert cache.refresh()['rows'] == []
    client.list_offers.return_value = [{'bad': 'malformed'}]
    assert cache.refresh()['error']
