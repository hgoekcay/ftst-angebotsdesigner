"""Synthetic source integration; no connector or real invoice data."""
import copy
import importlib.util
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

BASE = Path(__file__).parents[2] / 'ftst_atlas'
for name in ('bank_validation', 'bank_statements', 'bank_allocations', 'bank_reconciliation', 'bank_source_adapter'):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
adapter = sys.modules['bank_source_adapter']
drafts_module = sys.modules['bank_allocations']


@pytest.fixture
def context(tmp_path):
    drafts = drafts_module.DraftAllocations(tmp_path / 'drafts.sqlite')
    record = dict(id='i1', reviewed=True, issues=[], canceled=False, sha256='synthetic', source={'provider': 'billomat'},
                  fields=dict(currency='EUR', source_currency='EUR', source_open_amount='119.0000', direction='outgoing', source_status='OPEN'))
    reader = Mock()
    reader.get.side_effect = lambda owner, ident: copy.deepcopy(record) if (owner, ident) == ('owner', 'i1') else None
    return drafts, reader, record


def refresh(context, **changes):
    args = dict(actor='owner', owner='owner', invoice_id='i1')
    args.update(changes)
    return adapter.refresh_invoice_basis(context[0], context[1], **args)


def basis(context):
    return context[0].get_invoice_basis(actor='owner', owner='owner', invoice='i1')


def test_source_amount_and_revision_taken_from_scoped_store(context):
    initial = refresh(context)
    assert basis(context)['open_amount'] == '119.00'
    assert initial['confirmation_supported'] is False
    context[1].get.assert_called_with('owner', 'i1')
    assert refresh(context, expected_revision=initial['revision']) == initial
    context[2]['fields']['source_open_amount'] = '90.00'
    second = refresh(context, expected_revision=initial['revision'])
    assert second['revision'] != initial['revision']
    assert basis(context)['open_amount'] == '90.00'
    with pytest.raises(ValueError):
        refresh(context, expected_revision=initial['revision'])
    assert basis(context)['revision'] == second['revision']


@pytest.mark.parametrize('field,value', [('source_status', 'PAID'), ('source_status', 'CANCELED'),
    ('source_status', ''), ('source_open_amount', '1.001'), ('source_currency', 'USD'), ('direction', 'unknown')])
def test_bad_source_blocks_existing_basis(context, field, value):
    initial = refresh(context)
    context[2]['fields'][field] = value
    with pytest.raises(ValueError):
        refresh(context, expected_revision=initial['revision'])
    assert basis(context)['blocked'] is True


@pytest.mark.parametrize('field,value', [('reviewed', False), ('issues', ['review']), ('source', {'provider': 'upload'}), ('canceled', True)])
def test_review_provider_cancellation_guards(context, field, value):
    initial = refresh(context)
    context[2][field] = value
    with pytest.raises(ValueError):
        refresh(context, expected_revision=initial['revision'])
    assert basis(context)['blocked']


@pytest.mark.parametrize('mode', ['missing', 'error'])
def test_missing_or_unavailable_source_blocks_old_capacity(context, mode):
    initial = refresh(context)
    context[1].get.side_effect = (lambda *_: None) if mode == 'missing' else RuntimeError('synthetic outage')
    with pytest.raises(ValueError):
        refresh(context, expected_revision=initial['revision'])
    assert basis(context)['blocked']


def test_authorization_before_source_read_and_no_form_balances(context):
    with pytest.raises(ValueError):
        refresh(context, actor='other')
    context[1].get.assert_not_called()
    with pytest.raises(TypeError):
        refresh(context, open_amount='9999.00')
    with pytest.raises(ValueError):
        context[0].get_invoice_basis(actor='other', owner='owner', invoice='i1')
    assert basis(context) is None


def test_zero_source_closes_capacity(context):
    initial = refresh(context)
    context[2]['fields']['source_open_amount'] = '0.00'
    refresh(context, expected_revision=initial['revision'])
    assert basis(context)['open_amount'] == '0.00'


def test_real_bookkeeping_source_is_not_modified(tmp_path):
    sys.path.insert(0, str(BASE))
    try:
        spec = importlib.util.spec_from_file_location('bookkeeping_adapter_test', BASE / 'bookkeeping.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    path = tmp_path / 'source.sqlite'
    source = module.Bookkeeping(lambda: sqlite3.connect(path), tmp_path)
    record = source.ingest_billomat('owner', dict(id='synthetic', supplier='Synthetic Client', invoice_number='INV-TEST',
        invoice_date='2026-01-01', currency='EUR', net='100.00', tax='19.00', gross='119.00',
        direction='outgoing', source_status='OPEN', source_open_amount='119.00'))
    source.review('owner', record['id'], {'reviewed': True})
    def dump():
        with sqlite3.connect(path) as db:
            return '\n'.join(db.iterdump())
    before = dump()
    drafts = drafts_module.DraftAllocations(tmp_path / 'drafts.sqlite')
    result = adapter.refresh_invoice_basis(drafts, source, actor='owner', owner='owner', invoice_id=record['id'])
    assert len(result['revision']) == 64
    assert dump() == before
    assert source.get('owner', record['id'])['fields']['payment_status'] == 'unknown'


def test_changed_source_with_active_draft_blocks_further_reservation(context):
    initial = refresh(context)
    drafts = context[0]
    drafts.provision_account(actor='owner', owner='owner', account='account')
    drafts.import_csv('owner', 'account', b'transaction_id,booking_date,amount,currency,reference\ntx,2026-01-02,100.00,EUR,x\n',
                      opening_balance='0.00', closing_balance='100.00', start_date='2026-01-01', end_date='2026-01-31')
    args = dict(actor='owner', owner='owner', account='account', transaction_id='tx', request_key='first',
                selections=[dict(invoice_id='i1', revision=initial['revision'], amount='40.00')])
    drafts.reserve(**args)
    context[2]['fields']['source_open_amount'] = '79.00'
    with pytest.raises(ValueError):
        refresh(context, expected_revision=initial['revision'])
    args['request_key'] = 'second'
    with pytest.raises(ValueError):
        drafts.reserve(**args)
    assert basis(context)['blocked']
