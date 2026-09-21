from io import BytesIO
from copy import deepcopy
import pytest
from pypdf import PdfReader
import app as module
from quote_drafts import fingerprint
from test_quote_drafts import catalog, draft
from test_persistence import isolated_storage


@pytest.fixture
def exported(monkeypatch, draft):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    project = {'title': 'Kalkulationsprüfung', 'notes': '1 Hub + 11 FireProtect'}
    draft.update(revision='v1', source=fingerprint(project), reviewed=True, catalog_at='2026-09-13T12:00:00+00:00')
    store = module.offer_store()
    store.put_record('test', 'project', 'one', project)
    store.put_record('test', 'quote', 'one', draft)
    return module.app.test_client(), store, project, draft


def add_reference_images(store, count=8):
    """Tiny distinct test images avoid copying full-size customer photographs."""
    from PIL import Image
    folder = store.directory / 'images'
    folder.mkdir(exist_ok=True)
    categories = ('Alarmanlage', 'Videoüberwachung', 'Zutrittskontrolle', 'Türsprechanlage')
    ids = []
    for index in range(count):
        key = f'ref-{index}'
        Image.new('RGB', (12, 8), (index * 30, 10, 200)).save(folder / (key + '.png'))
        store.put_record('test', 'image', key, {
            'title': f'Referenzbild Nummer {index}', 'category': categories[index % len(categories)]})
        ids.append(key)
    return ids


def test_saved_quote_pdf_matches_discount_totals_and_draft_status(exported):
    client, store, project, draft = exported
    before = deepcopy(store.records('test', 'quote'))
    response = client.get('/projects/one/quote/pdf?revision=v1')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    pdf = PdfReader(BytesIO(response.data))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert all('NICHT FREIGEGEBEN' in page.extract_text() for page in pdf.pages)
    assert '203,49' in text and '171,00' in text and '32,49' in text
    assert 'Testkunde' in text and 'FireProtect RB' in text
    assert '10' in text and 'Rabatt' in text
    assert 'FESTPREIS' not in text and 'project-quote:' not in text
    assert store.records('test', 'quote') == before
    page = client.get('/projects/one/quote', headers={'X-Ingress-Path': '/ingress'}).text
    assert '/ingress/projects/one/quote/pdf?revision=v1' in page
    # PDFs use the authenticated in-app download, not a new browser session.
    assert 'data-pdf="FTST-Angebotsentwurf.pdf"' in page


@pytest.mark.parametrize('change', ['unreviewed', 'stale', 'invalid', 'revision'])
def test_export_blocks_incomplete_or_changed_data(exported, change):
    client, store, project, draft = exported
    if change == 'unreviewed':
        draft['reviewed'] = False
    elif change == 'invalid':
        draft['rows'][0]['article_id'] = 'missing'
    elif change == 'revision':
        draft['revision'] = 'v2'
    else:
        project['notes'] = '12 FireProtect'
        store.put_record('test', 'project', 'one', project)
    store.put_record('test', 'quote', 'one', draft)
    assert client.get('/projects/one/quote/pdf?revision=v1').status_code == 409


def test_export_rejects_cross_account_and_missing_revision(exported, monkeypatch):
    client, *_ = exported
    assert client.get('/projects/one/quote/pdf').status_code == 409
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    assert client.get('/projects/one/quote/pdf?revision=v1').status_code == 404


def test_concurrent_edit_during_export_is_rejected(exported, monkeypatch):
    client, store, project, draft = exported
    import quote_export
    original = quote_export.build
    def concurrent(*args):
        result = original(*args)
        store.put_record('test', 'quote', 'one', dict(draft, revision='v2'))
        return result
    monkeypatch.setattr(quote_export, 'build', concurrent)
    assert client.get('/projects/one/quote/pdf?revision=v1').status_code == 409


def test_export_currency_is_not_assumed_eur(exported):
    client, store, project, draft = exported
    draft['catalog']['settings']['currency_code'] = 'CHF'
    for article in draft['catalog']['articles']:
        article['currency_code'] = 'CHF'
    store.put_record('test', 'quote', 'one', draft)
    pdf = PdfReader(BytesIO(client.get('/projects/one/quote/pdf?revision=v1').data))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'CHF' in text and 'EUR' not in text and '€' not in text


def test_legacy_project_images_render_first_four_valid_unique_ids_on_one_page(exported):
    client, store, project, draft = exported
    ids = add_reference_images(store)
    selected = ['unavailable', ids[4], ids[4], ids[3], ids[2], ids[1], ids[0], ids[7]]
    draft['presentation'] = {'images': selected}
    store.put_record('test', 'quote', 'one', draft)
    before = deepcopy(store.record('test', 'quote', 'one'))
    response = client.get('/projects/one/quote/pdf?revision=v1')
    assert response.status_code == 200
    pdf = PdfReader(BytesIO(response.data))
    reference_pages = [page for page in pdf.pages if 'Referenzbild Nummer' in page.extract_text()]
    assert len(reference_pages) == 1
    text = reference_pages[0].extract_text()
    for index in (4, 3, 2, 1):
        assert f'Referenzbild Nummer {index}' in text
    for index in (0, 5, 6, 7):
        assert f'Referenzbild Nummer {index}' not in text
    assert store.record('test', 'quote', 'one') == before
    assert draft['presentation']['images'] == selected


@pytest.mark.parametrize('selected', [[], ['missing'], ['builtin-ftst-wide']])
def test_project_export_with_no_valid_reference_omits_empty_reference_page(exported, selected):
    client, store, project, draft = exported
    draft['presentation'] = {'images': selected}
    store.put_record('test', 'quote', 'one', draft)
    response = client.get('/projects/one/quote/pdf?revision=v1')
    assert response.status_code == 200
    pdf = PdfReader(BytesIO(response.data))
    assert all('EINBLICKE IN UNSERE ARBEIT' not in page.extract_text() for page in pdf.pages)
