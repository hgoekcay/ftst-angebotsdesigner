from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader

import app as module
from storage import RecordConflict
from test_quote_export import exported, draft, catalog, isolated_storage


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
