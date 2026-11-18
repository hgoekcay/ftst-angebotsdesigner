"""Trusted local Bookkeeping -> unconfirmed draft baseline adapter.

No routes or production wiring. Actor must come from authenticated context.
Only IDs/revision are accepted, never form-provided balances. Source freshness is
not atomic across the two stores, so this cannot confirm any financial payment.
"""
from bank_allocations import AllocationConflict, _scope
from bank_reconciliation import _source_amount, invoice_snapshot_token
from bank_validation import BankValidationError, _id


def refresh_invoice_basis(drafts, bookkeeping, *, actor, owner, invoice_id, expected_revision=None):
    _scope(actor, owner, 'unused')
    invoice_id = _id(invoice_id)
    if expected_revision is not None:
        _id(expected_revision)
    before = drafts.get_invoice_basis(actor=actor, owner=owner, invoice=invoice_id)
    if (before['revision'] if before else None) != expected_revision:
        raise AllocationConflict('Rechnungsbasis inzwischen geändert; erneut laden.')

    def block():
        # Conservative failure: even source-read failure must not retain usable
        # old capacity. A concurrent newer baseline may also be blocked, never paid.
        if drafts.get_invoice_basis(actor=actor, owner=owner, invoice=invoice_id) is not None:
            drafts.invalidate_invoice(actor=actor, owner=owner, invoice=invoice_id)

    try:
        record = bookkeeping.get(owner, invoice_id)
    except Exception:
        block()
        raise BankValidationError('Rechnungsquelle derzeit nicht lesbar; Entwurfsbasis gesperrt.') from None
    try:
        if (not isinstance(record, dict) or record.get('id') != invoice_id
                or record.get('source', {}).get('provider') != 'billomat'
                or record.get('reviewed') is not True or record.get('issues') or record.get('canceled')):
            raise ValueError
        fields = record['fields']
        if (fields.get('source_status') not in ('OPEN', 'OVERDUE')
                or fields.get('currency') != 'EUR' or fields.get('source_currency') != 'EUR'
                or fields.get('direction') not in ('incoming', 'outgoing')):
            raise ValueError
        amount = _source_amount(fields.get('source_open_amount'))
        revision = invoice_snapshot_token(record)
    except (ValueError, TypeError, KeyError, AttributeError):
        block()
        raise BankValidationError('Rechnungsquelle ungeprüft, geschlossen oder unbrauchbar; Entwurfsbasis gesperrt.') from None
    drafts.freeze_invoice(actor=actor, owner=owner, invoice=invoice_id, revision=revision,
                          open_amount=amount, direction=fields['direction'], expected_revision=expected_revision)
    return {'invoice_id': invoice_id, 'revision': revision, 'state': 'unconfirmed_source_basis',
            'confirmation_supported': False}
