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


def test_custom_title_suffix_is_preserved(raw):
    offer = module.apply_source(deepcopy(raw), {})
    offer['customer_title'] = 'Sicherheit für Ihr Objekt einschließlich Nebengebäude'
    pdf = PdfReader(module.make_pdf(offer))
    assert 'Nebengebäude' in pdf.pages[0].extract_text()


def test_long_cover_text_uses_content_template_for_overflow(raw):
    offer = module.apply_source(deepcopy(raw), {})
    offer['customer_title'] = 'Individuelle Sicherheitslösung ' * 30
    offer['customer_intro'] = ('Die Planung berücksichtigt die Anforderungen Ihres Objekts. ' * 100) + 'INTRO-ENDE'
    pdf = PdfReader(module.make_pdf(offer))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'INTRO-ENDE' in text
    assert 'IHR PERSÖNLICHES ANGEBOT' not in pdf.pages[1].extract_text()


def test_long_reference_caption_and_contact_can_span_pages(raw, client):
    from asset_library import catalog
    source = catalog(module.offer_store(), 'test')['builtin-video-entry']
    offer = module.apply_source(deepcopy(raw), {})
    offer['reference_images'] = [dict(source, title='Montageübersicht',
        description=('Ausführliche Beschreibung der Installation. ' * 350) + 'BILD-ENDE')]
    offer['company_profile'] = {'company': 'FT Sicherheitstechnik',
        'contact': ('Kontaktinformationen und Ansprechpartner. ' * 300) + 'KONTAKT-ENDE',
        'email': 'sehr-lange-kontaktadresse@' + 'beispiel.' * 20 + 'de'}
    pdf = PdfReader(module.make_pdf(offer))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'BILD-ENDE' in text
    assert 'KONTAKT-ENDE' in text
