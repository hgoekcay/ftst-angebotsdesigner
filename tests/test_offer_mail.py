from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from email import policy
from email.parser import BytesParser
import re
import smtplib

import pytest
from PIL import Image

import app as module
import offer_mail
import offer_smtp
from storage import OfferStore, RecordConflict
from test_baseline import raw
from test_persistence import isolated_storage, client


def fields(client, url='/offer/42/email'):
    html = client.get(url).text
    csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    return dict(csrf=csrf, account='test', recipient='kunde@example.org',
                subject='Leistungsvorschlag 42', text='Guten Tag,\n\nIhre Lösung <script>alert(1)</script>')


def prepared(client):
    result = client.post('/offer/42/email', data=fields(client))
    assert result.status_code == 303
    return result.headers['Location']


def test_preview_has_real_pdf_inline_logo_and_safe_html(client):
    url = prepared(client)
    eml = client.get(url + '/eml')
    assert eml.status_code == 200
    msg = BytesParser(policy=policy.default).parsebytes(eml.data)
    assert str(msg['To']) == 'kunde@example.org'
    assert 'info@ftst.eu' in str(msg['From'])
    assert msg['Message-ID'] and 'Bcc' not in msg
    attachment = list(msg.iter_attachments())[0]
    assert attachment.get_content_type() == 'application/pdf'
    assert attachment.get_payload(decode=True).startswith(b'%PDF-')
    assert client.get(url + '/pdf').data == attachment.get_payload(decode=True)
    html = msg.get_body(preferencelist=('html',)).get_content()
    assert '&lt;script&gt;' in html and '<script>' not in html
    assert 'cid:ftst-logo' in html and 'hassio_ingress' not in html
    assert any(x['Content-ID'] == '<ftst-logo>' for x in msg.walk())
    preview = client.get(url + '/preview')
    assert 'data:image/png;base64,' in preview.text
    assert 'no-store' in preview.headers['Cache-Control']
    assert "default-src 'none'" in preview.headers['Content-Security-Policy']
    assert 'Noch nicht eingerichtet' in client.get('/email-settings').text


@pytest.mark.parametrize('recipient', ['a@b.de\r\nBcc: bad@evil.org', 'a@b.de,b@c.de', 'a@b.de;b@c.de', '', 'invalid'])
def test_recipient_rejected_before_pdf_or_smtp(client, recipient, monkeypatch):
    data = fields(client)
    data['recipient'] = recipient
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *a: pytest.fail('must not send'))
    assert client.post('/offer/42/email', data=data).status_code == 400
    assert not module.offer_store().records('test', offer_mail.KIND)


def test_csrf_and_account_binding(client, monkeypatch):
    data = fields(client)
    data['csrf'] = 'bad'
    assert client.post('/offer/42/email', data=data).status_code == 400
    data = fields(client)
    data['account'] = 'other'
    assert client.post('/offer/42/email', data=data).status_code == 400
    url = prepared(client)
    monkeypatch.setenv('BILLOMAT_ID', 'other')
    assert client.get(url).status_code == 404
    assert client.get(url + '/eml').status_code == 404


def test_draft_and_cross_offer_response_blocked(client, raw, monkeypatch):
    draft = deepcopy(raw)
    draft['status'] = 'DRAFT'
    monkeypatch.setattr(module.BillomatClient, 'get_full_offer', lambda *a: draft)
    assert client.get('/offer/42/email').status_code == 409
    draft['id'] = '43'
    assert client.get('/offer/42/email').status_code == 404


def test_send_uses_frozen_bytes_requires_confirmation_and_never_repeats(client, monkeypatch):
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    url = prepared(client)
    raw_eml = client.get(url + '/eml').data
    calls = []
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *args: calls.append(args) or 'accepted')
    data = fields(client)
    assert client.post(url, data=data).status_code == 400
    data['confirm'] = 'yes'
    result = client.post(url, data=data)
    assert result.status_code == 200
    assert 'Vom Mailserver angenommen' in result.text
    assert 'Zustellung nicht bestätigt' in result.text
    assert calls == [('kunde@example.org', raw_eml)]
    assert client.post(url, data=data).status_code == 409
    assert len(calls) == 1


def test_expired_preview_and_disabled_sender_cannot_send(client, monkeypatch):
    url = prepared(client)
    key = url.rsplit('/', 1)[-1]
    with pytest.raises(ValueError):
        offer_mail.submit(module.offer_store(), 'test', key)
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    monkeypatch.setattr(offer_mail.time, 'time', lambda: 99999999999)
    with pytest.raises(ValueError):
        offer_mail.submit(module.offer_store(), 'test', key)
    assert module.offer_store().record('test', offer_mail.KIND, key)['status'] == 'prepared'


def test_concurrent_submissions_claim_only_once(client, monkeypatch):
    key = prepared(client).rsplit('/', 1)[-1]
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    calls = []
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *args: calls.append(args) or 'uncertain')
    directory = module.app.config['FTST_DATA_DIR']
    def send():
        try:
            return offer_mail.submit(OfferStore(directory), 'test', key)['status']
        except RecordConflict:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(), range(2)))
    assert sorted(results) == ['blocked', 'uncertain']
    assert len(calls) == 1


def test_reference_settings_embed_uploaded_logo_and_label(client, tmp_path):
    store = module.offer_store()
    image_dir = store.directory / 'images'
    image_dir.mkdir(exist_ok=True)
    Image.new('RGB', (300, 100), 'green').save(image_dir / 'sample.png')
    store.put_record('test', 'image', 'sample', {'title': 'Testlogo', 'category': 'Logo'})
    data = fields(client, '/email-settings')
    data.update(action='references', image_0='sample', label_0='Beispielkunde · Mannheim')
    assert client.post('/email-settings', data=data).status_code == 200
    msg = BytesParser(policy=policy.default).parsebytes(client.get(prepared(client) + '/eml').data)
    assert 'Beispielkunde · Mannheim' in msg.get_body(preferencelist=('html',)).get_content()
    assert any(x['Content-ID'] == '<reference-0>' for x in msg.walk())


class FakeSMTP:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.commands = []

    def login(self, *args):
        self.commands.append('login')
        if self.fail_at == 'login':
            raise smtplib.SMTPAuthenticationError(535, b'secret must not leak')

    def mail(self, *args):
        self.commands.append('mail')
        return 250, b'ok'

    def rcpt(self, *args):
        self.commands.append('rcpt')
        return (550, b'no') if self.fail_at == 'rcpt' else (250, b'ok')

    def data(self, *args):
        self.commands.append('data')
        if self.fail_at == 'disconnect':
            raise smtplib.SMTPServerDisconnected('unknown')
        if self.fail_at == 'reject':
            raise smtplib.SMTPDataError(552, b'rejected')
        return 250, b'accepted'

    def close(self):
        self.commands.append('close')


@pytest.mark.parametrize('failure,status', [(None, 'accepted'), ('login', 'failed'), ('rcpt', 'failed'), ('disconnect', 'uncertain'), ('reject', 'failed')])
def test_smtp_tls_and_outcome_classification(monkeypatch, failure, status):
    smtp = FakeSMTP(failure)
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    def connect(host, port, **kwargs):
        assert host == 'smtp.strato.de' and port == 465
        assert kwargs['context'].check_hostname and kwargs['timeout'] == 20
        return smtp
    monkeypatch.setattr(offer_smtp.smtplib, 'SMTP_SSL', connect)
    assert offer_smtp.deliver('kunde@example.org', b'fake MIME') == status
    assert smtp.commands.count('data') <= 1


def test_smtp_check_never_submits_message(monkeypatch):
    smtp = FakeSMTP()
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    monkeypatch.setattr(offer_smtp.smtplib, 'SMTP_SSL', lambda *a, **kw: smtp)
    assert offer_smtp.check()
    assert smtp.commands == ['login', 'close']


def test_original_reference_photos_fit_email_budget(client):
    from asset_library import ROOT
    with module.app.test_request_context():
        offer = module.get_offer('42')
    offer['reference_images'] = [{'path': str(ROOT / 'references' / 'Zerda_Gold_Rheinfelden_20260907_190456629.jpg'), 'title': 'Türstation'}] * 4
    pdf = module.make_pdf(offer).getvalue()
    assert pdf.startswith(b'%PDF-') and len(pdf) < 5 * 1024 * 1024
