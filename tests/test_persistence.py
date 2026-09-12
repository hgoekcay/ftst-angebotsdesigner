from copy import deepcopy
from io import BytesIO
import sqlite3

import pytest
from pypdf import PdfReader
import app as module
from storage import OfferStore, StorageError
from test_baseline import raw


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setitem(module.app.config, 'FTST_DATA_DIR', str(tmp_path))


@pytest.fixture
def client(raw, monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    monkeypatch.setenv('BILLOMAT_API_KEY', 'test-only')
    monkeypatch.setattr(module.BillomatClient, 'get_full_offer', lambda self, oid: deepcopy(raw))
    return module.app.test_client()


def test_store_reopens_and_separates_accounts(tmp_path):
    OfferStore(tmp_path).save('one', '42', {'customer_title': 'Gespeichert'})
    assert OfferStore(tmp_path).load('one', '42')['customer_title'] == 'Gespeichert'
    assert OfferStore(tmp_path).load('two', '42') == {}
    assert OfferStore(tmp_path).load('one', '43') == {}


def test_browser_independence_editor_and_pdf(client):
    response = client.post('/offer/42/edit', data={'offer_type': 'Brandwarnanlage', 'customer_title': 'Persistenter Kundentitel'})
    assert response.status_code == 302
    fresh = module.app.test_client()
    assert 'Persistenter Kundentitel' in fresh.get('/offer/42').text
    assert 'Persistenter Kundentitel' in fresh.get('/offer/42/edit').text
    pdf = PdfReader(BytesIO(fresh.get('/offer/42/pdf').data))
    assert 'Persistenter Kundentitel' in pdf.pages[0].extract_text()
    assert 'session=' not in response.headers.get('Set-Cookie', '')


def test_cookie_migration_does_not_overwrite_newer_edit(client):
    with client.session_transaction() as cookie:
        cookie['ftst_42'] = {'customer_title': 'Altbestand'}
    assert 'Altbestand' in client.get('/offer/42').text
    with client.session_transaction() as cookie:
        assert 'ftst_42' not in cookie
    module.offer_store().save('test', '42', {'customer_title': 'Neuer Stand'})
    with client.session_transaction() as cookie:
        cookie['ftst_42'] = {'customer_title': 'Altbestand'}
    assert 'Neuer Stand' in client.get('/offer/42').text


def test_corrupt_database_not_replaced(client, tmp_path):
    path = tmp_path / 'offers.sqlite3'
    path.write_bytes(b'not a database')
    assert client.get('/offer/42').status_code == 503
    assert client.get('/offer/42/pdf').status_code == 503
    assert client.get('/health').status_code == 503
    assert path.read_bytes() == b'not a database'


def test_future_schema_refused(tmp_path):
    with sqlite3.connect(tmp_path / 'offers.sqlite3') as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(StorageError):
        OfferStore(tmp_path).load('test', '42')


def test_invalid_type_rejected_and_pdf_new_tab(client):
    assert client.post('/offer/42/edit', data={'offer_type': 'BMA'}).status_code == 400
    page = client.get('/offer/42', headers={'X-Ingress-Path': '/api/hassio_ingress/test'}).text
    assert 'target="_blank" rel="noopener"' in page
    assert '/api/hassio_ingress/test/offer/42/pdf' in page


@pytest.mark.parametrize('items,expected', [
    (['Hub', 'FireProtect'], 'Rauchmeldeanlage'),
    (['Hub', 'CO-Melder'], 'Rauchmeldeanlage'),
    (['Hub', 'Rauchmelder', 'Hitzemelder'], 'Rauchmeldeanlage'),
    (['Hub', 'MotionProtect', 'FireProtect'], 'Alarmanlage'),
    (['Hub', 'DoorProtect'], 'Alarmanlage'),
    (['Hub', 'GlassProtect'], 'Alarmanlage'),
    (['Hub', 'KeyPad'], 'Alarmanlage'),
    (['Hub'], 'Kombination'),
    (['BWA', 'Hub', 'FireProtect'], 'Brandwarnanlage'),
    (['BWA.'], 'Brandwarnanlage'),
])
def test_detection(items, expected):
    assert module.detect_offer_type({'items': [{'title': t} for t in items]}) == expected


@pytest.mark.parametrize('legacy', ['BMA', 'Brandmeldeanlage', 'brandmeldeanlage', 'Unbekannt'])
def test_obsolete_types_cannot_escape(raw, legacy):
    assert module.apply_source(raw, {'offer_type': legacy})['offer_type'] == 'Rauchmeldeanlage'
