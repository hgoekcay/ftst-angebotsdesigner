"""Full local intake-to-PDF check; catalog is synthetic, external writes forbidden."""
from copy import deepcopy
from io import BytesIO

import app as module
import offer_chat
import offer_chat_ai
import pytest
from pypdf import PdfReader
from test_offer_chat import chat, send  # noqa: F401
from test_persistence import isolated_storage  # noqa: F401
from test_quote_drafts import catalog  # noqa: F401

real_extract = offer_chat_ai.extract


def test_ajax_intake_selection_review_pdf_without_external_writes(chat, monkeypatch):
    client, key, _, _ = chat
    monkeypatch.setattr(offer_chat_ai, 'extract', real_extract)
    monkeypatch.setattr(offer_chat_ai, 'request_local', lambda *a, **kw: pytest.fail('Compact intake needs no model'))
    monkeypatch.setattr(offer_chat.quote_transfer, 'api', lambda: pytest.fail('No external writes during audit'))
    prices = [100, 40, 120, 180, 250, 80]
    names = ['Ajax Bewegungsmelder', 'Ajax Türkontakt', 'Ajax Außensirene',
             'Ajax Außenbedienteil', 'Ajax Hub', 'Technikerstunde']
    catalog = dict(
        articles=[dict(id=str(i), title=name, sales_price=str(price),
                       currency_code='EUR', tax_id='1', unit_id='1')
                  for i, (name, price) in enumerate(zip(names, prices), 1)],
        clients=[dict(id='test-client', name='Testkunde Ablaufprüfung', price_group='1',
                      reduction='0', net_gross='NET', tax_rule='TAX', currency_code='EUR')],
        taxes=[dict(id='1', rate='19')], units=[dict(id='1', name='Stück')],
        settings=dict(net_gross='NET', currency_code='EUR'))
    monkeypatch.setattr(offer_chat, 'load_catalog', lambda *a, **kw: dict(data=deepcopy(catalog), at='2026-10-06'))
    note = ('erstelle ein angebot für Testkunde Ablaufprüfung Beispielstraße 10, 12345 Beispielstadt\n'
            '6x Bewegungsmelder 2x Türkontakt 1x Sirene 1x Außenbedienteil 1x Zentrale 3h Arbeit')
    assert send(chat, message=note).status_code == 303
    store = module.offer_store()
    draft = store.record('test', 'quote', key)
    assert [float(r['quantity']) for r in draft['rows']] == [6, 2, 1, 1, 1, 3]
    assert send(chat, message='Die Sirene ist für außen. Mit Zentrale meine ich einen Ajax Hub. '
                'Das Land ist Deutschland. Die E-Mail ist test@example.com.').status_code == 303
    state = store.record('test', 'offer_chat', key)['state']
    assert not state['questions']
    assert state['rows'][2]['description'] == 'Ajax Außensirene'
    assert state['rows'][4]['description'] == 'Ajax Hub'
    assert state['recipient'] == 'test@example.com' and state['country_code'] == 'DE'
    assert send(chat, 'select', client_id='test-client',
                article_id=[str(i) for i in range(1, 7)], quantity=['6', '2', '1', '1', '1', '3']).status_code == 303
    draft = store.record('test', 'quote', key)
    assert offer_chat.quotes.calculate(draft)['total'] == dict(net='1470.00', tax='279.30', gross='1749.30')
    assert send(chat, 'review', confirm='yes').status_code == 303
    assert store.record('test', 'quote', key)['reviewed'] is True
    current = store.record('test', 'offer_chat', key)
    response = client.get('/chat/' + key + '/pdf?revision=' + current['revision'])
    assert response.status_code == 200
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.data)).pages)
    assert 'Testkunde Ablaufprüfung' in text and '1.749,30' in text
    assert all(name in text for name in names)
    assert store.record('test', 'quote_transfer', key) is None
    page = client.get('/chat/' + key).text
    assert 'Geprüften Entwurf in Billomat anlegen' in page
    assert 'E-Mail mit PDF vorbereiten' not in page
