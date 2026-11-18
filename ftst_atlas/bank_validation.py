"""Pure, fail-closed bank-import preview. No persistence or payment-status writes.

Only the documented canonical CSV v1 is accepted, not arbitrary bank exports.
All amounts are EUR cents. Allocation previews need authoritative balances from
an owner-scoped transactional store before they may ever be persisted.
"""
import csv
import io
import re
from datetime import date


class BankValidationError(ValueError):
    """Safe error without imported customer data."""


HEADERS = ['transaction_id', 'booking_date', 'amount', 'currency', 'reference']
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000


def _cents(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]{0,11})\.[0-9]{2}', value):
        raise BankValidationError('Betrag benötigt einen exakten Dezimaltext mit zwei Nachkommastellen.')
    sign = -1 if value.startswith('-') else 1
    whole, fraction = value.lstrip('-').split('.')
    return sign * (int(whole) * 100 + int(fraction))


def _money(cents):
    return ('-' if cents < 0 else '') + f'{abs(cents) // 100}.{abs(cents) % 100:02d}'


def _date(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (ValueError, TypeError):
        raise BankValidationError('Datum benötigt YYYY-MM-DD.') from None
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise BankValidationError('Interne Referenz ungültig.')
    return value


def validate_csv(data, *, opening_balance, closing_balance, start_date, end_date):
    """Validate a complete, single-account EUR statement or reject all rows.

    Account/owner identity is intentionally not inferred from CSV text. Caller
    must bind the immutable source file to an explicit owner and account.
    """
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise BankValidationError('CSV fehlt oder überschreitet die Größenbegrenzung.')
    start_date, end_date = _date(start_date), _date(end_date)
    if start_date > end_date:
        raise BankValidationError('Zeitraum ist widersprüchlich.')
    opening, closing = _cents(opening_balance), _cents(closing_balance)
    try:
        text = data.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        if reader.fieldnames != HEADERS:
            raise BankValidationError('CSV-Kopf entspricht nicht dem unterstützten Format v1.')
        rows, seen, total = [], set(), 0
        for row in reader:
            if len(rows) >= MAX_ROWS or set(row) != set(HEADERS) or any(v is None for v in row.values()):
                raise BankValidationError('CSV-Zeile fehlt, enthält Zusatzfelder oder überschreitet das Limit.')
            ident = _id(row['transaction_id'])
            if ident in seen:
                raise BankValidationError('Doppelte Transaktionsreferenz im Auszug.')
            seen.add(ident)
            stamp = _date(row['booking_date'])
            if not start_date <= stamp <= end_date:
                raise BankValidationError('Transaktion liegt außerhalb des Auszugszeitraums.')
            amount = _cents(row['amount'])
            if not amount or row['currency'] != 'EUR':
                raise BankValidationError('Nur von null verschiedene EUR-Transaktionen werden unterstützt.')
            reference = row['reference']
            if len(reference) > 2000 or any(ord(c) < 32 and c not in '\r\n\t' for c in reference):
                raise BankValidationError('Verwendungszweck ist ungültig oder zu lang.')
            rows.append(dict(row, amount=_money(amount)))
            total += amount
    except (UnicodeError, csv.Error):
        raise BankValidationError('CSV ist nicht vollständig als UTF-8 lesbar.') from None
    if opening + total != closing:
        raise BankValidationError('Anfangssaldo und Transaktionen stimmen nicht mit dem Endsaldo überein.')
    return {'format': 'atlas-bank-csv/1', 'currency': 'EUR', 'transactions': rows,
            'opening_balance': _money(opening), 'closing_balance': _money(closing),
            'net_change': _money(total), 'status': 'validated_preview'}


def preview_allocation(*, available_amount, direction, allocations):
    """Validate explicit partial/batch allocations without claiming bank settlement.

    available_amount is signed: credit for outgoing invoices, debit for incoming.
    Each row supplies an internal invoice id, EUR currency, matching direction,
    authoritative open_amount and positive allocated amount. No auto-matching.
    """
    available = _cents(available_amount)
    if direction not in ('incoming', 'outgoing') or not available:
        raise BankValidationError('Zahlungsrichtung fehlt oder ist ungültig.')
    if (direction == 'outgoing') != (available > 0):
        raise BankValidationError('Bankbewegung und Rechnungsrichtung widersprechen sich.')
    if not isinstance(allocations, list) or not allocations or len(allocations) > 100:
        raise BankValidationError('Zuordnungen fehlen oder überschreiten das Limit.')
    total, seen, result = 0, set(), []
    expected = {'invoice_id', 'currency', 'direction', 'open_amount', 'amount'}
    for row in allocations:
        if not isinstance(row, dict) or set(row) != expected:
            raise BankValidationError('Zuordnung hat unbekannte oder fehlende Felder.')
        ident = _id(row['invoice_id'])
        if ident in seen:
            raise BankValidationError('Rechnung mehrfach in derselben Zuordnung.')
        seen.add(ident)
        amount, outstanding = _cents(row['amount']), _cents(row['open_amount'])
        if row['currency'] != 'EUR' or row['direction'] != direction:
            raise BankValidationError('Währung oder Richtung der Rechnung stimmt nicht überein.')
        if amount <= 0 or outstanding <= 0 or amount > outstanding:
            raise BankValidationError('Zuordnung übersteigt den offenen Betrag oder ist nicht positiv.')
        total += amount
        result.append({'invoice_id': ident, 'amount': _money(amount),
                       'remaining_open_amount': _money(outstanding - amount)})
    if total > abs(available):
        raise BankValidationError('Zuordnung übersteigt den verfügbaren Zahlungsbetrag.')
    return {'status': 'unconfirmed_preview', 'allocations': result,
            'unallocated_amount': _money(abs(available) - total)}
