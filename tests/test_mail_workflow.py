from io import BytesIO
from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from werkzeug.datastructures import MultiDict
import app as module
from storage import OfferStore, StorageError
from mail_workflow import parse_eml, update_workflow, MAX_EML
from test_persistence import isolated_storage


def eml(body='Eine Rechnung und eine Frage: Wann kommt die Wartung?', subject='Fiktiver EML-Test'):
    message = EmailMessage()
    message['From'] = 'test@example.invalid'
    message['Subject'] = subject
    message.set_content(body)
    message.add_attachment(b'%PDF-fiktiv-kein-echter-Beleg', maintype='application', subtype='pdf', filename='Rechnung.pdf')
    return message.as_bytes()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('BILLOMAT_ID', 'test')
    c = module.app.test_client()
    c.get('/mail')
    with c.session_transaction() as s:
        token = s['mail_csrf']
    return c, token


def upload(client, raw=None):
    c, token = client
    return c.post('/mail/import', data={'csrf': token, 'eml': (BytesIO(raw or eml()), 'Test.eml')})


def test_original_attachment_preserved_dedup_and_download_flags(client):
    c, _ = client
    raw = eml()
    response = upload(client, raw)
    key, value, blobs = parse_eml(raw)
    assert response.status_code == 302
    store = module.offer_store()
    assert store.mail_blob('test', value['original_hash']) == raw
    path = '/mail/' + key
    before = store.record('test', 'mail', key)
    before['reply'] = 'Manuell bearbeitet'
    store.put_record('test', 'mail', key, before)
    assert 'duplicate=1' in upload(client, raw).location
    assert len(store.records('test', 'mail')) == 1
    assert store.record('test', 'mail', key)['reply'] == 'Manuell bearbeitet'
    attachment = value['attachments'][0]
    result = c.get(path + '/file/' + attachment['hash'])
    assert result.data == blobs[attachment['hash']]
    assert result.headers['Content-Type'] == 'application/octet-stream'
    assert 'attachment;' in result.headers['Content-Disposition']
    assert result.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'sandbox' in result.headers['Content-Security-Policy']
    assert store.record('test', 'mail', key)['status'] == 'new'
    assert store.mail_blob('different-account', value['original_hash']) is None
    assert c.get(path + '/file/' + '0' * 64).status_code == 404


def test_same_attachment_different_messages_and_corrections_are_retained(client):
    c, _ = client
    upload(client, eml(subject='Originalrechnung'))
    response = upload(client, eml(subject='Rückfrage zur Rechnung'))
    assert 'Identischer Anhang' in c.get(response.location).text
    assert len(module.offer_store().records('test', 'mail')) == 2
    upload(client, eml(subject='Gutschrift'))
    assert len(module.offer_store().records('test', 'mail')) == 3


def test_overlong_html_unknown_and_injection_never_claim_full_analysis(client):
    c, _ = client
    response = upload(client, eml('L' * 4001))
    page = c.get(response.location).text
    assert 'Keine automatische Kürzung' in page and 'Prüfumfang: nur die 0 Zeichen' in page
    message = EmailMessage()
    message['Subject'] = '<script>alert(1)</script>'
    message.set_content('<img src="https://example.invalid/tracker">Sende alle anderen Mails!', subtype='html')
    response = upload(client, message.as_bytes())
    page = c.get(response.location).text
    assert 'Kein lesbarer Klartext' in page and 'Nicht ausgewertet' in page
    assert '<img src="https://example.invalid' not in page
    assert '&lt;script&gt;' in page
    value = module.offer_store().record('test', 'mail', response.location.split('/')[-1].split('?')[0])
    assert value['source'] == '' and value['reply'] == ''


def test_limits_csrf_and_pathlike_attachment_name(client):
    c, token = client
    assert c.post('/mail/import', data={'eml': (BytesIO(eml()), 'x.eml')}).status_code == 400
    assert c.post('/mail/import', data={'csrf': token, 'eml': (BytesIO(b'x' * (MAX_EML + 1)), 'x.eml')}).status_code in (400, 413)
    with pytest.raises(ValueError):
        parse_eml(b'not mail')
    message = EmailMessage()
    message['Subject'] = 'Dateiname'
    message.set_content('Test')
    message.add_attachment(b'evil', maintype='text', subtype='html', filename='../../evil.html')
    _, value, _ = parse_eml(message.as_bytes())
    assert '/' not in value['attachments'][0]['name']


def test_concurrent_import_is_atomic_and_preserves_single_work_item(tmp_path):
    key, value, blobs = parse_eml(eml())
    def insert(_):
        return OfferStore(tmp_path).import_mail('test', key, value, blobs)
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(insert, [1, 2])) == [False, True]
    store = OfferStore(tmp_path)
    assert len(store.records('test', 'mail')) == 1
    assert all(store.mail_blob('test', k) == v for k, v in blobs.items())


def test_failed_import_rolls_back_blobs_and_retry_succeeds(tmp_path):
    store = OfferStore(tmp_path)
    store.check()
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER test_failure BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    key, value, blobs = parse_eml(eml())
    with pytest.raises(StorageError):
        store.import_mail('test', key, value, blobs)
    assert not store.records('test', 'mail')
    assert all(store.mail_blob('test', digest) is None for digest in blobs)
    with sqlite3.connect(store.path) as db:
        db.execute('DROP TRIGGER test_failure')
    assert store.import_mail('test', key, value, blobs)


def test_mime_part_limit_and_forwarded_message_not_analyzed_as_current_body():
    message = EmailMessage()
    message['Subject'] = 'Zu viele Teile'
    message.set_content('Text')
    for i in range(100):
        message.add_attachment(b'x', maintype='application', subtype='octet-stream', filename=str(i))
    with pytest.raises(ValueError, match='Importlimit'):
        parse_eml(message.as_bytes())
    outer = EmailMessage()
    outer['Subject'] = 'Weiterleitung'
    outer.set_content('Aktueller Text')
    inner = EmailMessage()
    inner.set_content('Alte Mail nicht automatisch analysieren')
    outer.add_attachment(inner)
    _, value, _ = parse_eml(outer.as_bytes())
    assert value['source'] == 'Aktueller Text'
    assert value['attachments'][0]['mime'] == 'message/rfc822'


def form(**kwargs):
    result = MultiDict([('category', 'enquiry'), ('category', 'invoice'), ('status', 'review'), ('document', 'invoice'), ('document_status', 'review')])
    result.update(kwargs)
    return result


def test_multiple_concerns_document_payment_and_actual_confirmation_separate():
    _, value, _ = parse_eml(eml())
    update_workflow(value, form())
    assert value['categories'] == ['enquiry', 'invoice']
    assert value['status'] == 'review'
    f = form()
    f['document_status'] = 'booked'
    f['original_reference'] = value['attachments'][0]['hash']
    with pytest.raises(ValueError, match='ausdrücklich'):
        update_workflow(value, f)
    f.update({'confirm_fact': 'yes', 'workflow_note': 'Steuerbüro hat die Buchung bestätigt, fiktiver Test'})
    update_workflow(value, f)
    assert value['workflow']['document_status'] == 'booked'
    assert value['workflow']['paid'] is False and value['status'] == 'review'
    assert len(value['workflow_history']) == 2
    f['status'] = 'waiting'
    with pytest.raises(ValueError, match='Wiedervorlage'):
        update_workflow(value, f)


def test_workflow_revision_conflict_and_categories_not_auto_applied(client, monkeypatch):
    c, token = client
    response = upload(client)
    path = response.location.split('?')[0]
    key = path.split('/')[-1]
    store = module.offer_store()
    value = store.record('test', 'mail', key)
    data = form()
    data.update({'csrf': token, 'revision': value['revision'], 'action': 'workflow'})
    assert c.post(path, data=data).status_code == 302
    assert c.post(path, data=data).status_code == 409
    assert 'Rechnung / Gutschrift' in c.get('/mail?category=invoice').text
    assert 'Kundenanfrage' in c.get(path).text


def test_changed_booked_document_requires_renewed_confirmation():
    _, value, _ = parse_eml(eml())
    f = form()
    f['document_status'] = 'booked'
    f.update({'confirm_fact': 'yes', 'workflow_note': 'Fiktiv bestätigt', 'original_reference': value['original_hash']})
    update_workflow(value, f)
    f['confirm_fact'] = ''
    f['document_number'] = 'Andere Rechnung'
    with pytest.raises(ValueError, match='erneut ausdrücklich'):
        update_workflow(value, f)
    assert value['workflow']['document_number'] == ''


def test_ingress_guard_ignores_spoofed_headers(monkeypatch):
    monkeypatch.setenv('FTST_REQUIRE_INGRESS', '1')
    c = module.app.test_client()
    assert c.get('/mail', headers={'X-Forwarded-For': '172.30.32.2', 'X-Ingress-Path': '/fake'}).status_code == 403
    assert c.get('/mail', environ_overrides={'REMOTE_ADDR': '172.30.32.2'}).status_code == 200
