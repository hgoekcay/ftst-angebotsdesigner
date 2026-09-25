"""Persistent chat orchestrator. Only explicit, revision-bound UI actions write externally."""
import json
import hashlib
import secrets
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from flask import abort, redirect, request, session, send_file

import customers
import offer_chat_ai
import offer_mail
import quote_drafts as quotes
import quote_transfer
from materials import account
from storage import RecordConflict, StorageError
from project_ai import AIError

KIND = 'offer_chat'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def db_record(db, identity, kind, key):
    row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?', (identity, kind, key)).fetchone()
    return json.loads(row[0]) if row else None


def db_put(db, identity, kind, key, value):
    db.execute('INSERT INTO records(account,kind,id,payload) VALUES(?,?,?,?) '
               'ON CONFLICT(account,kind,id) DO UPDATE SET payload=excluded.payload',
               (identity, kind, key, json.dumps(value, ensure_ascii=False)))


def client_name(c):
    return ' '.join(str(c.get(k) or '') for k in ('name', 'first_name', 'last_name')).strip()


def load_catalog(store, identity, force=False):
    cache = store.record(identity, 'catalog', 'chat') or {}
    if force or not cache or time.time() - cache.get('epoch', 0) > 900:
        raw = quote_transfer.api().draft_catalog()
        data = quotes.catalog_snapshot(raw)
        # Keep customer addresses for the review PDF; prices still use existing calculator.
        data['clients'] = [dict(c, **{k: raw_c.get(k) for k in ('street', 'zip', 'city', 'country_code', 'email')})
                           for c, raw_c in zip(data['clients'], raw['clients'])]
        cache = dict(data=data, at=stamp(), epoch=time.time())
        store.put_record(identity, 'catalog', 'chat', cache)
    return cache


def make_draft(state, project, old, catalog):
    rows = []
    articles = catalog['data']['articles']
    for row in state['rows']:
        description = row['description']
        if any(word in description.casefold() for word in ('bewegungsmelder', 'magnetkontakt', 'sirene', 'bedienteil', 'alarmzentrale')) and 'ajax' not in description.casefold():
            description = 'Ajax ' + description
        selected = next((r.get('article_id', '') for r in old.get('rows', []) if r['description'] == description), '')
        exact = [a for a in articles if customers.normalize(description) in
                 (customers.normalize(a.get('article_number') or ''), customers.normalize(a.get('title') or ''))]
        if len(exact) == 1:
            selected = str(exact[0]['id'])
        rows.append(dict(description=description, quantity='' if row['quantity'] is None else str(row['quantity']), article_id=selected))
    matches = [c for c in catalog['data']['clients'] if state['name'] and str(c.get('archived')) != '1'
               and customers.normalize(state['name']) == customers.normalize(client_name(c))]
    cid = old.get('client_id', '') if old.get('chat_customer') == state['name'] else ''
    if not cid and len(matches) == 1:
        cid = str(matches[0]['id'])
    return dict(rows=rows, client_id=cid, chat_customer=state['name'], catalog=catalog['data'], catalog_at=catalog['at'],
                source=quotes.fingerprint(project), revision=uuid4().hex, reviewed=False, tax_confirmed='',
                presentation={'title': state['title'] or 'Ihr Leistungsvorschlag', 'intro': '', 'summary': ''})


def outcome_text(state, draft):
    result = quotes.calculate(draft)
    text = 'Ich habe ' + str(len(draft['rows'])) + (' Position' if len(draft['rows']) == 1 else ' Positionen') + ' im Entwurf gespeichert.'
    if result['total']:
        text += ' Die aktuelle Summe beträgt ' + quotes.display_money(result['total']['gross']) + ' ' + result['currency'] + ' brutto. Bitte prüfe unten die Auswahl und den Leistungsumfang.'
    else:
        text += ' Für die fertige Kalkulation fehlt noch: ' + ' '.join(result['problems'][:6])
    if state['questions']:
        text += '\n' + '\n'.join(state['questions'][:6])
    text += '\nDu kannst hier korrigieren, z. B. „statt 6 jetzt 8 Bewegungsmelder“, oder unten den passenden Artikel auswählen.'
    return text


def start_thread(target):
    threading.Thread(target=target, daemon=True, name='ftst-chat').start()


def register(app, base, ingress, clean, get_store, get_offer, make_pdf, infer_type):
    from offer_chat_view import render

    def csrf():
        return session.setdefault('offer_chat_csrf', secrets.token_urlsafe(32))

    def protect():
        if (not secrets.compare_digest(request.form.get('csrf', '').encode(), csrf().encode())
                or request.form.get('account') != account()):
            abort(400, 'Sitzung abgelaufen. Chat bitte neu öffnen.')

    def load(key):
        value = get_store().record(account(), KIND, key)
        if not value:
            abort(404)
        return value

    @app.route('/chat', methods=['GET', 'POST'])
    def chat_home():
        if request.method == 'POST':
            protect()
            key = uuid4().hex
            value = dict(revision=uuid4().hex, title='Neuer Leistungsvorschlag', state=deepcopy(offer_chat_ai.EMPTY),
                         messages=[dict(role='assistant', text='Was soll ich vorbereiten? Nenne Kunde, Geräte und Mengen. Für Alarmanlagen verwenden wir Ajax. Du kannst auch eine Sprachnotiz hochladen.')], job=None, at=stamp())
            get_store().put_record(account(), KIND, key, value)
            return redirect(ingress('chat/' + key), code=303)
        rows = sorted(get_store().records(account(), KIND).items(), key=lambda row: row[1].get('at', ''), reverse=True)
        cards = ''.join('<p><a href="' + ingress('chat/' + key) + '">' + clean(value['title']) + '</a></p>' for key, value in rows)
        return base('FTST Chat', '<section class="card"><h1>FTST Chat</h1><p>Vom Gespräch zum Leistungsvorschlag. Text und Sprache werden lokal verarbeitet.</p><form method="post"><input type="hidden" name="csrf" value="' + csrf() + '"><input type="hidden" name="account" value="' + clean(account()) + '"><button class="btn">Neuen Chat starten</button></form>' + cards + '</section>')

    def worker(identity, key, job, form, audio):
        with app.test_request_context():
            store = get_store()
            chat = store.record(identity, KIND, key)
            expected_project = store.record(identity, 'project', key)
            expected_draft = store.record(identity, 'quote', key)
            project, draft = deepcopy(expected_project), deepcopy(expected_draft)
            message, updates = '', {}
            action = job['action']
            try:
                transfer = store.record(identity, 'quote_transfer', key)
                if action not in ('voice', 'transfer_status', 'release_status') and job.get('snapshot') != [digest(expected_project), digest(expected_draft), digest(transfer)]:
                    raise RecordConflict('Projekt oder Kalkulation während der Verarbeitung geändert. Bitte den aktuellen Stand prüfen.')
                if action in ('select', 'review', 'create', 'customer') and (expected_draft or {}).get('revision', '') != form.get('draft_revision', ''):
                    raise RecordConflict('Kalkulation inzwischen geändert. Bitte neu laden und prüfen.')
                if action == 'release' and (transfer or {}).get('token', '') != form.get('transfer_token', ''):
                    raise RecordConflict('Billomat-Vorschau inzwischen geändert. Bitte neu laden.')
                if action in ('message', 'select', 'catalog', 'customer', 'review') and transfer:
                    raise ValueError('Dieser Entwurf wurde bereits an Billomat übergeben. Für einen anderen Leistungsumfang bitte einen neuen Chat beginnen. Den vorhandenen Vorgang kannst du unten fertigstellen.')
                if action == 'voice':
                    from chat_voice import transcribe
                    updates['transcript'] = transcribe(audio[0], audio[1])
                    message = 'Sprachnotiz erkannt. Bitte den Text im Eingabefeld prüfen und als Nachricht senden.'
                elif action == 'message' and form.get('message', '').strip().casefold().rstrip('.!') in ('ja', 'ja passt', 'ja, passt', 'ja passt so', 'ja, passt so', 'passt so', 'das passt'):
                    if not draft or quotes.calculate(draft)['total'] is None:
                        raise ValueError('Es fehlen noch Angaben in der Auswahl unten. Bitte zuerst Kunde, Artikelvarianten und Mengen vervollständigen.')
                    draft.update(reviewed=True, revision=uuid4().hex)
                    message = 'Die Kalkulation ist als geprüft gespeichert. Öffne den PDF-Entwurf; danach kannst du die Anlage in Billomat bestätigen. Es wurde noch nichts verschickt.'
                elif action in ('message', 'catalog'):
                    state = offer_chat_ai.extract(chat['state'], chat['messages']) if action == 'message' else chat['state']
                    updates['state'] = state
                    updates['title'] = state['name'] or state['title'] or chat['title']
                    notes = '\n'.join(m['text'] for m in chat['messages'] if m['role'] == 'user')
                    project = dict(title=updates['title'], notes=notes, analysis=dict(summary=state['title'], components=state['rows'], questions=state['questions']), offer_id='')
                    catalog = load_catalog(store, identity, force=action == 'catalog')
                    draft = make_draft(state, project, draft or {}, catalog)
                    message = outcome_text(state, draft)
                elif action == 'select':
                    if not draft:
                        raise ValueError('Bitte zuerst eine Nachricht mit den Anforderungen senden.')
                    if len(form.get('article_id', [])) != len(draft['rows']) or len(form.get('quantity', [])) != len(draft['rows']):
                        raise ValueError('Positionsliste wurde geändert. Bitte neu laden.')
                    valid_ids = {str(a['id']) for a in draft['catalog']['articles']} | {''}
                    for row, aid, qty in zip(draft['rows'], form['article_id'], form['quantity']):
                        if aid not in valid_ids:
                            raise ValueError('Artikel nicht im geladenen Katalog.')
                        if qty:
                            qty = str(quotes.number(qty, '1000000'))
                        row.update(article_id=aid, quantity=qty[:30])
                    cid = form.get('client_id', '')
                    if cid not in {str(c['id']) for c in draft['catalog']['clients'] if str(c.get('archived')) != '1'} | {''}:
                        raise ValueError('Kunde nicht im Katalog.')
                    draft.update(client_id=cid, tax_confirmed='yes' if form.get('tax_confirmed') == 'yes' else '', reviewed=False, revision=uuid4().hex)
                    # Manual quantities become explicit user facts for subsequent corrections.
                    state = deepcopy(chat['state'])
                    state['rows'] = [dict(description=r['description'], quantity=float(r['quantity']) if r['quantity'] else None,
                                          evidence=r['quantity'] + ' ' + r['description']) for r in draft['rows']]
                    updates['state'] = state
                    updates['manual_message'] = '\n'.join(r['evidence'] for r in state['rows'])
                    message = outcome_text(state, draft)
                elif action == 'review':
                    if not draft or quotes.calculate(draft)['total'] is None or draft['source'] != quotes.fingerprint(project):
                        raise ValueError('Bitte zuerst Kunde, Artikel, Mengen und Steuerregel vollständig auswählen.')
                    if form.get('confirm') != 'yes':
                        raise ValueError('Bitte Leistungsumfang und Kalkulation bestätigen.')
                    draft.update(reviewed=True, revision=uuid4().hex)
                    message = 'Die Kalkulation ist bestätigt. Öffne jetzt den PDF-Entwurf. Danach kannst du den geprüften Entwurf in Billomat anlegen.'
                elif action == 'create':
                    if form.get('confirm') != 'yes':
                        raise ValueError('Bitte den geprüften Entwurf zur Anlage bestätigen.')
                    review = quote_transfer.prepare(store, identity, key, quote_transfer.api(), infer_type)
                    if review['draft'] != expected_draft or review['project'] != expected_project:
                        raise RecordConflict('Entwurf inzwischen geändert. Bitte die aktuelle Vorschau prüfen.')
                    result = quote_transfer.submit(store, identity, key, review['token'], quote_transfer.api())
                    message = 'Billomat-Entwurf angelegt und geprüft.' if result['status'] == 'created' else 'Die Billomat-Rückmeldung ist noch nicht eindeutig. Bitte unten den Status prüfen; nicht erneut anlegen.'
                elif action in ('release', 'release_status'):
                    import chat_release
                    if action == 'release' and form.get('confirm') != 'yes':
                        raise ValueError('Bitte die Freigabe in Billomat bestätigen.')
                    operation = chat_release.complete if action == 'release' else chat_release.reconcile
                    result = operation(store, identity, key, quote_transfer.api())
                    message = 'Billomat-Freigabe geprüft. Den aktuellen Status und die nächste Aktion findest du unten.'
                elif action == 'transfer_status':
                    quote_transfer.reconcile(store, identity, key, quote_transfer.api())
                    message = 'Billomat-Status neu gelesen. Es wurde kein weiteres Angebot angelegt.'
                elif action == 'mail':
                    oid = (store.record(identity, 'project', key) or {}).get('offer_id')
                    if not oid:
                        raise ValueError('Bitte den Entwurf zuerst in Billomat anlegen und freigeben.')
                    offer = get_offer(oid)
                    if offer.get('is_draft') or str(offer.get('id')) != str(oid):
                        raise ValueError('Dieser Leistungsvorschlag ist noch nicht freigegeben.')
                    subject, text, _ = offer_mail.messages(offer)
                    recipient = form.get('recipient', '').strip()
                    values = dict(recipient=recipient, subject=subject, text=text)
                    offer_mail.validate(values)
                    record = offer_mail.freeze(store, identity, oid, values, offer, make_pdf(offer).getvalue())
                    updates['email_id'] = record['id']
                    message = 'E-Mail und PDF sind vorbereitet, noch nicht versendet. Bitte Empfänger und Vorschau prüfen. Für den Versand den grünen Bestätigungsknopf verwenden.'
                elif action == 'customer':
                    if form.get('confirm') != 'yes':
                        raise ValueError('Bitte die angezeigten Kundendaten zur Anlage bestätigen.')
                    fields = customers.customer_fields(dict(chat['state'], www=''))
                    customer_key = 'chat-' + key + '-' + chat['revision']
                    store.put_record(identity, 'customer_draft', customer_key, dict(fields=fields, revision=chat['revision']))
                    result = customers.submit(store, identity, customer_key, chat['revision'], quote_transfer.api())
                    if result['status'] != 'created':
                        raise ValueError('Kunde existiert bereits oder Anlage ist ungeklärt. Bitte Kundenbestand prüfen. Es wird kein zweiter Kunde angelegt.')
                    catalog = load_catalog(store, identity, True)
                    draft = make_draft(chat['state'], project, draft or {}, catalog)
                    draft['client_id'] = result['client_id']
                    message = 'Kunde in Billomat angelegt und im Entwurf ausgewählt. Die Versandadresse bleibt im Chat zur Prüfung hinterlegt.'
                else:
                    raise ValueError('Unbekannte Chataktion.')
            except StorageError:
                raise
            except (ValueError, RecordConflict, AIError) as exc:
                message = str(exc)
                project, draft, updates = expected_project, expected_draft, {}
            except Exception:
                message = 'Die Verarbeitung konnte nicht abgeschlossen werden. Deine Eingabe bleibt gespeichert. Bitte den Dienst beziehungsweise den Vorgangsstatus prüfen; es wird nichts automatisch wiederholt.'
                project, draft, updates = expected_project, expected_draft, {}

            def finish(current, db):
                if not current or (current.get('job') or {}).get('id') != job['id']:
                    return current
                if action in ('message', 'select', 'catalog', 'customer', 'review'):
                    if db_record(db, identity, 'project', key) != expected_project or db_record(db, identity, 'quote', key) != expected_draft:
                        current['messages'].append(dict(role='assistant', text='Der Entwurf wurde parallel geändert. Der andere Stand bleibt erhalten. Bitte neu laden und abgleichen.'))
                        return dict(current, job=None, revision=uuid4().hex, at=stamp())
                    if project is not None:
                        db_put(db, identity, 'project', key, project)
                    if draft is not None:
                        db_put(db, identity, 'quote', key, draft)
                current.update({k: v for k, v in updates.items() if k != 'manual_message'})
                if updates.get('manual_message'):
                    current['messages'].append(dict(role='user', text=updates['manual_message']))
                current['messages'].append(dict(role='assistant', text=message))
                return dict(current, job=None, revision=uuid4().hex, at=stamp())
            store.transact_record(identity, KIND, key, finish)

    @app.route('/chat/<key>', methods=['GET', 'POST'])
    def chat_detail(key):
        chat = load(key)
        store, identity = get_store(), account()
        if request.method == 'POST':
            protect()
            action = request.form.get('action', 'message')
            form = request.form.to_dict()
            for field in ('article_id', 'quantity'):
                form[field] = request.form.getlist(field)
            text = form.get('message', '').strip()
            if action == 'message' and (not text or len(text) > 2000):
                abort(400, 'Bitte 1 bis 2000 Zeichen pro Nachricht verwenden.')
            if action not in {'message', 'voice', 'select', 'review', 'create', 'release', 'release_status', 'transfer_status', 'catalog', 'mail', 'customer'}:
                abort(400)
            audio = None
            if action == 'voice':
                upload = request.files.get('audio')
                if not upload or not upload.filename:
                    abort(400, 'Bitte eine Sprachnotiz auswählen.')
                audio = (upload.filename, upload.stream.read(12 * 1024 * 1024 + 1))
                if len(audio[1]) > 12 * 1024 * 1024:
                    abort(413, 'Sprachnotiz maximal 12 MB.')
            job = dict(id=uuid4().hex, action=action, started=time.time())
            def claim(current, _db):
                if not current or current['revision'] != form.get('revision') or current.get('job'):
                    raise RecordConflict('Der Chat wurde geändert oder wird gerade verarbeitet. Bitte neu laden.')
                if action in ('message', 'voice') and len(current['messages']) >= 100:
                    raise RecordConflict('Bitte einen neuen Chat beginnen; der bisherige Verlauf bleibt erhalten.')
                if action in ('message', 'select', 'review', 'create', 'customer', 'catalog'):
                    saved_draft = db_record(_db, identity, 'quote', key) or {}
                    if saved_draft.get('revision', '') != form.get('draft_revision', ''):
                        raise RecordConflict('Die Kalkulation wurde außerhalb des Chats geändert. Bitte neu laden.')
                if action == 'release':
                    saved_transfer = db_record(_db, identity, 'quote_transfer', key) or {}
                    if saved_transfer.get('token', '') != form.get('transfer_token', ''):
                        raise RecordConflict('Die Billomat-Vorschau wurde geändert. Bitte neu laden.')
                job['snapshot'] = [digest(db_record(_db, identity, kind, key)) for kind in ('project', 'quote', 'quote_transfer')]
                if action == 'message':
                    current['messages'].append(dict(role='user', text=text))
                    current.pop('transcript', None)
                    current.pop('email_id', None)
                return dict(current, job=job, revision=uuid4().hex, at=stamp())
            try:
                store.transact_record(identity, KIND, key, claim)
            except RecordConflict as exc:
                abort(409, str(exc))
            start_thread(lambda: worker(identity, key, job, form, audio))
            return redirect(ingress('chat/' + key), code=303)
        draft = store.record(identity, 'quote', key)
        project = store.record(identity, 'project', key)
        transfer = store.record(identity, 'quote_transfer', key)
        release = store.record(identity, 'chat_release', key)
        mail = store.record(identity, offer_mail.KIND, chat.get('email_id', '')) if chat.get('email_id') else None
        body = render(chat, key, draft, project, transfer, release, mail, csrf(), identity, ingress, clean, app.config.get('CHAT_ASSET_VERSION', '0.23.0'))
        response = app.make_response(base('FTST Chat', body))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/chat/<key>/status')
    def chat_status(key):
        chat = load(key)
        # On a process restart do not replay a job, especially an external write.
        if chat.get('job') and time.time() - chat['job']['started'] > 300:
            def expire(current, _db):
                if current.get('job') == chat['job']:
                    current['messages'].append(dict(role='assistant', text='Verarbeitung unterbrochen. Eingaben sind erhalten. Bei Billomat-Aktionen den Status prüfen; nicht erneut anlegen.'))
                    return dict(current, job=None, revision=uuid4().hex)
                return current
            chat = get_store().transact_record(account(), KIND, key, expire)
        return {'busy': bool(chat.get('job')), 'revision': chat['revision']}, 200, {'Cache-Control': 'no-store'}

    @app.get('/chat/<key>/pdf')
    def chat_pdf(key):
        chat = load(key)
        store, identity = get_store(), account()
        project, draft = store.record(identity, 'project', key), store.record(identity, 'quote', key)
        if chat.get('job') or request.args.get('revision') != chat['revision'] or not draft or draft['source'] != quotes.fingerprint(project):
            abort(409, 'Bitte den aktuellen Chatstand öffnen.')
        import quote_export
        document = quote_export.build(dict(project, id=key), draft, quotes.calculate(draft), store)
        if store.record(identity, 'quote', key) != draft or store.record(identity, KIND, key) != chat:
            abort(409, 'Entwurf inzwischen geändert.')
        response = send_file(document, mimetype='application/pdf', download_name='FTST-Chat-Entwurf.pdf')
        response.headers['Cache-Control'] = 'no-store'
        return response

