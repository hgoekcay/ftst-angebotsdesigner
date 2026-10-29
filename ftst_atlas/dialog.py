"""Explicit voice turns: fixed commands, ordinary advice, no model-selected tools."""
import re
from datetime import datetime, timezone

from jobs import JobError
from workflows import TEMPLATES

MONTHS = {name: str(index).zfill(2) for index, name in enumerate(
    ('januar', 'februar', 'märz', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'dezember'), 1)}
HELP = ('Per Sprache kann ich eine Aufgabe in der Liste speichern, den Tagesüberblick starten und einen Monat zur Belegprüfung vorbereiten. '
        'Zum Beispiel: Aufgabe anlegen: Angebot prüfen. Oder: Bereite Buchhaltung für Oktober 2026 vor. '
        'Andere Aktionen habe ich nicht ausgeführt.')


def parse_command(message):
    text = message.strip().rstrip('.!').strip()
    task = re.fullmatch(r'(?:Aufgabe anlegen|Erstelle eine Aufgabe)\s*:?\s+(.+)', text, re.I)
    if task:
        title = task[1].strip()
        if not 1 <= len(title) <= 300 or any(ord(c) < 32 for c in title):
            raise ValueError('Aufgabentitel benötigt 1 bis 300 Zeichen ohne Zeilenumbrüche.')
        return {'kind': 'dialog_task', 'title': title}
    if re.fullmatch(r'(?:Starte den )?Tagesüberblick', text, re.I):
        return {'workflow': 'briefing'}
    month = re.fullmatch(r'Bereite (?:die )?Buchhaltung für (.+) vor', text, re.I)
    if month:
        value = month[1].casefold()
        named = re.fullmatch(r'(' + '|'.join(MONTHS) + r') ([1-9][0-9]{3})', value)
        if named:
            value = named[2] + '-' + MONTHS[named[1]]
        if not re.fullmatch(r'[1-9][0-9]{3}-(?:0[1-9]|1[0-2])', value):
            return {'kind': 'dialog_help'}
        return {'workflow': 'bookkeeping', 'month': value}
    # Narrow imperative detection avoids sending unsupported action requests to a
    # model that might phrase a draft as a completed real-world action.
    if re.match(r'(?:(?:bitte|atlas)[,:]?\s+)*(?:sende|schicke|versende|überweise|bezahle|lösche|buche|rufe|schalte|starte|lege|erstelle eine aufgabe|bereite (?:die )?buchhaltung|aufgabe anlegen)\b', text, re.I):
        return {'kind': 'dialog_help'}
    return {'kind': 'dialog_chat'}


class Dialog:
    def __init__(self, app):
        self.app = app

    def authorize(self, user):
        state = self.app.voice.status(user)
        if not state['enabled']:
            raise JobError(state['reason'])

    def submit(self, user, data):
        self.authorize(user)
        if not isinstance(data, dict) or set(data) - {'message', 'mode', 'history', 'request_id'}:
            raise ValueError('Ungültige Gesprächsanfrage.')
        message, mode, history, key = data.get('message'), data.get('mode', 'auto'), data.get('history', []), data.get('request_id')
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError('Nachricht benötigt 1 bis 2000 Zeichen.')
        if mode not in ('auto', 'local', 'online') or not isinstance(history, list) or len(history) > 4:
            raise ValueError('Ungültiger Gesprächskontext.')
        for entry in history:
            if (not isinstance(entry, dict) or set(entry) != {'role', 'content'} or entry['role'] not in ('user', 'assistant')
                    or not isinstance(entry['content'], str) or len(entry['content']) > 500):
                raise ValueError('Ungültiger Gesprächskontext.')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
            raise ValueError('Eindeutige Auftragskennung erforderlich.')
        command = parse_command(message)
        steps = []
        if 'workflow' in command:
            command = self.app.workflows.validate(user, command)
            steps = list(TEMPLATES[command['workflow']][2])
            command['kind'] = 'workflow'
        payload = dict(command, message=message.strip(), history=history, mode=mode, voice_dialog=True)
        return self.app.jobs.submit(user, payload, steps=steps, request_key=key)

    def execute(self, user, payload):
        self.authorize(user)
        kind = payload.get('kind')
        if kind == 'dialog_task':
            stamp = datetime.now(timezone.utc).isoformat()
            with self.app.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COUNT(*) FROM tasks WHERE user_id=?', (user,)).fetchone()[0] >= 500:
                    raise JobError('Aufgabenlimit erreicht. Aufgabe wurde nicht gespeichert.')
                cursor = db.execute('INSERT INTO tasks(user_id,title,created_at) VALUES (?,?,?)', (user, payload['title'], stamp))
                ident = cursor.lastrowid
            return {'provider': 'ATLAS', 'action': 'task_created', 'task': {'id': ident, 'title': payload['title']},
                    'reply': 'Aufgabe in deiner Liste gespeichert: ' + payload['title'] + '. Die Aufgabe selbst ist damit noch nicht erledigt.'}
        if kind == 'dialog_help':
            return {'provider': 'ATLAS', 'action': 'none', 'reply': HELP}
        if kind != 'dialog_chat':
            raise JobError('Unbekannte Gesprächsaktion.')
        result = self.app.respond(payload['message'], user, payload.get('history', []), payload.get('mode', 'auto'))
        return dict(result, action='none', routing_note=(result.get('routing_note', '') + ' Gesprächsantwort – keine Aktion ausgeführt.').strip())
