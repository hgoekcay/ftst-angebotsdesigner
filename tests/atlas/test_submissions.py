"""Upload invitations cannot disclose records, change owner or bypass durable quotas."""
import base64
import concurrent.futures
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('submission_tests_module', ROOT / 'submissions.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PNG = b'\x89PNG\r\n\x1a\nsynthetic'
ENCODED = base64.b64encode(PNG).decode()


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = lambda: sqlite3.connect(self.root / 'test.sqlite3', timeout=20)
        self.bookkeeping = Mock()
        self.bookkeeping.ingest_document.return_value = {'id': 'PRIVATE-RECORD', 'fields': {'gross': 'PRIVATE-GROSS'}, 'duplicate': True}
        self.store = m.Submissions(self.db, self.bookkeeping)
        self.access = self.store.create_access('owner', 'Monteur')

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, **values):
        args = {'token': self.access['token'], 'filename': 'beleg.png', 'mime': 'image/png',
                'data_base64': ENCODED, 'project': 'Baustelle A', 'note': 'Material geliefert'}
        args.update(values)
        return self.store.submit(**args)

    def test_tokens_are_hash_only_and_owner_scoped(self):
        self.assertEqual(len(self.access['token']), 43)
        with self.db() as db:
            row = db.execute('SELECT token_hash FROM atlas_submission_access').fetchone()
        self.assertEqual(row[0], m.hashlib.sha256(self.access['token'].encode()).hexdigest())
        self.assertNotIn(self.access['token'], json.dumps(self.store.list_access('owner')))
        self.assertEqual(self.store.list_access('other'), [])
        with self.assertRaises(m.SubmissionError):
            self.store.revoke_access('other', self.access['id'])
        self.assertTrue(self.store.validate_access(self.access['token'])['valid'])
        self.store.revoke_access('owner', self.access['id'])
        self.assertEqual(self.store.validate_access(self.access['token']), {'valid': False, 'label': ''})
        with self.assertRaises(m.SubmissionError):
            self.submit()
        self.bookkeeping.ingest_document.assert_not_called()

    def test_existing_token_is_blocked_when_owner_grant_changes(self):
        enabled = {'owner': True}
        self.store = m.Submissions(self.db, self.bookkeeping, owner_enabled=lambda owner: enabled.get(owner, False))
        self.assertTrue(self.store.validate_access(self.access['token'])['valid'])
        enabled['owner'] = False
        enabled['new-owner'] = True
        self.assertEqual(self.store.validate_access(self.access['token']), {'valid': False, 'label': ''})
        with patch.object(m.base64, 'b64decode') as decode, self.assertRaises(m.SubmissionError):
            self.submit()
        decode.assert_not_called()
        self.bookkeeping.ingest_document.assert_not_called()
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM atlas_submissions').fetchone()[0], 0)

    def test_receipt_has_no_record_identity_or_financial_data(self):
        result = self.submit(note='Zeile eins\nZeile zwei')
        self.assertEqual(set(result), {'accepted', 'receipt', 'message'})
        self.assertTrue(result['accepted'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        args = self.bookkeeping.ingest_document.call_args.args
        self.assertEqual(args[0], 'owner')
        self.assertEqual(args[1], PNG)
        self.assertEqual(args[4]['provider'], 'employee')
        self.assertEqual(args[4]['note'], 'Zeile eins Zeile zwei')
        self.assertEqual(args[4]['reference'], result['receipt'])
        self.assertNotIn(self.access['token'], json.dumps(args[4]))
        self.assertEqual(self.store.list_access('owner')[0]['submission_count'], 1)

    def test_invalid_tokens_never_decode_or_store(self):
        for token in ['', None, 'x' * 42, 'y' * 43, self.access['token'] + '\n']:
            with patch.object(m.base64, 'b64decode') as decode, self.assertRaises(m.SubmissionError):
                self.submit(token=token)
            decode.assert_not_called()
        self.bookkeeping.ingest_document.assert_not_called()

    def test_file_limits_fail_closed_and_errors_do_not_leak(self):
        for values in [{'data_base64': '%%%bad'}, {'mime': 'text/html'}, {'filename': 'bad\nname.pdf'}, {'data_base64': ''}]:
            with self.subTest(values=values), self.assertRaises(m.SubmissionError):
                self.submit(**values)
        with patch.object(m, 'MAX_FILE', 1), self.assertRaises(m.SubmissionError):
            self.submit()
        self.bookkeeping.ingest_document.assert_not_called()
        self.bookkeeping.ingest_document.side_effect = RuntimeError('SECRET CUSTOMER INVOICE')
        with self.assertRaises(m.SubmissionError) as error:
            self.submit()
        self.assertNotIn('SECRET', str(error.exception))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM atlas_submissions WHERE status='failed'").fetchone()[0], 6)

    def test_daily_quota_persists_across_restart_and_invalid_attempts(self):
        with patch.object(m, 'MAX_DAILY', 2):
            self.submit()
            with self.assertRaises(m.SubmissionError):
                self.submit(data_base64='bad!')
            self.store = m.Submissions(self.db, self.bookkeeping)
            with self.assertRaises(m.SubmissionError) as error:
                self.submit()
            self.assertIn('Limit', str(error.exception))
            self.assertEqual(self.bookkeeping.ingest_document.call_count, 1)

    def test_parallel_requests_cannot_exceed_quota(self):
        def submit_one(_):
            try:
                self.submit()
                return True
            except m.SubmissionError:
                return False
        with patch.object(m, 'MAX_DAILY', 3):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(submit_one, range(8)))
        self.assertEqual(sum(results), 3)
        self.assertEqual(self.bookkeeping.ingest_document.call_count, 3)

    def test_owner_and_token_total_quotas(self):
        with patch.object(m, 'MAX_OWNER_DAILY', 1):
            self.submit()
            self.access = self.store.create_access('owner', 'Zweiter Mitarbeiter')
            with self.assertRaises(m.SubmissionError):
                self.submit()
        with patch.object(m, 'MAX_TOKEN_TOTAL', 0), self.assertRaises(m.SubmissionError):
            self.submit()
        with patch.object(m, 'MAX_ACTIVE_ACCESS', 2), self.assertRaises(m.SubmissionError):
            self.store.create_access('owner', 'Dritter Mitarbeiter')

    def test_real_bookkeeping_stores_under_invitation_owner(self):
        spec = importlib.util.spec_from_file_location('submission_real_bookkeeping', ROOT / 'bookkeeping.py')
        bk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bk)
        real = bk.Bookkeeping(self.db, self.root)
        self.store = m.Submissions(self.db, real)
        result = self.submit(filename='../../scan.png')
        records = real.list('owner')
        self.assertEqual(len(records), 1)
        self.assertEqual(real.list('other'), [])
        self.assertEqual(records[0]['filename'], 'scan.png')
        self.assertNotIn(records[0]['id'], json.dumps(result))
        record = real.get('owner', records[0]['id'])
        self.assertEqual(record['sources'][0]['provider'], 'employee')
        self.assertEqual(record['sources'][0]['project'], 'Baustelle A')


class SubmissionOwnerRouteTests(unittest.TestCase):
    def test_owner_routes_require_ingress_owner_and_csrf(self):
        spec = importlib.util.spec_from_file_location('submission_owner_route_app', ROOT / 'app.py')
        app_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app_module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'options.json').write_text(json.dumps({'bookkeeping_enabled': True,
                'bookkeeping_ha_user_id': 'alice', 'submissions_public_url': 'https://uploads.example.test/submit'}))
            app = app_module.App(root, ROOT, dev=False)
            base = app_module.make_handler(app)
            class Ingress(base):
                def setup(self):
                    super().setup()
                    self.client_address = ('172.30.32.2', self.client_address[1])
            server = app_module.ThreadingHTTPServer(('127.0.0.1', 0), Ingress)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(path, method='GET', body=None, user='alice', csrf=True):
                headers = {'X-Remote-User-Id': user, 'Content-Type': 'application/json'}
                if csrf:
                    headers['X-Atlas-CSRF'] = app.csrf_token
                req = Request('http://127.0.0.1:' + str(server.server_port) + path, method=method,
                    data=json.dumps(body).encode() if body is not None else None, headers=headers)
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.loads(response.read())
                except HTTPError as exc:
                    return exc.code, json.loads(exc.read())
            try:
                route = '/api/submissions/access'
                self.assertEqual(request(route, 'POST', {'label': 'Techniker'}, csrf=False)[0], 403)
                self.assertEqual(request(route, 'POST', {'label': 'Techniker'}, user='bob')[0], 403)
                status, access = request(route, 'POST', {'label': 'Techniker'})
                self.assertEqual(status, 201)
                self.assertEqual(access['url'], 'https://uploads.example.test/submit#token=' + access['token'])
                self.assertEqual(request(route, user='bob')[0], 403)
                self.assertNotIn(access['token'], json.dumps(request(route)[1]))
                delete = route + '/' + access['id']
                self.assertEqual(request(delete, 'DELETE', csrf=False)[0], 403)
                self.assertEqual(request(delete, 'DELETE', user='bob')[0], 403)
                self.assertTrue(app.submissions.validate_access(access['token'])['valid'])
                self.assertEqual(request(delete, 'DELETE')[0], 200)
                self.assertFalse(app.submissions.validate_access(access['token'])['valid'])
            finally:
                server.shutdown()
                server.server_close()
                worker.join()


if __name__ == '__main__':
    unittest.main()
