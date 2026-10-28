"""Mail preview isolation, source integrity and hostile transport regression tests."""
import base64
import importlib.util
import pathlib
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('atlas_mail_client_tests', pathlib.Path(__file__).parents[2] / 'ftst_atlas/mail_client.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TOKEN = 'x' * 43
OPTIONS = {'mail_enabled': True, 'mail_ha_user_id': 'owner', 'mail_bridge_token': TOKEN}
ACCOUNT = {'id': 'primary', 'email': 'office@example.test', 'folder': 'INBOX'}
RAW = b'Subject: Anfrage\r\nFrom: client@example.test\r\nTo: office@example.test\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBitte ein Angebot.'


class MailClientTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
