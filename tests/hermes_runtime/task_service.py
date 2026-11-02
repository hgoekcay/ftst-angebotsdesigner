"""CI-only smoke startup for the actual ATLAS adapter, using a disposable SQLite DB."""
import sqlite3
from hermes_tasks import make_server


def db():
    conn = sqlite3.connect('/tmp/tasks.sqlite')
    conn.row_factory = sqlite3.Row
    return conn


with db() as conn:
    conn.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY, user_id TEXT, title TEXT, created_at TEXT, done INTEGER DEFAULT 0)')

make_server(db, {'hermes_tasks_enabled': True, 'hermes_tasks_ha_user_id': 'a' * 32, 'hermes_tasks_token': 'x' * 43}).serve_forever()
