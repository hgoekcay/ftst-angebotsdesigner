import html
import re
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from flask import Flask, request

import offer_cache
import offer_followup
from billomat_client import BillomatClient
from storage import OfferStore, RecordConflict


OFFER = {'id': '42', 'offer_number': '26-42', 'title': 'Alarmanlage', 'status': 'OPEN'}


def fields(response):
    return {name: html.unescape(value) for name, value in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', response.text)}


@pytest.fixture
def ui(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.secret_key = 'test-followup-only'
    monkeypatch.setenv('BILLOMAT_ID', 'customer-one')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'private-test-key')
    get = Mock(return_value=dict(OFFER))
    monkeypatch.setattr(BillomatClient, 'get_offer', get)
    store = OfferStore(tmp_path)
    clean = lambda value: html.escape(str(value or ''), quote=True)
    base = lambda title, body: body
    ingress = lambda path: '/ingress/test/' + path
    offer_followup.register(app, lambda: store, base, ingress, clean, str)
    monkeypatch.setattr(offer_cache.OfferCache, 'start', lambda self: None)
    listing = Mock()
    listing.list_offers.return_value = [dict(OFFER)]

    @app.get('/offers')
    def offers():
        return offer_cache.page(request, store, 'customer-one', listing, base, ingress, clean, str, str)

    return app.test_client(), store, get, listing


def test_followup_persists_date_note_and_escapes_output(ui):
    client, store, get, _ = ui
    page = client.get('/offer/42/followup')
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    values = dict(fields(page), due_date='2026-09-25', note='<script>alert(1)</script> Anrufen')
    response = client.post('/offer/42/followup', data=values)
    assert response.status_code == 303
    assert response.headers['Location'] == '/ingress/test/offer/42/followup?saved=1'
    saved = store.record('customer-one', offer_followup.KIND, '42')
    assert saved['due_date'] == '2026-09-25' and saved['note'] == values['note']
    assert saved['offer_number'] == '26-42'
    assert store.record('customer-two', offer_followup.KIND, '42') is None
    page = client.get('/offer/42/followup')
    assert '&lt;script&gt;' in page.text and '<script>' not in page.text
    assert 'Es werden keine Nachrichten versendet.' in page.text
    assert get.call_args.args == ('42',)


@pytest.mark.parametrize('patch', [
    {'due_date': '2026-02-30'}, {'due_date': '2026-1-1'}, {'due_date': '2101-01-01'},
    {'due_date': 'not-a-date'}, {'note': 'n' * 2001}, {'operation': 'not-valid'}, {'revision': 'bad'},
])
def test_invalid_input_never_writes_or_calls_billomat(ui, patch):
    client, store, get, _ = ui
    values = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Sichern')
    values.update(patch)
    get.reset_mock()
    result = client.post('/offer/42/followup', data=values)
    assert result.status_code == 400
    get.assert_not_called()
    assert store.records('customer-one', offer_followup.KIND) == {}


def test_forged_or_other_account_forms_cannot_save(ui, monkeypatch):
    client, store, get, _ = ui
    values = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Sichern')
    get.reset_mock()
    assert client.post('/offer/42/followup', data=dict(values, csrf='wrong')).status_code == 400
    assert client.post('/offer/42/followup', data=dict(values, csrf='ungültig')).status_code == 400
    monkeypatch.setenv('BILLOMAT_ID', 'customer-two')
    assert client.post('/offer/42/followup', data=values).status_code == 409
    get.assert_not_called()
    assert store.records('customer-one', offer_followup.KIND) == {}
    assert store.records('customer-two', offer_followup.KIND) == {}


@pytest.mark.parametrize('oid', ['0', '-1', 'hello', '1' * 19])
def test_bad_offer_ids_rejected_before_api(ui, oid):
    client, _, get, _ = ui
    assert client.get('/offer/' + oid + '/followup').status_code == 400
    get.assert_not_called()


def test_offer_must_exist_in_current_billomat_account(ui):
    client, store, get, _ = ui
    values = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Sichern')
    get.return_value = {'id': '999'}
    assert client.post('/offer/42/followup', data=values).status_code == 404
    assert store.records('customer-one', offer_followup.KIND) == {}
    get.side_effect = RuntimeError('private upstream error')
    result = client.post('/offer/42/followup', data=values)
    assert result.status_code == 502 and 'private upstream' not in result.text
    assert store.records('customer-one', offer_followup.KIND) == {}


def test_retry_after_lost_response_keeps_revision_and_does_not_duplicate(ui):
    client, store, _, _ = ui
    values = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Anrufen')
    assert client.post('/offer/42/followup', data=values).status_code == 303
    first = store.record('customer-one', offer_followup.KIND, '42')
    assert client.post('/offer/42/followup', data=values).status_code == 303
    assert store.record('customer-one', offer_followup.KIND, '42') == first
    assert len(store.records('customer-one', offer_followup.KIND)) == 1
    assert client.post('/offer/42/followup', data=dict(values, note='Abweichend')).status_code == 409
    assert store.record('customer-one', offer_followup.KIND, '42') == first


def test_stale_edit_is_retained_in_conflict_form_and_never_overwrites(ui):
    client, store, _, _ = ui
    first = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Gewinner')
    stale = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-26', note='Meine ungesicherte Notiz')
    assert client.post('/offer/42/followup', data=first).status_code == 303
    result = client.post('/offer/42/followup', data=stale)
    assert result.status_code == 409 and stale['note'] in result.text
    assert 'Aktuellen Stand öffnen' in result.text
    assert store.record('customer-one', offer_followup.KIND, '42')['note'] == 'Gewinner'


def test_parallel_first_save_has_one_winner(tmp_path):
    def write(number):
        values = dict(due_date='2026-09-25', note=str(number), revision='', operation=str(number) * 32)
        try:
            return offer_followup.save(OfferStore(tmp_path), 'one', OFFER, values)
        except RecordConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert OfferStore(tmp_path).record('one', offer_followup.KIND, '42') == winner


def test_clearing_date_keeps_note_and_new_revision(ui):
    client, store, _, _ = ui
    values = dict(fields(client.get('/offer/42/followup')), due_date='2026-09-25', note='Erledigt')
    assert client.post('/offer/42/followup', data=values).status_code == 303
    first = store.record('customer-one', offer_followup.KIND, '42')
    values = dict(fields(client.get('/offer/42/followup')), due_date='', note='Erledigt')
    assert client.post('/offer/42/followup', data=values).status_code == 303
    cleared = store.record('customer-one', offer_followup.KIND, '42')
    assert cleared['due_date'] == '' and cleared['note'] == 'Erledigt'
    assert cleared['revision'] != first['revision']


def test_actual_status_is_cached_and_displayed_without_guessing(ui):
    client, store, _, listing = ui
    listing.list_offers.return_value = [dict(OFFER, status='WON'), dict(OFFER, id='43', status=None), dict(OFFER, id='44', status='<script>')]
    cache = offer_cache.OfferCache(store, 'customer-one', listing)
    assert cache.refresh()['rows'][0]['status'] == 'WON'
    listing.list_offers.reset_mock()
    result = client.get('/offers')
    assert result.status_code == 200 and 'data-label="Billomat-Status">Gewonnen' in result.text
    assert 'Status nicht verfügbar' in result.text and 'Unbekannter Status: &lt;script&gt;' in result.text
    assert 'Datenstand:' in result.text and 'UTC' in result.text
    listing.list_offers.assert_not_called()


def test_status_filter_uses_full_billomat_pagination_and_preserves_search(ui):
    client, _, _, listing = ui
    listing.list_offers.return_value = [dict(OFFER, id=str(i + 1)) for i in range(30)]
    result = client.get('/offers?search=26-&status=OPEN&page=2')
    listing.list_offers.assert_called_once_with('26-', page=2, status='OPEN')
    assert 'für alle Billomat-Angebote: Offen' in result.text
    assert '/ingress/test/offers?page=3&amp;search=26-&amp;status=OPEN' in result.text
    assert '/ingress/test/offers?page=1&amp;search=26-&amp;status=OPEN' in result.text
    assert 'value="OPEN" selected' in result.text
    listing.list_offers.reset_mock()
    assert client.get('/offers?status=FAKE').status_code == 400
    listing.list_offers.assert_not_called()


def test_reminders_remain_visible_when_offer_leaves_cached_thirty(ui):
    client, store, _, _ = ui
    offer_followup.save(store, 'customer-one', OFFER,
                        dict(due_date='2026-09-25', note='Noch offen <b>', revision='', operation='a' * 32))
    store.put_record('customer-one', 'offer_list', 'recent', {'rows': [], 'updated_at': '2026-09-20T10:00:00+00:00'})
    result = client.get('/offers')
    assert '26-42' in result.text and 'Noch offen &lt;b&gt;' in result.text
    assert '/ingress/test/offer/42/followup' in result.text
    assert 'data-label="Termin"' in result.text


def test_status_refresh_keeps_last_good_state_after_billomat_failure(ui):
    _, store, _, listing = ui
    listing.list_offers.return_value = [dict(OFFER, status='LOST')]
    cache = offer_cache.OfferCache(store, 'customer-one', listing)
    first = cache.refresh()
    listing.list_offers.side_effect = RuntimeError('private credentials')
    failed = cache.refresh()
    assert failed['rows'][0]['status'] == 'LOST'
    assert failed['updated_at'] == first['updated_at'] and failed['error'] is True
    assert 'private credentials' not in str(failed)
