"""Knowledge migrations, corrections, owner isolation and task context."""
import json
import unittest
from unittest.mock import patch
import test_backend as backend
module = backend.module


class KnowledgeTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown
    request = backend.BackendTests.request
    # Reuse the HTTP fixture, not its inherited tests.
    def test_knowledge_revision_search_and_conflict(self):
        _, raw = self.request('/api/memories', 'POST', {'text': 'Alte Angabe', 'source': 'Notiz', 'tags': ['Projekt Alpha']})
        note = json.loads(raw)['memory']
        self.assertEqual(json.loads(self.request('/api/memories?q=Alpha')[1])['memories'][0]['id'], note['id'])
        path = '/api/memories/' + str(note['id'])
        code, raw = self.request(path, 'PATCH', {'revision': 1, 'text': 'Korrigierte Angabe', 'source': 'Besprechung'})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['memory']['revision'], 2)
        self.assertEqual(self.request(path, 'PATCH', {'revision': 1, 'text': 'Veralteter Browser'})[0], 409)
        revisions = json.loads(self.request(path + '/revisions')[1])['revisions']
        self.assertEqual([r['text'] for r in revisions], ['Korrigierte Angabe', 'Alte Angabe'])
        reloaded = module.App(self.root, self.root, dev=True)
        self.assertEqual(len(reloaded.knowledge.history('dev', note['id'])), 2)
        self.assertIsNone(reloaded.knowledge.history('other', note['id']))
        self.assertIsNone(reloaded.knowledge.update('other', note['id'], {'revision': 2, 'text': 'Fremd'}))
        self.assertEqual(reloaded.knowledge.search('other', 'Alpha'), [])
        self.assertEqual(self.request(path, 'DELETE')[0], 200)
        self.assertEqual(self.request(path + '/revisions')[0], 404)
        with self.app.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM atlas_knowledge_revisions').fetchone()[0], 0)

    def test_link_validation_rollback_and_cleanup(self):
        note = self.app.knowledge.create('dev', {'text': 'Kundenwissen'})
        foreign = self.app.knowledge.create('other', {'text': 'Geheim'})
        self.assertEqual(self.request('/api/tasks', 'POST', {'title': 'Ungültig', 'knowledge_ids': [foreign['id']]})[0], 400)
        self.assertEqual(self.app.collection('tasks', 'dev'), [])
        code, raw = self.request('/api/tasks', 'POST', {'title': 'Projekt prüfen', 'knowledge_ids': [note['id']]})
        self.assertEqual(code, 201)
        task = json.loads(raw)['task']
        self.assertEqual(task['knowledge_ids'], [note['id']])
        path = '/api/tasks/' + str(task['id'])
        self.assertEqual(self.request(path, 'PATCH', {'done': True, 'knowledge_ids': [foreign['id']]})[0], 400)
        self.assertFalse(self.app.collection('tasks', 'dev')[0]['done'])
        self.assertEqual(self.request(path, 'PATCH', {'knowledge_ids': [True]})[0], 400)
        self.request('/api/memories/' + str(note['id']), 'DELETE')
        self.assertEqual(self.app.collection('tasks', 'dev')[0]['knowledge_ids'], [])

    def test_knowledge_csrf_and_input_bounds(self):
        note = self.app.knowledge.create('dev', {'text': 'Test'})
        self.assertEqual(self.request('/api/memories/' + str(note['id']), 'PATCH', {'revision': 1, 'text': 'Neu'}, token=False)[0], 403)
        for bad in (['x'] * 9, ['x' * 61], 'project', [1]):
            self.assertEqual(self.request('/api/memories', 'POST', {'text': 'Test', 'tags': bad})[0], 400)

    def test_chat_uses_corrected_knowledge_not_history(self):
        note = self.app.knowledge.create('dev', {'text': 'Alpha alt', 'source': 'Alt', 'tags': ['Projekt']})
        self.app.knowledge.update('dev', note['id'], {'revision': 1, 'text': 'Alpha aktuell'})
        with patch.object(self.app, 'generate', return_value={'reply': 'OK'}) as generate:
            self.app.chat('Alpha', 'dev')
            prompt = generate.call_args.args[0][0]['content']
            self.assertIn('Alpha aktuell', prompt)
            self.assertNotIn('Alpha alt', prompt)
            self.assertIn('revision', prompt)



    def test_task_link_retrieves_note_with_different_vocabulary(self):
        note = self.app.knowledge.create('dev', {'text': 'Montage nur dienstags', 'tags': ['Baustelle']})
        self.request('/api/tasks', 'POST', {'title': 'Projekt Alpha vorbereiten', 'knowledge_ids': [note['id']]})
        with patch.object(self.app, 'generate', return_value={'reply': 'OK'}) as generate:
            self.app.chat('Alpha vorbereiten', 'dev')
            self.assertIn('Montage nur dienstags', generate.call_args.args[0][0]['content'])
        with patch.object(self.app, 'generate', return_value={'reply': 'OK'}) as generate:
            self.app.chat('Alpha vorbereiten', 'other')
            self.assertNotIn('Montage nur dienstags', generate.call_args.args[0][0]['content'])

    def test_legacy_inserts_remain_readable(self):
        with self.app.db() as db:
            db.execute("INSERT INTO memories(user_id,text,source,created_at) VALUES ('dev','Altbestand','Telegram','2026-01-01')")
        reloaded = module.App(self.root, self.root, dev=True)
        note = reloaded.knowledge.search('dev', 'Altbestand')[0]
        self.assertEqual(note['revision'], 1)
        self.assertEqual(note['tags'], [])
        self.assertEqual(note['updated_at'], '2026-01-01')
        reloaded.knowledge.update('dev', note['id'], {'revision': 1, 'text': 'Aktualisiert'})
        self.assertEqual(reloaded.knowledge.history('dev', note['id'])[1]['text'], 'Altbestand')

    def test_chat_keeps_top_match_with_long_metadata_within_budget(self):
        for special in ('x', chr(1), '"'):
            with self.subTest(special=repr(special)):
                with self.app.db() as db:
                    db.execute('DELETE FROM memories')
                note = self.app.knowledge.create('dev', {
                    'text': 'Alpha ' + special * 1800,
                    'source': 'Quelle ' + special * 193,
                    'tags': [str(i) + special * 59 for i in range(8)]})
                with patch.object(self.app, 'generate', return_value={'reply': 'OK'}) as generate:
                    self.app.chat('Alpha', 'dev')
                    prompt = generate.call_args.args[0][0]['content']
                serialized = prompt.split('Bestätigte Notizen: ', 1)[1].split('\nOffene Aufgaben:', 1)[0]
                self.assertLessEqual(len(serialized), 1500)
                selected = json.loads(serialized)
                self.assertEqual(selected[0]['id'], note['id'])
                self.assertTrue(selected[0]['text'].startswith('Alpha'))
                self.assertEqual(selected[0]['revision'], 1)
                self.assertEqual(selected[0]['updated_at'], note['updated_at'])
                self.assertTrue(selected[0]['source'].startswith('Quelle'))
                self.assertTrue(selected[0]['excerpt'])
                self.assertTrue(selected[0]['metadata_excerpt'])
