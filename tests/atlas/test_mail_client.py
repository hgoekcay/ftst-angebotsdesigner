"""Mail preview isolation, source integrity and hostile transport regression tests."""
import base64
import json
import importlib.util
import pathlib
import unittest
from email.message import EmailMessage
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('atlas_mail_client_tests', pathlib.Path(__file__).parents[2] / 'ftst_atlas/mail_client.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TOKEN = 'x' * 43
OPTIONS = {'mail_enabled': True, 'mail_ha_user_id': 'owner', 'mail_bridge_token': TOKEN}
ACCOUNT = {'id': 'primary', 'email': 'office@example.test', 'folder': 'INBOX'}
RAW = b'Subject: Anfrage\r\nFrom: client@example.test\r\nTo: office@example.test\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBitte ein Angebot.'


class MailClientTests(unittest.TestCase):
    def test_bridge_failures_are_actionable_without_exposing_server_text(self):
        for code, expected in [('mail_auth_failed', 'Anmeldung'), ('mail_message_too_large', '32 MiB'), ('mail_limit_exceeded', 'Sicherheitsgrenze'), ('unknown', 'Antwort ungültig')]:
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = 502
            payload = json.dumps({'error': code, 'detail': 'secret password server trace'}).encode()
            response.getheader.side_effect = lambda key, default=None: 'application/json' if key == 'Content-Type' else str(len(payload))
            response.read1.side_effect = [payload, b'']
            with self.subTest(code=code), patch.object(m.http.client, 'HTTPConnection', return_value=connection):
                with self.assertRaises(m.ImapFetchError) as caught:
                    m._request(TOKEN, '/internal/mail/batch')
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn('secret', str(caught.exception))
                connection.close.assert_called_once()

    def test_large_mime_is_received_but_oversized_attachment_remains_flagged(self):
        raw = b'Content-Type: text/plain\r\n\r\n' + b'a' * (9 * 1024 * 1024)
        with patch.object(m, '_request', return_value={'uidvalidity': 1, 'pending': False, 'messages': [{'uid': 2, 'raw_base64': base64.b64encode(raw).decode()}]}):
            batch = m.fetch_batch(TOKEN, '2026-10-28', 1, 0)
        self.assertEqual(batch['messages'][0][1], raw)
        self.assertEqual(m.MAX_ATTACHMENT, 8 * 1024 * 1024)

    def test_disabled_and_other_user_never_contact_bridge(self):
        with patch.object(m, '_request') as request:
            for client, user in [(m.MailClient({}), 'owner'), (m.MailClient(OPTIONS), 'other'), (m.MailClient(OPTIONS), '')]:
                with self.assertRaises(m.MailAccessError):
                    client.preview(user)
            request.assert_not_called()

    def test_destination_and_owner_validation(self):
        for url in ['https://example.org:8098', 'http://127.0.0.1:8098', 'http://local-ftst-strato-mail:8098/path', 'http://local-ftst-strato-mail:8098?x', 'http://user@local-ftst-strato-mail:8098', 'http://local-ftst-strato-mail:80']:
            with self.subTest(url=url), self.assertRaises(m.MailError):
                m.MailClient(dict(OPTIONS, mail_bridge_url=url))
        for key, value in [('mail_ha_user_id', ''), ('mail_bridge_token', 'secret\r\nHost: example.org'), ('mail_account_id', '../other')]:
            with self.subTest(key=key), self.assertRaises(m.MailError):
                m.MailClient(dict(OPTIONS, **{key: value}))

    def test_preview_binds_source_and_preserves_identity(self):
        with patch.object(m, '_request', side_effect=[{'accounts': [ACCOUNT]}, {'uidvalidity': 123, 'after_uid': 12}, {'uidvalidity': 123, 'pending': True, 'messages': [{'uid': 9, 'raw_base64': base64.b64encode(RAW).decode()}]}]) as request:
            result = m.MailClient(OPTIONS).preview('owner')
            self.assertTrue(result['pending'])
            self.assertEqual(result['order'], 'oldest_first')
            row = result['messages'][0]
            self.assertEqual(row['body'], 'Bitte ein Angebot.')
            self.assertEqual(row['source'], {'account_id': 'primary', 'mailbox': ACCOUNT['email'], 'folder': 'INBOX', 'uidvalidity': 123, 'uid': 9})
            batch_args = request.call_args_list[2].args[2]
            self.assertEqual(batch_args['expected_email'], ACCOUNT['email'])
            self.assertEqual(batch_args['expected_folder'], 'INBOX')
            self.assertEqual(batch_args['after_uid'], 0)

    def test_uid_epoch_and_duplicate_uid_rejected(self):
        for result in [{'uidvalidity': 124, 'pending': False, 'messages': []}, {'uidvalidity': 123, 'pending': True, 'messages': []}, {'uidvalidity': 123, 'pending': False, 'messages': [{'uid': 9, 'raw_base64': base64.b64encode(RAW).decode()}] * 2}]:
            with patch.object(m, '_request', return_value=result), self.assertRaises(m.MailError):
                m.fetch_batch(TOKEN, '2026-10-28', 123, 0)

    def test_html_is_text_and_attachments_not_read(self):
        raw = b'Content-Type: text/html; charset=utf-8\r\n\r\n<head>hidden</head><p>Hallo</p><script>bad()</script><img src="https://track.example/a">'
        result = m._message(raw, {}, 1, 2)
        self.assertIn('Hallo', result['body'])
        self.assertNotIn('bad', result['body'])
        self.assertNotIn('https', result['body'])
        self.assertNotIn('hidden', result['body'])
        long = m._message(b'Content-Type: text/plain\r\n\r\n' + b'a' * 13000, {}, 1, 2)
        self.assertEqual(len(long['body']), 12000)
        self.assertTrue(long['body_truncated'])
        self.assertTrue(long['warnings'])

    def test_request_never_redirects_and_hides_errors(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 302
        with patch.object(m.http.client, 'HTTPConnection', return_value=connection) as factory:
            with self.assertRaises(m.MailError) as caught:
                m._request(TOKEN, '/internal/mail/accounts', host='76b650ab-ftst-strato-mail')
            self.assertNotIn(TOKEN, str(caught.exception))
            factory.assert_called_once_with('76b650ab-ftst-strato-mail', 8098, timeout=15)
            self.assertEqual(connection.request.call_args.kwargs['headers']['Host'], 'local-ftst-strato-mail:8098')
            connection.close.assert_called_once()

    def test_duplicate_json_and_oversize_response_rejected(self):
        for payload, length in [(b'{"accounts":[],"accounts":[]}', None), (b'{}', str(m.MAX_RESPONSE + 1))]:
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = 200
            response.getheader.side_effect = lambda key, default=None: 'application/json' if key == 'Content-Type' else length
            response.read1.side_effect = [payload, b'']
            with patch.object(m.http.client, 'HTTPConnection', return_value=connection), self.assertRaises(m.MailError):
                m._request(TOKEN, '/internal/mail/accounts')

    def test_accounts_scope_and_account_switch(self):
        second = {'id': 'billing', 'email': 'billing@example.test', 'folder': 'Invoices'}
        hidden = {'id': 'private', 'email': 'private@example.test', 'folder': 'INBOX'}
        client = m.MailClient(dict(OPTIONS, mail_account_ids=['primary', 'billing']))
        with patch.object(m, '_request', return_value={'accounts': [ACCOUNT, second, hidden]}) as request:
            self.assertEqual(client.accounts('owner'), [ACCOUNT, second])
            for operation in [lambda: client.accounts('other'), lambda: client.preview('owner', account_id='private'),
                              lambda: client.invoice_batch('owner', 'private', 7)]:
                count = request.call_count
                with self.assertRaises(m.MailAccessError):
                    operation()
                self.assertEqual(request.call_count, count)
        with patch.object(m, '_request', side_effect=[{'accounts': [ACCOUNT, second]}, {'uidvalidity': 12, 'after_uid': 100}, {'uidvalidity': 12, 'messages': [], 'pending': False}]) as request:
            result = client.preview('owner', account_id='billing')
            self.assertEqual(result['source']['mailbox'], second['email'])
            self.assertEqual(request.call_args.args[2]['account_id'], 'billing')
            self.assertEqual(request.call_args.args[2]['expected_folder'], 'Invoices')

    def test_allowlist_requires_explicit_well_formed_unique_entries(self):
        for allowlist in [['primary', 'primary'], ['*'], ['PRIMARY'], 'primary', [None], ['a' + str(i) for i in range(22)]]:
            with self.subTest(allowlist=allowlist), self.assertRaises(m.MailError):
                m.MailClient(dict(OPTIONS, mail_account_ids=allowlist))
        self.assertEqual(m.MailClient(OPTIONS).account_ids, ('primary',))
        self.assertEqual(m.MailClient(dict(OPTIONS, mail_account_ids=[])).account_ids, ('primary',))
        self.assertEqual(m.MailClient(dict(OPTIONS, mail_account_ids=['billing'])).account_id, 'billing')

    def document_mail(self, attachments):
        message = EmailMessage()
        message['Subject'] = 'Belegprüfung'
        message['From'] = 'sender@example.test'
        message.set_content('Bitte prüfen.')
        for data, mime, name, disposition in attachments:
            main, sub = mime.split('/')
            message.add_attachment(data, maintype=main, subtype=sub, filename=name, disposition=disposition)
        return message.as_bytes()

    def test_invoice_batch_source_hash_and_continuation(self):
        pdf = b'%PDF-1.4\nfixture'
        raw = self.document_mail([(pdf, 'application/pdf', '../../rechnungen\\beleg.pdf', 'attachment')])
        result = {'uidvalidity': 123, 'messages': [{'uid': 8, 'raw_base64': base64.b64encode(raw).decode()},
                  {'uid': 9, 'raw_base64': base64.b64encode(RAW).decode()}], 'pending': True}
        with patch.object(m, '_request', side_effect=[{'accounts': [ACCOUNT]}, result]) as request:
            batch = m.MailClient(OPTIONS).invoice_batch('owner', 'primary', 7, after_uid=7, uidvalidity=123)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.args[2]['after_uid'], 7)
            self.assertEqual(batch['after_uid'], 9)
            self.assertTrue(batch['pending'])
            attachment = batch['messages'][0]['attachments'][0]
            self.assertEqual(attachment['name'], 'beleg.pdf')
            self.assertEqual(attachment['data'], pdf)
            self.assertEqual(attachment['sha256'], m.hashlib.sha256(pdf).hexdigest())
            self.assertEqual(attachment['source']['account_id'], 'primary')
            self.assertEqual(attachment['source']['uidvalidity'], 123)
            self.assertEqual(attachment['source']['uid'], 8)
            self.assertTrue(attachment['candidate_only'])
            self.assertEqual(batch['messages'][1]['attachments'], [])
            self.assertEqual(batch['messages'][0]['raw_sha256'], m.hashlib.sha256(raw).hexdigest())
            self.assertNotIn('raw', batch['messages'][0])
        with patch.object(m, '_request') as request:
            with self.assertRaises(m.MailError):
                m.MailClient(OPTIONS).invoice_batch('owner', 'primary', 7, after_uid=7)
            request.assert_not_called()

    def test_attachment_type_confusion_xml_entities_and_inline_excluded(self):
        raw = self.document_mail([
            (b'<html>not pdf</html>', 'application/pdf', 'bill.pdf', 'attachment'),
            (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><x>&e;</x>', 'application/xml', 'bill.xml', 'attachment'),
            (b'\x89PNG\r\n\x1a\nimage', 'image/png', 'logo.png', 'inline'),
            (b'PKzip', 'application/zip', 'bundle.zip', 'attachment'),
            (b'%PDF-1.4\ncorrect', 'application/octet-stream', 'receipt.pdf', 'attachment'),
            (b'<?xml version="1.0"?><Invoice/>', 'application/xml', 'invoice.xml', 'attachment')])
        message = m._invoice_message(raw, {'account_id': 'primary'}, 1, 2)
        self.assertEqual([a['name'] for a in message['attachments']], ['receipt.pdf', 'invoice.xml'])
        self.assertEqual(len(message['warnings']), 3)

    def test_attachment_and_structure_limits_are_explicit(self):
        raw = self.document_mail([(b'%PDF-1.4\nfixture', 'application/pdf', 'bill.pdf', 'attachment')] * 3)
        with patch.object(m, 'MAX_ATTACHMENT', 4):
            message = m._invoice_message(raw, {}, 1, 2)
            self.assertEqual(message['attachments'], [])
            self.assertTrue(message['warnings'])
        with patch.object(m, 'MAX_ATTACHMENTS', 1):
            message = m._invoice_message(raw, {}, 1, 2)
            self.assertEqual(len(message['attachments']), 1)
            self.assertIn('Mengenlimit', ' '.join(message['warnings']))
        with patch.object(m, 'MAX_MIME_PARTS', 2):
            message = m._invoice_message(raw, {}, 1, 2)
            self.assertEqual(message['attachments'], [])
            self.assertTrue(message['warnings'])
        malformed = b'Content-Type: application/pdf\nContent-Disposition: attachment; filename="a.pdf"\nContent-Transfer-Encoding: base64\n\n%%%bad%%%%'
        message = m._invoice_message(malformed, {}, 1, 2)
        self.assertEqual(message['attachments'], [])
        self.assertTrue(message['warnings'])

    def test_skipped_attachment_still_advances_invoice_cursor(self):
        raw = self.document_mail([(b'not a PDF', 'application/pdf', 'bad.pdf', 'attachment')])
        with patch.object(m, '_request', side_effect=[{'accounts': [ACCOUNT]}, {'uidvalidity': 1, 'after_uid': 3},
                {'uidvalidity': 1, 'messages': [{'uid': 3, 'raw_base64': base64.b64encode(raw).decode()}], 'pending': False}]):
            result = m.MailClient(OPTIONS).invoice_batch('owner', 'primary', 7)
        self.assertEqual(result['after_uid'], 3)
        self.assertEqual(result['messages'][0]['attachments'], [])
        self.assertTrue(result['messages'][0]['warnings'])

    def test_invoice_since_is_stable_and_bounded(self):
        start = (m.date.today() - m.timedelta(days=40)).isoformat()
        with patch.object(m, '_request', side_effect=[{'accounts': [ACCOUNT]}, {'uidvalidity': 1, 'messages': [], 'pending': False}]) as request:
            batch = m.MailClient(OPTIONS).invoice_batch('owner', 'primary', 7, after_uid=9, uidvalidity=1, since=start)
            self.assertEqual(batch['since'], start)
            self.assertEqual(request.call_args.args[2]['since'], start)
            self.assertEqual(batch['after_uid'], 9)
        with patch.object(m, '_request') as request:
            for since in ['bad', (m.date.today() + m.timedelta(days=1)).isoformat(), (m.date.today() - m.timedelta(days=366)).isoformat()]:
                with self.assertRaises(m.MailError):
                    m.MailClient(OPTIONS).invoice_batch('owner', 'primary', 7, since=since)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
