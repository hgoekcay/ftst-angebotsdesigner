from copy import deepcopy
from pypdf import PdfReader
import app as module
from test_baseline import raw
from test_persistence import client, isolated_storage


def test_many_positions_and_full_description(raw):
    raw['items'] = [dict(raw['items'][0], title=f'Artikel {n}', description='Ausführliche Leistungsbeschreibung. '*30) for n in range(35)]
    raw['items'][-1]['description'] += 'ENDE-DER-LEISTUNG'
    pdf = PdfReader(module.make_pdf(module.apply_source(raw, {})))
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert 'Artikel 34' in text
    assert 'ENDE-DER-LEISTUNG' in text
    assert len(pdf.pages) > 4
    for n, page in enumerate(pdf.pages, 1):
        assert f'{n:02d} / {len(pdf.pages):02d}' in page.extract_text()


def test_four_photos_share_one_reference_page(client):
    from werkzeug.datastructures import MultiDict
    store = module.offer_store()
    from asset_library import catalog
    source = catalog(store, 'test')['builtin-video-entry']
    from PIL import Image
    folder = store.directory / 'images'
    folder.mkdir()
    for n in range(4):
        with Image.open(source['path']) as image:
            image.save(folder / f'photo{n}.png')
        store.put_record('test', 'image', f'photo{n}', {'title':f'Installation {n}', 'category':'Videoüberwachung'})
    client.post('/offer/42/references', data=MultiDict([('images', f'photo{n}') for n in range(4)]))
    from io import BytesIO
    pdf = PdfReader(BytesIO(client.get('/offer/42/pdf').data))
    assert len(pdf.pages) == 5
    page = next(p for p in pdf.pages if 'Installation 0' in p.extract_text())
    assert all(f'Installation {n}' in page.extract_text() for n in range(4))


def test_no_reference_claims_or_payment_promises_from_template(raw):
    pdf = PdfReader(module.make_pdf(module.apply_source(deepcopy(raw), {})))
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert '500+' not in text
    assert '5-7 Werktage' not in text
    assert 'Vorkasse' not in text
