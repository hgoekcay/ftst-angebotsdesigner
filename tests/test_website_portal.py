from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4
import pytest
from storage import OfferStore
from website_portal import snapshot, accepted_configuration, attach, fingerprint, synchronize
from offer_delivery import messages


def offer():
    return dict(id=42, status='OPEN', is_draft=False, date=str(date.today()),
                validity_date=str(date.today() + timedelta(days=30)), title='Sicherheitsprojekt',
                total_net='290.00', total_gross='345.10', client={'first_name': 'Test', 'last_name': 'Kunde'},
                items=[dict(title='Ajax Hub', quantity=1, unit_price='100.00', total_net='100.00'),
                       dict(title='Home Assistant', quantity=1, unit_price='190.00', total_net='190.00')])


def saved():
    original = offer()
    return dict(snapshot=snapshot(original, 1, ['position-1', 'position-2']), original_offer=original)


def response(s):
    return dict(request_id=str(uuid4()), proposal_id=str(uuid4()), kind='approval',
                status='customer_confirmed', document_id=s['snapshot']['document_id'], revision=1,
                confirmed=True, message='', selections=[dict(line_id='position-1', option_id='original', quantity='2'),
                dict(line_id='position-2', option_id='original', quantity='0')],
                preview_totals=dict(net='200.00', tax='38.00', gross='238.00'),
                final_totals=dict(net='200.00', tax='38.00', gross='238.00'), created_at='2026-10-10T10:00:00Z')


def test_snapshot_allowlist_and_effective_discount():
    o = offer()
    o['private_notes'] = 'secret'
    o['items'][0]['unit_price'] = '120.00'
    s = snapshot(o, 1, ['position-1', 'position-2'])
    assert 'private_notes' not in s and 'client' not in s
    assert s['lines'][0]['options'][0]['effective_unit_net'] == '100.00'
    assert s['price_source'] == 'BILLOMAT'
    assert s['lines'][1]['optional_service'] is True


@pytest.mark.parametrize('mutation', ['draft', 'total', 'expired', 'fraction'])
def test_snapshot_rejects_unsafe_source(mutation):
    o = offer()
    if mutation == 'draft': o['is_draft'] = True
    if mutation == 'total': o['total_gross'] = '344.99'
    if mutation == 'expired': o['validity_date'] = '2020-01-01'
    if mutation == 'fraction': o['items'][0]['quantity'] = '1.5'
    with pytest.raises(ValueError): snapshot(o, 1, ['position-1'])


def test_montage_cannot_be_editable():
    o = offer()
    o['items'][0]['title'] = 'Montage und Inbetriebnahme'
    s = snapshot(o, 1, ['position-1'])
    assert not s['lines'][0]['editable']
    assert s['lines'][0]['unit'] == 'Pauschale'


def test_confirmed_changes_become_separate_offer_no_source_mutation():
    s = saved()
    original = deepcopy(s)
    r = response(s)
    r['selections'][0].update(unit_net='0.01', title='untrusted')
    result = accepted_configuration(s, r)
    assert result['totals']['gross'] == '238.00'
    assert len(result['items']) == 1
    assert result['items'][0]['unit_price'] == '100.00'
    assert result['items'][0]['title'] == 'Ajax Hub'
    assert result['status'] == 'customer_confirmed'
    assert s == original


@pytest.mark.parametrize('mutation', ['revision', 'price', 'unknown', 'duplicate', 'state', 'quantity'])
def test_acceptance_rejects_untrusted_response(mutation):
    s = saved(); r = response(s)
    if mutation == 'revision': r['revision'] = 2
    if mutation == 'price': r['final_totals']['gross'] = '0.00'
    if mutation == 'unknown': r['selections'][0]['option_id'] = 'hacked'
    if mutation == 'duplicate': r['selections'][1] = deepcopy(r['selections'][0])
    if mutation == 'state': r['status'] = 'pending_internal_review'
    if mutation == 'quantity': r['selections'][0]['quantity'] = '1000'
    with pytest.raises(ValueError): accepted_configuration(s, r)


def test_link_attached_only_for_same_source_and_messages_both_channels(tmp_path, monkeypatch):
    monkeypatch.setenv('WEBSITE_PORTAL_ENABLED', 'true')
    store = OfferStore(tmp_path); o = offer()
    link = 'https://portal.example/angebot/' + str(uuid4()) + '#' + 'a' * 43
    store.put_record('test', 'website_portal_offer', '42', dict(source_digest=fingerprint(o),
                     link=dict(customer_url=link, expires_at='2099-01-01T00:00:00Z')))
    linked = attach(store, 'test', o)
    _, email, whatsapp = messages(linked)
    assert link in email and link in whatsapp
    o['total_net'] = '291.00'
    assert 'customer_portal_url' not in attach(store, 'test', o)
    assert 'customer_portal_url' not in attach(store, 'other', offer())


def test_sync_idempotent_and_pdf_retry_identical(tmp_path):
    store = OfferStore(tmp_path); s = saved(); r = response(s)
    store.put_record('test', 'website_portal_revision', r['proposal_id'], s)
    class Transport:
        failed = False
        uploads = []
        def responses(self, after):
            return dict(responses=[r] if after == 0 else [], next_cursor=1)
        def publish_final_pdf(self, proposal, key, pdf):
            self.uploads.append(pdf)
            if not self.failed:
                self.failed = True
                raise ValueError('temporary failure')
    transport = Transport()
    calls = []
    def pdf(o):
        calls.append(o)
        return BytesIO(b'%PDF-1.7 original renderer exact bytes')
    with pytest.raises(ValueError): synchronize(store, 'test', pdf, transport)
    assert not store.record('test', 'website_portal_cursor', 'current')
    synchronize(store, 'test', pdf, transport)
    synchronize(store, 'test', pdf, transport)
    assert len(calls) == 1 and transport.uploads[0] == transport.uploads[1]
    assert calls[0]['total_gross'] == '238.00'
    assert store.record('test', 'website_portal_accepted', r['request_id'])['status'] == 'customer_confirmed'
    assert store.record('test', 'website_portal_cursor', 'current') == {'after': 1}


def test_feature_default_disabled():
    import website_portal
    assert not website_portal.configured()


def test_optional_catalog_has_exact_net_prices_and_zero_baseline():
    from website_portal import additional_catalog
    raw = dict(settings=dict(net_gross='NET', currency_code='EUR'), units=[dict(id=1, name='Stück')],
               articles=[dict(id=55, title='Ajax MotionProtect Outdoor weiß', sales_price='123.45', unit_id=1),
                         dict(id=56, title='Ajax DualCurtain Outdoor weiß', sales_price='180.00', unit_id=1),
                         dict(id=57, title='Unbekannte Kamera', sales_price='1.00', unit_id=1)])
    catalog = additional_catalog(raw)
    assert set(catalog) == {'55', '56'}
    s = snapshot(offer(), 1, [], list(catalog.values()))
    assert s['totals']['gross'] == '345.10'
    assert s['lines'][-1]['quantity'] == '0'
    assert s['lines'][-1]['visual_category'] == 'perimeter'
    assert s['lines'][-2]['visual_category'] == 'outdoor_motion'
    assert s['lines'][-2]['options'][0]['effective_unit_net'] == '123.45'
    assert s['lines'][-2]['options'][0]['product_image_id'] == 'ax-motion-protect-outdoor-w'
    raw['settings']['net_gross'] = 'GROSS'
    with pytest.raises(ValueError): additional_catalog(raw)


def test_product_image_does_not_guess_similar_models():
    from website_portal import product_image
    assert product_image('Ajax MotionProtect Outdoor weiß') == 'ax-motion-protect-outdoor-w'
    assert product_image('Ajax MotionCam Outdoor weiß') is None
    assert product_image('Ajax TurretCam 8MP 2.8mm weiß') == 'ax-turretcam-8mp-2.8-w'
    assert product_image('Ajax TurretCam 5MP 4mm weiß') is None
    assert product_image('Ajax MotionProtect Outdoor') is None


def test_flask_publish_requires_csrf_and_freezes_link(tmp_path, monkeypatch):
    import html
    import website_portal
    from flask import Flask
    from offer_mail import csrf
    app = Flask(__name__); app.secret_key = 'test-secret'
    store = OfferStore(tmp_path)
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('WEBSITE_PORTAL_ENABLED', 'true')
    monkeypatch.setenv('WEBSITE_PORTAL_URL', 'https://portal.example')
    monkeypatch.setattr(website_portal, 'read_catalog', lambda: {})
    pid = str(uuid4())
    class Transport:
        published = []
        def publish(self, snapshot, pdf, images):
            self.published.append((snapshot, pdf, images))
            return dict(proposal_id=pid)
        def create_link(self, proposal_id):
            return dict(customer_url='https://portal.example/angebot/' + pid + '#' + 'a' * 43,
                        expires_at='2099-01-01T00:00:00Z', link_id='a' * 64)
    transport = Transport()
    monkeypatch.setattr(website_portal, 'client', lambda: transport)
    website_portal.register(app, lambda title, body: body, lambda path: '/' + path,
                            html.escape, lambda: store, lambda oid: offer(),
                            lambda o: BytesIO(b'%PDF-1.7 exact original'))
    client = app.test_client()
    assert client.post('/offer/42/portal', data={'approved': 'yes'}).status_code == 400
    # Render establishes the helper token inside the client's real session.
    page = client.get('/offer/42/portal')
    import re
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    result = client.post('/offer/42/portal', data=dict(csrf=token, account='test', approved='yes',
                         digest=fingerprint(offer()), editable=['position-1', 'position-2']))
    assert result.status_code == 302
    stored = store.record('test', 'website_portal_offer', '42')
    assert stored['snapshot']['price_source'] == 'BILLOMAT'
    assert transport.published[0][1] == b'%PDF-1.7 exact original'
    assert stored['proposal_id'] == pid
    assert stored['snapshot']['approved_for_customer'] is True


def test_account_namespace_and_hub_required(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'account-a')
    a = snapshot(offer(), 1, ['position-1'])
    monkeypatch.setenv('BILLOMAT_ID', 'account-b')
    b = snapshot(offer(), 1, ['position-1'])
    assert a['document_id'] != b['document_id']
    assert 'account-a' not in a['document_id']
    assert a['lines'][0]['min_quantity'] == 1


def test_home_assistant_hyphen_and_original_picture():
    o = offer()
    o['items'][0]['title'] = 'Ajax Hub 2 (4G) weiß'
    o['items'][1]['title'] = 'Home-Assistant-Anbindung'
    s = snapshot(o, 1, ['position-1', 'position-2'])
    assert s['lines'][0]['options'][0]['product_image_id'] == 'ax-hub-2-4g-w'
    assert s['lines'][1]['visual_category'] == 'service'
    assert s['lines'][1]['optional_service']


def test_real_renderer_matches_final_tax_and_quantities(tmp_path):
    from app import make_pdf
    from website_portal import final_pdf
    from pypdf import PdfReader
    s = saved(); r = response(s)
    accepted = accepted_configuration(s, r)
    path = final_pdf(OfferStore(tmp_path), s, accepted, make_pdf)
    text = '\n'.join(p.extract_text() for p in PdfReader(path).pages)
    assert '238,00' in text and '38,00' in text and '345,10' not in text
    assert '2 × Ajax Hub' in text


def test_all_base_product_images_are_allowlisted():
    from website_portal import product_image
    for title, expected in [('Ajax Hub 2 Plus schwarz', 'ax-hub-2-plus-b'),
                            ('Ajax DoorProtect Plus weiß', 'ax-door-protect-plus-w'),
                            ('Ajax MotionProtect Plus schwarz', 'ax-motion-protect-plus-b'),
                            ('Ajax KeyPad weiß', 'ax-keypad-w'),
                            ('Ajax KeyPad Plus schwarz', 'ax-keypad-plus-b')]:
        assert product_image(title) == expected
