from io import BytesIO
from pathlib import Path
import base64
import re
from xml.etree import ElementTree

from PIL import Image
from pypdf import PdfReader

import app as module
import materials
from asset_library import ASSETS, ROOT, catalog, DEFAULT_LOGO
from test_baseline import raw
from test_persistence import client, isolated_storage


def test_packaged_originals_and_ingress(client):
    assert len(ASSETS) == 13
    for _, filename, *_ in ASSETS:
        with Image.open(ROOT / filename) as image:
            image.verify()
    images = catalog(module.offer_store(), 'test')
    assert len(images) == 13
    for key in images:
        response = client.get('/materials/' + key)
        assert response.status_code == 200
        assert response.mimetype in ('image/jpeg', 'image/png', 'image/svg+xml')
    page = client.get('/offer/42/references', headers={'X-Ingress-Path': '/ingress/test'}).text
    assert '/ingress/test/materials/builtin-access-card' in page
    assert 'builtin-ftronics' not in page
    assert 'KI-generiert' not in page


def test_logo_default_and_explicit_disable_survive_restart(client):
    store = module.offer_store()
    offer = materials.enrich({'id': '42'}, store)
    assert Path(offer['logo_path']).is_file()
    assert offer['logo_crop'] == (40, 230, 945, 180)
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get('/company').text).group(1)
    assert client.post('/company', data={'logo': '', 'csrf': csrf}).status_code == 302
    disabled = materials.enrich(offer, module.offer_store())
    assert 'logo_path' not in disabled
    assert 'logo_crop' not in disabled
    assert client.post('/company', data={'logo': DEFAULT_LOGO, 'csrf': csrf}).status_code == 302
    restored = materials.enrich({'id': '42'}, module.offer_store())
    assert 'logo_path' in restored
    assert restored['logo_crop'] == (40, 230, 945, 180)


def test_registered_logo_svg_embeds_unchanged_original_and_clips_ft_wordmark(client):
    response = client.get('/materials/' + DEFAULT_LOGO)
    assert response.mimetype == 'image/svg+xml'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    svg = ElementTree.fromstring(response.data)
    assert svg.attrib['viewBox'] == '40 230 945 180'
    assert svg.attrib['width'] == '945'
    assert svg.attrib['height'] == '180'
    image = svg.find('{http://www.w3.org/2000/svg}image')
    assert image is not None
    assert image.attrib['width'] == image.attrib['height'] == '1000'
    source = catalog(module.offer_store(), 'test')[DEFAULT_LOGO]
    assert base64.b64decode(image.attrib['href'].split(',', 1)[1]) == Path(source['path']).read_bytes()
    page = client.get('/', headers={'X-Ingress-Path': '/ingress/test'}).text
    assert '/ingress/test/materials/' + DEFAULT_LOGO in page
    assert 'alt="FT Sicherheitstechnik ®"' in page


def test_explicit_legacy_logo_does_not_receive_registered_crop(client):
    module.offer_store().put_record('test', 'profile', 'company', {'logo': 'builtin-ftst-wide'})
    offer = materials.enrich({'id': '42', 'logo_crop': (40, 230, 945, 180)}, module.offer_store())
    assert Path(offer['logo_path']).name == 'FT SICHERHEITSTECHNIK - Logo.jpg'
    assert 'logo_crop' not in offer


def test_builtin_selection_persists_and_pdf_labels_stock(client):
    assert client.post('/offer/42/references', data={'images': 'builtin-access-card'}).status_code == 302
    fresh = module.app.test_client()
    assert 'value="builtin-access-card" checked' in fresh.get('/offer/42/references').text
    pdf = PdfReader(BytesIO(fresh.get('/offer/42/pdf').data))
    assert any('Symbolfoto' in page.extract_text() for page in pdf.pages)
    assert len(pdf.pages[0].images) >= 1
    assert any(len(page.images) >= 2 for page in pdf.pages[1:])
    assert client.post('/offer/42/references', data={}).status_code == 302
    assert materials.enrich({'id': '42'}, module.offer_store())['reference_images'] == []


def test_missing_bundle_file_is_skipped(client, monkeypatch, tmp_path):
    import asset_library
    monkeypatch.setattr(asset_library, 'ROOT', tmp_path)
    assert client.get('/materials/' + DEFAULT_LOGO).status_code == 404
    assert 'logo_path' not in materials.enrich({'id': '42'}, module.offer_store())
    assert client.get('/offer/42/pdf').status_code == 200


def test_account_uploads_are_not_shared(client, monkeypatch):
    image = BytesIO()
    Image.new('RGB', (20, 20)).save(image, format='PNG')
    image.seek(0)
    client.post('/materials', data={'image': (image, 'private.png'), 'title': 'Privates Foto'})
    key = next(iter(module.offer_store().records('test', 'image')))
    monkeypatch.setenv('BILLOMAT_ID', 'another-account')
    assert client.get('/materials/' + key).status_code == 404
    assert client.get('/materials/' + DEFAULT_LOGO).status_code == 200
