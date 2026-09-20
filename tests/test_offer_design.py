from copy import deepcopy
import pytest
from PIL import Image
from pypdf import PdfReader
import app as module
from test_baseline import raw
from test_persistence import client, isolated_storage


@pytest.fixture
def small_reference(tmp_path):
    path = tmp_path / 'reference.png'
    Image.new('RGB', (60, 80), '#cbd3d8').save(path)
    return {'path': str(path), 'title': 'Testreferenz', 'category': 'Videoüberwachung',
            'kind': 'FTST-Originalfoto', 'description': ''}


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
    folder = store.directory / 'images'
    folder.mkdir()
    for n in range(4):
        Image.new('RGB', (60, 80), (100+n*20, 120, 150)).save(folder / f'photo{n}.png')
        store.put_record('test', 'image', f'photo{n}', {'title':f'Installation {n}', 'category':'Videoüberwachung'})
    client.post('/offer/42/references', data=MultiDict([('images', f'photo{n}') for n in range(4)]))
    from io import BytesIO
    pdf = PdfReader(BytesIO(client.get('/offer/42/pdf').data))
    assert len(pdf.pages) == 6
    page = next(p for p in pdf.pages if 'Installation 0' in p.extract_text())
    assert all(f'Installation {n}' in page.extract_text() for n in range(4))


@pytest.mark.parametrize('count', [0, 1, 2, 3, 4])
def test_up_to_four_mixed_reference_categories_share_one_page(raw, small_reference, count):
    offer = module.apply_source(deepcopy(raw), {})
    categories = ('Alarmanlage', 'Videoüberwachung', 'Zutrittskontrolle', 'Türsprechanlage')
    offer['reference_images'] = [dict(small_reference, title=f'Mischreferenz {n}', category=category)
                                 for n, category in enumerate(categories[:count])]
    pdf = PdfReader(module.make_pdf(offer))
    reference_pages = [page for page in pdf.pages if 'Mischreferenz' in page.extract_text()]
    assert len(reference_pages) == bool(count)
    assert len(pdf.pages) == 5 + bool(count)
    if count:
        assert all(f'Mischreferenz {n}' in reference_pages[0].extract_text() for n in range(count))


def test_legacy_eight_references_and_long_captions_fit_exactly_one_page(raw, small_reference):
    offer = module.apply_source(deepcopy(raw), {})
    categories = ('Alarmanlage', 'Videoüberwachung', 'Zutrittskontrolle', 'Türsprechanlage')
    offer['reference_images'] = [dict(small_reference,
        title=f'REFERENZ-{n} ' + 'Ausführlicher Titel ' * 200,
        category=categories[n % 4] + ' sehr lange Kategorie' * 100,
        kind='Symbolfoto', place='Musterstadt ' * 100,
        object_type='Gewerbeobjekt ' * 100,
        description='Lange Beschreibung der Sicherheitstechnik. ' * 350 + 'BILD-ENDE')
        for n in range(8)]
    # Unselected legacy entries must not even be opened by the renderer.
    for reference in offer['reference_images'][4:]:
        reference['path'] = 'does-not-exist.png'
    pdf = PdfReader(module.make_pdf(offer))
    assert len(pdf.pages) == 6
    pages = [page for page in pdf.pages if 'EINBLICKE IN UNSERE ARBEIT' in page.extract_text()]
    assert len(pages) == 1
    text = pages[0].extract_text()
    assert all(f'REFERENZ-{n}' in text for n in range(4))
    assert all(f'REFERENZ-{n}' not in text for n in range(4, 8))
    assert 'BILD-ENDE' not in text
    assert text.count('Symbolfoto') == 4
    assert '...' in text
    assert 'Beratung' in text and 'Einweisung' in text
    operations = pages[0].get_contents().operations
    assert sum(operator == b'Do' for _, operator in operations) == 4
    visible_titles = []
    def visit(text, cm, tm, font_dict, font_size):
        if 'REFERENZ-' in text:
            assert font_size >= 8
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            visible_titles.append((x, y))
    pages[0].extract_text(visitor_text=visit)
    assert len(visible_titles) == 4
    assert abs(visible_titles[0][1] - visible_titles[1][1]) < .1
    assert abs(visible_titles[2][1] - visible_titles[3][1]) < .1
    assert visible_titles[0][1] > visible_titles[2][1]
    assert visible_titles[0][0] < visible_titles[1][0]
    assert min(y for _, y in visible_titles) > 41 * 72 / 25.4


def test_long_footer_fields_stay_complete_inside_footer_region(raw):
    offer = module.apply_source(deepcopy(raw), {})
    offer['company_profile'] = {
        'company': 'Testfirma ' * 40 + 'FIRMA-ENDE',
        'owner': 'Testperson ' * 40 + 'INHABER-ENDE',
        'street': 'Lange Teststrasse ' * 25 + 'STRASSE-ENDE',
        'city': '12345 Musterstadt',
        'phone': '0123 456789',
        'email': 'kontakt@' + 'test.' * 80 + 'EMAIL-ENDE',
        'website': 'https://' + 'example.invalid/' * 25 + 'WEB-ENDE',
        'bank_name': 'Testbank ' * 45 + 'BANK-ENDE',
        'iban': 'DE89370400440532013000',
        'bic': 'COBADEFFXXX',
    }
    pdf = PdfReader(module.make_pdf(offer))
    footer_markers = ('FIRMA-ENDE', 'INHABER-ENDE', 'STRASSE-ENDE', 'EMAIL-ENDE',
                      'WEB-ENDE', 'BANK-ENDE', 'DE89370400440532013000', 'COBADEFFXXX')
    for page in pdf.pages:
        below_footer_rule = []
        def visit(text, cm, tm, font_dict, font_size):
            # PDF text coordinates after the current KeepInFrame scale/translation.
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            if text.strip() and y < 35 * 72 / 25.4:
                below_footer_rule.append(text)
                assert 0 <= x <= float(page.mediabox.width)
                assert y >= 0
        page.extract_text(visitor_text=visit)
        footer_text = ''.join(''.join(below_footer_rule).split())
        for marker in footer_markers:
            assert marker in footer_text


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


def test_reference_caption_stays_short_but_long_contact_can_span_pages(raw, small_reference):
    offer = module.apply_source(deepcopy(raw), {})
    offer['reference_images'] = [dict(small_reference, title='Montageübersicht',
        description=('Ausführliche Beschreibung der Installation. ' * 350) + 'BILD-ENDE')]
    offer['company_profile'] = {'company': 'FT Sicherheitstechnik',
        'contact': ('Kontaktinformationen und Ansprechpartner. ' * 300) + 'KONTAKT-ENDE',
        'email': 'sehr-lange-kontaktadresse@' + 'beispiel.' * 20 + 'de'}
    pdf = PdfReader(module.make_pdf(offer))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'BILD-ENDE' not in text
    assert 'KONTAKT-ENDE' in text
    reference_pages = [page for page in pdf.pages if 'Montageübersicht' in page.extract_text()]
    assert len(reference_pages) == 1
    assert 'Beratung' in reference_pages[0].extract_text()
