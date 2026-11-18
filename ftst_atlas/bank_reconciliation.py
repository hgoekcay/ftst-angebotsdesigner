"""Read-only bridge from stored bank rows to owner-scoped invoice snapshots.

No confirmation, reservation or payment update. This is not an authoritative
remaining-balance calculation: existing allocations are not persisted yet.
"""
import hashlib
import json
import re

from bank_validation import BankValidationError, _id, preview_allocation


def _source_amount(value):
    # Billomat snapshots may retain harmless extra decimal zeros. Never round.
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2}0*)?', value):
        raise BankValidationError('Quellbetrag fehlt oder ist nicht centgenau.')
    whole, _, fraction = value.partition('.')
    return whole + '.' + (fraction + '00')[:2]


def invoice_snapshot_token(record):
    """Stable relevant-source fingerprint, not authorization or a source lock."""
    relevant = {'fields': record['fields'], 'sha256': record.get('sha256'),
                'reviewed': record['reviewed'], 'source': record['source']}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, allow_nan=False).encode()).hexdigest()


def preview_selected(statements, bookkeeping, *, owner, account, transaction_id, selections):
    """Read selected invoices via BookkeepingStore.get(owner, id), never form balances.

    The service caller must resolve authenticated owner/account permission and
    enabled bookkeeping feature. No routes currently call this helper.
    """
    owner, account, transaction_id = _id(owner), _id(account), _id(transaction_id)
    if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
        raise BankValidationError('Rechnungsauswahl fehlt oder überschreitet das Limit.')
    ids = []
    for item in selections:
        if not isinstance(item, dict) or set(item) != {'invoice_id', 'amount'}:
            raise BankValidationError('Auswahl darf nur Rechnungskennung und Betrag enthalten.')
        ids.append(_id(item['invoice_id']))
    if len(set(ids)) != len(ids):
        raise BankValidationError('Rechnung mehrfach ausgewählt.')
    transaction = statements.get_transaction(owner, account, transaction_id)
    if transaction is None:
        raise BankValidationError('Bankbewegung nicht verfügbar.')
    direction = 'incoming' if transaction['amount'].startswith('-') else 'outgoing'
    rows, revisions = [], []
    for item in selections:
        record = bookkeeping.get(owner, item['invoice_id'])
        if not record or record.get('id') != item['invoice_id']:
            raise BankValidationError('Rechnung nicht verfügbar.')
        fields = record.get('fields', {})
        if (record.get('source', {}).get('provider') != 'billomat'
                or record.get('reviewed') is not True or record.get('issues')
                or record.get('canceled') or fields.get('source_status') not in ('OPEN', 'OVERDUE')):
            raise BankValidationError('Rechnungsquelle ist nicht als geprüfter offener Beleg verwendbar.')
        if fields.get('currency') != 'EUR' or fields.get('source_currency') != 'EUR':
            raise BankValidationError('Rechnungswährung fehlt oder widerspricht EUR.')
        rows.append({'invoice_id': record['id'], 'amount': item['amount'],
                     'open_amount': _source_amount(fields.get('source_open_amount')),
                     'currency': fields['source_currency'], 'direction': fields.get('direction')})
        # Change token for later review; not an authorization token or atomic lock.
        revisions.append({'invoice_id': record['id'], 'snapshot_token': invoice_snapshot_token(record)})
    result = preview_allocation(available_amount=transaction['amount'], direction=direction, allocations=rows)
    return {**result, 'status': 'unconfirmed_source_snapshot', 'read_only': True,
            'confirmation_supported': False, 'statement_digest': transaction['statement_digest'],
            'transaction_id': transaction_id, 'invoice_snapshots': revisions,
            'limitations': ['Lokale Quellstände können veraltet sein.',
                            'Bereits zugeordnete Zahlungen werden noch nicht berücksichtigt.',
                            'Keine Reservierung, Buchung oder Änderung des Zahlungsstatus.']}
