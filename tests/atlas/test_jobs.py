import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('atlas_jobs_test_module', Path(__file__).parents[2] / 'ftst_atlas/jobs.py')
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'jobs.db')
        self.db = lambda: sqlite3.connect(self.path, timeout=5)
        self.execute = Mock(return_value={'reply': 'Antwort'})
        self.queue = jobs.JobQueue(self.db, self.execute)

    def tearDown(self):
        self.queue.stop()
        self.tmp.cleanup()

    def test_owner_isolation_and_no_payload_exposure(self):
        job = self.queue.submit('alice', {'message': 'private question'})
        self.assertIsNone(self.queue.get('bob', job['id']))
        self.assertEqual(self.queue.list('bob'), [])
        self.assertEqual(job['title'], 'private question')
        self.assertNotIn('payload', job)
        self.assertNotIn('payload', self.queue.get('alice', job['id']))
        self.queue._process_one()
        public = self.queue.get('alice', job['id'])
        self.assertEqual(public['status'], 'completed')
        self.assertEqual(public['result'], {'reply': 'Antwort'})
        self.execute.assert_called_once_with('alice', {'message': 'private question'})
        with self.db() as db:
            self.assertEqual(db.execute('SELECT payload FROM atlas_jobs').fetchone()[0], '{}')

    def test_queued_jobs_survive_restart_but_running_jobs_never_replay(self):
        failed = self.queue.submit('one', {'message': 'already started'})
        pending = self.queue.submit('two', {'message': 'waiting'})
        with self.db() as db:
            db.execute("UPDATE atlas_jobs SET status='running' WHERE id=?", (failed['id'],))
        reached = threading.Event()
        def execute(user, payload):
            reached.set()
            return {'reply': user}
        self.queue = jobs.JobQueue(self.db, execute)
        self.queue.start()
        self.assertTrue(reached.wait(3))
        self.queue.stop()
        self.assertEqual(self.queue.get('one', failed['id'])['status'], 'failed')
        self.assertIn('nicht automatisch wiederholt', self.queue.get('one', failed['id'])['error'])
        self.assertEqual(self.queue.get('two', pending['id'])['status'], 'completed')

    def test_pending_limits_and_atomic_same_owner_reservation(self):
        self.queue.submit('alice', {})
        with self.assertRaises(jobs.JobError):
            self.queue.submit('alice', {})
        for i in range(9):
            self.queue.submit(str(i), {})
        with self.assertRaises(jobs.JobError):
            self.queue.submit('eleventh', {})
        self.queue._process_one()
        self.assertEqual(self.queue.submit('alice', {})['status'], 'queued')

    def test_titles_are_bounded_and_do_not_include_history(self):
        job = self.queue.submit('alice', {'message': 'a' * 200, 'history': 'not for listing'})
        self.assertEqual(job['title'], 'a' * 120)
        public = self.queue.list('alice')
        self.assertNotIn('not for listing', json.dumps(public))
        self.assertEqual(public[0]['title'], 'a' * 120)
        self.assertEqual(self.queue.list('other'), [])

    def test_simultaneous_submissions_allow_only_one_active_job(self):
        barrier = threading.Barrier(3)
        results = []
        def submit():
            barrier.wait()
            try:
                results.append(self.queue.submit('alice', {}))
            except jobs.JobError:
                results.append(None)
        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(3)
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(len(self.queue.list('alice')), 1)

    def test_limits_count_utf8_and_reject_non_json_payload(self):
        for value in [{'x': 'ä' * 17000}, {'x': float('nan')}, {'x': object()}, [], None]:
            with self.subTest(value_type=type(value)), self.assertRaises(jobs.JobError):
                self.queue.submit('alice', value)
        self.assertEqual(self.queue.list('alice'), [])

    def test_internal_errors_and_oversize_results_are_redacted(self):
        for outcome in [RuntimeError('sk-secret confidential details'), {'reply': 'x' * 70000}, None]:
            self.execute.side_effect = outcome if isinstance(outcome, Exception) else None
            self.execute.return_value = outcome
            job = self.queue.submit('alice', {})
            self.queue._process_one()
            public = self.queue.get('alice', job['id'])
            self.assertEqual(public['status'], 'failed')
            self.assertIsNone(public['result'])
            self.assertNotIn('sk-secret', json.dumps(public))
        self.execute.side_effect = jobs.JobError('Tageslimit erreicht.')
        job = self.queue.submit('alice', {})
        self.queue._process_one()
        self.assertEqual(self.queue.get('alice', job['id'])['error'], 'Tageslimit erreicht.')

    def test_retention_cleans_only_finished_work(self):
        old = self.queue.submit('old', {})
        self.queue._process_one()
        pending = self.queue.submit('pending', {})
        with self.db() as db:
            db.execute("UPDATE atlas_jobs SET finished_at='2000-01-01T00:00:00+00:00' WHERE id=?", (old['id'],))
            db.execute("UPDATE atlas_jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (pending['id'],))
        self.assertEqual(self.queue.list('old'), [])
        self.assertEqual(self.queue.get('pending', pending['id'])['status'], 'queued')

    def test_start_is_idempotent_and_running_blocks_second_owner_job(self):
        entered, release = threading.Event(), threading.Event()
        def execute(user, payload):
            entered.set()
            release.wait(3)
            return {'reply': 'done'}
        self.queue.execute = execute
        job = self.queue.submit('alice', {})
        self.queue.start()
        self.assertTrue(entered.wait(3))
        self.queue.start()
        with self.assertRaises(jobs.JobError):
            self.queue.submit('alice', {})
        release.set()
        self.queue.stop()
        self.assertEqual(self.queue.get('alice', job['id'])['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
