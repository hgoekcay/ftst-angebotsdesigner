"""Ingress isolation, review/download and upload-access management integration."""
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

source = Path(__file__).parents[2] / 'ftst_atlas/app.py'
spec = importlib.util.spec_from_file_location('atlas_bookkeeping_http', source)
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(source.parent))
try:
    spec.loader.exec_module(module)
finally:
    sys.path.remove(str(source.parent))


class BookkeepingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'options.json').write_text(json.dumps({'bookkeeping_enabled': True,
            'bookkeeping_ha_user_id': 'alice', 'submissions_public_url': 'https://upload.example.test'}))
        self.app = module.App(root, dev=False)
        base = module.make_handler(self.app)
        class Ingress(base):
            def setup(self):
                super().setup()
                self.client_address = ('172.30.32.2', self.client_address[1])
        self.server = module.ThreadingHTTPServer(('127.0.0.1', 0), Ingress)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.app.jobs.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, method='GET', payload=None, user='alice', csrf=True):
        headers = {'X-Remote-User-Id': user, 'Content-Type': 'application/json'}
        if csrf:
            headers['X-Atlas-CSRF'] = self.app.csrf_token
        req = Request(self.url + path, method=method, headers=headers,
                      data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            data = response.read()
            if response.headers.get('Content-Type', '').startswith('application/json'):
                data = json.loads(data)
            return response.status, data, response.headers

    def test_scope_and_sync_queue(self):
        self.assertFalse(self.request('/api/bookkeeping', user='bob')[1]['enabled'])
        self.assertEqual(self.request('/api/bookkeeping/report', user='bob')[0], 403)
        self.assertEqual(self.request('/api/bookkeeping/sync', 'POST', {}, csrf=False)[0], 403)
        self.assertEqual(self.request('/api/bookkeeping/sync', 'POST', {}, user='bob')[0], 403)
        code, job, _ = self.request('/api/bookkeeping/sync', 'POST', {})
        self.assertEqual(code, 202)
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(self.request('/api/jobs/' + job['id'], user='bob')[0], 404)

    def test_original_export_and_owner_isolation(self):
        raw = b'\x89PNG\r\n\x1a\n' + b'synthetic-test-image'
        record = self.app.bookkeeping.ingest_document('alice', raw, 'test.png', 'image/png', {'provider': 'upload'})
        identifier = record['id']
        code, data, headers = self.request('/api/bookkeeping/' + identifier + '/document')
        self.assertEqual((code, data), (200, raw))
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.request('/api/bookkeeping/' + identifier, user='bob')[0], 403)
        self.assertEqual(self.request('/api/bookkeeping/' + identifier, 'PATCH', {'fields': {'reviewed': True}})[0], 400)
        code, data, _ = self.request('/api/bookkeeping/export?month=2026-10')
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('ai-bookkeeping.documents.json', archive.namelist())
            self.assertTrue(any(name.endswith('.png') for name in archive.namelist()))

    def test_access_create_revoke_and_no_token_listing(self):
        path = '/api/submissions/access'
        self.assertEqual(self.request(path, 'POST', {'label': 'Team'}, user='bob')[0], 403)
        self.assertEqual(self.request(path, 'POST', {'label': 'Team'}, csrf=False)[0], 403)
        code, result, _ = self.request(path, 'POST', {'label': 'Team'})
        self.assertEqual(code, 201)
        self.assertTrue(result['url'].startswith('https://upload.example.test/submit#token='))
        self.assertNotIn(result['token'], json.dumps(self.request(path)[1]))
        self.assertEqual(self.request(path + '/' + result['id'], 'DELETE')[0], 200)
        self.assertFalse(self.app.submissions.validate_access(result['token'])['valid'])


if __name__ == '__main__':
    unittest.main()
