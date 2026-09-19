"""Explicit bounded read-only STRATO pilot. Secrets stay in HA options/environment."""
import os
import hashlib
import secrets
import threading
import uuid
from datetime import datetime, timezone, date
from flask import abort, request, session
from materials import account
from mail_workflow import parse_eml
from storage import RecordConflict, StorageError
import strato_imap
import strato_bridge

LOCK = threading.Lock()


def provider():
    name = os.getenv('STRATO_PROVIDER', 'direct')
    if name == 'bridge':
        return strato_bridge, os.getenv('STRATO_BRIDGE_TOKEN', '')
    if name == 'direct':
        return strato_imap, os.getenv('STRATO_IMAP_PASSWORD', '')
    return None, ''


def configured():
    transport, secret = provider()
    return os.getenv('STRATO_IMAP_ENABLED', '').lower() == 'true' and transport is not None and bool(secret)


def sync_key(account_id='primary'):
    strato_bridge.validate_account_id(account_id)
    return 'strato' if account_id == 'primary' else 'strato:' + account_id


def list_mailboxes():
    transport, secret = provider()
    if transport is strato_bridge:
        return strato_bridge.list_accounts(secret)
    return [{'id': 'primary', 'email': 'info@ftst.eu', 'folder': 'INBOX'}]


def _bound_source(account_id):
    mailbox = next((item for item in list_mailboxes() if item['id'] == account_id), None)
    if mailbox is None:
        raise RecordConflict('Postfach ist nicht verfügbar oder deaktiviert.')
    return {'provider': os.getenv('STRATO_PROVIDER', 'direct'), 'account_id': account_id,
            'mailbox': mailbox['email'], 'folder': mailbox['folder']}


def _execute(store, identity, action, expected=None, account_id='primary'):
    if not configured():
        raise strato_imap.ImapFetchError('Postfachzugang fehlt oder ist deaktiviert.')
    if not LOCK.acquire(blocking=False):
        raise RecordConflict('Ein Abruf läuft bereits. Bitte später erneut prüfen.')
    try:
        checkpoint_key = sync_key(account_id)
        state = store.record(identity, 'mail_sync', checkpoint_key) or {}
        revision = state.get('revision', '')
        if expected is not None and expected != revision:
            raise RecordConflict('Der Abrufstand wurde geändert. Bitte neu laden.')
        legacy_source = {'provider': 'direct', 'mailbox': 'info@ftst.eu', 'folder': 'INBOX'}
        source = _bound_source(account_id)
        previous_source = dict(state.get('source', legacy_source))
        previous_source.setdefault('account_id', 'primary')
        if state and previous_source != source:
            raise RecordConflict('Die Postfachquelle wurde geändert. Vor dem Weiterabruf ist ein technischer Abgleich erforderlich.')
        transport, secret = provider()
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if action == 'activate' and not state:
            checkpoint = transport.activation_checkpoint(secret, account_id=account_id, expected_source={'email': source['mailbox'], 'folder': source['folder']}) if transport is strato_bridge else transport.activation_checkpoint(secret)
            updated = dict(checkpoint, revision=uuid.uuid4().hex, activated_at=now, since=now[:10], source=source)
            store.commit_mail_batch(identity, revision, updated, [], sync_key=checkpoint_key)
            return {'added': 0, 'processed': 0, 'keys': [], 'state': updated}
        if action in ('pause', 'resume') and state:
            updated = dict(state, paused=action == 'pause', revision=uuid.uuid4().hex)
            store.commit_mail_batch(identity, revision, updated, [], sync_key=checkpoint_key)
            return {'added': 0, 'processed': 0, 'keys': [], 'state': updated}
        if action != 'sync' or not state:
            raise RecordConflict('Startpunkt fehlt oder wurde bereits festgelegt.')
        if state.get('paused'):
            raise RecordConflict('Dieses Postfach ist pausiert.')
        kwargs = {'account_id': account_id, 'expected_source': {'email': source['mailbox'], 'folder': source['folder']}} if transport is strato_bridge else {}
        batch = transport.fetch_batch(secret, date.fromisoformat(state['since']), state['uidvalidity'], state['after_uid'], **kwargs)
        parsed = []
        for uid, raw in batch['messages']:
            key, value, blobs = parse_eml(raw)
            if account_id != 'primary':
                key = hashlib.sha256((account_id + ':' + key).encode()).hexdigest()
            value['mail_origin'] = {'account_id': account_id, 'mailbox': source['mailbox'], 'folder': source['folder'], 'uidvalidity': batch['uidvalidity'], 'uid': uid}
            parsed.append((uid, key, value, blobs))
        # Capture only genuinely new records; retries must preserve human edits.
        new_keys = list(dict.fromkeys(key for _, key, _, _ in parsed if store.record(identity, 'mail', key) is None))
        updated = dict(state, uidvalidity=batch['uidvalidity'], source=source,
                       after_uid=max([state['after_uid']] + [x[0] for x in parsed]),
                       revision=uuid.uuid4().hex, checked_at=now, pending=batch['pending'])
        added = store.commit_mail_batch(identity, revision, updated, parsed, sync_key=checkpoint_key)
        return {'added': added, 'processed': len(parsed), 'keys': new_keys, 'state': updated}
    finally:
        LOCK.release()


def activate(store, identity, expected=None, account_id='primary'):
    """Explicit activation only; establish baseline without importing old mail."""
    return _execute(store, identity, 'activate', expected, account_id)


def sync_once(store, identity, expected=None, account_id='primary'):
    """Bounded atomic import using the same lock as the UI; never auto-activate."""
    return _execute(store, identity, 'sync', expected, account_id)


def register(app, base, ingress, escape, get_store):
    @app.route('/mail/strato', methods=['GET', 'POST'])
    def strato_mail():
        store, identity = get_store(), account()
        session.setdefault('strato_csrf', secrets.token_urlsafe(32))
        notice, status = '', 200
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf', ''), session['strato_csrf']):
                abort(400)
            if not configured():
                notice, status = 'Postfachzugang fehlt oder ist in Home Assistant deaktiviert.', 400
            else:
                try:
                    expected = request.form.get('revision', '')
                    action = request.form.get('action')
                    account_id = request.form.get('account_id', 'primary')
                    if action == 'activate':
                        activate(store, identity, expected, account_id)
                        notice = 'Startpunkt gespeichert. Bereits vorhandene Nachrichten wurden nicht importiert.'
                    elif action == 'sync':
                        result = sync_once(store, identity, expected, account_id)
                        notice = f"{result['added']} neue Arbeitsvorgänge übernommen; {result['processed']-result['added']} identische Originale bereits vorhanden."
                        if result['state'].get('pending'):
                            notice += ' Weitere Nachrichten warten auf den nächsten Abruf.'
                    elif action in ('pause', 'resume'):
                        _execute(store, identity, action, expected, account_id)
                        notice = 'Postfach pausiert.' if action == 'pause' else 'Postfach wieder aktiviert.'
                    else:
                        abort(400)
                except strato_imap.UIDValidityChanged:
                    notice, status = 'Die Postfachkennung hat sich geändert. Der Abruf bleibt unverändert angehalten; technischer Abgleich erforderlich.', 409
                except (strato_imap.ImapFetchError, RecordConflict, StorageError) as exc:
                    notice, status = str(exc), 409
                except ValueError:
                    notice, status = 'Eine Nachricht konnte nicht sicher importiert werden. Der ganze Abruf bleibt unverändert.', 400
        mailboxes = []
        if configured():
            try:
                mailboxes = list_mailboxes()
            except strato_imap.ImapFetchError:
                notice = notice or 'Postfachliste derzeit nicht erreichbar. Vorhandene Abrufstände bleiben erhalten.'
        else:
            notice = notice or 'Nicht eingerichtet: Freigabeschalter oder Verbindungsschlüssel fehlt.'
        automation = store.record(identity, 'mail_automation', 'state') or {}
        cards = []
        token = '<input type="hidden" name="csrf" value="' + escape(session['strato_csrf']) + '">'
        for mailbox in mailboxes:
            account_id = mailbox['id']
            state = store.record(identity, 'mail_sync', sync_key(account_id)) or {}
            account_status = automation.get('accounts', {}).get(account_id, {})
            connection = 'Zugang konfiguriert; Verbindung noch nicht geprüft.'
            if state:
                connection = 'Startpunkt erfolgreich bestätigt.'
                if state.get('checked_at'):
                    connection = 'Mindestens ein lesender Abruf wurde erfolgreich abgeschlossen.'
                if state.get('paused'):
                    connection = 'Postfach pausiert. Kein Import und keine automatische KI-Auswertung.'
            hidden = token + '<input type="hidden" name="revision" value="' + escape(state.get('revision', '')) + '"><input type="hidden" name="account_id" value="' + escape(account_id) + '">'
            controls = '<form method="post">' + hidden
            if not state:
                controls += '<button class="btn" name="action" value="activate">Startpunkt ab jetzt festlegen</button>'
            elif state.get('paused'):
                controls += '<button class="btn" name="action" value="resume">Postfach fortsetzen</button>'
            else:
                controls += '<button class="btn" name="action" value="sync">Jetzt bis zu 10 neue E-Mails lesen</button> <button class="btn" name="action" value="pause">Postfach pausieren</button>'
            controls += '</form>'
            details = '<p>Noch kein Startpunkt. Bestehende Nachrichten werden bei Aktivierung ausgeschlossen.</p>'
            if state:
                details = '<p>Aktiviert: ' + escape(state['activated_at']) + ' UTC · Zuletzt geprüft: ' + escape(state.get('checked_at', 'Noch kein Abruf')) + '</p>'
            if account_status:
                details += '<p>Automatikstatus: ' + escape(str(account_status.get('state', 'unbekannt'))) + ' · Letzter Abruf: ' + escape(str(account_status.get('last_sync_at', 'Noch kein Abruf'))) + '</p>'
            cards.append('<div class="card"><h2>' + escape(mailbox['email']) + '</h2><p>Ordner ' + escape(mailbox['folder']) + ' · ' + connection + '</p>' + details + controls + '</div>')
        body = ('<div class="back"><a href="' + ingress('mail') + '">← Mail-Arbeitsliste</a></div>'
                '<div class="card"><h1>STRATO-Postfächer</h1><p role="status">' + escape(notice) + '</p>'
                '<p>Jedes Postfach hat einen eigenen Startpunkt und kann separat pausiert werden. Automatischer Import: ' + ('aktiviert' if os.getenv('STRATO_AUTO_IMPORT', '').lower() == 'true' else 'deaktiviert') + '. Lokale KI-Entwürfe: ' + ('aktiviert' if os.getenv('STRATO_AUTO_AI', '').lower() == 'true' else 'deaktiviert') + '.</p>'
                '<p>Pro Postfach und Abruf höchstens 10 Nachrichten und 20 MiB, höchstens 8 MiB je Nachricht. Originale und Anhänge bleiben erhalten. Keine Gelesen-Markierung, kein Verschieben, Löschen oder Versand. KI-Entwürfe vor Verwendung prüfen.</p></div>' + ''.join(cards) +
                '<div class="card"><h2>Weitere Postfächer hinzufügen</h2><p>In Home Assistant → Apps → FTST STRATO Mail → Konfiguration unter accounts eine dauerhafte eindeutige ID, E-Mail-Adresse, Passwort und Ordner eintragen; das Konto aktivieren. Anschließend die Mail-App neu starten und diese Seite neu laden. Pro neuem Konto hier den Startpunkt festlegen.</p>'
                '<p>Zugangsdaten bleiben in der lokalen Mail-App. Der AngebotsDesigner benötigt bei Anbieter bridge nur den gemeinsamen Verbindungsschlüssel. Kein automatischer Wechsel zu direct. Passwörter nicht im Chat eingeben; Sicherungen verschlüsselt aufbewahren.</p></div>')
        response = app.make_response((base('STRATO-Postfächer', body), status))
        response.headers['Cache-Control'] = 'no-store'
        return response
