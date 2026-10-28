"""Explicit owner-confirmed knowledge and task links; no automatic ingestion."""
import json
import re
from datetime import datetime, timezone


class KnowledgeConflict(ValueError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Ungültiger Wissenstext.')
    return value.strip()


def tags(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError('Höchstens acht Schlagwörter erlaubt.')
    return list(dict.fromkeys(text(v, 60) for v in value))


class Knowledge:
    def __init__(self, db_factory):
        self.db = db_factory
        with self.db() as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(memories)')}
            for name, definition in [('tags', "TEXT NOT NULL DEFAULT '[]'"),
                                     ('revision', 'INTEGER NOT NULL DEFAULT 1'),
                                     ('updated_at', "TEXT NOT NULL DEFAULT ''")]:
                if name not in columns:
                    db.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
            db.executescript('''CREATE TABLE IF NOT EXISTS atlas_knowledge_revisions (
                memory_id INTEGER NOT NULL, user_id TEXT NOT NULL, revision INTEGER NOT NULL,
                text TEXT NOT NULL, source TEXT NOT NULL, tags TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(memory_id, revision));
                CREATE TABLE IF NOT EXISTS atlas_task_knowledge (
                task_id INTEGER NOT NULL, memory_id INTEGER NOT NULL, user_id TEXT NOT NULL,
                PRIMARY KEY(task_id,memory_id));''')

    @staticmethod
    def public(row):
        result = dict(row)
        result['tags'] = json.loads(result.get('tags', '[]'))
        result['updated_at'] = result.get('updated_at') or result.get('created_at', '')
        return result

    def search(self, user, query='', tag='', limit=500):
        if not isinstance(query, str) or len(query) > 2000 or not isinstance(tag, str) or len(tag) > 60:
            raise ValueError('Ungültige Wissenssuche.')
        with self.db() as db:
            rows = [self.public(r) for r in db.execute('SELECT * FROM memories WHERE user_id=? ORDER BY id DESC LIMIT 500', (user,))]
        if tag:
            rows = [r for r in rows if tag.casefold() in {t.casefold() for t in r['tags']}]
        words = set(re.findall(r'\w{2,}', query.casefold()))
        if words:
            def score(row):
                haystack = (row['text'] + ' ' + row['source'] + ' ' + ' '.join(row['tags'])).casefold()
                return sum(word in haystack for word in words)
            rows = sorted((r for r in rows if score(r)), key=score, reverse=True)
        return rows[:limit]

    def create(self, user, data):
        content, source, labels = text(data.get('text'), 2000), text(data.get('source', 'Vom Nutzer bestätigt'), 200), tags(data.get('tags', []))
        date = stamp()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM memories WHERE user_id=?', (user,)).fetchone()[0] >= 500:
                raise ValueError('Speicherlimit erreicht.')
            ident = db.execute('INSERT INTO memories(user_id,text,source,created_at,tags,updated_at) VALUES (?,?,?,?,?,?)',
                               (user, content, source, date, json.dumps(labels, ensure_ascii=False), date)).lastrowid
            return self.public(db.execute('SELECT * FROM memories WHERE id=?', (ident,)).fetchone())

    def update(self, user, ident, data):
        if set(data) - {'text', 'source', 'tags', 'revision'} or type(data.get('revision')) is not int:
            raise ValueError('Versionsnummer erforderlich.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM memories WHERE user_id=? AND id=?', (user, ident)).fetchone()
            if not row:
                return None
            current = self.public(row)
            if data['revision'] != current['revision']:
                raise KnowledgeConflict('Die Notiz wurde inzwischen geändert. Bitte neu laden.')
            if current['revision'] >= 100:
                raise ValueError('Versionslimit erreicht.')
            content = text(data.get('text', current['text']), 2000)
            source = text(data.get('source', current['source']), 200)
            labels = tags(data.get('tags', current['tags']))
            db.execute('INSERT INTO atlas_knowledge_revisions VALUES (?,?,?,?,?,?,?)',
                       (ident, user, current['revision'], current['text'], current['source'], json.dumps(current['tags'], ensure_ascii=False), current['updated_at']))
            db.execute('UPDATE memories SET text=?,source=?,tags=?,revision=revision+1,updated_at=? WHERE id=? AND user_id=?',
                       (content, source, json.dumps(labels, ensure_ascii=False), stamp(), ident, user))
            return self.public(db.execute('SELECT * FROM memories WHERE id=? AND user_id=?', (ident, user)).fetchone())

    def history(self, user, ident):
        with self.db() as db:
            current = db.execute('SELECT * FROM memories WHERE id=? AND user_id=?', (ident, user)).fetchone()
            if not current:
                return None
            previous = [self.public(r) for r in db.execute('SELECT * FROM atlas_knowledge_revisions WHERE memory_id=? AND user_id=? ORDER BY revision DESC', (ident, user))]
            return [self.public(current)] + previous

    def delete(self, user, ident):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute('DELETE FROM memories WHERE id=? AND user_id=?', (ident, user)).rowcount
            if found:
                db.execute('DELETE FROM atlas_knowledge_revisions WHERE memory_id=? AND user_id=?', (ident, user))
                db.execute('DELETE FROM atlas_task_knowledge WHERE memory_id=? AND user_id=?', (ident, user))
            return bool(found)

    def link_task(self, db, user, ident, ids):
        if not isinstance(ids, list) or len(ids) > 8 or any(type(i) is not int or not 0 < i < 2**63 for i in ids):
            raise ValueError('Ungültige Wissensverknüpfung.')
        if not db.execute('SELECT 1 FROM tasks WHERE id=? AND user_id=?', (ident, user)).fetchone():
            raise ValueError('Aufgabe nicht gefunden.')
        for memory in ids:
            if not db.execute('SELECT 1 FROM memories WHERE id=? AND user_id=?', (memory, user)).fetchone():
                raise ValueError('Notiz nicht gefunden.')
        db.execute('DELETE FROM atlas_task_knowledge WHERE task_id=? AND user_id=?', (ident, user))
        db.executemany('INSERT INTO atlas_task_knowledge VALUES (?,?,?)', ((ident, memory, user) for memory in dict.fromkeys(ids)))

    def task_ids(self, db, user, ident):
        return [r[0] for r in db.execute('SELECT memory_id FROM atlas_task_knowledge WHERE task_id=? AND user_id=? ORDER BY memory_id', (ident, user))]
