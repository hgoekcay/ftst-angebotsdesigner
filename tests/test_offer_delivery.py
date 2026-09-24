from offer_delivery import panel, messages
from test_baseline import raw
from test_persistence import client, isolated_storage


def test_contacts_are_prefilled_and_escaped():
    html = panel({'id': 42, 'client': {'email': 'test@example.org', 'mobile': '+49 171 1234567', 'phone': 'other'},
                  'offer_number': '<script>alert(1)</script>'}, lambda path: '/ingress/' + path)
    assert 'value="test@example.org"' in html
    assert 'value="+49 171 1234567"' in html
    assert '<script>alert' not in html
    assert 'data-pdf-url="/ingress/offer/42/pdf"' in html
    assert 'PDF für E-Mail vorbereiten' in html and 'PDF für WhatsApp vorbereiten' in html
    assert 'delivery-email-text' in html and 'delivery-whatsapp-text' in html


def test_channel_specific_text_and_supplied_signature():
    subject, email, whatsapp = messages({'id': 42, 'offer_number': '26-141'})
    assert 'Leistungsvorschlag 26-141' in subject
    assert 'DE301351179' in email and '+49 176 329 563 00' in email
    assert 'Hafenbahnstraße 15' in email and 'tidycal.com/ftsicherheit/erstberatung' in email
    assert len(whatsapp) < 200 and len(email) > 800
    assert 'führender Anbieter' not in email and 'garantieren' not in email
    assert 'Leistungsvorschlag 26-141' in whatsapp and 'tidycal' not in whatsapp


def test_drafts_cannot_be_shared():
    assert panel({'is_draft': True}, lambda path: path) == ''


def test_missing_contacts_are_editable():
    html = panel({'id': 1}, lambda path: '/' + path)
    assert 'type="email"' in html and 'type="tel"' in html
    assert 'value=""' in html


def test_delivery_panel_on_offer_route(client):
    response = client.get('/offer/42', headers={'X-Ingress-Path': '/api/hassio_ingress/test'})
    assert response.status_code == 200
    from app import APP_VERSION
    assert f'/api/hassio_ingress/test/ui-assets/{APP_VERSION}/offer-delivery.js'.encode() in response.data
    assert f'/api/hassio_ingress/test/ui-assets/{APP_VERSION}/pdf-download.js'.encode() in response.data
    assert b'/api/hassio_ingress/test/offer/42/pdf' in response.data


def test_customer_pdf_uses_leistungsvorschlag(client):
    from io import BytesIO
    from pypdf import PdfReader
    response = client.get('/offer/42/pdf')
    assert 'FTST-Leistungsvorschlag-42.pdf' in response.headers['Content-Disposition']
    pdf = PdfReader(BytesIO(response.data))
    assert 'Leistungsvorschlag' in pdf.metadata.title
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'LEISTUNGSVORSCHLAG' in text
    assert 'IHR PERSÖNLICHES ANGEBOT' not in text


def test_versioned_asset_delivers_current_code_without_cache(client):
    from app import APP_VERSION
    response = client.get(f'/ui-assets/{APP_VERSION}/offer-delivery.js')
    assert response.status_code == 200
    assert b'#delivery-whatsapp-text' in response.data
    assert b"querySelector('#delivery-text')" not in response.data
    assert 'no-store' in response.headers['Cache-Control']
    assert client.get('/ui-assets/old/offer-delivery.js').status_code == 404
    assert client.get(f'/ui-assets/{APP_VERSION}/app.py').status_code == 404
