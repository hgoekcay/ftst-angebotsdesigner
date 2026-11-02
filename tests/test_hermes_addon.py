import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parents[1] / 'ftst_hermes'
spec = importlib.util.spec_from_file_location('ftst_hermes_server', HERE / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class HermesIngress(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = 'a' * 32
        self.pilot = server.Pilot({'owner_ha_user_id': self.owner}, self.root)
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.http.pilot = self.pilot
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path, message=None, owner=None, csrf=None):
        headers = {'Content-Type': 'application/json'}
        if owner is not None:
            headers['X-Remote-User-Id'] = owner
        if csrf is not None:
            headers['X-FTST-CSRF'] = csrf
        url = f'http://127.0.0.1:{self.http.server_port}{path}'
        try:
            with urlopen(Request(url, headers=headers, data=json.dumps({'message': message}).encode() if message is not None else None), timeout=5) as resp:
                return resp.status, resp.read()
        except HTTPError as err:
            return err.code, err.read()

    def test_forged_identity_on_direct_request_denied(self):
        self.assertEqual(self.request('/state', owner=self.owner)[0], 403)

    @patch.object(server, 'INGRESS', '127.0.0.1')
    def test_owner_and_csrf_boundaries(self):
        self.assertEqual(self.request('/state', owner='other')[0], 403)
        code, payload = self.request('/state', owner=self.owner)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(payload)['tasks'])
        self.assertEqual(self.request('/turn', 'Test', self.owner, 'wrong')[0], 403)
        self.assertEqual(self.request('/turn', '', self.owner, json.loads(payload)['csrf'])[0], 400)
        self.http.pilot = server.Pilot({}, self.root)
        self.assertEqual(self.request('/state', owner=self.owner)[0], 403)
        self.assertIn(b'FTST Hermes', self.request('/', owner=self.owner)[1])

    @patch.object(server, 'INGRESS', '127.0.0.1')
    def test_cli_lifecycle_and_error_isolation(self):
        cli = self.root / 'fake-hermes'
        cli.write_text("""#!/usr/bin/env python3
import json, sys
assert '--format' in sys.argv and 'stream-json' in sys.argv
assert sys.argv[sys.argv.index('--toolsets') + 1] == 'bot_room'
query = sys.stdin.read()
if query == 'Folgefrage':
    assert sys.argv[sys.argv.index('--resume') + 1] == 'session_01'
if query == 'Fehler':
    print('SECRET-SENTINEL', file=sys.stderr)
    raise SystemExit(3)
print(json.dumps({'type':'result', 'session_id':'session_01', 'exit_code':0, 'text':'Antwort '+query}))
""")
        cli.chmod(0o700)
        token = json.loads(self.request('/state', owner=self.owner)[1])['csrf']
        with patch.object(server, 'CLI', str(cli)):
            for msg in ['Hallo', 'Folgefrage']:
                code, raw = self.request('/turn', msg, self.owner, token)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(raw)['reply'], 'Antwort ' + msg)
            code, raw = self.request('/turn', 'Fehler', self.owner, token)
            self.assertEqual(code, 502)
            self.assertNotIn(b'SECRET-SENTINEL', raw)
        self.assertEqual((self.pilot.home / 'ftst-session').read_text(), 'session_01')


if __name__ == '__main__':
    unittest.main()
