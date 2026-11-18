"""Synthetic integration between SQLite staging and scoped invoice-reader protocol."""
import copy
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

BASE = Path(__file__).parents[2] / 'ftst_atlas'
for name in ('bank_validation', 'bank_statements', 'bank_reconciliation'):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
bridge = sys.modules['bank_reconciliation']


@pytest.fixture
def context(tmp_path):
    statements = sys.modules['bank_statements'].StatementStore(tmp_path / 'test.sqlite')
    statements.import_csv('owner', 'account', b'transaction_id,booking_date,amount,currency,reference\ntx,2026-01-02,100.00,EUR,synthetic\n',
                          opening_balance='0.00', closing_balance='100.00', start_date='2026-01-01', end_date='2026-01-31')
    record = dict(id='invoice', reviewed=True, issues=[], canceled=False, sha256='synthetic', source={'provider': 'billomat'},
                  fields=dict(currency='EUR', source_currency='EUR', source_open_amount='120.0000', direction='outgoing', source_status='OPEN'))
    reader = Mock()
    reader.get.side_effect = lambda owner, ident: copy.deepcopy(record) if (owner, ident) == ('owner', 'invoice') else None
    return statements, reader, record


def preview(context, **changes):
    statements, reader, _ = context
    args = dict(owner='owner', account='account', transaction_id='tx', selections=[{'invoice_id': 'invoice', 'amount': '40.00'}])
    args.update(changes)
    return bridge.preview_selected(statements, reader, **args)


def test_read_only_scoped_preview_and_stale_snapshot_token(context):
    result = preview(context)
    assert result['status'] == 'unconfirmed_source_snapshot'
    assert result['confirmation_supported'] is False
    assert result['allocations'][0]['remaining_open_amount'] == '80.00'
    assert result['unallocated_amount'] == '60.00'
    context[1].get.assert_called_with('owner', 'invoice')
    assert [call[0] for call in context[1].method_calls] == ['get']
    before = result['invoice_snapshots']
    context[2]['fields']['source_open_amount'] = '90.00'
    assert preview(context)['invoice_snapshots'] != before


@pytest.mark.parametrize('changes', [{'owner': 'other'}, {'account': 'other'}, {'transaction_id': 'missing'},
    {'selections': [{'invoice_id': 'missing', 'amount': '1.00'}]},
    {'selections': [{'invoice_id': 'invoice', 'amount': '1.00', 'open_amount': '999.00'}]},
    {'selections': [{'invoice_id': 'invoice', 'amount': '1.00'}] * 2}])
def test_inaccessible_or_tampered_selection_fails(context, changes):
    with pytest.raises(ValueError):
        preview(context, **changes)


@pytest.mark.parametrize('field,value', [('source_status', 'PAID'), ('source_status', 'CANCELED'),
    ('source_currency', 'USD'), ('currency', 'USD'), ('source_open_amount', ''),
    ('source_open_amount', '1.001'), ('source_open_amount', '0.00'), ('direction', 'incoming')])
def test_invalid_source_never_proposes(context, field, value):
    context[2]['fields'][field] = value
    with pytest.raises(ValueError):
        preview(context)


@pytest.mark.parametrize('field,value', [('reviewed', False), ('issues', ['review']), ('canceled', True), ('source', {'provider': 'upload'})])
def test_review_and_provider_guard(context, field, value):
    context[2][field] = value
    with pytest.raises(ValueError):
        preview(context)


def test_source_open_amount_not_gross_or_form_value(context):
    context[2]['fields'].update(source_open_amount='30.00', gross='999.00')
    with pytest.raises(ValueError):
        preview(context)


def test_real_bookkeeping_store_read_only_batch_and_owner_boundary(context, tmp_path):
    import sqlite3
    sys.path.insert(0, str(BASE))
    try:
        spec = importlib.util.spec_from_file_location('bookkeeping_bridge_test', BASE / 'bookkeeping.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    path = tmp_path / 'invoices.sqlite'
    invoices = module.Bookkeeping(lambda: sqlite3.connect(path), tmp_path)
    ids = []
    for ident in ('one', 'two'):
        record = invoices.ingest_billomat('owner', dict(id=ident, supplier='Synthetic Client', invoice_number='INV-' + ident,
            invoice_date='2026-01-02', currency='EUR', net='100.00', tax='19.00', gross='119.00',
            direction='outgoing', source_status='OPEN', source_open_amount='119.00'))
        invoices.review('owner', record['id'], {'reviewed': True})
        ids.append(record['id'])
    def dump():
        with sqlite3.connect(path) as db:
            return '\n'.join(db.iterdump())
    before = dump()
    result = bridge.preview_selected(context[0], invoices, owner='owner', account='account', transaction_id='tx',
                                    selections=[{'invoice_id': ids[0], 'amount': '40.00'}, {'invoice_id': ids[1], 'amount': '60.00'}])
    assert result['unallocated_amount'] == '0.00'
    assert [row['remaining_open_amount'] for row in result['allocations']] == ['79.00', '59.00']
    assert dump() == before
    assert invoices.get('other', ids[0]) is None
    assert all(invoices.get('owner', ident)['fields']['payment_status'] == 'unknown' for ident in ids)


def test_supplier_debit_preview_and_repeat_are_read_only(context):
    context[0].import_csv('owner', 'account', b'transaction_id,booking_date,amount,currency,reference\ndebit,2026-01-03,-50.00,EUR,synthetic\n',
                         opening_balance='100.00', closing_balance='50.00', start_date='2026-01-03', end_date='2026-01-03')
    context[2]['fields']['direction'] = 'incoming'
    result = preview(context, transaction_id='debit')
    assert result['unallocated_amount'] == '10.00'
    assert preview(context, transaction_id='debit') == result
