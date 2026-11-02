"""Opt-in internal ATLAS task service. The bearer is scoped to one configured owner."""
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import re
import sqlite3
import threading
import unicodedata


def public_task(row):
    return {'id': row['id'], 'title': row['title'], 'done': bool(row['done'])}


def make_server(db_factory, options, address=('0.0.0.0', 8102)):
    if options.get('hermes_tasks_enabled') is not True:
        return None
    owner = options.get('hermes_tasks_ha_user_id', '')
    token = options.get('hermes_tasks_token', '')
    if not isinstance(owner, str) or not re.fullmatch(r'[0-9a-f]{32}', owner):
        raise ValueError('Ungültiger ATLAS-Aufgabenbesitzer.')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ValueError('Ungültiger ATLAS-Aufgabenschlüssel.')
    authorization = ('Bearer ' + token).encode('ascii')

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            values = self.headers.get_all('Authorization', [])
            if len(values) == 1 and 'Origin' not in self.headers and hmac.compare_digest(
                values[0].encode('latin-1'), authorization
            ):
                return True
            self.reply(403, {'error': 'Zugriff verweigert.'})
            return False

        def do_GET(self):
            if not self.authorized():
                return
            match = re.fullmatch(r'/tasks/([1-9][0-9]{0,17})', self.path)
            try:
                with closing(db_factory()) as db:
                    if self.path == '/tasks':
                        rows = db.execute('SELECT id,title,done FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 51', (owner,)).fetchall()
                        return self.reply(200, {'tasks': [public_task(row) for row in rows[:50]], 'more': len(rows) > 50})
                    if match:
                        row = db.execute('SELECT id,title,done FROM tasks WHERE user_id=? AND id=?', (owner, int(match[1]))).fetchone()
                        if row:
                            return self.reply(200, {'task': public_task(row)})
            except sqlite3.Error:
                return self.reply(503, {'error': 'Aufgaben momentan nicht abrufbar.'})
            self.reply(404, {'error': 'Nicht gefunden.'})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/tasks':
                return self.reply(404, {'error': 'Nicht gefunden.'})
            length = self.headers.get('Content-Length', '')
            if (len(self.headers.get_all('Content-Length', [])) != 1 or self.headers.get('Transfer-Encoding')
                    or not re.fullmatch(r'[1-9][0-9]{0,3}', length) or int(length) > 4096
                    or self.headers.get_content_type() != 'application/json'):
                return self.reply(400, {'error': 'Ungültige Aufgabendaten.'})
            try:
                data = json.loads(self.rfile.read(int(length)).decode('utf-8'))
                if not isinstance(data, dict) or set(data) != {'title'} or not isinstance(data['title'], str):
                    raise ValueError()
                title = data['title'].strip()
                if not title or len(title) > 300 or any(unicodedata.category(c) in ('Cc','Cs') for c in title):
                    raise ValueError()
            except (ValueError, UnicodeError, RecursionError):
                return self.reply(400, {'error': 'Ein Titel mit 1 bis 300 Zeichen ist erforderlich.'})
            try:
                with closing(db_factory()) as db, db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT id,title,done FROM tasks WHERE user_id=? AND title=? AND done=0 ORDER BY id DESC LIMIT 1', (owner, title)).fetchone()
                    if row:
                        payload = {'task': public_task(row), 'created': False}
                    else:
                        if db.execute('SELECT COUNT(*) FROM tasks WHERE user_id=?', (owner,)).fetchone()[0] >= 500:
                            return self.reply(409, {'error': 'Aufgabenlimit erreicht.'})
                        stamp = datetime.now(timezone.utc).isoformat()
                        ident = db.execute('INSERT INTO tasks(user_id,title,created_at) VALUES (?,?,?)', (owner, title, stamp)).lastrowid
                        payload = {'task': {'id': ident, 'title': title, 'done': False}, 'created': True}
                self.reply(201 if payload['created'] else 200, payload)
            except sqlite3.Error:
                self.reply(503, {'error': 'Speichern fehlgeschlagen. Aufgabenliste vor erneutem Anlegen prüfen.'})

    return HTTPServer(address, Handler)


def start_server(app, options):
    server = make_server(app.db, options)
    if server:
        threading.Thread(target=server.serve_forever, name='hermes-tasks', daemon=True).start()
    return server
