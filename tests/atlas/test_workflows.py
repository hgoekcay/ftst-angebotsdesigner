import io
import json
import unittest
import zipfile
from unittest.mock import patch
import test_backend as backend


class WorkflowTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown
    request = backend.BackendTests.request

    def enable(self):
        self.app.bookkeeping_sync.owner = 'dev'
        self.app.bookkeeping_sync.enabled = True

    def submit(self, kind='briefing', **kwargs):
        code, raw = self.request('/api/workflows', 'POST', dict(workflow=kind, **kwargs))
        self.assertEqual(code, 202, raw)
        return json.loads(raw)

    def test_catalog_validation_and_csrf(self):
        code, raw = self.request('/api/workflows/catalog')
        self.assertEqual(code, 200)
        self.assertEqual([x['enabled'] for x in json.loads(raw)['workflows']], [True, False])
        self.assertEqual(self.request('/api/workflows', 'POST', {'workflow': 'briefing'}, token=False)[0], 403)
        for data in ({'workflow':'shell'}, {'workflow':[]}, {'workflow':'briefing','command':'x'}, {'workflow':'bookkeeping','month':'2026-10'}):
            self.assertEqual(self.request('/api/workflows', 'POST', data)[0], 400)
        self.enable()
        for month in ('2026-13','0000-01',None, ['2026-10']):
            self.assertEqual(self.request('/api/workflows', 'POST', {'workflow':'bookkeeping','month':month})[0], 400)

    def test_briefing_scope_and_durable_steps(self):
        self.request('/api/tasks', 'POST', {'title':'Eigene Aufgabe'})
        with self.app.db() as db:
            db.execute("INSERT INTO tasks(user_id,title,done,created_at) VALUES('other','Fremdes Geheimnis',0,'now')")
        job = self.submit()
        self.assertEqual([s['status'] for s in job['steps']], ['pending']*4)
        self.app.jobs._process_one()
        job = self.app.jobs.get('dev',job['id'])
        self.assertEqual(job['status'],'completed')
        self.assertEqual([s['status'] for s in job['steps']], ['completed']*4)
        self.assertIn('Eigene Aufgabe',job['result']['reply'])
        self.assertNotIn('Fremdes Geheimnis',job['result']['reply'])
        self.assertIsNone(self.app.jobs.get('other',job['id']))
        reloaded = backend.module.App(self.root,self.root,dev=True)
        self.assertEqual(reloaded.jobs.get('dev',job['id'])['steps'],job['steps'])

    def test_bookkeeping_prepares_private_incomplete_zip(self):
        self.enable()
        job = self.submit('bookkeeping',month='2026-10')
        self.app.jobs._process_one()  # No sources: real sync must yield explicit incomplete snapshot.
        completed = self.app.jobs.get('dev',job['id'])
        self.assertEqual(completed['status'],'completed',completed)
        self.assertTrue(completed['result']['incomplete'])
        url = '/' + completed['result']['artifact']['url']
        code, raw = self.request(url)
        self.assertEqual(code,200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertTrue(archive.namelist())
        self.assertIsNone(self.app.workflows.download('other',job['id']))
        self.app.bookkeeping_sync.enabled = False
        self.assertEqual(self.request(url)[0],404)

    def test_step_failure_redacted_and_not_replayed(self):
        self.enable()
        job = self.submit('bookkeeping',month='2026-10')
        with patch.object(self.app.bookkeeping_sync,'sync',side_effect=RuntimeError('SECRET credential')) as sync:
            self.app.jobs._process_one()
            self.app.jobs._process_one()
            self.assertEqual(sync.call_count,1)
        failed = self.app.jobs.get('dev',job['id'])
        self.assertEqual(failed['status'],'failed')
        self.assertEqual([s['status'] for s in failed['steps']],['completed','failed','pending','pending'])
        self.assertNotIn('SECRET',json.dumps(failed))
        self.assertIsNone(self.app.workflows.download('dev',job['id']))

    def test_queued_permission_recheck_and_restart(self):
        self.enable()
        job = self.submit('bookkeeping',month='2026-10')
        self.app.bookkeeping_sync.enabled = False
        with patch.object(self.app.bookkeeping_sync,'sync') as sync:
            self.app.jobs._process_one()
            sync.assert_not_called()
        self.assertEqual(self.app.jobs.get('dev',job['id'])['steps'][0]['status'],'failed')
        job = self.submit()
        with self.app.db() as db:
            db.execute("UPDATE atlas_jobs SET status='running' WHERE id=?",(job['id'],))
        self.app.jobs.progress(job['id'],0,'running')
        with patch.object(self.app.jobs,'workflow') as execute:
            self.app.jobs.start()
            self.app.jobs.stop()
            execute.assert_not_called()
        stopped = self.app.jobs.get('dev',job['id'])
        self.assertEqual(stopped['status'],'failed')
        self.assertEqual(stopped['steps'][0]['status'],'failed')

    def test_revoked_bookkeeping_hides_mixed_briefing_everywhere(self):
        self.enable()
        job = self.submit()
        self.app.jobs._process_one()
        before = self.app.jobs.get('dev', job['id'])
        self.assertTrue(before['result']['requires_bookkeeping'])
        self.assertIn('Ausgangsrechnungen', before['result']['reply'])
        self.app.bookkeeping_sync.enabled = False
        result = json.loads(self.request('/api/jobs/' + job['id'])[1])['result']
        self.assertTrue(result['restricted'])
        self.assertNotIn('Ausgangsrechnungen', result['reply'])
        self.assertNotIn('artifact', result)
        listed = json.loads(self.request('/api/jobs')[1])['jobs'][0]['result']
        self.assertEqual(listed, result)
        # Telegram uses the same jobs.get; ordinary briefings remain accessible.
        self.assertEqual(self.app.jobs.get('dev', job['id'])['result'], result)
        own = self.submit()
        self.app.jobs._process_one()
        self.assertFalse(self.app.jobs.get('dev', own['id'])['result']['requires_bookkeeping'])

    def test_artifact_retention(self):
        self.enable()
        ids = []
        for _ in range(4):
            job = self.submit('bookkeeping',month='2026-10')
            self.app.jobs._process_one()
            ids.append(job['id'])
        self.assertIsNone(self.app.workflows.download('dev',ids[0]))
        self.assertIsNotNone(self.app.workflows.download('dev',ids[-1]))
        with self.app.db() as db:
            db.execute("UPDATE atlas_workflow_artifacts SET created_at='2000-01-01'")
        self.assertIsNone(self.app.workflows.download('dev',ids[-1]))
