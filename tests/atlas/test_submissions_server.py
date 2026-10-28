import base64
import contextlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    spec = importlib.util.spec_from_file_location('atlas_submissions_server_tests', ROOT / 'submissions_server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
finally:
    sys.path.pop(0)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.token = 'A' * 43
        self.store.validate_access.side_effect = lambda token: {'valid': token == self.token, 'label': 'Monteur' if token == self.token else ''}
        self.store.submit.return_value = {'accepted': True, 'receipt': 'receipt'}
        self.server = module._Server(('127.0.0.1', 0), self.store, 'https://upload.example.test', ROOT)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, method='GET', body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            client.request(method, path, body, headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def payload(self, **overrides):
        body = {'token': self.token, 'filename': 'receipt.png', 'mime': 'image/png', 'data_base64': base64.b64encode(b'\x89PNG\r\n\x1a\n').decode(), 'project': '', 'note': ''}
        body.update(overrides)
        return json.dumps(body)

    def upload(self, body=None, headers=None):
        defaults = {'Content-Type': 'application/json', 'Origin': self.server.origin}
        defaults.update(headers or {})
        return self.request('/api/submissions', 'POST', self.payload() if body is None else body, defaults)

    def access(self, token, headers=None, body=None):
        return self.request('/api/submissions/access', 'POST', json.dumps({'token': token}) if body is None else body,
                            {'Origin': self.server.origin, 'Content-Type': 'application/json', **(headers or {})})

    def test_only_public_assets_and_access_are_available_no_trusted_headers(self):
        for path in ('/api/bookkeeping', '/api/status', '/api/mail', '/api/submissions/access/owner', '/config', '/../../app.py', '/app.py'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, headers={'X-Remote-User-Id': 'owner'})[0], 404)
        for path in ('/submit', '/app.js', '/style.css'):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        code, _, body = self.access(self.token)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {'valid': True, 'label': 'Monteur'})

    def test_invitation_navigation_from_email_allowed_but_cross_site_api_denied(self):
        self.assertEqual(self.request('/submit', headers={'Sec-Fetch-Site': 'cross-site'})[0], 200)
        self.assertEqual(self.request('/api/submissions/access?token=' + self.token, headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        code, headers, _ = self.request('/submit/')
        self.assertEqual(code, 302)
        self.assertEqual(headers['Location'], '/submit')

    def test_upload_requires_origin_and_valid_token_before_ingestion(self):
        self.assertEqual(self.request('/api/submissions', 'POST', self.payload(), {'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.upload(headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.upload(self.payload(token='invalid', data_base64='notbase64'))[0], 403)
        self.store.submit.assert_not_called()
        code, _, body = self.upload()
        self.assertEqual(code, 201)
        self.assertEqual(json.loads(body), {'accepted': True, 'receipt': 'receipt'})
        self.store.submit.assert_called_once()
        self.assertEqual(self.store.submit.call_args.kwargs['token'], self.token)

    def test_body_limits_transfer_encoding_content_type_and_unknown_fields(self):
        self.assertEqual(self.upload(headers={'Content-Length': str(module.MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.upload(headers={'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.upload(headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.upload(self.payload(owner='victim'))[0], 400)
        self.assertEqual(self.upload('{"token":"a","token":"b"}')[0], 400)
        self.assertEqual(self.request('/api/bookkeeping', 'POST', self.payload(), {'Origin': self.server.origin})[0], 404)
        self.store.submit.assert_not_called()

    def test_generic_failure_redacted_and_access_not_logged(self):
        self.store.submit.side_effect = RuntimeError('secret-body-key')
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            code, _, body = self.upload()
            self.access(self.token)
        self.assertEqual(code, 503)
        self.assertNotIn(b'secret-body-key', body)
        self.assertNotIn(self.token, capture.getvalue())
        self.assertNotIn('secret-body-key', capture.getvalue())

    def test_request_ip_rate_limit_ignores_forwarded_headers(self):
        for i in range(20):
            self.assertEqual(self.upload(headers={'X-Forwarded-For': str(i)})[0], 201)
        self.assertEqual(self.upload(headers={'X-Forwarded-For': 'new'})[0], 429)
        self.assertEqual(self.store.submit.call_count, 20)

    def test_access_validation_has_small_body_and_separate_upload_rate_budget(self):
        for _ in range(21):
            self.assertEqual(self.access(self.token)[0], 200)
        self.assertEqual(self.upload()[0], 201)
        self.assertEqual(self.request('/api/submissions/access', 'POST', json.dumps({'token': self.token}),
                                      {'Content-Type': 'application/json'})[0], 403)
        self.assertEqual(self.access(self.token, body=' ' * 1025)[0], 413)

    def test_parallel_request_cap_rejects_without_starting_extra_worker(self):
        for _ in range(4):
            self.server.slots.acquire()
        try:
            self.assertEqual(self.request('/submit')[0], 503)
        finally:
            for _ in range(4):
                self.server.slots.release()
        self.assertEqual(self.request('/submit')[0], 200)

    def test_origin_validation_and_disabled_server_never_binds(self):
        self.assertEqual(module._origin('https://upload.example.test/submit'), 'https://upload.example.test')
        self.assertEqual(module._origin('https://upload.example.test:443'), 'https://upload.example.test')
        self.assertEqual(module._origin('http://127.0.0.1:1234', dev=True), 'http://127.0.0.1:1234')
        for url in ('http://example.test', 'http://127.0.0.1', 'https://user:pass@example.test', 'https://example.test/?token=x', 'https://example.test/path', ''):
            with self.subTest(url=url), self.assertRaises(module.SubmissionsServerError):
                module._origin(url)
        with patch.object(module, '_Server') as factory:
            self.assertIsNone(module.start_server(Mock(), {}))
            factory.assert_not_called()

    def test_real_store_upload_owner_scoping_and_revocation(self):
        def load(name, filename):
            spec = importlib.util.spec_from_file_location(name, ROOT / filename)
            value = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(ROOT))
            try:
                spec.loader.exec_module(value)
            finally:
                sys.path.pop(0)
            return value
        bookkeeping = load('public_server_bookkeeping', 'bookkeeping.py')
        submissions = load('public_server_submissions', 'submissions.py')
        with tempfile.TemporaryDirectory() as directory:
            db = lambda: sqlite3.connect(str(Path(directory) / 'test.db'))
            book = bookkeeping.Bookkeeping(db, directory)
            store = submissions.Submissions(db, book)
            invite = store.create_access('real-owner', 'Techniker')
            self.server.submissions = store
            payload = self.payload(token=invite['token'])
            code, _, body = self.upload(payload)
            self.assertEqual(code, 201)
            accepted = json.loads(body)
            self.assertTrue(accepted['accepted'])
            self.assertNotIn('owner', accepted)
            self.assertNotIn('id', accepted)
            records = book.list('real-owner')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['source']['provider'], 'employee')
            self.assertEqual(book.list('other'), [])
            store.revoke_access('real-owner', invite['id'])
            self.assertEqual(self.upload(payload)[0], 403)
            self.assertEqual(len(book.list('real-owner')), 1)

    def test_invalid_and_revoked_access_never_returns_identity_or_owner(self):
        code, _, body = self.access('wrong')
        self.assertEqual(code, 403)
        self.assertNotIn('label', json.loads(body))
        self.assertEqual(self.request('/api/submissions/access?token=' + self.token)[0], 404)
        self.assertEqual(self.access(self.token, body=json.dumps({'owner': 'owner'}))[0], 400)
        self.assertEqual(self.access(self.token, body='x' * 1025)[0], 413)
        self.assertEqual(self.access(self.token, headers={'Origin': 'https://evil.test'})[0], 403)


if __name__ == '__main__':
    unittest.main()
