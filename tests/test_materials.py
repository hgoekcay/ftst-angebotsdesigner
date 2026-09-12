from io import BytesIO
from PIL import Image
from pypdf import PdfReader
import app as module
from test_persistence import client, isolated_storage
from test_baseline import raw


def test_profile_photo_and_pdf_persist(client):
    image = BytesIO()
    Image.new('RGB', (100, 50), 'white').save(image, format='PNG')
    image.seek(0)
    response = client.post('/materials', data={'image': (image, 'test.png'), 'title':'Testreferenz', 'description':'Testfoto', 'category':'Rauchmeldeanlage'}, content_type='multipart/form-data')
    assert response.status_code == 302
    key = next(iter(module.offer_store().records('test', 'image')))
    assert client.get('/materials/'+key).status_code == 200
    assert client.post('/company', data={'company':'FTST Testfirma', 'phone':'TEST', 'logo':key}).status_code == 302
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
