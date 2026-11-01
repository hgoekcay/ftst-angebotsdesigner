import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('google_oauth_test_module', Path(__file__).parents[2] / 'ftst_atlas/google_oauth.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.options = {'calendar_enabled': True, 'calendar_provider': 'google', 'calendar_ha_user_id': 'owner',
            'google_client_id': '1234567890-example.apps.googleusercontent.com', 'google_client_secret': 'test-client-secret',
            'google_redirect_uri': 'https://calendar.example.com/oauth/google/callback'}
        self.oauth = m.GoogleOAuth(self.options, self.temp.name)
        self.tokens = {'access_token': 'access-secret', 'refresh_token': 'refresh-secret', 'token_type': 'Bearer',
                       'expires_in': 3600, 'scope': ' '.join(m.SCOPES)}

    def begin(self):
        return parse_qs(urlsplit(self.oauth.begin('owner')['authorization_url']).query)

    def connect(self):
        flow = self.begin()
        with patch.object(m, '_exchange', return_value=self.tokens):
            self.oauth.callback({'state': flow['state'][0], 'code': 'test-code'})
        self.oauth.finish('owner')

    def test_pkce_stages_before_owner_finish(self):
        flow = self.begin()
        self.assertEqual(flow['code_challenge_method'], ['S256'])
        self.assertEqual(flow['access_type'], ['offline'])
        with patch.object(m, '_exchange', return_value=self.tokens) as exchange:
            self.assertEqual(self.oauth.callback({'state': flow['state'][0], 'code': 'test-code'}), {'pending': True})
            self.assertIn('code_verifier', exchange.call_args.args[0])
        status = self.oauth.status('owner')
        self.assertTrue(status['pending'])
        self.assertFalse(status['connected'])
        with self.assertRaises(m.GoogleOAuthError):
            self.oauth.access_token('owner')
        self.oauth.finish('owner')
        self.assertEqual(self.oauth.access_token('owner'), 'access-secret')
        self.assertTrue(self.oauth.status('owner')['connection_id'])
        self.assertNotIn('secret', str(self.oauth.status('owner')))

    def test_wrong_owner_and_wrong_state_do_not_consume_flow(self):
        flow = self.begin()
        with self.assertRaises(m.GoogleOAuthError):
            self.oauth.begin('other')
        with self.assertRaises(m.GoogleOAuthError):
            self.oauth.callback({'state': 'wrong', 'code': 'code'})
        with patch.object(m, '_exchange', return_value=self.tokens):
            self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
        with self.assertRaises(m.GoogleOAuthError):
            self.oauth.finish('other')
        self.assertFalse(self.oauth.status('other')['pending'])
        self.oauth.finish('owner')
        with self.assertRaises(m.GoogleOAuthError):
            self.oauth.access_token('other')

    def test_callback_replay_and_failure_are_single_attempt(self):
        flow = self.begin()
        with patch.object(m, '_exchange', side_effect=m.GoogleOAuthError('Unavailable')) as exchange:
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
            self.assertEqual(exchange.call_count, 1)

    def test_expired_flow_and_pending(self):
        flow = self.begin()
        with patch.object(m.time, 'time', return_value=m.time.time() + 601):
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
        flow = self.begin()
        with patch.object(m, '_exchange', return_value=self.tokens):
            self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
        with patch.object(m.time, 'time', return_value=m.time.time() + 601):
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.finish('owner')

    def test_missing_scope_rejected(self):
        flow = self.begin()
        with patch.object(m, '_exchange', return_value={**self.tokens, 'scope': 'openid'}):
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.callback({'state': flow['state'][0], 'code': 'code'})
        self.assertFalse(self.oauth.status('owner')['connected'])

    def test_restart_refresh_and_private_file(self):
        self.connect()
        path = Path(self.temp.name) / 'google-oauth.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        restored = m.GoogleOAuth(self.options, self.temp.name)
        with patch.object(m.time, 'time', return_value=m.time.time() + 4000), patch.object(m, '_exchange', return_value={
                'access_token': 'new-secret', 'token_type': 'Bearer', 'expires_in': 3600}) as exchange:
            self.assertEqual(restored.access_token('owner'), 'new-secret')
            self.assertEqual(exchange.call_args.args[0]['grant_type'], 'refresh_token')
        self.assertEqual(m.GoogleOAuth(self.options, self.temp.name).access_token('owner'), 'new-secret')

    def test_configuration_binding_and_disconnect(self):
        self.connect()
        changed = m.GoogleOAuth({**self.options, 'calendar_ha_user_id': 'other'}, self.temp.name)
        self.assertFalse(changed.status('other')['connected'])
        with self.assertRaises(m.GoogleOAuthError):
            changed.access_token('other')
        self.oauth.disconnect('owner')
        self.assertFalse(m.GoogleOAuth(self.options, self.temp.name).status('owner')['connected'])

    def test_reconnect_changes_connection_id(self):
        self.connect()
        before = self.oauth.status('owner')['connection_id']
        self.connect()
        self.assertNotEqual(before, self.oauth.status('owner')['connection_id'])

    def test_reject_invalid_redirect_and_client_id(self):
        for redirect in ('http://example.com/oauth/google/callback', 'https://x/a', 'https://user@x/oauth/google/callback',
                         'https://x/oauth/google/callback?x=1', 'https://x:444/oauth/google/callback'):
            self.assertFalse(m.GoogleOAuth({**self.options, 'google_redirect_uri': redirect}, self.temp.name).configured)
        self.assertFalse(m.GoogleOAuth({**self.options, 'google_client_id': 'project-number'}, self.temp.name).configured)

    def test_refresh_is_serialized(self):
        self.connect()
        self.oauth._data['grant']['expires_at'] = 0
        results = []
        with patch.object(m, '_exchange', return_value={
                'access_token': 'new-secret', 'token_type': 'Bearer', 'expires_in': 3600}) as exchange:
            threads = [threading.Thread(target=lambda: results.append(self.oauth.access_token('owner'))) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            self.assertEqual(results, ['new-secret'] * 4)
            self.assertEqual(exchange.call_count, 1)

    def test_exchange_refuses_redirect_without_leaking_body(self):
        from unittest.mock import Mock
        conn = Mock()
        conn.getresponse.return_value.status = 302
        with patch.object(m.http.client, 'HTTPSConnection', return_value=conn) as constructor:
            with self.assertRaises(m.GoogleOAuthError) as caught:
                m._exchange({'client_secret': 'DO-NOT-LEAK'})
            self.assertNotIn('DO-NOT-LEAK', str(caught.exception))
            self.assertEqual(constructor.call_args.args[:2], ('oauth2.googleapis.com', 443))
            self.assertEqual(conn.request.call_count, 1)
            conn.getresponse.return_value.read1.assert_not_called()
            conn.close.assert_called_once()

    def test_denial_consumes_flow_without_exchange(self):
        flow = self.begin()
        with patch.object(m, '_exchange') as exchange:
            with self.assertRaises(m.GoogleOAuthError):
                self.oauth.callback({'state': flow['state'][0], 'error': 'access_denied'})
            exchange.assert_not_called()
        self.assertFalse(self.oauth.status('owner')['pending'])


if __name__ == '__main__':
    unittest.main()
