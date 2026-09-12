from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader
import app as module


@pytest.fixture
def raw():
    return {'id': '42', 'offer_number': 'TEST-42', 'title': 'Sicherheit',
            'date': '2026-09-12', 'client': {'first_name': 'Test', 'last_name': 'Kunde'},
            'total_net': '1000', 'total_gross': '1190', 'taxes': {'tax': {'amount': '190'}},
            'items': [{'title': 'Ajax Hub 2', 'quantity': 1, 'unit_price': 120, 'total_net': 120},
                      {'title': 'FireProtect', 'quantity': 11, 'unit_price': 80, 'total_net': 880}]}


def test_baseline_type_and_pdf(raw):
    offer = module.apply_source(raw, {})
    assert offer['offer_type'] == 'Rauchmeldeanlage'
    pdf = PdfReader(module.make_pdf(offer))
    assert len(pdf.pages) == 3
    assert all(abs(float(p.mediabox.width) - 595.276) < 1 for p in pdf.pages)
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert 'Test Kunde' in text
    assert '1.190,00' in text


def test_baseline_routes(raw, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test-only')
    monkeypatch.setattr(module.BillomatClient, 'get_full_offer', lambda self, oid: deepcopy(raw))
    monkeypatch.setattr(module.BillomatClient, 'list_offers', lambda self, search='': [deepcopy(raw)])
    client = module.app.test_client()
    for url in ['/', '/health', '/offers', '/offer/42', '/offer/42/edit']:
        assert client.get(url).status_code == 200
    response = client.get('/offer/42/pdf')
    assert response.status_code == 200
    assert len(PdfReader(BytesIO(response.data)).pages) == 3
