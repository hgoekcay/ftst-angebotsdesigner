"""Routing/privacy boundaries and durable-job ingress integration."""
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

app_path = Path(__file__).parents[2] / 'ftst_atlas/app.py'
spec = importlib.util.spec_from_file_location('atlas_routing_app', app_path)
app_module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(app_path.parent))
try:
    spec.loader.exec_module(app_module)
finally:
    sys.path.remove(str(app_path.parent))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = app_module.App(self.root, self.root, dev=True)
        self.app.chat = Mock(return_value={'reply': 'Lokal', 'model': 'local-model'})

    def tearDown(self):
        self.app.jobs.stop()
        self.tmp.cleanup()

    def configure_online(self):
        self.app.online = app_module.OnlineClient({'online_enabled': True,
            'online_ha_user_id': 'alice', 'openai_api_key': 'sk-' + 'x' * 30}, self.app.db)
        self.app.online.answer = Mock(return_value={'reply': 'Online', 'online': True})

    def test_local_mode_never_contacts_online_even_with_research_keywords(self):
        self.configure_online()
        history = [{'role': 'user', 'content': 'Privater Verlauf'}]
        result = self.app.respond('Recherchiere aktuelle Produkte online', 'alice', history, mode='local')
        self.assertEqual(result['provider'], 'Lokal')
        self.app.online.answer.assert_not_called()
        self.app.chat.assert_called_once_with('Recherchiere aktuelle Produkte online', 'alice', history)

    def test_auto_research_routes_online_and_ordinary_question_stays_local(self):
        self.configure_online()
        for text in ['Aktuelle Ajax Produkte', 'Recherchiere den Hersteller', 'https://example.com', 'Vergleiche zwei Kameras']:
            with self.subTest(text=text):
                self.app.respond(text, 'alice', mode='auto')
                self.app.online.answer.assert_called_with('alice', text, context='', web=True)
        self.app.chat.assert_not_called()
        self.app.online.answer.reset_mock()
        self.app.respond('Formuliere eine freundliche Begrüßung', 'alice', mode='auto')
        self.app.online.answer.assert_not_called()
        self.app.chat.assert_called_once()

    def test_missing_online_access_does_not_fabricate_current_answer_locally(self):
        with patch.object(sys.modules['online_client'], '_request') as request:
            with self.assertRaises(app_module.OnlineError):
                self.app.respond('Was sind die neuesten Produkte?', 'alice', mode='auto')
            request.assert_not_called()
        self.app.chat.assert_not_called()

    def test_online_receives_no_implicit_history_memory_tasks_or_profile(self):
        self.configure_online()
        with self.app.db() as db:
            db.execute('INSERT INTO profiles VALUES (?,?)', ('alice', 'PRIVATE_PROFILE'))
            db.execute('INSERT INTO memories(user_id,text,source,created_at) VALUES (?,?,?,?)',
                       ('alice', 'PRIVATE_MEMORY', 'user', app_module.now()))
            db.execute('INSERT INTO tasks(user_id,title,created_at) VALUES (?,?,?)',
                       ('alice', 'PRIVATE_TASK', app_module.now()))
        self.app.respond('Eine Frage', 'alice', [{'role': 'user', 'content': 'PRIVATE_HISTORY'}], mode='online')
        self.app.online.answer.assert_called_once_with('alice', 'Eine Frage', context='', web=True)
        self.assertNotIn('PRIVATE_', str(self.app.online.answer.call_args))
        self.app.chat.assert_not_called()

    def test_profile_sharing_is_explicit_bounded_and_owner_scoped(self):
        self.configure_online()
        self.app.online_share_profile = True
        with self.app.db() as db:
            db.execute('INSERT INTO profiles VALUES (?,?)', ('alice', 'a' * 3000))
            db.execute('INSERT INTO profiles VALUES (?,?)', ('bob', 'BOB_PRIVATE'))
        self.app.respond('Eine Frage', 'alice', mode='online')
        self.assertEqual(self.app.online.answer.call_args.kwargs['context'], 'a' * 2000)
        self.assertNotIn('BOB_PRIVATE', str(self.app.online.answer.call_args))

    def test_auto_fallback_only_for_model_error_and_authorized_owner(self):
        self.configure_online()
        self.app.chat.side_effect = app_module.ModelError('Lokales Modell nicht bereit.')
        result = self.app.respond('Formuliere eine Begrüßung', 'alice', mode='auto')
        self.app.online.answer.assert_called_once_with('alice', 'Formuliere eine Begrüßung', context='', web=False)
        self.assertIn('Lokale Antwort fehlgeschlagen', result['routing_note'])
        self.app.online.answer.reset_mock()
        for user, mode in [('bob', 'auto'), ('alice', 'local')]:
            with self.subTest(user=user, mode=mode), self.assertRaises(app_module.ModelError):
                self.app.respond('Formuliere eine Begrüßung', user, mode=mode)
        self.app.online.answer.assert_not_called()

    def test_busy_or_unexpected_error_never_triggers_paid_fallback(self):
        self.configure_online()
        for error in [app_module.BusyError('Beschäftigt'), RuntimeError('internal')]:
            self.app.chat.side_effect = error
            with self.assertRaises(type(error)):
                self.app.respond('Formuliere eine Begrüßung', 'alice', mode='auto')
        self.app.online.answer.assert_not_called()

    def test_local_failure_without_configured_online_remains_local_error(self):
        self.app.chat.side_effect = app_module.ModelError('Lokales Modell nicht bereit.')
        with patch.object(self.app.online, 'answer') as online_answer:
            with self.assertRaises(app_module.ModelError):
                self.app.respond('Formuliere eine Begrüßung', 'alice', mode='auto')
            online_answer.assert_not_called()

    def test_invalid_mode_and_controlled_job_errors(self):
        self.configure_online()
        with self.assertRaises(ValueError):
            self.app.respond('Hallo', 'alice', mode='shell')
        self.app.chat.assert_not_called()
        self.app.online.answer.assert_not_called()
        self.app.chat.side_effect = app_module.BusyError('Bitte warten.')
        with self.assertRaisesRegex(app_module.JobError, 'Bitte warten'):
            self.app.execute_job('alice', {'message': 'Hallo', 'mode': 'local'})


class JobHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = app_module.App(self.root, self.root, dev=False)
        base = app_module.make_handler(self.app)
        class IngressHandler(base):
            def setup(self):
                super().setup()
                self.client_address = ('172.30.32.2', self.client_address[1])
        self.server = app_module.ThreadingHTTPServer(('127.0.0.1', 0), IngressHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.app.jobs.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, user='alice', payload=None, token=True):
        headers = {'X-Remote-User-Id': user, 'Content-Type': 'application/json'}
        if token:
            headers['X-Atlas-CSRF'] = self.app.csrf_token
        request = Request(self.url + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_submission_requires_csrf_and_owner_controls_reads(self):
        payload = {'message': 'private question', 'mode': 'local'}
        self.assertEqual(self.request('/api/jobs', payload=payload, token=False)[0], 403)
        self.assertEqual(self.request('/api/jobs', payload={**payload, 'mode': 'shell'})[0], 400)
        code, job = self.request('/api/jobs', payload=payload)
        self.assertEqual(code, 202)
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(self.request('/api/jobs/' + job['id'], user='bob')[0], 404)
        self.assertEqual(self.request('/api/jobs', user='bob')[1]['jobs'], [])
        self.assertNotIn('payload', self.request('/api/jobs/' + job['id'])[1])
        self.assertEqual(self.request('/api/jobs', payload=payload)[0], 503)

    def test_saved_queue_runs_after_reload_and_http_returns_result(self):
        code, job = self.request('/api/jobs', payload={'message': 'Hallo', 'mode': 'local'})
        self.assertEqual(code, 202)
        reloaded = app_module.App(self.root, self.root, dev=False)
        reached = threading.Event()
        def respond(message, user, history, mode):
            self.assertEqual((message, user, history, mode), ('Hallo', 'alice', [], 'local'))
            reached.set()
            return {'reply': 'Fertig', 'provider': 'Lokal'}
        reloaded.respond = respond
        reloaded.jobs.start()
        self.assertTrue(reached.wait(3))
        reloaded.jobs.stop()
        code, result = self.request('/api/jobs/' + job['id'])
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['result']['reply'], 'Fertig')
        self.assertEqual(self.request('/api/jobs/' + job['id'], user='bob')[0], 404)


if __name__ == '__main__':
    unittest.main()
