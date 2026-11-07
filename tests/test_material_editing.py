"""Synthetic regression coverage for saved-photo editing and multipart boundaries."""
import hashlib
import html
import io
import queue
import re
from types import SimpleNamespace

from flask import Flask, request
from PIL import Image
import pytest

import materials
import material_uploads
from storage import OfferStore


TOKEN = 'a' * 32
TOKEN2 = 'b' * 32
CATEGORIES = ('Alarmanlage', 'Videoüberwachung')


def png():
    value = io.BytesIO()
    Image.new('RGB', (14, 12), 'white').save(value, format='PNG')
    return value.getvalue()


def jpeg():
    value = io.BytesIO()
    Image.new('RGB', (14, 12), 'white').save(value, format='JPEG')
    return value.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    store = OfferStore(tmp_path)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'synthetic-material-edit-tests-only'
    monkeypatch.setattr(materials, 'account', lambda: request.headers.get('Account', 'one'))
    monkeypatch.setattr(material_uploads, '_jobs', queue.Queue(maxsize=20))
    monkeypatch.setattr(material_uploads, '_pending', set())
    monkeypatch.setattr(material_uploads, '_worker', SimpleNamespace(is_alive=lambda: True))
    materials.register(app, lambda title, body: body, lambda path='': '/ingress/' + path,
                       html.escape, lambda: store, CATEGORIES)
    folder = store.directory / 'images'
    folder.mkdir(parents=True, exist_ok=True)
    records = {}
    for token, title in ((TOKEN, 'Erstes Foto'), (TOKEN2, 'Zweites Foto')):
        (folder / (token + '.png')).write_bytes(png())
        record = dict(title=title, category='Videoüberwachung', description='Alte Beschreibung ' + title,
                      place='Synthetischer Ort', object_type='Synthetischer Objekttyp')
        store.put_record('one', 'image', token, record)
        records[token] = record
    return SimpleNamespace(app=app, client=app.test_client(), store=store, records=records)


def edit_csrf(library, token=TOKEN):
    response = library.client.get('/materials/' + token + '/edit')
    assert response.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def metadata(csrf, **changes):
    return dict(csrf=csrf, account='one', title='Geprüftes Foto',
                category='Alarmanlage', description='Eigene Beschreibung', **changes)


def test_each_saved_photo_can_be_edited_without_changing_other_photo_or_image_bytes(library):
    path = library.store.directory / 'images' / (TOKEN + '.png')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    original_second = dict(library.records[TOKEN2])
    response = library.client.post('/materials/' + TOKEN + '/edit', data=metadata(edit_csrf(library)))
    assert response.status_code == 302 and response.headers['Location'].endswith('/materials?saved=1')
    saved = library.store.record('one', 'image', TOKEN)
    assert saved['title'] == 'Geprüftes Foto'
    assert saved['description'] == 'Eigene Beschreibung'
    assert saved['category'] == 'Alarmanlage'
    assert saved['place'] == 'Synthetischer Ort'
    assert saved['object_type'] == 'Synthetischer Objekttyp'
    assert library.store.record('one', 'image', TOKEN2) == original_second
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    csrf = edit_csrf(library, TOKEN2)
    values = dict(metadata(csrf), title='Zweite Änderung', description='Andere Beschreibung')
    assert library.client.post('/materials/' + TOKEN2 + '/edit', data=values).status_code == 302
    assert library.store.record('one', 'image', TOKEN)['description'] == 'Eigene Beschreibung'
    assert library.store.record('one', 'image', TOKEN2)['description'] == 'Andere Beschreibung'
    page = library.client.get('/materials').text
    assert TOKEN + '/edit' in page and TOKEN2 + '/edit' in page


@pytest.mark.parametrize('csrf', [None, '', 'forged'])
def test_saved_photo_edit_requires_csrf_without_metadata_changes(library, csrf):
    edit_csrf(library)
    values = metadata(csrf or '')
    if csrf is None:
        values.pop('csrf')
    response = library.client.post('/materials/' + TOKEN + '/edit', data=values)
    assert response.status_code == 400
    assert library.store.record('one', 'image', TOKEN) == library.records[TOKEN]


def test_saved_photo_edit_requires_matching_account_and_rejects_other_account_reads(library):
    csrf = edit_csrf(library)
    values = dict(metadata(csrf), account='two')
    assert library.client.post('/materials/' + TOKEN + '/edit', data=values).status_code == 400
    assert library.client.get('/materials/' + TOKEN + '/edit', headers={'Account': 'two'}).status_code == 404
    response = library.client.post('/materials/' + TOKEN + '/edit',
                                   headers={'Account': 'two'}, data=metadata(csrf))
    assert response.status_code == 404
    assert library.store.record('one', 'image', TOKEN) == library.records[TOKEN]
    assert library.store.record('two', 'image', TOKEN) is None


@pytest.mark.parametrize('changes', [
    {'title': ''}, {'title': '   '}, {'title': 'x' * 201},
    {'description': 'x' * 2001}, {'category': 'Unbekannte Kategorie'},
])
def test_invalid_saved_photo_metadata_is_rejected_without_changes(library, changes):
    values = dict(metadata(edit_csrf(library)), **changes)
    response = library.client.post('/materials/' + TOKEN + '/edit', data=values)
    assert response.status_code == 400
    assert library.store.record('one', 'image', TOKEN) == library.records[TOKEN]


def test_saved_photo_edit_escapes_metadata_and_enforces_builtins_readonly(library):
    record = dict(library.records[TOKEN], title='<script>alert(1)</script>', description='<img src=x onerror=alert(1)>')
    library.store.put_record('one', 'image', TOKEN, record)
    response = library.client.get('/materials/' + TOKEN + '/edit')
    assert response.status_code == 200
    assert '<script>alert(1)</script>' not in response.text
    assert '&lt;script&gt;' in response.text and '&lt;img' in response.text
    assert library.client.get('/materials/builtin-ftst-registered/edit').status_code in (400, 404)
    assert library.client.post('/materials/builtin-ftst-registered/edit',
                               data=metadata(edit_csrf(library))).status_code in (400, 404)
    assert library.store.record('one', 'image', 'builtin-ftst-registered') is None


def test_missing_image_file_cannot_be_edited(library):
    (library.store.directory / 'images' / (TOKEN + '.png')).unlink()
    assert library.client.get('/materials/' + TOKEN + '/edit').status_code == 404


def test_real_material_registration_reserves_multipart_overhead_for_twelve_mib_file(library):
    # The actual registration, not an overridden fixture limit, must permit the
    # file bytes plus multipart headers. JPEG decoders ignore padding after EOI.
    assert library.app.config['MAX_CONTENT_LENGTH'] == 13 * 1024 * 1024
    raw = jpeg()
    payload = raw + b'\0' * (12 * 1024 * 1024 - len(raw))
    token = 'e' * 32
    response = library.client.post('/materials/batch/prepare',
                                   data={'token': token, 'image': (io.BytesIO(payload), 'boundary.jpg')})
    assert response.status_code == 202
    assert library.store.record('one', 'image_upload', token)['status'] == 'queued'
    assert library.store.record('one', 'image', token) is None


def test_file_limit_stays_twelve_mib_even_with_larger_request_budget(library):
    raw = jpeg()
    payload = raw + b'\0' * (12 * 1024 * 1024 + 1 - len(raw))
    token = 'f' * 32
    response = library.client.post('/materials/batch/prepare',
                                   data={'token': token, 'image': (io.BytesIO(payload), 'oversized.jpg')})
    assert response.status_code == 413 and response.is_json
    assert '12 MB' in response.json['error']
    assert library.store.record('one', 'image_upload', token) is None
    assert not (library.store.directory / 'images' / (token + '.png')).exists()
