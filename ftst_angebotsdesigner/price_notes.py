"""Explain Billomat pricing without recalculating or changing source amounts."""
from decimal import Decimal, InvalidOperation


def reduction_label(value, currency='EUR'):
    text = str(value or '').strip()
    percent = text.endswith('%')
    try:
        amount = Decimal(text.rstrip('%').strip())
    except InvalidOperation:
        return text
    if not amount.is_finite() or amount == 0:
        return ''
    number = format(amount, 'f').rstrip('0').rstrip('.') if '.' in format(amount, 'f') else format(amount, 'f')
    return number.replace('.', ',') + (' %' if percent else ' ' + currency)


def item_notes(item, currency='EUR'):
    notes = []
    if str(item.get('optional', '0')).strip().lower() in ('1', 'true'):
        notes.append('Optional - nicht im Gesamtpreis enthalten.')
    reduction = reduction_label(item.get('reduction'), currency)
    if reduction:
        notes.append('Positionsrabatt: ' + reduction + '. Im Positionsbetrag berücksichtigt.')
    return notes


def offer_notes(offer):
    if offer.get('is_draft'):
        return []
    notes = []
    reduction = reduction_label(offer.get('reduction'), offer.get('currency_code') or 'EUR')
    if reduction:
        notes.append('Angebotsrabatt: ' + reduction + '. In der Gesamtsumme berücksichtigt.')
    if any(str(i.get('optional', '0')).strip().lower() in ('1', 'true') for i in offer.get('items', [])):
        notes.append('Optionale Positionen sind separat ausgewiesen und nicht im Gesamtpreis enthalten.')
    return notes


def unit_price_heading(offer):
    return 'Einzelpreis brutto' if offer.get('net_gross') == 'GROSS' else 'Einzelpreis netto'
