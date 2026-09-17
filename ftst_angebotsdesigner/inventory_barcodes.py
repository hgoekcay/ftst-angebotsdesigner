"""Explicit product/pack mappings; codes are case-sensitive opaque strings."""
import re
from decimal import Decimal

from inventory import InventoryError, quantity


def code_value(value):
    if not isinstance(value, str):
        raise InventoryError('Barcode muss als Text erfasst werden.')
    value = value.strip()
    if not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', value):
        raise InventoryError('Nur einfache Produktcodes. GS1-Verbundcodes, URLs und Seriennummern hier nicht zuordnen.')
    return value


def resolve(state, raw):
    code = code_value(raw)
    matches = [m for m in state['barcodes'].values() if m['code'] == code]
    if len(matches) != 1:
        raise InventoryError('Barcode unbekannt oder mehrdeutig. Produktzuordnung zuerst prüfen.')
    return matches[0]


def issue_payload(state, form):
    mapping = resolve(state, form.get('code'))
    if str(mapping['revision']) != str(form.get('mapping_revision')):
        raise InventoryError('Barcodezuordnung geändert. Neu scannen und prüfen.')
    article = state['articles'][mapping['article']]
    entered = quantity(form.get('scan_quantity'), 'Stück' if mapping['kind'] == 'pack' else article['unit'])
    base = Decimal(entered) * Decimal(mapping['factor']) / Decimal(1000000)
    quantity(str(base), article['unit'])
    return dict(article=mapping['article'], order=str(form.get('order', '')), quantity=str(base),
                barcode=mapping['code'], mapping_revision=mapping['revision'],
                scan_quantity=str(form.get('scan_quantity', '')).strip(), factor=mapping['factor'],
                warehouse='main', note=str(form.get('note', ''))[:300])


def check_issue(state, payload):
    mapping = resolve(state, payload['barcode'])
    article = state['articles'][mapping['article']]
    entered = quantity(payload.get('scan_quantity'), 'Stück' if mapping['kind'] == 'pack' else article['unit'])
    expected = Decimal(entered) * Decimal(mapping['factor']) / Decimal(1000)
    if (payload.get('article') != mapping['article'] or payload.get('mapping_revision') != mapping['revision']
            or payload.get('factor') != mapping['factor'] or payload.get('warehouse') != 'main'
            or quantity(payload.get('quantity'), article['unit']) != expected):
        raise InventoryError('Barcode, Verpackung und Entnahmemenge stimmen nicht überein. Neu prüfen.')
