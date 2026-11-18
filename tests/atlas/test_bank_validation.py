"""Synthetic data only; validation is not a real financial action."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('bank_validation', Path(__file__).parents[2] / 'ftst_atlas/bank_validation.py')
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)
HEADER = b'transaction_id,booking_date,amount,currency,reference\n'


def validate(rows=b't1,2026-01-02,119.00,EUR,INV-1\n', **changes):
    args = dict(opening_balance='0.00', closing_balance='119.00', start_date='2026-01-01', end_date='2026-01-31')
    args.update(changes)
    return bank.validate_csv(HEADER + rows, **args)


def allocation(ident='i1', amount='40.00', outstanding='119.00', direction='outgoing'):
    return dict(invoice_id=ident, amount=amount, open_amount=outstanding, direction=direction, currency='EUR')


def test_statement_balances_and_multiline_reference():
    result = validate(b't1,2026-01-02,120.00,EUR,"INV-1\ncontinued"\nt2,2026-01-03,-1.00,EUR,fee\n')
    assert result['net_change'] == '119.00'
    assert result['transactions'][0]['reference'] == 'INV-1\ncontinued'
    assert result['status'] == 'validated_preview'


@pytest.mark.parametrize('rows', [
    b't1,2026-01-02,119.00,EUR,x\nt1,2026-01-02,119.00,EUR,x\n',
    b't1,2026-02-01,119.00,EUR,x\n', b't1,2026-01-02,119.00,USD,x\n',
    b't1,2026-01-02,119.00,EUR,x,extra\n', b't1,2026-01-02,119.00,EUR\n',
    b't1,2026-01-02,119.00,EUR,"unfinished', b'\xff',
    b't1,2026-01-02,0.00,EUR,x\n', b't1,2026-01-02,119.00,EUR,\x00\n',
])
def test_bad_csv_rejected_as_whole(rows):
    with pytest.raises(bank.BankValidationError):
        validate(rows)


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '1e2', '1,00', '1.001', '01.00', '+1.00', 1.0, True, None])
def test_noncanonical_amounts(amount):
    with pytest.raises(bank.BankValidationError):
        validate(opening_balance=amount)


def test_header_balance_dates_limits():
    for data in [b'', HEADER.replace(b'amount', b'value'), b'x' * (bank.MAX_BYTES + 1)]:
        with pytest.raises(bank.BankValidationError):
            bank.validate_csv(data, opening_balance='0.00', closing_balance='0.00', start_date='2026-01-01', end_date='2026-01-31')
    for changes in [dict(closing_balance='118.99'), dict(start_date='2026-02-01'), dict(end_date='2026-02-30')]:
        with pytest.raises(bank.BankValidationError):
            validate(**changes)


def test_partial_and_batch_preview_does_not_mutate_input():
    rows = [allocation(), allocation('i2', '60.00', '60.00')]
    result = bank.preview_allocation(available_amount='120.00', direction='outgoing', allocations=rows)
    assert result['status'] == 'unconfirmed_preview'
    assert result['unallocated_amount'] == '20.00'
    assert result['allocations'][0]['remaining_open_amount'] == '79.00'
    assert result['allocations'][1]['remaining_open_amount'] == '0.00'
    assert rows[0]['open_amount'] == '119.00'
    assert bank.preview_allocation(available_amount='120.00', direction='outgoing', allocations=rows) == result


def test_outgoing_bank_payment_for_supplier_invoice():
    result = bank.preview_allocation(available_amount='-40.00', direction='incoming', allocations=[allocation(direction='incoming')])
    assert result['unallocated_amount'] == '0.00'


@pytest.mark.parametrize('changes', [dict(amount='120.00'), dict(amount='-1.00'), dict(amount='0.00'), dict(currency='USD'), dict(direction='incoming'), dict(open_amount='-1.00'), dict(invoice_id=''), dict(extra='x')])
def test_bad_allocation(changes):
    row = allocation()
    row.update(changes)
    with pytest.raises(bank.BankValidationError):
        bank.preview_allocation(available_amount='100.00', direction='outgoing', allocations=[row])


def test_total_and_duplicate_guards():
    for rows in [[], [allocation(), allocation()], [allocation(), allocation('i2')]]:
        with pytest.raises(bank.BankValidationError):
            bank.preview_allocation(available_amount='60.00', direction='outgoing', allocations=rows)
    with pytest.raises(bank.BankValidationError):
        bank.preview_allocation(available_amount='-60.00', direction='outgoing', allocations=[allocation()])


def test_row_bound_and_utf8_bom(monkeypatch):
    monkeypatch.setattr(bank, 'MAX_ROWS', 1)
    with pytest.raises(bank.BankValidationError):
        validate(b't1,2026-01-02,120.00,EUR,x\nt2,2026-01-03,-1.00,EUR,fee\n')
    result = bank.validate_csv(b'\xef\xbb\xbf' + HEADER, opening_balance='12.00', closing_balance='12.00', start_date='2026-01-01', end_date='2026-01-31')
    assert result['transactions'] == []


def test_exact_cent_boundary_and_allocation_limit():
    result = bank.preview_allocation(available_amount='0.30', direction='outgoing', allocations=[allocation('a', '0.10', '0.10'), allocation('b', '0.20', '0.20')])
    assert result['unallocated_amount'] == '0.00'
    with pytest.raises(bank.BankValidationError):
        bank.preview_allocation(available_amount='1000.00', direction='outgoing', allocations=[allocation(str(i)) for i in range(101)])
