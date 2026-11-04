from email import policy
from email.parser import BytesParser
import time

import pytest

import app as module
import offer_mail
import offer_sent
import offer_smtp
from storage import RecordConflict
from test_baseline import raw
from test_persistence import isolated_storage, client
from test_offer_mail import prepared, fields


class Mailbox:
    def __init__(self):
        self.rows = [b'(\\Sent) "/" "Sent Items"']
        self.matches = b''
        self.append_result = 'OK'
        self.append_error = False
        self.copies = []
        self.selected = None

    def login(self, sender, password):
        assert sender == 'info@ftst.eu' and password == 'test-only'

    def list(self):
        return 'OK', self.rows

    def select(self, folder, readonly):
        assert readonly
        self.selected = folder
        return 'OK', [b'0']

    def uid(self, *args):
        assert args[:4] == ('SEARCH', None, 'HEADER', 'Message-ID')
        return 'OK', [self.matches]

    def append(self, folder, flags, date, message):
        assert folder == self.selected and flags == r'\Seen'
        self.copies.append(message)
        if self.append_error:
            raise TimeoutError('private server detail')
        return self.append_result, []

    def logout(self):
        pass


@pytest.fixture
def mailbox(monkeypatch):
    box = Mailbox()
    monkeypatch.setenv('STRATO_SMTP_ENABLED', 'true')
    monkeypatch.setenv('STRATO_SMTP_PASSWORD', 'test-only')
    def connect(host, port, ssl_context, timeout):
        assert host == 'imap.strato.de' and port == 993
        assert ssl_context.check_hostname and timeout == 20
        return box
    monkeypatch.setattr(offer_sent.imaplib, 'IMAP4_SSL', connect)
    return box


def test_sent_copy_uses_original_bytes_and_deduplicates(mailbox):
    assert offer_sent.copy_to_sent(b'original MIME', '<unique@ftst.eu>') == 'saved'
    assert mailbox.copies == [b'original MIME']
    mailbox.matches = b'42'
    assert offer_sent.copy_to_sent(b'original MIME', '<unique@ftst.eu>') == 'saved'
    assert len(mailbox.copies) == 1


def test_folder_discovery_and_documented_strato_fallback(mailbox):
    mailbox.rows = [b'(\\Sent) "/" "INBOX.Sent"']
    assert offer_sent.sent_folder(mailbox) == 'INBOX.Sent'
    mailbox.rows = [b'() "/" "Sent Items"']
    assert offer_sent.sent_folder(mailbox) == 'Sent Items'
    mailbox.rows = [b'(\\Sent) "/" "one"', b'(\\Sent) "/" "two"']
    assert offer_sent.copy_to_sent(b'mail', '<unique@ftst.eu>') == 'failed'
    assert not mailbox.copies


def test_append_ambiguity_never_blindly_repeats(mailbox):
    mailbox.append_error = True
    assert offer_sent.copy_to_sent(b'mail', '<unique@ftst.eu>') == 'uncertain'
    assert offer_sent.copy_to_sent(b'mail', '<unique@ftst.eu>', allow_append=False) == 'uncertain'
    assert len(mailbox.copies) == 1
    mailbox.matches = b'42'
    assert offer_sent.copy_to_sent(b'mail', '<unique@ftst.eu>', allow_append=False) == 'saved'
    assert len(mailbox.copies) == 1


def test_accepted_send_saves_copy_retry_cannot_send_smtp(client, mailbox, monkeypatch):
    url = prepared(client)
    key = url.rsplit('/', 1)[-1]
    smtp_calls = []
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *a: smtp_calls.append(a) or 'accepted')
    mailbox.append_result = 'NO'
    record = offer_mail.submit(module.offer_store(), 'test', key)
    assert record['status'] == 'accepted' and record['sent_copy_status'] == 'failed'
    original = module.offer_store().mail_blob('test', record['digest'])
    assert mailbox.copies == [original]
    assert list(BytesParser(policy=policy.default).parsebytes(original).iter_attachments())
    mailbox.append_result = 'OK'
    data = fields(client)
    data['action'] = 'sent-copy'
    assert client.post(url, data=data).status_code == 303
    assert len(smtp_calls) == 1
    assert 'Kopie im Ordner „Gesendet“ gespeichert' in client.get(url).text
    assert client.post(url, data=data).status_code == 409
    assert len(mailbox.copies) == 2


@pytest.mark.parametrize('outcome', ['failed', 'uncertain'])
def test_nonaccepted_send_never_copies(client, mailbox, monkeypatch, outcome):
    key = prepared(client).rsplit('/', 1)[-1]
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *a: outcome)
    assert offer_mail.submit(module.offer_store(), 'test', key)['status'] == outcome
    with pytest.raises(RecordConflict):
        offer_mail.save_sent_copy(module.offer_store(), 'test', key)
    assert not mailbox.copies


def test_copy_recovery_after_disconnect_or_crash_is_search_only(client, mailbox, monkeypatch):
    key = prepared(client).rsplit('/', 1)[-1]
    monkeypatch.setattr(offer_smtp, 'deliver', lambda *a: 'accepted')
    mailbox.append_error = True
    record = offer_mail.submit(module.offer_store(), 'test', key)
    assert record['sent_copy_status'] == 'uncertain'
    offer_mail.save_sent_copy(module.offer_store(), 'test', key)
    assert len(mailbox.copies) == 1
    store = module.offer_store()
    store.transact_record('test', offer_mail.KIND, key,
                          lambda v, _: dict(v, sent_copy_status='saving', sent_copy_epoch=time.time()))
    with pytest.raises(RecordConflict):
        offer_mail.save_sent_copy(store, 'test', key)
    store.transact_record('test', offer_mail.KIND, key,
                          lambda v, _: dict(v, sent_copy_epoch=time.time() - 301))
    mailbox.matches = b'42'
    assert offer_mail.save_sent_copy(store, 'test', key)['sent_copy_status'] == 'saved'
    assert len(mailbox.copies) == 1


def test_copy_route_checks_csrf_and_account(client, mailbox):
    url = prepared(client)
    assert client.post(url, data={'action': 'sent-copy'}).status_code == 400
    data = fields(client)
    data.update(action='sent-copy', account='other')
    assert client.post(url, data=data).status_code == 400
    assert not mailbox.copies
