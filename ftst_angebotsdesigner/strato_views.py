"""Explicit bounded read-only STRATO pilot. Secrets stay in HA options/environment."""
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone, date
from flask import abort, request, session
from materials import account
from mail_workflow import parse_eml
from storage import RecordConflict, StorageError
import strato_imap

LOCK = threading.Lock()


def configured():
    return os.getenv('STRATO_IMAP_ENABLED', '').lower() == 'true' and bool(os.getenv('STRATO_IMAP_PASSWORD', ''))


def register(app, base, ingress, escape, get_store):
    @app.route('/mail/strato', methods=['GET', 'POST'])
    def strato_mail():
        store, identity = get_store(), account()
        state = store.record(identity, 'mail_sync', 'strato') or {}
        session.setdefault('strato_csrf', secrets.token_urlsafe(32))
        notice, status = '', 200
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf', ''), session['strato_csrf']):
                abort(400)
            if not configured():
                notice, status = 'Postfachzugang fehlt oder ist in Home Assistant deaktiviert.', 400
            elif not LOCK.acquire(blocking=False):
                notice, status = 'Ein Abruf läuft bereits. Bitte später erneut prüfen.', 409
            else:
                try:
                    expected = request.form.get('revision', '')
                    if expected != state.get('revision', ''):
                        raise RecordConflict('Der Abrufstand wurde geändert. Bitte neu laden.')
                    action = request.form.get('action')
                    password = os.environ['STRATO_IMAP_PASSWORD']
                    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    if action == 'activate' and not state:
                        checkpoint = strato_imap.activation_checkpoint(password)
                        state = dict(checkpoint, revision=uuid.uuid4().hex, activated_at=now, since=now[:10])
                        store.commit_mail_batch(identity, expected, state, [])
                        notice = 'Startpunkt gespeichert. Bereits vorhandene Nachrichten wurden nicht importiert.'
                    elif action == 'sync' and state:
                        batch = strato_imap.fetch_batch(password, date.fromisoformat(state['since']),
                                                        state['uidvalidity'], state['after_uid'])
                        parsed = []
                        for uid, raw in batch['messages']:
                            key, value, blobs = parse_eml(raw)
                            value['mail_origin'] = {'mailbox': 'info@ftst.eu', 'folder': 'INBOX',
                                                    'uidvalidity': batch['uidvalidity'], 'uid': uid}
                            parsed.append((uid, key, value, blobs))
                        updated = dict(state, uidvalidity=batch['uidvalidity'],
                                       after_uid=max([state['after_uid']] + [x[0] for x in parsed]),
                                       revision=uuid.uuid4().hex, checked_at=now, pending=batch['pending'])
                        added = store.commit_mail_batch(identity, expected, updated, parsed)
                        state = updated
                        notice = f'{added} neue Arbeitsvorgänge übernommen; {len(parsed)-added} identische Originale bereits vorhanden.'
                        if batch['pending']:
                            notice += ' Weitere Nachrichten warten. Nächsten Abruf bewusst starten.'
                    else:
                        abort(400)
                except strato_imap.UIDValidityChanged:
                    notice, status = 'Die Postfachkennung hat sich geändert. Der Abruf wurde unverändert angehalten. Vor einer neuen Aktivierung ist ein technischer Abgleich der bereits importierten Nachrichten nötig; dieser Pilot bietet keinen automatischen Neustart.', 409
                except (strato_imap.ImapFetchError, RecordConflict, StorageError) as exc:
                    notice, status = str(exc), 409
                except ValueError:
                    notice, status = 'Eine Nachricht konnte nicht sicher importiert werden. Der ganze Abruf bleibt unverändert; bitte Original separat prüfen.', 400
                finally:
                    LOCK.release()
                state = store.record(identity, 'mail_sync', 'strato') or {}
        token = '<input type="hidden" name="csrf" value="' + escape(session['strato_csrf']) + '">'
        revision = '<input type="hidden" name="revision" value="' + escape(state.get('revision', '')) + '">'
        connection = 'Zugang konfiguriert; Verbindung noch nicht geprüft.' if configured() else 'Nicht eingerichtet: Freigabeschalter oder Passwort fehlt.'
        if configured() and state:
            connection = 'Startpunkt erfolgreich bestätigt.'
            if state.get('checked_at'):
                connection = 'Mindestens ein lesender Abruf wurde erfolgreich abgeschlossen. Zeitpunkt siehe unten.'
        controls = ''
        if configured():
            action, label = ('sync', 'Jetzt bis zu 10 neue E-Mails lesen') if state else ('activate', 'Startpunkt ab jetzt festlegen')
            controls = '<form method="post">' + token + revision + '<button class="btn" name="action" value="' + action + '">' + label + '</button></form>'
        state_text = ('<p>Aktiviert: ' + escape(state['activated_at']) + ' UTC</p><p>Zuletzt geprüft: ' + escape(state.get('checked_at', 'Noch kein Abruf')) + '</p>') if state else '<p>Noch kein Startpunkt. Nach Aktivierung werden nur anschließend eingegangene Nachrichten angeboten.</p>'
        body = ('<div class="back"><a href="' + ingress('mail') + '">← Mail-Arbeitsliste</a></div>'
                '<div class="card"><div class="eyebrow">Lesender Postfachpilot</div><h1>STRATO-Eingang</h1>'
                '<p>info@ftst.eu · Posteingang INBOX</p><p>' + connection + '</p>'
                '<p role="status">' + escape(notice) + '</p>' + state_text +
                '<p>Höchstens 10 Nachrichten und 20 MiB pro Abruf, höchstens 8 MiB je Nachricht. Originale und Anhänge bleiben erhalten. '
                'Keine Gelesen-Markierung, kein Verschieben, Löschen oder Versand. Keine automatische KI-Auswertung.</p>' + controls + '</div>'
                '<div class="card"><h2>Zugang in Home Assistant einrichten</h2><p>Nach Installation: Einstellungen → Apps → FTST AngebotsDesigner → Konfiguration. '
                'Dort STRATO-Lesepilot aktivieren und das Postfachpasswort im verdeckten Passwortfeld eintragen, speichern und App neu starten. '
                'Das Passwort nicht hier oder im Chat eingeben.</p><p>Nur vertrauenswürdige Home-Assistant-Administratoren dürfen Zugriff auf die App haben. '
                'Die HA-Konfiguration enthält das Passwort; die verdeckte Anzeige ist keine Verschlüsselung der Konfigurationsdatei. '
                'Sicherungen mit Zugangsdaten nur verschlüsselt aufbewahren.</p></div>')
        response = app.make_response((base('STRATO-Eingang', body), status))
        response.headers['Cache-Control'] = 'no-store'
        return response
