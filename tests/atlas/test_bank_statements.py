"""Temporary SQLite databases and wholly synthetic account/transaction labels."""
import hashlib
import importlib.util
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BASE = Path(__file__).parents[2] / 'ftst_atlas'
for name in ('bank_validation', 'bank_statements'):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
bank = sys.modules['bank_statements']
HEADER = b'transaction_id,booking_date,amount,currency,reference\n'
SOURCE = HEADER + b't1,2026-01-02,10.00,EUR,synthetic\n'


def put(store, source=SOURCE, owner='owner1', account='account1', **changes):
    args = dict(opening_balance='0.00', closing_balance='10.00', start_date='2026-01-01', end_date='2026-01-31')
    args.update(changes)
    return store.import_csv(owner, account, source, **args)


@pytest.fixture
def store(tmp_path):
    return bank.StatementStore(tmp_path / 'synthetic.sqlite')


def counts(store):
    with sqlite3.connect(store.path) as db:
        return tuple(db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                     for table in ('bank_statements_v1', 'bank_transactions_v1'))


def test_exact_original_hash_and_restart_replay(store):
    first = put(store)
    assert first['status'] == 'staged_unreconciled'
    assert first['digest'] == hashlib.sha256(SOURCE).hexdigest()
    saved = store.get_statement('owner1', 'account1', first['digest'])
    assert saved['source'] == SOURCE
    assert saved['metadata']['closing_balance'] == '10.00'
    restarted = bank.StatementStore(store.path)
    assert put(restarted)['status'] == 'already_staged'
    assert restarted.get_statement('owner1', 'account1', first['digest']) == saved
    assert counts(store) == (1, 1)


def test_owner_and_account_isolation(store):
    first = put(store)
    assert store.get_statement('owner2', 'account1', first['digest']) is None
    assert store.get_statement('owner1', 'account2', first['digest']) is None
    put(store, owner='owner2')
    put(store, account='account2')
    assert counts(store) == (3, 3)


def test_changed_metadata_rejected_without_mutation(store):
    put(store)
    with pytest.raises(bank.StatementConflict):
        put(store, opening_balance='1.00', closing_balance='11.00')
    assert counts(store) == (1, 1)


def test_overlap_rolls_back_whole_file_including_new_rows(store):
    put(store)
    overlapping = HEADER + b't2,2026-01-02,5.00,EUR,new\nt1,2026-01-02,10.00,EUR,synthetic\n'
    with pytest.raises(bank.StatementConflict):
        put(store, overlapping, closing_balance='15.00')
    assert counts(store) == (1, 1)
    assert store.get_statement('owner1', 'account1', hashlib.sha256(overlapping).hexdigest()) is None
    put(store, HEADER + b't2,2026-01-02,5.00,EUR,new\n', closing_balance='5.00')
    assert counts(store) == (2, 2)


def test_malformed_or_unbalanced_source_never_written(store):
    for changes in [dict(closing_balance='9.00'), dict(source=b'invalid'), dict(owner=''), dict(account='../account')]:
        with pytest.raises(bank.BankValidationError):
            put(store, **changes)
    assert counts(store) == (0, 0)


def test_concurrent_retries_stage_once(store):
    def run(_):
        return put(bank.StatementStore(store.path))['status']
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(run, range(8)))
    assert statuses.count('staged_unreconciled') == 1
    assert statuses.count('already_staged') == 7
    assert counts(store) == (1, 1)


def test_concurrent_conflicting_files_are_atomic(store):
    def run(label):
        try:
            return put(bank.StatementStore(store.path), SOURCE.replace(b'synthetic', label))['status']
        except bank.StatementConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(run, [b'first', b'second']))
    assert sorted(statuses) == ['conflict', 'staged_unreconciled']
    assert counts(store) == (1, 1)


def test_invalid_lookup_and_no_implicit_database(store):
    with pytest.raises(bank.BankValidationError):
        store.get_statement('owner1', 'account1', '../file')
    for value in (':memory:', '', None, 123):
        with pytest.raises(ValueError):
            bank.StatementStore(value)


def test_controls_rechecked_on_retry_and_do_not_mutate_original(store):
    first = put(store, control_totals=dict(credits='10.00', debits='0.00', transaction_count=1))
    original = store.get_statement('owner1', 'account1', first['digest'])
    assert put(store, control_totals=dict(credits='10.00', debits='0.00', transaction_count=1))['status'] == 'already_staged'
    with pytest.raises(ValueError):
        put(store, control_totals=dict(credits='11.00', debits='1.00', transaction_count=1))
    assert store.get_statement('owner1', 'account1', first['digest']) == original
    assert counts(store) == (1, 1)


def test_distinct_account_types_are_separate_scopes(store):
    for account in ('giro', 'pro', 'pocket1', 'pocket2'):
        assert put(store, account=account)['status'] == 'staged_unreconciled'
    assert counts(store) == (4, 4)
    # Classification is supplied by a trusted account map, not guessed from reference.
    for account in ('giro', 'pro', 'pocket1', 'pocket2'):
        assert put(store, account=account)['status'] == 'already_staged'
