"""Public callback cannot access application data or activate a grant."""
import http.client
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).parents[2] / 'ftst_atlas'))
from google_callback import CallbackServer


class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.oauth = Mock()
        self.server = CallbackServer(('127.0.0.1', 0), self.oauth)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, method='GET'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            conn.request(method, path)
            res = conn.getresponse()
            return res.status, dict(res.getheaders()), res.read().decode()
        finally:
            conn.close()

    def test_callback_stages_only_and_never_echoes_secrets(self):
        code, headers, body = self.request('/oauth/google/callback?state=secret-state&code=secret-code')
        self.assertEqual(code, 200)
        self.oauth.callback.assert_called_once_with({'state': 'secret-state', 'code': 'secret-code'})
        self.oauth.finish.assert_not_called()
        self.assertNotIn('secret', body)
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('default-src', headers['Content-Security-Policy'])

    def test_no_application_routes_and_no_post(self):
        for path in ('/', '/api/status', '/api/google/finish', '/api/frontdesk/confirm', '/oauth/google/callback/extra'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/oauth/google/callback', 'POST')[0], 405)
        self.oauth.callback.assert_not_called()

    def test_duplicate_parameters_and_failed_exchange_safe(self):
        self.assertEqual(self.request('/oauth/google/callback?state=a&state=b')[0], 400)
        self.oauth.callback.assert_not_called()
        self.oauth.callback.side_effect = ValueError('provider secret')
        code, _, body = self.request('/oauth/google/callback?state=a&code=b')
        self.assertEqual(code, 400)
        self.assertNotIn('provider secret', body)
