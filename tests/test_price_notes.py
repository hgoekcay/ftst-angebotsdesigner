from io import BytesIO
from copy import deepcopy
from pypdf import PdfReader
import app as module
from price_notes import reduction_label
from test_baseline import raw


def test_optional_and_discount_survive_normalization_and_render(raw, monkeypatch):
    raw['items'][1].update(optional='1', reduction='10%')
    raw.update(reduction='20', total_net='100', total_gross='119')
    normalized = module.apply_source(raw, {})
    assert normalized['items'][1]['optional'] == '1'
    assert normalized['items'][1]['reduction'] == '10%'
    assert normalized['total_net'] == '100'
    monkeypatch.setattr(module, 'get_offer', lambda oid: deepcopy(normalized))
    client = module.app.test_client()
    html = client.get('/offer/42').get_data(as_text=True)
    pdf = PdfReader(BytesIO(client.get('/offer/42/pdf').data))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    for output in (html, text):
        assert 'Optional - nicht im Gesamtpreis enthalten.' in output
        assert 'Positionsrabatt: 10 %' in output
        assert 'Angebotsrabatt: 20 EUR' in output
        assert 'Einzelpreis netto' in output
        assert '119,00' in output


def test_regular_position_not_marked_optional_and_gross_label(raw):
    raw['items'][0].update(optional='0', reduction='0.00')
    raw['net_gross'] = 'GROSS'
    offer = module.apply_source(raw, {})
    with module.app.test_request_context():
        html = module.detail(offer)
    text = '\n'.join(p.extract_text() for p in PdfReader(module.make_pdf(offer)).pages)
    for output in (html, text):
        assert 'Optional -' not in output
        assert 'Positionsrabatt:' not in output
        assert 'Einzelpreis brutto' in output


def test_discount_escaping_and_decimal_semantics(raw):
    assert reduction_label('10') == '10 EUR'
    assert reduction_label('10%') == '10 %'
    assert reduction_label('10.50', 'CHF') == '10,5 CHF'
    assert reduction_label('0%') == ''
    raw['items'][0]['reduction'] = '<script>alert(1)</script>'
    with module.app.test_request_context():
        html = module.detail(module.apply_source(raw, {}))
    assert '<script>' not in html
