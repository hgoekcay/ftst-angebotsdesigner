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


def test_manual_refresh_updates_snapshot_and_retains_data_on_failure(tmp_path, monkeypatch):
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('BILLOMAT_ID', 'refresh-test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test')
    monkeypatch.setattr(offer_cache.OfferCache, 'start', lambda self: None)
    api = Mock(return_value=[{'id': '123', 'title': 'Frisch geladen'}])
    monkeypatch.setattr(BillomatClient, 'list_offers', api)
    client = module.app.test_client()
    result = client.get('/offers?refresh=1', headers={'X-Ingress-Path': '/ingress/test'})
    assert result.status_code == 200
    assert 'Frisch geladen' in result.text and 'Jetzt manuell aktualisiert' in result.text
    assert '/ingress/test/offers?page=1&amp;search=&amp;refresh=1' in result.text
    api.assert_called_once_with()
    api.side_effect = RuntimeError('private error')
    failed = client.get('/offers?refresh=1')
    assert 'Frisch geladen' in failed.text and 'Aktualisierung derzeit nicht' in failed.text
    assert 'private error' not in failed.text


def test_parallel_manual_refresh_does_not_duplicate_request(tmp_path):
    cache = offer_cache.OfferCache(OfferStore(tmp_path), 'test', Mock())
    with cache.refresh_lock:
        assert cache.refresh()['refreshing'] is True
    cache.client.list_offers.assert_not_called()


def test_drafts_hidden_reversibly_without_mutating_cache_and_pagination(tmp_path, monkeypatch):
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('BILLOMAT_ID', 'draft-filter')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test')
    monkeypatch.setattr(offer_cache.OfferCache, 'start', lambda self: None)
    rows = [{'id': str(i + 1), 'status': 'DRAFT', 'title': 'Hidden draft'} for i in range(30)]
    store = OfferStore(tmp_path)
    store.put_record('draft-filter', 'offer_list', 'recent', {'rows': rows, 'updated_at': '2026-10-07'})
    api = Mock(return_value=[{'id': '31', 'status': 'OPEN', 'title': 'Visible offer'}])
    monkeypatch.setattr(BillomatClient, 'list_offers', api)
    client = module.app.test_client()
    hidden = client.get('/offers').text
    assert 'Hidden draft' not in hidden and 'Entwürfe ausgeblendet (30' in hidden
    assert 'Weitere 30 Angebote' in hidden
    shown = client.get('/offers?status=ALL').text
    assert 'Hidden draft' in shown and 'status=ALL' in shown
    api.assert_not_called()
    assert store.record('draft-filter', 'offer_list', 'recent')['rows'] == rows
    assert 'Visible offer' in client.get('/offers?page=2').text
    api.assert_called_once_with('', page=2)
    api.reset_mock()
    client.get('/offers?page=2&status=ALL')
    api.assert_called_once_with('', page=2)

