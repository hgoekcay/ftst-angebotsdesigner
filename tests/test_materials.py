from io import BytesIO
import re
import pytest
from PIL import Image
from pypdf import PdfReader
import app as module
from test_persistence import client, isolated_storage
from test_baseline import raw


def company_csrf(client):
    page = client.get('/company')
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def test_profile_photo_and_pdf_persist(client):
    image = BytesIO()
    Image.new('RGB', (100, 50), 'white').save(image, format='PNG')
    image.seek(0)
    response = client.post('/materials', data={'image': (image, 'test.png'), 'title':'Testreferenz', 'description':'Testfoto', 'category':'Rauchmeldeanlage'}, content_type='multipart/form-data')
    assert response.status_code == 302
    key = next(iter(module.offer_store().records('test', 'image')))
    assert client.get('/materials/'+key).status_code == 200
    assert client.post('/company', data={'company':'FTST Testfirma', 'phone':'TEST', 'logo':key, 'csrf':company_csrf(client)}).status_code == 302
    assert client.post('/offer/42/references', data={'images':key}).status_code == 302
    fresh = module.app.test_client()
    assert 'FTST Testfirma' in fresh.get('/company').text
    pdf = PdfReader(BytesIO(fresh.get('/offer/42/pdf').data))
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert 'FTST Testfirma' in text
    assert 'Testreferenz' in text
    assert len(pdf.pages) >= 4
    assert sum(len(page.images) for page in pdf.pages) >= 2


def test_bad_image_and_unknown_selection(client):
    response = client.post('/materials', data={'image': (BytesIO(b'<script>bad</script>'), 'bad.png')}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert client.post('/offer/42/references', data={'images':'../not-owned'}).status_code == 400
    assert client.get('/materials/not-owned').status_code == 404


@pytest.mark.parametrize('token', [None, '', 'forged-token'])
def test_company_rejects_missing_or_forged_csrf_without_mutation(client, token):
    original = {'company': 'Gespeicherte Testfirma', 'iban': 'DE89370400440532013000'}
    module.offer_store().put_record('test', 'profile', 'company', original)
    company_csrf(client)
    submitted = {'company': 'Nicht speichern'}
    if token is not None:
        submitted['csrf'] = token
    assert client.post('/company', data=submitted).status_code == 400
    assert module.offer_store().records('test', 'profile')['company'] == original


@pytest.mark.parametrize('bank_fields, message', [
    ({'iban': 'DE00370400440532013000'}, 'IBAN ist nicht gültig'),
    ({'iban': 'DE8937040044053201300'}, 'IBAN ist nicht gültig'),
    ({'iban': 'no-bank-account'}, 'IBAN ist nicht gültig'),
    ({'bic': 'TEST'}, 'BIC muss aus 8 oder 11'),
    ({'bic': '12345678'}, 'BIC muss aus 8 oder 11'),
    ({'bank_name': 'A' * 501}, 'höchstens 500 Zeichen'),
])
def test_invalid_bank_details_leave_saved_profile_unchanged(client, bank_fields, message):
    original = {'company': 'Gespeicherte Testfirma', 'iban': 'DE89370400440532013000', 'bic': 'COBADEFFXXX'}
    module.offer_store().put_record('test', 'profile', 'company', original)
    submitted = dict(original, company='Nicht speichern', csrf=company_csrf(client), **bank_fields)
    response = client.post('/company', data=submitted)
    assert response.status_code == 400
    assert message in response.text
    assert 'Nicht speichern' in response.text
    assert module.offer_store().records('test', 'profile')['company'] == original


def test_company_bank_details_roundtrip_and_footer_on_every_page(client):
    from asset_library import DEFAULT_LOGO
    profile = {'company': 'FTST Testfirma', 'owner': 'Testperson', 'street': 'Testweg 5',
               'city': '12345 Musterstadt', 'phone': '0123 456789', 'email': 'test@example.invalid',
               'website': 'https://example.invalid', 'bank_name': 'Testbank',
               'iban': ' de89 3704 0044 0532 0130 00 ', 'bic': ' cobadeffxxx ', 'logo': DEFAULT_LOGO}
    response = client.post('/company', data=dict(profile, csrf=company_csrf(client)))
    assert response.status_code == 302
    saved = module.offer_store().records('test', 'profile')['company']
    assert saved['iban'] == 'DE89370400440532013000'
    assert saved['bic'] == 'COBADEFFXXX'
    assert saved['owner'] == 'Testperson'
    fresh = module.app.test_client()
    page = fresh.get('/company').text
    assert 'DE89370400440532013000' in page
    assert 'COBADEFFXXX' in page
    pdf = PdfReader(BytesIO(fresh.get('/offer/42/pdf').data))
    assert len(pdf.pages) >= 5
    for page in pdf.pages:
        text = page.extract_text()
        compact = ''.join(text.split())
        for expected in ('FTST Testfirma', 'Testperson', 'Testweg 5', '12345 Musterstadt',
                         'Testbank', 'test@example.invalid', 'DE89370400440532013000', 'COBADEFFXXX'):
            assert ''.join(expected.split()) in compact
