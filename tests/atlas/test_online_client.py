import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('atlas_online_test', Path(__file__).parents[2] / 'ftst_atlas/online_client.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
KEY = 'sk-' + 'a' * 40
OPTIONS = {'online_enabled': True, 'openai_api_key': KEY, 'online_ha_user_id': 'owner', 'online_daily_limit': 2}


def response(text='Eine Antwort', annotations=None):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': annotations or []}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 3}}


def web_response():
    value = response(annotations=[{'type': 'url_citation', 'url': 'https://example.com/source',
                                  'title': 'Quelle', 'start_index': 0, 'end_index': 3}])
    value['output'].insert(0, {'type': 'web_search_call', 'status': 'completed'})
    return value


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'atlas.sqlite3')
        self.db = lambda: sqlite3.connect(self.path, timeout=10)
        self.client = m.OnlineClient(OPTIONS, self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_missing_key_foreign_owner_never_contact_provider(self):
        with patch.object(m, '_request') as request:
            for options, owner in [(dict(OPTIONS, online_enabled=False), 'owner'),
                                   (dict(OPTIONS, openai_api_key=''), 'owner'),
                                   (OPTIONS, 'other'), (dict(OPTIONS, online_daily_limit=True), 'owner')]:
                client = m.OnlineClient(options, self.db)
                self.assertFalse(client.status(owner)['enabled'])
                with self.assertRaises(m.OnlineError):
                    client.answer(owner, 'Hallo')
                self.assertNotIn(KEY, json.dumps(client.status(owner)))
            request.assert_not_called()
        self.assertEqual(self.client.status('other')['used'], 0)
        self.assertFalse(self.client.status('other')['configured'])

    def test_payload_uses_only_supplied_context_store_false_and_no_exec_tools(self):
        with patch.object(m, '_request', return_value=web_response()) as request:
            result = self.client.answer('owner', 'Frage', 'ausdrücklicher Kontext', web=True)
            key, payload = request.call_args.args
            self.assertEqual(key, KEY)
            self.assertFalse(payload['store'])
            self.assertEqual(payload['max_output_tokens'], 1500)
            self.assertEqual(payload['max_tool_calls'], 2)
            self.assertEqual(payload['tool_choice'], 'required')
            self.assertEqual(payload['tools'], [{'type': 'web_search', 'search_context_size': 'low'}])
            self.assertEqual(json.loads(payload['input']), {'frage': 'Frage', 'ausdruecklich_uebergebener_kontext': 'ausdrücklicher Kontext'})
            self.assertEqual(result['provider'], 'OpenAI')
            self.assertEqual(result['reply'], 'Eine Antwort')
        self.assertEqual(self.client.status('owner')['used'], 1)
        with self.db() as db:
            row = db.execute('SELECT outcome,input_tokens,output_tokens FROM online_usage').fetchone()
            self.assertEqual(row, ('completed', 10, 3))
            all_data = str(db.execute('SELECT * FROM online_usage').fetchall())
        self.assertNotIn('Frage', all_data)
        self.assertNotIn('Kontext', all_data)
        self.assertNotIn(KEY, all_data)

    def test_limit_persists_and_failures_count_without_retry(self):
        with patch.object(m, '_request', side_effect=ValueError('credential ' + KEY)) as request:
            for _ in range(2):
                with self.assertRaises(m.OnlineError) as caught:
                    self.client.answer('owner', 'Frage')
                self.assertNotIn(KEY, str(caught.exception))
            restarted = m.OnlineClient(OPTIONS, self.db)
            self.assertEqual(restarted.status('owner')['used'], 2)
            with self.assertRaises(m.OnlineError):
                restarted.answer('owner', 'Frage')
            self.assertEqual(request.call_count, 2)
        with patch.object(m, 'utc_day', return_value='2099-01-01'), patch.object(m, '_request', return_value=response()):
            self.assertEqual(self.client.status('owner')['used'], 0)
            self.client.answer('owner', 'Frage', web=False)
            self.assertEqual(self.client.status('owner')['used'], 1)

    def test_concurrent_calls_cannot_exceed_limit(self):
        errors = []
        def run():
            try:
                self.client.answer('owner', 'Parallel', web=False)
            except m.OnlineError:
                errors.append(True)
        with patch.object(m, '_request', return_value=response()) as request:
            threads = [threading.Thread(target=run) for _ in range(6)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(request.call_count, 2)
        self.assertEqual(len(errors), 4)
        self.assertEqual(self.client.status('owner')['used'], 2)

    def test_invalid_requests_do_not_consume_quota(self):
        with patch.object(m, '_request') as request:
            for message, context, web in [('', '', True), ('x' * 2001, '', True),
                                          ('x', 'y' * 4001, True), ('x', '', 'yes')]:
                with self.assertRaises(m.OnlineError):
                    self.client.answer('owner', message, context, web)
            request.assert_not_called()
        self.assertEqual(self.client.status('owner')['used'], 0)

    def test_only_complete_assistant_output_is_returned(self):
        for value in [[], None, {'status': 'incomplete', 'output': []},
                      {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': 'PRIVATE'}]},
                      {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'in_progress', 'content': []}]}]:
            with self.subTest(value=value), self.assertRaises(m.OnlineError):
                m._parse(value)
        value = response()
        value['output'].insert(0, {'type': 'reasoning', 'summary': 'PRIVATE'})
        self.assertNotIn('PRIVATE', json.dumps(m._parse(value)))

    def test_sources_validate_urls_offsets_and_multiblock_positions(self):
        valid = {'type': 'url_citation', 'url': 'https://example.com/source', 'title': 'Quelle', 'start_index': 0, 'end_index': 3}
        unsafe = [dict(valid, url=url) for url in ['javascript:alert(1)', 'https://user:pass@example.com', 'http://127.0.0.1/a', 'http://localhost/a', 'https://example.com/\n']]
        value = response('abc', [valid] + unsafe + [dict(valid, end_index=100), dict(valid, start_index=True)])
        value['output'][0]['content'].append({'type': 'output_text', 'text': 'def', 'annotations': [valid]})
        result = m._parse(value)
        self.assertEqual(result['reply'], 'abc\n\ndef')
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(result['sources'][1]['start_index'], 5)

    def test_requested_web_requires_completed_search_and_safe_sources(self):
        no_sources = response()
        no_sources['output'].insert(0, {'type': 'web_search_call', 'status': 'completed'})
        no_search = web_response()
        no_search['output'].pop(0)
        for value in [no_sources, no_search]:
            with patch.object(m, '_request', return_value=value), self.assertRaises(m.OnlineError):
                self.client.answer('owner', 'Was ist aktuell?', web=True)
        self.assertEqual(self.client.status('owner')['used'], 2)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM online_usage WHERE outcome='failed'").fetchone()[0], 2)

    def test_transport_pin_no_redirects_safe_errors_and_response_limit(self):
        for status, length, body in [(302, None, b''), (401, None, KEY.encode()),
                                     (200, str(m.MAX_RESPONSE + 1), b''), (200, '100', b'{}')]:
            connection = MagicMock()
            result = connection.getresponse.return_value
            result.status = status
            result.getheader.side_effect = lambda key, default=None: 'application/json' if key == 'Content-Type' else length
            result.read1.side_effect = [body, b'']
            with patch.object(m.http.client, 'HTTPSConnection', return_value=connection) as factory:
                with self.assertRaises(m.OnlineError) as caught:
                    m._request(KEY, {})
                self.assertNotIn(KEY, str(caught.exception))
                self.assertEqual(factory.call_args.args, ('api.openai.com', 443))
                self.assertEqual(connection.request.call_args.args, ('POST', '/v1/responses'))
                connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
