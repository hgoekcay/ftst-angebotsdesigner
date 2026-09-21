from copy import deepcopy
from io import BytesIO

from pypdf import PdfReader

from test_persistence import isolated_storage
from test_project_intake import ui, fields, PATH, HEADERS


def test_confirmed_intake_opens_quote_even_without_customer_and_keeps_existing_draft(ui):
    client, store, model, _ = ui
    old = dict(rows=[dict(description='Manuell', quantity='3', article_id='42')],
               revision='old', source='older', client_id='customer')
    store.put_record('one', 'quote', 'job-1', old)
    values = fields(client, action='apply', reviewed='yes', customer_name='', object_address='',
                    description=['Bewegungsmelder'], quantity=['6'], evidence=['Geprüft'])
    response = client.post(PATH, data=values, headers=HEADERS)
    assert response.status_code == 303
    assert response.headers['Location'].endswith('/projects/job-1/quote?intake_applied=1')
    assert store.record('one', 'quote', 'job-1') == old
    page = client.get('/projects/job-1/quote')
    assert page.status_code == 200
    assert 'bisherige Kalkulation bleibt erhalten' in page.text
    assert 'Billomat-Kunden auswählen' in page.text
    model.assert_not_called()


def test_save_does_not_confirm_or_redirect_to_quote(ui):
    client, store, model, original = ui
    response = client.post(PATH, data=fields(client, action='upload', customer_name='Neuer Kunde',
                           description=['BM'], quantity=['6'], evidence=['Foto']))
    assert response.status_code == 303
    assert '/intake?saved=1' in response.headers['Location']
    assert store.record('one', 'project', 'job-1') == original
    assert store.record('one', 'quote', 'job-1') is None
    page = client.get(response.headers['Location'])
    assert 'Aufnahme gespeichert. Noch kein Angebot erstellt.' in page.text
    assert 'Nächster Schritt: Komponenten prüfen' in page.text


def test_handoff_displays_customer_safely_without_selecting_billomat_client(ui):
    client, store, model, p = ui
    p = deepcopy(p)
    p['customer_name'] = '<script>bad()</script>'
    store.put_record('one', 'project', 'job-1', p)
    response = client.get('/projects/job-1/quote')
    assert '&lt;script&gt;bad()&lt;/script&gt;' in response.text
    assert '<script>bad()</script>' not in response.text
    assert store.record('one', 'quote', 'job-1') is None
    model.assert_not_called()


def test_template_is_interactive_two_page_pdf_linked_through_download_handler(ui):
    client, store, model, _ = ui
    page = client.get(PATH, headers=HEADERS)
    assert 'data-pdf="FTST-Technikeraufnahme-Ajax.pdf"' in page.text
    response = client.get('/static/FTST-Technikeraufnahme-Ajax.pdf')
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    pdf = PdfReader(BytesIO(response.data))
    assert len(pdf.pages) == 2
    assert len(pdf.get_fields()) == 70
    assert 'objektadresse' in pdf.get_fields()
    assert 'position_1_menge' in pdf.get_fields()
