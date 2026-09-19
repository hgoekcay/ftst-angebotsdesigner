"""Render a saved quote calculation without fetching or changing any data."""
from datetime import datetime
from decimal import Decimal
from html import escape

from materials import enrich
from asset_library import catalog
from materials import account
from offer_design import build as build_offer
from quote_drafts import display_money


def _customer_name(customer):
    return ' · '.join(filter(None, (
        str(customer.get('name') or '').strip(),
        ' '.join(str(customer.get(k) or '').strip()
                 for k in ('first_name', 'last_name')).strip(),
    ))) or 'Kunde ohne Namensangabe'


def _date(value):
    if not value:
        return 'Nicht festgelegt'
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%d.%m.%Y')
    except ValueError:
        return str(value)


def build(project, draft, result, store):
    """Return BytesIO for a valid saved calculation; callers gate revision/review."""
    if result.get('problems') or not result.get('total') or not result.get('currency'):
        raise ValueError('Nur vollständig kalkulierte Entwürfe können exportiert werden.')
    key = str(project.get('id') or '')
    if not key:
        raise ValueError('Die Projekt-ID fehlt.')
    customer = next((dict(c) for c in draft.get('catalog', {}).get('clients', [])
                     if str(c['id']) == str(draft.get('client_id'))), None)
    if customer is None:
        raise ValueError('Der gespeicherte Kunde fehlt.')
    currency = str(result['currency'])
    reduction = str(result.get('reduction') or '0')
    money = lambda value: display_money(Decimal(str(value or '0'))) + ' ' + currency
    items = []
    for index, line in enumerate(result['lines'], 1):
        detail = (
            f"Artikelnummer: {line.get('article_number') or 'Nicht hinterlegt'}. "
            f"Einzelpreis netto vor Kundenrabatt. Kundenrabatt: {reduction} %. "
            f"Positionssumme netto nach Rabatt: {money(line['net'])}. "
            f"Steuersatz: {line['tax_rate']} %."
        )
        items.append(dict(position=index, title=line.get('title') or 'Artikel',
                          description=detail, quantity=line['quantity'], unit=line['unit'],
                          unit_price=line['price'], total_net=line['net']))
    total = result['total']
    source = (
        f"Billomat-Katalogstand: {draft.get('catalog_at') or 'Nicht hinterlegt'}. "
        f"Kundenpreisgruppe: {result.get('group') or 'Nicht hinterlegt'}. "
        f"Kundenrabatt: {reduction} %. Währung: {currency}. "
        "Einzelpreise sind Nettopreise vor Rabatt; Positionssummen und Gesamtsumme "
        "berücksichtigen den Kundenrabatt. Skonto ist nicht abgezogen. "
        "Die Steuer wird je Position gerundet."
    )
    notes = str(project.get('notes') or '').strip()
    if notes:
        source += '\n\nProjektnotizen: ' + notes
    offer = dict(
        id='project-quote:' + key, is_draft=True, offer_number='', number='',
        catalog_at=draft.get('catalog_at', ''),
        client=customer, customer_title=project.get('title') or 'Angebotsentwurf',
        customer_intro='ANGEBOTSENTWURF - NICHT FREIGEGEBEN. '
                       'Zur internen Prüfung. In Billomat wurde kein Angebot angelegt. '
                       'Eine Angebotsnummer und Gültigkeit sind noch nicht vergeben.',
        project_summary=source, offer_type='Projektkalkulation', items=items,
        total_net=total['net'], tax_amount=total['tax'], total_gross=total['gross'],
        benefits=[], next_steps=[
            'Artikelvarianten, Mengen, Montage, Anfahrt und Zubehör fachlich prüfen.',
            'Kundenangaben, Preis- und Steuerkonditionen abschließend prüfen.',
            'Entwurf separat freigeben und anschließend als Angebot übernehmen.',
        ],
    )
    enrich(offer, store)
    presentation = draft.get('presentation') or {}
    if presentation.get('title'):
        offer['customer_title'] = presentation['title']
    if presentation.get('intro'):
        offer['customer_intro'] += '\n\n' + presentation['intro']
    if presentation.get('summary'):
        offer['project_summary'] = presentation['summary'] + '\n\n' + source
    if 'images' in presentation:
        images = catalog(store, account())
        selected = presentation['images']
        if any(key not in images for key in selected):
            raise ValueError('Ein ausgewähltes Projektbild fehlt. Bitte die Kundendarstellung prüfen und speichern.')
        offer['reference_images'] = [images[key] for key in selected]
    return build_offer(offer, escape, money, _date, _customer_name)
