"""Test the real network and sqlite boundary; no live HA or external provider."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ftst_atlas'))
try:
    import hermes_tasks
finally:
    sys.path.pop(0)


class InternalTasks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = 'a' * 32
        self.token = 'x' * 43
        self.options = dict(hermes_tasks_enabled=True, hermes_tasks_ha_user_id=self.owner, hermes_tasks_token=self.token)
        with closing(self.db()) as db, db:
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,user_id TEXT,title TEXT,done INTEGER DEFAULT 0,created_at TEXT)')
            db.execute("INSERT INTO tasks(user_id,title,created_at) VALUES ('other','private','now')")
        self.server = hermes_tasks.make_server(self.db, self.options, ('127.0.0.1', 0))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def db(self):
        db = sqlite3.connect(Path(self.temp.name) / 'test.sqlite')
        db.row_factory = sqlite3.Row
        return db

    def request(self, method, path, payload=None, **headers):
        with closing(http.client.HTTPConnection(*self.server.server_address, timeout=3)) as con:
            con.request(method, path, body=None if payload is None else json.dumps(payload),
                        headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', **headers})
            response = con.getresponse()
            return response.status, json.loads(response.read())

    def test_configuration(self):
        self.assertIsNone(hermes_tasks.make_server(self.db, {}))
        for bad in ({'hermes_tasks_token': 'weak'}, {'hermes_tasks_ha_user_id': ''}):
            with self.assertRaises(ValueError):
                hermes_tasks.make_server(self.db, {**self.options, **bad}, ('127.0.0.1', 0))

    def test_access_boundaries(self):
        for headers in ({'Authorization': ''}, {'Authorization': 'Bearer wrong'}, {'Origin': 'https://example.com'}):
            self.assertEqual(self.request('GET', '/tasks', **headers)[0], 403)
        for path in ('/tasks/1', '/tasks?owner=other', '/api/status'):
            self.assertEqual(self.request('GET', path)[0], 404)
        for payload in ({'user_id':'other','title':'x'}, {'title':' '}, {'title':'one\ntwo'}):
            self.assertEqual(self.request('POST', '/tasks', payload)[0], 400)
        self.assertEqual(self.request('GET', '/tasks')[1]['tasks'], [])

    def test_concurrent_writes_readback(self):
        def write(_):
            return self.request('POST','/tasks',{'title':'Wartungsangebot vorbereiten'})
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(write, range(2)))
        self.assertEqual(sorted(s for s, _ in results), [200,201])
        self.assertEqual(results[0][1]['task'], results[1][1]['task'])
        task = results[0][1]['task']
        self.assertEqual(self.request('GET','/tasks/' + str(task['id'])), (200, {'task':task}))
        self.assertEqual(self.request('GET','/tasks')[1], {'tasks':[task],'more':False})
        self.assertEqual(set(task), {'id','title','done'})
