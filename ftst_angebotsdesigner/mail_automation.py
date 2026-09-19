"""Local inbox polling and review-only suggestions; never sends or changes mail."""
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from storage import RecordConflict
from mail_workflow import stamp

LOG = logging.getLogger('ftst.mail.automation')


def enabled(name):
    return os.getenv(name, '').lower() == 'true'


class MailAutomation:
    def __init__(self, get_store, identity, sync=None, analyze=None):
        self.get_store, self.identity = get_store, identity
        self.sync = sync
        self.analyze = analyze
        self.stop_event = threading.Event()
        self.next_sync = {}
        self.failures = {}
        self.last_ai_account = None
        self.thread = None
        self.lock_file = None
        self.status = {}

    def save_status(self, **fields):
        self.status.update(fields)
        self.get_store().put_record(self.identity, 'mail_automation', 'state', self.status)

    def analyze_one(self, allowed_accounts=None):
        """Only untouched imported records; CAS protects edits during inference."""
        import mail_assistant
        store = self.get_store()
        candidates = []
        for key, value in reversed(list(store.records(self.identity, 'mail').items())):
            if (not value.get('mail_origin') or value.get('analysis') or value.get('automation')
                    or value.get('reply') or value.get('workflow') or value.get('status', 'new') != 'new'):
                continue
            account_id = value['mail_origin'].get('account_id', 'primary')
            if allowed_accounts is not None and account_id not in allowed_accounts:
                continue
            candidates.append((key, value, account_id))
        # Alternate mailboxes when several have work, preserving oldest-first within each.
        account_ids = list(dict.fromkeys(row[2] for row in candidates))
        if self.last_ai_account in account_ids:
            split = account_ids.index(self.last_ai_account) + 1
            account_ids = account_ids[split:] + account_ids[:split]
        candidates.sort(key=lambda row: account_ids.index(row[2]))
        for key, value, account_id in candidates:
            self.last_ai_account = account_id
            expected = value['revision']
            value['revision'] = uuid.uuid4().hex
            value['automation'] = {'state': 'running', 'at': stamp()}
            source = value.get('source', '')
            if not source.strip() or len(source) > 4000 or value.get('warnings'):
                value['automation']['state'] = 'skipped'
            try:
                store.put_revision(self.identity, 'mail', key, value, expected)
            except RecordConflict:
                continue
            if value['automation']['state'] == 'skipped':
                return True
            expected = value['revision']
            try:
                digest = hashlib.sha256(json.dumps([mail_assistant.VERSION, mail_assistant.MODEL,
                    mail_assistant.model_digest(), source], ensure_ascii=False).encode()).hexdigest()
                result = (self.analyze or mail_assistant.analyze)(source)
                # Keep categories and the user's response untouched. These remain proposals.
                value.update(analysis=result, proposal=mail_assistant.compose(result), fingerprint=digest)
                value['automation'] = {'state': 'ready', 'at': stamp()}
            except Exception:
                # Never log customer content, raw model output or network exception values.
                value['automation'] = {'state': 'failed', 'at': stamp()}
            value['revision'] = uuid.uuid4().hex
            try:
                store.put_revision(self.identity, 'mail', key, value, expected)
            except RecordConflict:
                # A person changed the record while inference ran; keep their version.
                pass
            return True
        return False

    def tick(self, now=None):
        import strato_views
        now = time.monotonic() if now is None else now
        auto_import, auto_ai = enabled('STRATO_AUTO_IMPORT'), enabled('STRATO_AUTO_AI')
        try:
            interval = max(60, min(3600, int(os.getenv('STRATO_POLL_SECONDS', '300'))))
        except ValueError:
            interval = 300
        self.status.update(auto_import=auto_import, auto_ai=auto_ai, interval_seconds=interval)
        store = self.get_store()
        if not strato_views.configured():
            self.save_status(state='waiting', error='Mail-Verbindung einrichten.')
            return
        try:
            mailboxes = strato_views.list_mailboxes()
        except Exception:
            self.save_status(state='degraded', error='Postfachliste nicht erreichbar.')
            return
        statuses = self.status.setdefault('accounts', {})
        enabled_ids = {box['id'] for box in mailboxes}
        self.status['accounts'] = statuses = {k: v for k, v in statuses.items() if k in enabled_ids}
        active = set()
        for box in mailboxes:
            if self.stop_event.is_set():
                break
            account_id = box['id']
            state = store.record(self.identity, 'mail_sync', strato_views.sync_key(account_id))
            report = statuses.setdefault(account_id, {})
            if not state or state.get('paused'):
                report.update(state='paused' if state else 'waiting', error='')
                continue
            # A changed address/folder must not process earlier mail under the new identity.
            source = state.get('source', {})
            if source and (source.get('mailbox') != box['email'] or source.get('folder') != box['folder']):
                report.update(state='degraded', error='Postfachquelle geändert; technischen Abgleich durchführen.')
                continue
            active.add(account_id)
            if auto_import and now >= self.next_sync.get(account_id, 0):
                try:
                    (self.sync or strato_views.sync_once)(store, self.identity, account_id=account_id)
                    self.failures[account_id] = 0
                    report.update(state='healthy', last_sync_at=stamp(), error='')
                except Exception:
                    self.failures[account_id] = self.failures.get(account_id, 0) + 1
                    report.update(state='degraded', error='Abruf nicht abgeschlossen. STRATO-Eingang prüfen.')
                    LOG.warning('Automatischer Postfachabruf nicht abgeschlossen.')
                self.next_sync[account_id] = now + min(3600, interval * 2 ** min(self.failures[account_id], 4))
        self.save_status(state='degraded' if any(v.get('state') == 'degraded' for v in statuses.values())
                         else 'healthy' if active else 'waiting', error='')
        if auto_ai and active:
            self.analyze_one(active)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                LOG.warning('Lokale Mail-Automation konnte diesen Durchlauf nicht abschließen.')
            self.stop_event.wait(60)

    def start(self, data_dir):
        if not (enabled('STRATO_AUTO_IMPORT') or enabled('STRATO_AUTO_AI')):
            return
        import fcntl
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.lock_file = open(Path(data_dir) / '.mail-automation.lock', 'a')
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            self.lock_file = None
            return
        self.thread = threading.Thread(target=self._run, name='mail-automation', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        # Retain the process lock until an in-flight worker actually finishes.
        if self.lock_file and not (self.thread and self.thread.is_alive()):
            self.lock_file.close()
