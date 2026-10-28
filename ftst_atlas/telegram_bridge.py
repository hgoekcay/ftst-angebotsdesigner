"""Opt-in Telegram private-chat bridge. No inbound ports or automatic account binding.

Offsets are committed BEFORE handling updates: a crash may lose a reply, but cannot
replay an already claimed update. Delivery is not exactly-once. Tokens never enter
logs/status/database. Telegram carries the message content; this is not offline.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class TelegramError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TelegramError('Telegram-Weiterleitung abgelehnt.')


class TelegramBridge:
    def __init__(self, app, options):
        token = options.get('telegram_token', '')
        uid = options.get('telegram_user_id') or ''
        ha_uid = options.get('telegram_ha_user_id', '')
        if not isinstance(token, str) or not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,100}', token):
            raise ValueError('Telegram-Zugang ist unvollständig.')
        if not isinstance(uid, str) or (uid and not re.fullmatch(r'[1-9][0-9]{0,15}', uid)):
            raise ValueError('Telegram-Nutzerkennung fehlt.')
        if not isinstance(ha_uid, str) or not ha_uid or len(ha_uid) > 128:
            raise ValueError('ATLAS-Profilzuordnung fehlt.')
        with app.db() as db:
            if not db.execute('SELECT 1 FROM profiles WHERE user_id=?', (ha_uid,)).fetchone():
                raise ValueError('ATLAS-Profil muss zuerst gespeichert werden.')
            db.execute('CREATE TABLE IF NOT EXISTS telegram_offsets(bot_id TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
        self.app, self.user_id, self.ha_user_id = app, int(uid) if uid else None, ha_uid
        self._token, self.bot_id = token, token.split(':')[0]
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.stop_event = threading.Event()
        self.history = []
        self.state = 'bereit'
        self.discovery_times = {}

    def call(self, method, body):
        if method not in ('getUpdates', 'sendMessage'):
            raise TelegramError('Telegram-Methode abgelehnt.')
        try:
            req = Request('https://api.telegram.org/bot' + self._token + '/' + method,
                          data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            with self.opener.open(req, timeout=40) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ValueError()
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('ok') is not True:
                raise ValueError()
            return data['result']
        except Exception:
            # Transport exceptions include the credential-bearing URL: never surface them.
            raise TelegramError('Telegram momentan nicht erreichbar oder Zugang ungültig.') from None

    def offset(self):
        with self.app.db() as db:
            row = db.execute('SELECT next_id FROM telegram_offsets WHERE bot_id=?', (self.bot_id,)).fetchone()
        return row[0] if row else 0

    def claim(self, update_id):
        if type(update_id) is not int or not 0 <= update_id < 2**63-1:
            return False
        with self.app.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT next_id FROM telegram_offsets WHERE bot_id=?', (self.bot_id,)).fetchone()
            if row and update_id < row[0]:
                return False
            db.execute('INSERT INTO telegram_offsets VALUES (?,?) ON CONFLICT(bot_id) DO UPDATE SET next_id=excluded.next_id',
                       (self.bot_id, update_id+1))
        return True

    def reply(self, text):
        self.call('sendMessage', {'chat_id': self.user_id, 'text': text[:4000]})

    def handle(self, update):
        if not isinstance(update, dict) or not self.claim(update.get('update_id')):
            return
        m = update.get('message')
        if not isinstance(m, dict):
            return
        chat, sender = m.get('chat', {}), m.get('from', {})
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return
        if chat.get('type') != 'private' or sender.get('is_bot') or type(sender.get('id')) is not int or sender.get('id') <= 0 or chat.get('id') != sender.get('id'):
            return
        stamp = m.get('date')
        if type(stamp) is not int or not -60 <= time.time() - stamp <= 300:
            return
        text = m.get('text')
        if not isinstance(text, str) or not text.strip():
            return
        if self.user_id is None:
            if text.strip() == '/id':
                uid = sender['id']
                if time.monotonic() - self.discovery_times.get(uid, float('-inf')) >= 30:
                    if uid not in self.discovery_times and len(self.discovery_times) >= 100:
                        return
                    self.discovery_times[uid] = time.monotonic()
                    self.call('sendMessage', {'chat_id': uid, 'text': 'Deine Telegram-ID: ' + str(uid) + '. In ATLAS-Konfiguration freigeben. Noch kein Zugriff auf Firmenwissen.'})
            return
        if sender['id'] != self.user_id:
            return
        text = text.strip()
        if len(text) > 2000:
            self.reply('Bitte maximal 2.000 Zeichen senden.')
            return
        if text in ('/start', '/help'):
            self.reply('ATLAS: Schreibe deine Frage. /tasks zeigt Aufgaben, /remember TEXT speichert ausdrücklich Wissen, /id zeigt deine freigegebene ID. /online FRAGE nutzt Online-Beratung mit Websuche, /lokal FRAGE bleibt lokal. Automatisch kann eine Recherchefrage oder ein lokaler Modellfehler an OpenAI gehen, wenn eingerichtet. Keine Geräteaktionen. Nachrichten laufen über Telegram.')
        elif text == '/id':
            self.reply('Deine freigegebene Telegram-ID: ' + str(self.user_id))
        elif text.lower() in ('/tasks', 'tasks', 'aufgaben'):
            tasks = self.app.collection('tasks', self.ha_user_id)
            lines = [('- ' if not t['done'] else '✓ ') + t['title'] for t in tasks[:20]]
            self.reply('\n'.join(lines) if lines else 'Keine Aufgaben gespeichert.')
        elif text.startswith('/remember '):
            note = text[len('/remember '):].strip()
            if not note:
                return
            with self.app.db() as db:
                count = db.execute('SELECT COUNT(*) FROM memories WHERE user_id=?', (self.ha_user_id,)).fetchone()[0]
                if count < 500:
                    db.execute('INSERT INTO memories(user_id,text,source,created_at) VALUES (?,?,?,?)',
                               (self.ha_user_id, note, 'Explizit über freigegebenes Telegram-Konto gespeichert', datetime.now(timezone.utc).isoformat()))
            self.reply('Wissen gespeichert.' if count < 500 else 'Wissensspeicher voll. Bitte in ATLAS aufräumen.')
        elif text.startswith('/') and not text.startswith(('/online ', '/lokal ')):
            self.reply('Unbekannter Befehl. Nutze /help.')
        else:
            mode = 'online' if text.startswith('/online ') else 'local' if text.startswith('/lokal ') else 'auto'
            question = text.split(' ', 1)[1].strip() if mode != 'auto' else text
            if not question:
                self.reply('Bitte eine Frage ergänzen.')
                return
            self.reply('Ich bearbeite deine Frage. Je nach Modus lokal oder über die eingerichtete Online-Beratung.')
            try:
                result = self.app.respond(question, self.ha_user_id, history=self.history, mode=mode)
                answer = result['reply']
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError()
            except Exception:
                self.reply('ATLAS konnte keine vollständige Antwort liefern. Bei Online-Fragen den OpenAI-Zugang und das Tageslimit unter System prüfen; /lokal FRAGE bleibt lokal.')
                return
            if result.get('online'):
                source_lines = [str(item.get('title', 'Quelle'))[:80] + ': ' + item['url'] for item in result.get('sources', [])[:3]]
                footer = '\n\nOpenAI · ' + result.get('model', '') + ('\nQuellen:\n' + '\n'.join(source_lines) if source_lines else '\nOhne Websuche')
                footer = footer[:1800]
                available = 3900 - len(footer)
                self.reply((answer if len(answer) <= available else answer[:available-30] + '\n[Antwort gekürzt]') + footer)
            else:
                self.reply(answer)
            self.history = (self.history + [{'role': 'user', 'content': text[:500]}, {'role': 'assistant', 'content': answer[:500]}])[-4:]

    def run(self):
        while not self.stop_event.is_set():
            try:
                updates = self.call('getUpdates', {'offset': self.offset(), 'timeout': 25, 'limit': 10, 'allowed_updates': ['message']})
                if not isinstance(updates, list):
                    raise TelegramError('Ungültige Antwort.')
                if self.state != 'verbunden':
                    print('Telegram verbunden: ' + ('ID-Ermittlung aktiv.' if self.user_id is None else 'Privater Nutzer freigegeben.'), flush=True)
                self.state = 'verbunden'
                for update in updates:
                    if self.stop_event.is_set():
                        return
                    self.handle(update)
                self.stop_event.wait(1)
            except Exception:
                if self.state != 'Verbindung oder Verarbeitung gestört':
                    print('Telegram: Verbindung oder Verarbeitung gestört. Zugang und Netzwerk prüfen.', flush=True)
                self.state = 'Verbindung oder Verarbeitung gestört'
                self.stop_event.wait(30)


def start_bridge(app, options):
    """Return bridge or None; disabled/misconfigured bridges never contact Telegram."""
    if options.get('telegram_enabled') is not True:
        return None
    try:
        bridge = TelegramBridge(app, options)
    except (ValueError, TypeError):
        print('Telegram deaktiviert: Zugang, Freigabe oder gespeichertes ATLAS-Profil fehlt.', flush=True)
        return None
    threading.Thread(target=bridge.run, name='atlas-telegram', daemon=True).start()
    return bridge
