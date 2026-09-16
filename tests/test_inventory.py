import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
import pytest
import app as module
from inventory import InventoryError, execute, load, procurement, quantity, reserved
from operations_planning import suggestions, local_time
from storage import OfferStore, RecordConflict
from test_persistence import isolated_storage
from test_quote_drafts import catalog, draft
from quote_drafts import fingerprint


@pytest.fixture
def warehouse(tmp_path):
    store = OfferStore(tmp_path)
    def command(action, payload, operation=None, expected=None):
        return execute(store, 'test', action, payload, operation or uuid.uuid4().hex, 'Testperson',
                       load(store, 'test')['revision'] if expected is None else expected)
    command('article', dict(id='1', title='Kontakt', unit='Stück'))
    return store, command


def order(command, oid='p', n='7'):
    return command('order', dict(id=oid, title=oid, reference='Bestätigung Test', quote_revision='r1',
                                lines=[dict(article_id='1', quantity=n)]))


def move(command, action, quantity, **extra):
    return command(action, dict(article='1', quantity=quantity, order='p', note='Testbeleg', **extra))


def test_unknown_is_not_zero_and_no_purchase_claim(warehouse):
    store, command = warehouse
    state = order(command)
    assert not state['articles']['1']['known']
    assert procurement(state, 'p')[0]['status'] == 'Zuerst Bestand zählen'
    with pytest.raises(InventoryError, match='Zuerst'):
        move(command, 'receive', '5')
    assert load(store, 'test')['revision'] == 2
    assert load(store, 'other')['articles'] == {}


def test_partial_reservation_cannot_be_stolen_and_cancel_releases(warehouse):
    store, command = warehouse
    move(command, 'opening', '8')
    order(command, 'a', '3')
    state = order(command)
    assert state['orders']['p']['reserved']['1'] == 5000
    assert procurement(state, 'p')[0]['quantity'] == 2000
    with pytest.raises(InventoryError, match='Andere Auftragsreservierungen'):
        move(command, 'issue', '6')
    command('cancel', dict(order='a'))
    state = command('reserve', dict(order='p'))
    assert state['orders']['p']['reserved']['1'] == 7000
    assert reserved(state, '1') == 7000
    assert not procurement(state, 'p')


def test_issue_return_and_restart_preserve_audit_and_shortage(warehouse):
    store, command = warehouse
    move(command, 'opening', '8')
    order(command)
    move(command, 'issue', '4')
    state = move(command, 'return', '2', usable='yes')
    assert state['articles']['1']['stock'] == 6000
    assert state['orders']['p']['reserved']['1'] == 3000
    assert state['orders']['p']['issued']['1'] == 2000
    assert procurement(state, 'p')[0]['quantity'] == 2000
    assert load(OfferStore(store.directory), 'test') == state
    with pytest.raises(InventoryError):
        move(command, 'return', '3', usable='yes')
    with pytest.raises(InventoryError):
        move(command, 'return', '1', usable='no')


def test_idempotency_including_stale_retry_and_payload_conflict(warehouse):
    store, command = warehouse
    payload = dict(article='1', quantity='8')
    state = command('opening', payload, operation='unique', expected=1)
    again = command('opening', payload, operation='unique', expected=1)
    assert again == state
    with pytest.raises(RecordConflict):
        command('opening', dict(payload, quantity='9'), operation='unique', expected=1)
    with pytest.raises(RecordConflict):
        command('receive', payload, expected=1)
    assert load(store, 'test') == state


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-1', '0', '0.1', '1000001'])
def test_invalid_piece_quantities(bad):
    with pytest.raises(InventoryError):
        quantity(bad, 'Stück')


def test_meter_precision_and_zero_count():
    assert quantity('1,125', 'm') == 1125
    assert quantity('0', 'Stück', zero=True) == 0
    with pytest.raises(InventoryError):
        quantity('0.0001', 'm')


def test_count_requires_reason_and_cannot_reduce_reserved(warehouse):
    store, command = warehouse
    move(command, 'opening', '8')
    order(command)
    with pytest.raises(InventoryError):
        move(command, 'count', '6')
    with pytest.raises(InventoryError):
        command('count', dict(article='1', quantity='9'))
    command('release', dict(order='p', note='Zähldifferenz prüfen'))
    state = move(command, 'count', '6')
    assert state['articles']['1']['stock'] == 6000
    assert procurement(state, 'p')[0]['quantity'] == 7000
    assert state['events'][-1]['action'] == 'count'


def test_demand_versions_and_issued_floor(warehouse):
    store, command = warehouse
    move(command, 'opening', '8')
    order(command)
    move(command, 'issue', '3')
    with pytest.raises(InventoryError):
        command('need', dict(order='p', article='1', quantity='2', note='Änderung'))
    state = command('need', dict(order='p', article='1', quantity='4', note='Änderung'))
    assert state['orders']['p']['reserved']['1'] == 1000
    assert len([e for e in state['events'] if e['action'] == 'need']) == 1


def test_reversal_is_referenced_immutable_and_once_only(warehouse):
    store, command = warehouse
    move(command, 'opening', '8')
    order(command)
    state = move(command, 'issue', '3')
    event = state['events'][-1]
    state = command('reverse', dict(event=event['id'], note='Falsche Entnahme'))
    assert state['articles']['1']['stock'] == 8000
    assert state['orders']['p']['issued']['1'] == 0
    assert state['orders']['p']['reserved']['1'] == 4000
    assert state['events'][-2] == event
    with pytest.raises(InventoryError):
        command('reverse', dict(event=event['id'], note='Nochmals'))
    assert load(store, 'test') == state


def test_receipt_reversal_cannot_remove_reserved_stock(warehouse):
    store, command = warehouse
    move(command, 'opening', '0')
    receipt = move(command, 'receive', '5')['events'][-1]
    order(command, n='5')
    with pytest.raises(InventoryError):
        command('reverse', dict(event=receipt['id'], note='Falscher Eingang'))
    command('cancel', dict(order='p'))
    assert command('reverse', dict(event=receipt['id'], note='Falscher Eingang'))['articles']['1']['stock'] == 0


def test_concurrent_last_item_is_taken_once(warehouse):
    store, command = warehouse
    move(command, 'opening', '1')
    state = order(command, n='1')
    barrier = Barrier(2)
    def issue(_):
        barrier.wait()
        try:
            command('issue', dict(article='1', quantity='1', order='p'), expected=state['revision'])
            return 'saved'
        except RecordConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(issue, range(2))) == ['conflict', 'saved']
    assert load(store, 'test')['articles']['1']['stock'] == 0


def test_concurrent_orders_never_double_reserve(warehouse):
    store, command = warehouse
    move(command, 'opening', '0')
    order(command, 'a', '5')
    order(command, 'b', '5')
    state = move(command, 'receive', '5')
    barrier = Barrier(2)
    def allocate(oid):
        barrier.wait()
        try:
            command('reserve', dict(order=oid), expected=state['revision'])
        except RecordConflict:
            command('reserve', dict(order=oid))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(allocate, ['a', 'b']))
    assert reserved(load(store, 'test'), '1') == 5000
    assert sum(r['quantity'] for o in ('a','b') for r in procurement(load(store,'test'),o)) == 5000


def test_material_and_shared_capacity_gate_planning(warehouse):
    store, command = warehouse
    state = order(command, n='1')
    now = datetime(2026,9,16,8,tzinfo=timezone.utc)
    windows = 'A;Alarm;2026-09-17T08:00;2026-09-17T12:00\nB;Alarm;2026-09-17T10:00;2026-09-17T14:00'
    def plan(s, crew=2, mins=90, skills='Alarm', check='2026-09-16T09:00'):
        return suggestions(s, 'p', windows, mins, crew, skills, 30, check, now)
    assert not plan(state)['slots']
    move(command, 'opening', '1')
    state = command('reserve', dict(order='p'))
    assert plan(state)['slots'][0]['start'] == '2026-09-17T10:00:00+02:00'
    assert plan(state)['slots'][0]['end'] == '2026-09-17T12:00:00+02:00'
    assert not plan(state, crew=3)['slots']
    assert not plan(state, mins=91)['slots']
    assert not plan(state, skills='Video')['slots']
    with pytest.raises(InventoryError):
        plan(state, check='2026-09-14T09:00')


def test_dst_ambiguous_and_nonexistent_times_require_offset():
    for value in ('2026-03-29T02:30', '2026-10-25T02:30'):
        with pytest.raises(InventoryError):
            local_time(value)
    assert local_time('2026-10-25T02:30+02:00') != local_time('2026-10-25T02:30+01:00')


def form(response):
    return {name: re.search(r'name="'+name+r'" value="([^"]+)"', response.text)[1] for name in ('csrf','revision','operation')}


def test_ui_catalog_order_purchase_export_and_csrf(isolated_storage, monkeypatch, draft):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    store = module.offer_store()
    p = dict(title='=Testauftrag', notes='1 Hub')
    draft.update(revision='r1', reviewed=True, source=fingerprint(p))
    store.put_record('test', 'project', 'p', p)
    store.put_record('test', 'quote', 'p', draft)
    client = module.app.test_client()
    assert client.post('/inventory', data=dict(action='article')).status_code == 400
    response = client.get('/inventory')
    data = dict(form(response), action='article', article='1', unit='Stück', actor='Tester')
    assert client.post('/inventory', data=data).status_code == 302
    assert 'Noch nicht gezählt' in client.get('/inventory').text
    data = dict(form(client.get('/projects/p/operations')), action='order', quote_revision='r1',
                material='0', reference='Kundenauftrag 123', actor='Tester', confirmed='yes')
    assert client.post('/projects/p/operations', data=data).status_code == 302
    response = client.get('/projects/p/procurement.csv')
    assert "'=Testauftrag" in response.text
    assert 'Unbestellter Prüfvorschlag' in response.text and 'Zuerst Bestand zählen' in response.text
    assert 'Keine Kalenderanbindung' in client.get('/projects/p/operations').text
    assert client.get('/inventory/journal.csv').status_code == 200
    assert client.get('/projects/unknown/operations').status_code == 404


def test_unreviewed_quote_cannot_become_order(isolated_storage, monkeypatch, draft):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    store = module.offer_store()
    p = dict(title='Test', notes='1 Hub')
    store.put_record('test', 'project', 'p', p)
    draft.update(revision='r1', reviewed=False, source=fingerprint(p))
    store.put_record('test', 'quote', 'p', draft)
    client = module.app.test_client()
    data = dict(form(client.get('/projects/p/operations')), action='order', quote_revision='r1', material='0', actor='Tester', confirmed='yes')
    assert client.post('/projects/p/operations', data=data).status_code == 409
    assert not load(store, 'test')['orders']
