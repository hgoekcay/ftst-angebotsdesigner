"""Voice Ingress endpoints reject untrusted identity/framing before upload."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch

import unittest
import tempfile

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    spec = importlib.util.spec_from_file_location('atlas_frontdesk_http_test', ROOT / 'app.py')
    appmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(appmod)
    from submissions_server import _Server
finally:
    sys.path.remove(str(ROOT))



def request(server, path='/api/voice/transcribe', body=b'audio', user='owner', csrf=True, extra=None, method='POST'):
    app, port = server
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    headers = {'X-Remote-User-Id': user, 'Content-Type': 'application/json'}
    if csrf:
        headers['X-Atlas-CSRF'] = app.csrf_token
    headers.update(extra or {})
    try:
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def call(server, action, data, **kwargs):
    code, _, raw = request(server, '/api/frontdesk/' + action, json.dumps(data).encode(), **kwargs)
    return code, json.loads(raw)


class FrontDeskHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        app = appmod.App(Path(self.temp.name), dev=False)
        base = appmod.make_handler(app)
        class Ingress(base):
            def setup(self):
                super().setup()
                self.client_address = ('172.30.32.2', self.client_address[1])
        self.http = appmod.ThreadingHTTPServer(('127.0.0.1', 0), Ingress)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.server = (app, self.http.server_port)

    def tearDown(self):
        self.server[0].jobs.stop()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def test_demo_confirmation_and_owner_isolation(self):
        server = self.server
        code, _, raw = request(server, '/api/frontdesk/state', body=None, method='GET')
        assert code == 200
        state = json.loads(raw)
        assert state['demo'] and not state['live']['enabled']
        slot = state['available'][0]['id']
        code, result = call(server, 'propose', {'slot_id': slot, 'name': 'Demo Visitor'})
        assert code == 200 and result['state']['bookings'] == []
        pid = result['result']['id']
        assert call(server, 'confirm', {'proposal_id': pid})[0] == 400
        assert call(server, 'confirm', {'proposal_id': pid, 'confirmed': True}, csrf=False)[0] == 403
        assert call(server, 'confirm', {'proposal_id': pid, 'confirmed': True}, user='other')[0] == 409
        for _ in range(2):
            code, result = call(server, 'confirm', {'proposal_id': pid, 'confirmed': True})
            assert code == 200 and len(result['state']['bookings']) == 1
        assert all(s['id'] != slot for s in result['state']['available'])


    def test_model_tool_cannot_confirm(self):
        server = self.server
        app, _ = server
        with patch.object(app.frontdesk, 'active_for', return_value=True):
            code, _ = call(server, 'tool', {'session_id': 'fake', 'name': 'confirm', 'arguments': {'confirmed': True}})
            assert code == 400
        assert call(server, 'tool', {'session_id': 'fake', 'name': 'list_bookings', 'arguments': {}})[0] == 403


    def test_disabled_live_cannot_create_session(self):
        server = self.server
        assert call(server, 'session', {'sdp': 'v=0\r\n'})[0] == 503
        assert call(server, 'session', {'sdp': 'v=0\r\n'}, csrf=False)[0] == 403


    def test_local_assets_served(self):
        server = self.server
        for name in ['frontdesk.js', 'frontdesk.css']:
            code, headers, raw = request(server, '/' + name, body=None, method='GET')
            assert code == 200 and raw
            assert 'no-store' in headers['Cache-Control']

    def test_real_calendar_failure_blocks_paid_session(self):
        app, _ = self.server
        app.calendar_enabled = True
        with patch.object(app.appointments, 'state', return_value={'demo': False, 'provider_status': {'availability_verified': False}}), patch.object(app.frontdesk, 'create') as create:
            assert call(self.server, 'session', {'sdp': 'v=0\r\n'})[0] == 503
            create.assert_not_called()

    def test_reconciliation_is_csrf_protected_and_has_no_model_tool(self):
        app, _ = self.server
        app.calendar_enabled = True
        with patch.object(app.appointments, 'reconcile', create=True, return_value={'status': 'unknown'}) as reconcile:
            assert call(self.server, 'reconcile', {'proposal_id': 'p'}, csrf=False)[0] == 403
            reconcile.assert_not_called()
            code, result = call(self.server, 'reconcile', {'proposal_id': 'p'})
            assert code == 200 and result['result']['status'] == 'unknown'
            reconcile.assert_called_once_with('owner', 'p')

    def test_google_setup_is_owner_and_csrf_gated(self):
        app, _ = self.server
        code, _, raw = request(self.server, '/api/google/status', body=None, method='GET')
        assert code == 200 and not json.loads(raw)['oauth']['connected']
        assert request(self.server, '/api/google/begin', b'{}', csrf=False)[0] == 403
        assert request(self.server, '/api/google/begin', b'{}', user='other')[0] == 503
        assert request(self.server, '/api/google/finish', b'{}', user='other')[0] == 503
        assert request(self.server, '/api/google/select', b'{"calendar_id":"private"}', user='other')[0] == 503

    def test_google_setup_only_post_and_no_callback_in_ingress(self):
        assert request(self.server, '/api/google/begin', b'{}', method='PUT')[0] == 405
        assert request(self.server, '/oauth/google/callback?code=example&state=example', body=None, method='GET')[0] == 404
