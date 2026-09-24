from offer_delivery import panel
from test_baseline import raw
from test_persistence import client, isolated_storage


def test_contacts_are_prefilled_and_escaped():
    html = panel({'id': 42, 'client': {'email': 'test@example.org', 'mobile': '+49 171 1234567', 'phone': 'other'},
                  'offer_number': '<script>alert(1)</script>'}, lambda path: '/ingress/' + path)
    assert 'value="test@example.org"' in html
    assert 'value="+49 171 1234567"' in html
    assert '<script>alert' not in html
    assert 'data-pdf-url="/ingress/offer/42/pdf"' in html
    assert 'Per E-Mail versenden' in html and 'Per WhatsApp versenden' in html


def test_drafts_cannot_be_shared():
    assert panel({'is_draft': True}, lambda path: path) == ''


def test_missing_contacts_are_editable():
    html = panel({'id': 1}, lambda path: '/' + path)
    assert 'type="email"' in html and 'type="tel"' in html
    assert 'value=""' in html


def test_delivery_panel_on_offer_route(client):
    response = client.get('/offer/42', headers={'X-Ingress-Path': '/api/hassio_ingress/test'})
    assert response.status_code == 200
    assert b'/api/hassio_ingress/test/static/offer-delivery.js' in response.data
    assert b'/api/hassio_ingress/test/offer/42/pdf' in response.data
