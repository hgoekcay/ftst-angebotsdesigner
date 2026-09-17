import re
import uuid

import pytest

import app as module
from inventory import InventoryError, execute, load
from inventory_barcodes import code_value, issue_payload, resolve
from storage import RecordConflict
from test_inventory import order, warehouse


def mapping(command, code='00123456', **extra):
    return command('barcode_assign', dict(code=code, article='1', kind='single', factor='1', confirmed='yes', **extra))


def form(state, code='00123456', amount='2', oid='p'):
    return dict(code=code, mapping_revision=str(resolve(state, code)['revision']), scan_quantity=amount, order=oid)


def setup(command, stock='8'):
    command('opening', dict(article='1', quantity=stock))
    order(command)
    return mapping(command)


def test_code_preserves_zeros_and_case(warehouse):
    _, command = warehouse
    state = mapping(command)
    assert resolve(state, '00123456')['code'] == '00123456'
    with pytest.raises(InventoryError):
        resolve(state, '123456')
    assert code_value('aB-001\r\n') == 'aB-001'


@pytest.mark.parametrize('code', [123, '', '(01)01234567890128(21)serial', ']C10101234567890128', '010123\x1d21xx', 'https://example.org/1'])
def test_composite_and_link_codes_are_not_product_aliases(code):
    with pytest.raises(InventoryError):
        code_value(code)


def test_duplicate_or_unconfirmed_mapping_does_not_change_stock(warehouse):
    store, command = warehouse
    state = mapping(command)
    with pytest.raises(InventoryError, match='bereits'):
        mapping(command)
    with pytest.raises(InventoryError, match='bestätigen'):
        command('barcode_assign', dict(code='other', article='1', kind='serial', factor='1', confirmed='yes'))
    assert load(store, 'test') == state
    assert not state['articles']['1']['known']


def test_lookup_never_books_and_issue_twice_only_once(warehouse):
    store, command = warehouse
    state = setup(command)
    payload = issue_payload(state, form(state))
    assert load(store, 'test') == state
    operation = uuid.uuid4().hex
    updated = command('issue', payload, operation, state['revision'])
    assert updated['articles']['1']['stock'] == 6000
    assert command('issue', payload, operation, state['revision']) == updated
    with pytest.raises(RecordConflict):
        command('issue', dict(payload, quantity='3'), operation, state['revision'])


def test_pack_conversion_is_confirmed_and_server_validated(warehouse):
    _, command = warehouse
    command('opening', dict(article='1', quantity='30'))
    order(command, n='30')
    state = command('barcode_assign', dict(code='box10', article='1', kind='pack', factor='10', confirmed='yes'))
    payload = issue_payload(state, form(state, code='box10', amount='2'))
    assert payload['quantity'] == '20'
    with pytest.raises(InventoryError, match='stimmen'):
        command('issue', dict(payload, quantity='2'))
    with pytest.raises(InventoryError):
        issue_payload(state, form(state, code='box10', amount='0.5'))
    assert command('issue', payload)['articles']['1']['stock'] == 10000


def test_unknown_stock_and_foreign_reservations_stay_protected(warehouse):
    _, command = warehouse
    state = order(command)
    state = mapping(command)
    with pytest.raises(InventoryError, match='unbekannt'):
        command('issue', issue_payload(state, form(state)))
    command('opening', dict(article='1', quantity='3'))
    order(command, oid='other', n='2')
    state = load(warehouse[0], 'test')
    with pytest.raises(InventoryError, match='Andere Auftragsreservierungen'):
        command('issue', issue_payload(state, form(state)))


def test_changed_mapping_rejects_stale_confirmation(warehouse):
    _, command = warehouse
    state = setup(command)
    stale = form(state)
    command('barcode_remove', dict(code='00123456', note='Falsches Etikett'))
    state = mapping(command)
    with pytest.raises(InventoryError, match='geändert'):
        issue_payload(state, stale)


def test_ambiguous_projection_is_not_silently_selected(warehouse):
    _, command = warehouse
    state = mapping(command)
    state['barcodes']['duplicate'] = dict(state['barcodes']['00123456'])
    with pytest.raises(InventoryError, match='mehrdeutig'):
        resolve(state, '00123456')


def test_scan_ui_and_lost_response_after_mapping_removal(warehouse, monkeypatch):
    store, command = warehouse
    setup(command)
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(store.directory))
    client = module.app.test_client()
    response = client.get('/inventory/scan?order=p&code=00123456')
    assert response.status_code == 200
    assert 'einschließlich eigener Reservierung): 8' in response.text
    assert 'Browser-Scanner' not in response.text
    assert '/static/vendor/zxing-browser-0.2.1.min.js' in response.text
    assert client.get('/static/vendor/zxing-browser-0.2.1.min.js').status_code == 200
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', response.text))
    fields.update(scan_quantity='2', actor='Testperson', confirmed='yes', note='')
    headers = {'Accept': 'application/json'}
    denied = client.post('/inventory/scan', data=dict(fields, csrf='wrong'), headers=headers)
    assert denied.status_code == 400
    assert load(store, 'test')['articles']['1']['stock'] == 8000
    posted = client.post('/inventory/scan', data=fields, headers=headers)
    assert posted.status_code == 200 and posted.json['stock'] == '6'
    command('barcode_remove', dict(code='00123456', note='Später aufgehoben'))
    retried = client.post('/inventory/scan', data=fields, headers=headers)
    assert retried.status_code == 200 and retried.json['stock'] == '6'
    status = client.get('/inventory/scan/operations/' + fields['operation'], headers=headers)
    assert status.json['found'] and status.json['quantity'] == '2'
    assert status.headers['Cache-Control'] == 'no-store'
    assert not client.get('/inventory/scan/operations/unknown', headers=headers).json['found']
    conflict = client.post('/inventory/scan', data=dict(fields, scan_quantity='3'), headers=headers)
    assert conflict.status_code == 409
    assert conflict.json['already_recorded'] and not conflict.json['rejected']


def test_operation_status_is_account_scoped(warehouse, monkeypatch):
    store, command = warehouse
    state = setup(command)
    command('issue', issue_payload(state, form(state)), operation='op')
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(store.directory))
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    result = module.app.test_client().get('/inventory/scan/operations/op', headers={'Accept': 'application/json'})
    assert result.json['found'] is False


def test_meter_pack_conversion_has_exact_thousandths(warehouse):
    store, command = warehouse
    command('article', dict(id='cable', title='Kabel', unit='m'))
    state = command('barcode_assign', dict(code='cablepack', article='cable', kind='pack', factor='0.125', confirmed='yes'))
    payload = issue_payload(state, form(state, code='cablepack', amount='3'))
    assert payload['quantity'] == '0.375'
    assert load(store, 'test')['articles']['cable']['known'] is False


def test_overlong_scan_is_not_truncated_to_existing_code(warehouse, monkeypatch):
    store, command = warehouse
    command('opening', dict(article='1', quantity='8'))
    order(command)
    mapping(command, code='A' * 100)
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(store.directory))
    result = module.app.test_client().get('/inventory/scan', query_string=dict(order='p', code='A' * 101))
    assert 'id="barcode-issue"' not in result.text
    assert 'Nur einfache Produktcodes' in result.text
