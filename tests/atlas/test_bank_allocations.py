"""Atomic local draft reservations with synthetic invoices and temporary SQLite."""
import importlib.util
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BASE = Path(__file__).parents[2] / 'ftst_atlas'
for name in ('bank_validation', 'bank_statements', 'bank_allocations'):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
bank = sys.modules['bank_allocations']


@pytest.fixture
def store(tmp_path):
    result = bank.DraftAllocations(tmp_path / 'synthetic.sqlite')
    result.provision_account(actor='owner', owner='owner', account='account')
    result.import_csv('owner', 'account', b'transaction_id,booking_date,amount,currency,reference\nt1,2026-01-02,100.00,EUR,x\nt2,2026-01-03,100.00,EUR,y\n',
                      opening_balance='0.00', closing_balance='200.00', start_date='2026-01-01', end_date='2026-01-31')
    freeze(result)
    return result


def freeze(store, **changes):
    args = dict(actor='owner', owner='owner', invoice='i1', revision='v1', open_amount='150.00', direction='outgoing')
    args.update(changes)
    return store.freeze_invoice(**args)


def reserve(store, **changes):
    args = dict(actor='owner', owner='owner', account='account', transaction_id='t1', request_key='r1', selections=[dict(invoice_id='i1', revision='v1', amount='60.00')])
    args.update(changes)
    return store.reserve(**args)


def reverse(store, **changes):
    args = dict(actor='owner', owner='owner', account='account', request_key='r1')
    args.update(changes)
    return store.reverse(**args)


def counts(store):
    with sqlite3.connect(store.path) as db:
        return tuple(db.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in ('bank_draft_batches_v1', 'bank_draft_lines_v1'))


def test_retries_restart_reversal_and_no_resurrection(store):
    assert reserve(store)['state'] == 'reserved_unconfirmed'
    restarted = bank.DraftAllocations(store.path)
    assert reserve(restarted)['replayed']
    assert counts(store) == (1, 1)
    assert reverse(store)['replayed'] is False
    assert reverse(store)['replayed'] is True
    assert reserve(store)['state'] == 'reversed'
    assert counts(store) == (1, 1)
    assert reserve(store, request_key='new')['state'] == 'reserved_unconfirmed'
    with sqlite3.connect(store.path) as db:
        row = db.execute("SELECT actor,reversed_by,reversed_at FROM bank_draft_batches_v1 WHERE request_key='r1'").fetchone()
        assert row[0:2] == ('owner', 'owner') and row[2]


@pytest.mark.parametrize('changes', [dict(actor='intruder'), dict(owner='other'), dict(account='unregistered'),
    dict(transaction_id='missing'), dict(selections=[dict(invoice_id='missing', revision='v1', amount='1.00')]),
    dict(selections=[dict(invoice_id='i1', revision='old', amount='1.00')]),
    dict(selections=[dict(invoice_id='i1', revision='v1', amount='-1.00')])])
def test_permission_and_invalid_selection_no_write(store, changes):
    with pytest.raises(ValueError):
        reserve(store, **changes)
    assert counts(store) == (0, 0)


def test_partial_batch_and_total_limits(store):
    freeze(store, invoice='i2', open_amount='40.00')
    reserve(store, selections=[dict(invoice_id='i1', revision='v1', amount='60.00'), dict(invoice_id='i2', revision='v1', amount='40.00')])
    with pytest.raises(ValueError):
        reserve(store, request_key='r2')
    with pytest.raises(ValueError):
        reserve(store, request_key='r3', transaction_id='t2', selections=[dict(invoice_id='i2', revision='v1', amount='1.00')])
    assert counts(store) == (1, 2)


def test_atomic_invalid_second_selection_and_duplicate(store):
    for second in ('i1', 'missing'):
        with pytest.raises(ValueError):
            reserve(store, selections=[dict(invoice_id='i1', revision='v1', amount='20.00'), dict(invoice_id=second, revision='v1', amount='20.00')])
    assert counts(store) == (0, 0)


def test_key_reuse_for_changed_request_rejected(store):
    reserve(store)
    with pytest.raises(ValueError):
        reserve(store, transaction_id='t2')
    assert counts(store) == (1, 1)


def test_source_change_blocks_old_revision_until_reversal_and_refreeze(store):
    reserve(store)
    with pytest.raises(ValueError):
        freeze(store, revision='v2', open_amount='90.00', expected_revision='v1')
    with pytest.raises(ValueError):
        reserve(store, transaction_id='t2', request_key='r2')
    with pytest.raises(ValueError):
        freeze(store)  # Old snapshot retry must not clear stale-source block.
    reverse(store)
    freeze(store, revision='v2', open_amount='90.00', expected_revision='v1')
    with pytest.raises(ValueError):
        reserve(store, request_key='r3')
    reserve(store, request_key='r4', selections=[dict(invoice_id='i1', revision='v2', amount='80.00')])


def test_cross_account_invoice_limit(store):
    reserve(store, selections=[dict(invoice_id='i1', revision='v1', amount='100.00')])
    store.provision_account(actor='owner', owner='owner', account='second')
    store.import_csv('owner', 'second', b'transaction_id,booking_date,amount,currency,reference\nt1,2026-01-02,100.00,EUR,x\n', opening_balance='0.00', closing_balance='100.00', start_date='2026-01-01', end_date='2026-01-31')
    with pytest.raises(ValueError):
        reserve(store, account='second', request_key='r2')
    assert counts(store) == (1, 1)


def test_concurrent_competing_reservations_allow_only_one(store):
    def run(key):
        try:
            return reserve(bank.DraftAllocations(store.path), request_key=key)['state']
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['a', 'b'])) == ['conflict', 'reserved_unconfirmed']
    assert counts(store) == (1, 1)


def test_concurrent_same_key_is_idempotent(store):
    def run(_):
        return reserve(bank.DraftAllocations(store.path))['replayed']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(8)))
    assert results.count(False) == 1
    assert counts(store) == (1, 1)


def test_reverse_owner_boundary_and_revision_conflict(store):
    reserve(store)
    with pytest.raises(ValueError):
        reverse(store, actor='intruder')
    with pytest.raises(ValueError):
        freeze(store, open_amount='10.00', expected_revision='v1')
    assert reserve(store)['state'] == 'reserved_unconfirmed'


def test_concurrent_different_transactions_share_invoice_limit(store):
    def run(tx):
        try:
            return reserve(bank.DraftAllocations(store.path), request_key=tx, transaction_id=tx,
                           selections=[dict(invoice_id='i1', revision='v1', amount='100.00')])['state']
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ['t1', 't2'])) == ['conflict', 'reserved_unconfirmed']
    assert counts(store) == (1, 1)


def test_supplier_debit_and_direction_mismatch(store):
    store.import_csv('owner', 'account', b'transaction_id,booking_date,amount,currency,reference\ndebit,2026-01-02,-100.00,EUR,x\n', opening_balance='100.00', closing_balance='0.00', start_date='2026-01-01', end_date='2026-01-31')
    with pytest.raises(ValueError):
        reserve(store, transaction_id='debit')
    freeze(store, revision='supplier-v1', direction='incoming', expected_revision='v1')
    reserve(store, transaction_id='debit', selections=[dict(invoice_id='i1', revision='supplier-v1', amount='60.00')])
    reverse(store)
    assert counts(store) == (1, 1)


@pytest.mark.parametrize('active', [False, True])
def test_zero_source_baseline_cannot_leave_positive_capacity(store, active):
    if active:
        reserve(store)
        with pytest.raises(ValueError):
            freeze(store, revision='paid', open_amount='0.00', expected_revision='v1')
    else:
        freeze(store, revision='paid', open_amount='0.00', expected_revision='v1')
    with pytest.raises(ValueError):
        reserve(store, request_key='new')
    with pytest.raises(ValueError):
        reserve(store, request_key='paid-key', selections=[dict(invoice_id='i1', revision='paid', amount='1.00')])


def test_invalidation_and_stale_refresh_fail_closed(store):
    freeze(store, revision='v2', expected_revision='v1')
    with pytest.raises(ValueError):
        freeze(store, revision='old-response', open_amount='999.00', expected_revision='v1')
    store.invalidate_invoice(actor='owner', owner='owner', invoice='i1')
    with pytest.raises(ValueError):
        reserve(store, selections=[dict(invoice_id='i1', revision='v2', amount='1.00')])
    with pytest.raises(ValueError):
        store.invalidate_invoice(actor='intruder', owner='owner', invoice='i1')
    freeze(store, revision='v3', expected_revision='v2')
    reserve(store, selections=[dict(invoice_id='i1', revision='v3', amount='1.00')])
