import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('atlas_live_test', Path(__file__).parents[2] / 'ftst_atlas/frontdesk_live.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
KEY = 'sk-' + 'a' * 40
OPTIONS = {'live_enabled': True, 'openai_api_key': KEY, 'online_ha_user_id': 'owner',
           'live_daily_limit': 2, 'live_max_seconds': 600}
SDP = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n'
RESULT = {'session': {'id': 'live_session_1', 'api_key': KEY, 'instructions': 'private'},
          'transport': {'sdp': SDP}, 'secret': KEY}


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = str(Path(self.tmp.name) / 'db')
        self.db = lambda: sqlite3.connect(path, timeout=10)
        self.timer_patch = patch.object(m.threading, 'Timer')
        self.timer = self.timer_patch.start()
        self.client = m.FrontDeskLive(OPTIONS, self.db)

    def tearDown(self):
        self.timer_patch.stop()
        self.tmp.cleanup()

    def test_disabled_foreign_and_invalid_config_do_not_call_provider(self):
        with patch.object(m, '_request') as request:
            for options, user in [(dict(OPTIONS, live_enabled=False), 'owner'),
                                  (OPTIONS, 'other'), (dict(OPTIONS, openai_api_key=''), 'owner'),
                                  (dict(OPTIONS, live_max_seconds=True), 'owner'),
                                  (dict(OPTIONS, live_daily_limit=0), 'owner')]:
                with self.subTest(options=options):
                    client = m.FrontDeskLive(options, self.db)
                    self.assertFalse(client.status(user)['enabled'])
                    with self.assertRaises(m.LiveError):
                        client.create(user, SDP)
            request.assert_not_called()

    def test_only_sdp_and_id_returned_and_prompt_has_no_confirmation_tool(self):
        with patch.object(m, '_request', return_value=RESULT) as request:
            result = self.client.create('owner', SDP)
        self.assertEqual(result, {'session': {'id': 'live_session_1'}, 'transport': {'sdp': SDP}, 'max_seconds': 600})
        self.assertNotIn(KEY, json.dumps(result))
        payload = request.call_args.args[1]
        self.assertEqual(payload['session']['model'], 'gpt-live-1')
        backend = payload['session']['delegation']['responses']
        self.assertEqual(backend['model'], 'gpt-6-luna')
        self.assertFalse(backend['parallel_tool_calls'])
        self.assertEqual({t['name'] for t in backend['tools']}, {'check_availability', 'propose_appointment', 'cancel_proposal', 'list_bookings', 'end_conversation'})
        self.assertNotIn('session.update', payload['session']['client']['data_channel']['allowed_client_events'])
        self.assertTrue(self.client.active_for('owner', 'live_session_1'))
        self.assertFalse(self.client.active_for('other', 'live_session_1'))
        self.timer.assert_called_once()
        self.assertTrue(self.timer.return_value.daemon)

    def test_active_duplicate_is_blocked_and_no_second_paid_create(self):
        with patch.object(m, '_request', return_value=RESULT) as request:
            self.client.create('owner', SDP)
            with self.assertRaises(m.LiveError):
                self.client.create('owner', SDP)
        self.assertEqual(request.call_count, 1)

    def test_failed_network_attempt_is_counted_and_does_not_retry(self):
        with patch.object(m, '_request', side_effect=RuntimeError(KEY)) as request:
            with self.assertRaises(m.LiveError) as caught:
                self.client.create('owner', SDP)
            self.assertNotIn(KEY, str(caught.exception))
            with self.assertRaises(m.LiveError):
                self.client.create('owner', SDP)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.client.status('owner')['used'], 1)
        self.assertEqual(self.client.status('other')['used'], 0)

    def test_daily_attempt_limit_survives_new_instance(self):
        with patch.object(m, '_request', side_effect=[RESULT, {'session': {'id': 'live_session_2'}, 'transport': {'sdp': SDP}}]), patch.object(m, '_close_remote', return_value=True):
            self.client.create('owner', SDP)
            self.client.close('owner', 'live_session_1')
            self.client.create('owner', SDP)
            self.client.close('owner', 'live_session_2')
            client = m.FrontDeskLive(OPTIONS, self.db)
            with self.assertRaisesRegex(m.LiveError, 'Startlimit'):
                client.create('owner', SDP)

    def test_invalid_sdp_not_counted(self):
        for value in ['', 'http://evil', None, SDP * 10000, SDP + '\0']:
            with self.assertRaises(ValueError):
                self.client.create('owner', value)
        self.assertEqual(self.client.status('owner')['used'], 0)

    def test_close_owner_checked_and_confirmation_requires_provider_event(self):
        with patch.object(m, '_request', return_value=RESULT):
            self.client.create('owner', SDP)
        with patch.object(m, '_close_remote', return_value=False) as close:
            with self.assertRaises(m.LiveError):
                self.client.close('other', 'live_session_1')
            close.assert_not_called()
            result = self.client.close('owner', 'live_session_1')
            self.assertFalse(result['released'])
            self.assertEqual(result['provider_finalization'], 'unconfirmed')
            self.assertFalse(self.client.active_for('owner', 'live_session_1'))
        with patch.object(m, '_close_remote', return_value=True) as close:
            result = self.client.close('owner', 'live_session_1')
            self.assertTrue(result['released'])
            self.client.close('owner', 'live_session_1')
            self.assertEqual(close.call_count, 1)

    def test_server_watchdog_uses_close_and_retries_only_once(self):
        with patch.object(m, '_request', return_value=RESULT):
            self.client.create('owner', SDP)
        callback = self.timer.call_args.args[1]
        with patch.object(m, '_close_remote', return_value=False) as close:
            callback()
            self.assertEqual(close.call_count, 1)
            retry_callback = self.timer.call_args.args[1]
            count = self.timer.call_count
            retry_callback()
            self.assertEqual(close.call_count, 2)
            self.assertEqual(self.timer.call_count, count)

    def test_known_remote_id_with_bad_answer_schedules_immediate_cleanup(self):
        with patch.object(m, '_request', return_value={'session': {'id': 'live_bad'}, 'transport': {'sdp': 'bad'}}):
            with self.assertRaises(m.LiveError):
                self.client.create('owner', SDP)
        self.assertEqual(self.timer.call_args.args[0], 0)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT session_id FROM atlas_live_sessions').fetchone()[0], 'live_bad')

    def test_client_closed_releases_local_lease_without_claiming_provider_confirmation(self):
        with patch.object(m, '_request', return_value=RESULT):
            self.client.create('owner', SDP)
        with patch.object(m, '_close_remote') as close:
            result = self.client.close('owner', 'live_session_1', client_closed=True)
            self.assertTrue(result['released'])
            self.assertEqual(result['provider_finalization'], 'unconfirmed')
            close.assert_not_called()
        self.assertFalse(self.client.active_for('owner', 'live_session_1'))
        self.timer.return_value.cancel.assert_not_called()
        with patch.object(m, '_request', return_value={'session': {'id': 'live_session_2'}, 'transport': {'sdp': SDP}}):
            self.client.create('owner', SDP)
        with patch.object(m, '_close_remote', return_value=False):
            self.client.close('owner', 'live_session_1')
        with self.db() as db:
            self.assertEqual(db.execute("SELECT state FROM atlas_live_sessions WHERE session_id='live_session_1'").fetchone()[0], 'client_closed')

    def test_provider_raw_error_is_redacted_and_fixed_destination(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 401
        with patch.object(m.http.client, 'HTTPSConnection', return_value=connection) as https:
            with self.assertRaises(m.LiveError) as caught:
                m._request(KEY, {})
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(https.call_args.args, ('api.openai.com', 443))
        self.assertEqual(connection.request.call_args.args[:2], ('POST', '/v1/live/sessions'))
        connection.close.assert_called_once()

    def test_sideband_is_fixed_url_and_requires_session_closed(self):
        websocket = MagicMock()
        websocket.create_connection.return_value.recv.side_effect = [json.dumps({'type': 'session.usage.updated'}), json.dumps({'type': 'session.closed'})]
        with patch.dict('sys.modules', {'websocket': websocket}):
            self.assertTrue(m._close_remote(KEY, 'live_session_1'))
        self.assertEqual(websocket.create_connection.call_args.args[0], 'wss://api.openai.com/v1/live/sessions/live_session_1/attach')
        self.assertEqual(websocket.create_connection.call_args.kwargs['redirect_limit'], 0)
        websocket.create_connection.return_value.send.assert_called_once_with(json.dumps({'type': 'session.close'}))
        websocket.create_connection.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
