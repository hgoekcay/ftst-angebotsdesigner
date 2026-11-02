"""Fixed, owner-scoped workflows. No model-selected actions or external writes."""
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from bookkeeping_reports import build_report, format_report
from bookkeeping import BookkeepingError
from jobs import JobError

TEMPLATES = {
    'briefing': ('Tagesüberblick', 'Profil, Firmenwissen, Aufgaben und verfügbarer Belegstand.',
                 ['Profil und Wissen lesen', 'Offene Aufgaben lesen', 'Belegstand prüfen', 'Überblick erstellen']),
    'bookkeeping': ('Monatsvorbereitung', 'Freigegebene Quellen lesen und ein Belegpaket zur Prüfung vorbereiten.',
                    ['Berechtigung und Monat prüfen', 'Freigegebene Quellen abgleichen', 'Prüfbericht erstellen', 'Monatspaket vorbereiten']),
}
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_STORED_BYTES = 10 * MAX_ARCHIVE
MAX_PARTS = 100
PACKAGE_LIMIT = "Monatspaket überschreitet das Speicherlimit von 1000 MiB oder 100 Teilen."
# Exact, source-reviewed messages only. Never reflect arbitrary exception text,
# paths, document contents, remote responses or credentials into a job result.
SAFE_EXPORT_ERRORS = frozenset({
    'Ein einzelner Beleg mit Prüfdaten überschreitet das Teilpaket-Limit.',
    'Export enthält mehr als 2000 Belege; Auswahl eingrenzen.',
    'Export überschreitet 100 MiB.',
    'Export einschließlich Prüfdaten überschreitet 100 MiB.',
    'Originalpfad ungültig.',
    'Originaldatei ist zu groß.',
    'Originaldatei nicht verfügbar.',
    'Originaldatei ist beschädigt.',
    'Billomat-Datenstand ist ungültig.',
    'Billomat-Datenstand ist beschädigt.',
})


class Workflows:
    def __init__(self, app):
        self.app = app
        with app.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS atlas_workflow_artifacts (
                job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL,
                created_at TEXT NOT NULL, archive BLOB NOT NULL)''')

            db.execute('''CREATE TABLE IF NOT EXISTS atlas_workflow_parts (
                job_id TEXT NOT NULL, number INTEGER NOT NULL, filename TEXT NOT NULL,
                archive BLOB NOT NULL, PRIMARY KEY(job_id, number))''')
            db.execute('''CREATE TRIGGER IF NOT EXISTS atlas_workflow_delete_parts
                AFTER DELETE ON atlas_workflow_artifacts BEGIN
                DELETE FROM atlas_workflow_parts WHERE job_id=OLD.job_id; END''')

    def catalog(self, user):
        return {'workflows': [dict(id=kind, title=entry[0], description=entry[1], steps=entry[2],
                requires_month=kind == 'bookkeeping',
                enabled=kind != 'bookkeeping' or self.app.bookkeeping_sync.enabled_for(user))
                for kind, entry in TEMPLATES.items()]}

    def validate(self, user, data):
        if not isinstance(data, dict) or set(data) - {'workflow', 'month'}:
            raise ValueError('Ungültiger Arbeitsablauf.')
        kind = data.get('workflow')
        if not isinstance(kind, str) or kind not in TEMPLATES:
            raise ValueError('Unbekannter Arbeitsablauf.')
        if kind == 'bookkeeping':
            if not self.app.bookkeeping_sync.enabled_for(user):
                raise ValueError('Buchhaltung ist für dieses Profil nicht freigegeben.')
            month = data.get('month')
            if not isinstance(month, str) or not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])', month):
                raise ValueError('Monat benötigt YYYY-MM.')
        elif 'month' in data:
            raise ValueError('Dieser Ablauf benötigt keinen Monat.')
        return dict(data)

    def submit(self, user, data):
        payload = self.validate(user, data)
        kind = payload['workflow']
        return self.app.jobs.submit(user, dict(payload, kind='workflow', message=TEMPLATES[kind][0]),
                                    steps=list(TEMPLATES[kind][2]))

    def _cleanup(self, db):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        db.execute('DELETE FROM atlas_workflow_artifacts WHERE created_at<?', (cutoff,))
        db.execute('''DELETE FROM atlas_workflow_artifacts WHERE job_id NOT IN
            (SELECT job_id FROM atlas_workflow_artifacts ORDER BY created_at DESC,rowid DESC LIMIT 10)''')

    def _prepare_package(self, user, ident, month):
        base = 'atlas-belege-' + month
        url = 'api/workflows/' + ident + '/download'
        parts = []
        total = 0
        seen = set()
        # Stage on disk outside the database transaction. Export checks originals
        # under its own lock and reads through independent database connections.
        with tempfile.TemporaryFile(dir=self.app.data_dir) as staged:
            def add_part(archive, ids):
                nonlocal total
                if not isinstance(archive, bytes) or len(archive) > MAX_ARCHIVE:
                    raise JobError('Monatspaket überschreitet das Größenlimit von 100 MiB.')
                total += len(archive)
                number = len(parts) + 1
                if total > MAX_STORED_BYTES or number > MAX_PARTS:
                    raise JobError(PACKAGE_LIMIT)
                if len(ids) != len(set(ids)) or seen.intersection(ids):
                    raise JobError('Belegzuordnung widersprüchlich.')
                seen.update(ids)
                staged.write(archive)
                parts.append({'number': number, 'filename': f'{base}-teil-{number:03d}.zip',
                              'bytes': len(archive), 'sha256': hashlib.sha256(archive).hexdigest(),
                              'record_count': len(ids), 'record_ids': list(ids)})

            self.app.bookkeeping.export(user, month, part_sink=add_part)
            if not parts:
                raise JobError('Kein Paket erzeugt.')
            self.validate(user, {'workflow': 'bookkeeping', 'month': month})
            staged.seek(0)
            filename = base + '.zip'
            if len(parts) == 1:
                header = staged.read(parts[0]['bytes'])
            else:
                filename = base + '-paketverzeichnis.json'
                manifest = {'format': 'atlas-monatspaket/1', 'month': month, 'parts': parts,
                            'part_count': len(parts), 'record_count': len(seen)}
                header = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
                if total + len(header) > MAX_STORED_BYTES:
                    raise JobError(PACKAGE_LIMIT)
            with self.app.db() as db:
                db.execute('INSERT INTO atlas_workflow_artifacts VALUES (?,?,?,?,?)',
                           (ident, user, filename, datetime.now(timezone.utc).isoformat(), header))
                if len(parts) > 1:
                    for part in parts:
                        db.execute('INSERT INTO atlas_workflow_parts VALUES (?,?,?,?)',
                                   (ident, part['number'], part['filename'], staged.read(part['bytes'])))
                db.execute('''DELETE FROM atlas_workflow_artifacts WHERE user_id=? AND job_id NOT IN
                    (SELECT job_id FROM atlas_workflow_artifacts WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 3)''', (user, user))
                self._cleanup(db)
                # Retain whole packages, newest first, under the previous global
                # ten-archive storage ceiling (SQLite length(BLOB) reads metadata).
                rows = db.execute('''SELECT a.job_id, length(a.archive) + COALESCE(
                    (SELECT SUM(length(p.archive)) FROM atlas_workflow_parts p WHERE p.job_id=a.job_id),0)
                    FROM atlas_workflow_artifacts a ORDER BY a.created_at DESC,a.rowid DESC''').fetchall()
                retained = 0
                for job_id, size in rows:
                    retained += size
                    if retained > MAX_STORED_BYTES:
                        db.execute('DELETE FROM atlas_workflow_artifacts WHERE job_id=?', (job_id,))
        result = {'url': url, 'filename': filename}
        if len(parts) > 1:
            result['parts'] = [{'url': f"{url}/{part['number']}", 'filename': part['filename'],
                                'record_count': part['record_count']} for part in parts]
        return result

    def filter_result(self, user, result):
        # Recheck on every read, including Telegram polling. Previously persisted
        # mixed briefings must not disclose bookkeeping after scope revocation.
        contains_books = result.get('requires_bookkeeping') or result.get('workflow') == 'bookkeeping'
        if contains_books and not self.app.bookkeeping_sync.enabled_for(user):
            return {'workflow': result.get('workflow'), 'provider': 'ATLAS', 'restricted': True,
                    'reply': 'Dieses Ergebnis enthält Buchhaltungsdaten. Die Freigabe ist nicht mehr aktiv.'}
        return result

    def download(self, user, ident, number=None):
        if not self.app.bookkeeping_sync.enabled_for(user):
            return None
        with self.app.db() as db:
            self._cleanup(db)
            if number is None:
                source = 'SELECT a.filename,a.archive FROM atlas_workflow_artifacts a '
                params = (ident, user, user)
            else:
                source = ('SELECT p.filename,p.archive FROM atlas_workflow_parts p '
                          'JOIN atlas_workflow_artifacts a ON p.job_id=a.job_id AND p.number=? ')
                params = (number, ident, user, user)
            row = db.execute(source + '''JOIN atlas_jobs j ON j.id=a.job_id
                WHERE a.job_id=? AND a.user_id=? AND j.user_id=? AND j.status='completed' ''', params).fetchone()
        return (row[0], bytes(row[1])) if row else None

    def execute(self, user, payload, ident, progress):
        def step(index, action, detail='Abgeschlossen.'):
            progress(index, 'running')
            try:
                result = action()
            except Exception as exc:
                message = 'Quellen und Protokoll prüfen.'
                if index == 3 and isinstance(exc, BookkeepingError) and str(exc) in SAFE_EXPORT_ERRORS:
                    message = str(exc)
                elif index == 3 and isinstance(exc, JobError) and str(exc) in (PACKAGE_LIMIT, 'Monatspaket überschreitet das Größenlimit von 100 MiB.'):
                    message = str(exc)
                progress(index, 'failed', message + ' Keine automatische Wiederholung.')
                raise JobError('Arbeitsablauf bei Schritt ' + str(index + 1) + ' unterbrochen. ' + message) from None
            progress(index, 'completed', detail)
            return result

        kind = payload.get('workflow')
        if kind not in TEMPLATES:
            raise JobError('Unbekannter Arbeitsablauf.')
        data = {key: payload[key] for key in ('workflow', 'month') if key in payload}
        if kind == 'bookkeeping':
            step(0, lambda: self.validate(user, data))
            sync = step(1, lambda: self.app.bookkeeping_sync.sync(user), 'Importversuch beendet; Vollständigkeit im Bericht prüfen.')
            report = step(2, lambda: build_report(self.app, user))
            def export():
                self.validate(user, data)  # Permission can be revoked during a queued/running job.
                return self._prepare_package(user, ident, data['month'])
            artifact = step(3, export)
            incomplete = bool(report['incomplete'] or sync.get('pending') or sync.get('errors'))
            reply = ('Monatspaket ' + data['month'] + ' zur Prüfung vorbereitet. '
                     + ('Quellen unvollständig; Paket enthält nur den verfügbaren Teilbestand.\n' if incomplete else '\n')
                     + 'Der folgende Überblick umfasst den gesamten importierten Bestand, nicht nur diesen Monat.\n'
                     + format_report(report) + '\nKeine fertige Buchhaltung. Pakete werden bis zu 7 Tage aufbewahrt, höchstens 3 je Profil und innerhalb des Speicherlimits.')
            return dict(workflow=kind, provider='ATLAS', reply=reply, incomplete=incomplete, artifact=artifact, requires_bookkeeping=True)
        def knowledge():
            self.validate(user, data)
            return self.app.profile(user), self.app.collection('memories', user)
        profile, memories = step(0, knowledge)
        tasks = step(1, lambda: [task for task in self.app.collection('tasks', user) if not task['done']])
        report = step(2, lambda: build_report(self.app, user) if self.app.bookkeeping_sync.enabled_for(user) else None)
        def overview():
            lines = ['ATLAS · Tagesüberblick', 'Profil: ' + (profile[:700] or 'Noch kein Profil hinterlegt.'),
                     'Gespeichertes Wissen (Auswahl):']
            lines.extend('• ' + str(item['text'])[:250] for item in memories[:5])
            if not memories:
                lines.append('Noch keine Wissenseinträge hinterlegt.')
            lines.append('Offene Aufgaben (bis zu 500 aktuelle Aufgaben geprüft): ' + str(len(tasks)))
            lines.extend('• ' + str(task['title'])[:180] for task in tasks[:10])
            if len(tasks) > 10:
                lines.append('Weitere Aufgaben in der Aufgabenliste.')
            lines.append(format_report(report) if report else 'Buchhaltungsquellen sind für dieses Profil nicht freigegeben.')
            lines.append('Überblick aus gespeicherten Daten; keine neue E-Mail-Abfrage.')
            return '\n'.join(lines)[:6000]
        reply = step(3, overview)
        return dict(workflow=kind, provider='ATLAS', reply=reply, incomplete=bool(report and report['incomplete']), requires_bookkeeping=report is not None)
