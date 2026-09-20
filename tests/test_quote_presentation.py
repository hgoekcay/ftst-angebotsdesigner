from copy import deepcopy
from io import BytesIO
import re

import pytest
from PIL import Image
from pypdf import PdfReader

import app as module
from storage import RecordConflict
from test_quote_export import exported, draft, catalog, isolated_storage, add_reference_images


@pytest.fixture
def presentation_client(exported):
    client, store, project, quote = exported
    # Production app registration is supplied by app.py.
    folder = store.directory / 'images'
    folder.mkdir(exist_ok=True)
    Image.new('RGB', (12, 8), 'red').save(folder / 'small.png')
    store.put_record('test', 'image', 'small', {
        'title': 'Fiktive Montageaufnahme', 'category': 'Videoüberwachung'})
    return client, store, project, quote


def payload(**kwargs):
    return dict(revision='v1', title='Individuelle Sicherheitslösung',
                intro='Einleitung für den Kunden.', summary='Projektbeschreibung für das Objekt.',
                images='small', **kwargs)


def test_saved_presentation_pdf_and_revision(presentation_client):
    client, store, project, quote = presentation_client
    before = deepcopy(quote)
    response = client.post('/projects/one/quote/presentation', data=payload())
    assert response.status_code == 302
    saved = store.record('test', 'quote', 'one')
    assert saved['revision'] != 'v1'
    assert saved['rows'] == before['rows'] and saved['reviewed'] == before['reviewed']
    assert saved['catalog'] == before['catalog']
    assert client.get('/projects/one/quote/pdf?revision=v1').status_code == 409
    pdf = PdfReader(BytesIO(client.get('/projects/one/quote/pdf?revision=' + saved['revision']).data))
    text = ' '.join(' '.join(p.extract_text() for p in pdf.pages).split())
    for value in ('Individuelle Sicherheitslösung', 'Einleitung für den Kunden.',
                  'Projektbeschreibung für das Objekt.', 'Fiktive Montageaufnahme', '203,49'):
        assert value in text
    assert all('NICHT FREIGEGEBEN' in p.extract_text() for p in pdf.pages)
    page = client.get('/projects/one/quote/presentation').text
    assert 'Fiktive Montageaufnahme' in page and 'value="small" checked' in page


@pytest.mark.parametrize('change', ['stale', 'missing', 'unknown_image', 'long_title', 'too_many'])
def test_invalid_submission_does_not_write(presentation_client, change):
    client, store, *_ = presentation_client
    data = payload()
    if change == 'stale':
        data['revision'] = 'old'
    elif change == 'missing':
        data.pop('revision')
    elif change == 'unknown_image':
        data['images'] = 'unavailable'
    elif change == 'long_title':
        data['title'] = 'x' * 241
    else:
        data['images'] = [str(n) for n in range(9)]
    before = store.record('test', 'quote', 'one')
    assert client.post('/projects/one/quote/presentation', data=data).status_code in (400, 409)
    assert store.record('test', 'quote', 'one') == before


def test_concurrent_edit_is_not_overwritten(presentation_client, monkeypatch):
    client, store, *_ = presentation_client
    def conflict(*args):
        raise RecordConflict('Bitte neu laden.')
    monkeypatch.setattr(type(store), 'put_revision', conflict)
    assert client.post('/projects/one/quote/presentation', data=payload()).status_code == 409
    assert store.record('test', 'quote', 'one')['revision'] == 'v1'


def test_clear_images_and_escape_text(presentation_client):
    client, store, *_ = presentation_client
    data = payload()
    data.update(title='<script>alert(1)</script>', images=[])
    assert client.post('/projects/one/quote/presentation', data=data).status_code == 302
    saved = store.record('test', 'quote', 'one')
    assert saved['presentation']['images'] == []
    page = client.get('/projects/one/quote/presentation').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert '<script>alert(1)</script>' not in page


def test_cross_account_and_missing_project(presentation_client, monkeypatch):
    client, *_ = presentation_client
    assert client.get('/projects/missing/quote/presentation').status_code == 404
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    assert client.get('/projects/one/quote/presentation').status_code == 404
    assert client.post('/projects/one/quote/presentation', data=payload()).status_code == 404


@pytest.mark.parametrize('count', [5, 8])
def test_more_than_four_valid_project_images_are_rejected_without_changing_selection(presentation_client, count):
    client, store, project, quote = presentation_client
    ids = add_reference_images(store)
    quote['presentation'] = {'title': 'Gespeicherte Darstellung', 'images': ['small']}
    store.put_record('test', 'quote', 'one', quote)
    before = deepcopy(store.record('test', 'quote', 'one'))
    data = payload()
    data['images'] = ids[:count]
    response = client.post('/projects/one/quote/presentation', data=data)
    assert response.status_code == 400
    assert 'Höchstens vier' in response.text
    assert store.record('test', 'quote', 'one') == before


def test_four_valid_project_images_save_and_duplicate_ids_do_not_add_images(presentation_client):
    client, store, *_ = presentation_client
    ids = add_reference_images(store)
    data = payload()
    data['images'] = ids[:4] + [ids[0]]
    assert client.post('/projects/one/quote/presentation', data=data).status_code == 302
    assert store.record('test', 'quote', 'one')['presentation']['images'] == ids[:4]
    page = client.get('/projects/one/quote/presentation').text
    assert 'Maximal vier Bilder gemeinsam auf einer Referenzseite' in page
    assert 'Maximal acht' not in page
    assert 'id="project-reference-count" aria-live="polite">4</span> von 4' in page


def test_legacy_project_image_selection_is_capped_for_display_without_writing(presentation_client):
    client, store, project, quote = presentation_client
    ids = add_reference_images(store)
    quote['presentation'] = {'images': ['unavailable', ids[7], ids[7], *ids]}
    store.put_record('test', 'quote', 'one', quote)
    before = deepcopy(store.record('test', 'quote', 'one'))
    page = client.get('/projects/one/quote/presentation').text
    checked = re.findall(r'name="images" value="([^"]+)" checked', page)
    assert set(checked) == {ids[7], ids[0], ids[1], ids[2]}
    assert len(checked) == 4
    assert 'ersten vier verfügbaren Bilder' in page
    assert 'nicht mehr verfügbar' in page
    assert store.record('test', 'quote', 'one') == before
