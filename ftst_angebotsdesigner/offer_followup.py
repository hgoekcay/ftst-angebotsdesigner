"""Account-bound local offer reminders; never sends mail or changes Billomat."""
import hmac
import os
import re
import secrets
from datetime import date, datetime, timezone
from uuid import uuid4

from flask import abort, redirect, request, session

from billomat_client import BillomatClient
from storage import RecordConflict

KIND = 'offer_followup'


def current_account():
    bid = os.getenv('BILLOMAT_ID', '').strip()
    key = os.getenv('BILLOMAT_API_KEY', '').strip()
    if not bid or not key:
        abort(503, 'Billomat-Verbindung bitte einrichten.')
    return bid.lower(), BillomatClient(bid, key)


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,17}', value):
        abort(400, 'Ungültige Angebots-ID.')
    return value


def valid_input(values):
    due = values.get('due_date', '').strip()
    note = values.get('note', '').strip()
    revision = values.get('revision', '')
    operation = values.get('operation', '')
    if len(note) > 2000:
        raise ValueError('Die Notiz darf höchstens 2000 Zeichen enthalten.')
    if due:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due):
            raise ValueError('Bitte ein gültiges Datum auswählen.')
        try:
            parsed = date.fromisoformat(due)
        except ValueError as exc:
            raise ValueError('Bitte ein gültiges Datum auswählen.') from exc
        if not 2000 <= parsed.year <= 2100:
            raise ValueError('Bitte ein Datum zwischen 2000 und 2100 auswählen.')
    if revision and not re.fullmatch(r'[a-f0-9]{32}', revision):
        raise ValueError('Der Bearbeitungsstand ist ungültig. Bitte neu laden.')
    if not re.fullmatch(r'[a-f0-9]{32}', operation):
        raise ValueError('Der Speicherversuch ist ungültig. Bitte neu laden.')
    return due, note, revision, operation


def save(store, account, offer, values):
    due, note, expected, operation = valid_input(values)
    oid = valid_id(str(offer.get('id', '')))

    def change(current, _db):
        current = current or {}
        if current.get('operation') == operation:
            if current.get('due_date', '') == due and current.get('note', '') == note:
                return current
            raise RecordConflict('Dieser Speicherversuch wurde bereits mit anderen Angaben übernommen. Bitte den aktuellen Stand öffnen.')
        if current.get('revision', '') != expected:
            raise RecordConflict('Die Wiedervorlage wurde inzwischen geändert. Ihre Eingaben wurden nicht überschrieben. Bitte den aktuellen Stand öffnen.')
        return {'offer_id': oid, 'offer_number': str(offer.get('offer_number') or offer.get('number') or oid),
                'title': str(offer.get('title') or offer.get('label') or '')[:300],
                'due_date': due, 'note': note, 'revision': uuid4().hex, 'operation': operation,
                'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}

    return store.transact_record(account, KIND, oid, change)


def register(app, get_store, base, ingress, clean, date_de):
    @app.route('/offer/<oid>/followup', methods=['GET', 'POST'])
    def offer_followup(oid):
        valid_id(oid)
        account, client = current_account()
        store = get_store()
        csrf = session.setdefault('offer_followup_csrf', secrets.token_urlsafe(32))

        def form(offer, value, *, error='', status=200):
            number = clean(offer.get('offer_number') or offer.get('number') or oid)
            saved = '<p class="success" role="status">Wiedervorlage gespeichert.</p>' if request.args.get('saved') == '1' and not error else ''
            alert = '<p role="alert">' + clean(error) + '</p>' if error else ''
            body = ('<div class="back"><a href="' + ingress('offers') + '">← Zur Angebotsübersicht</a></div>'
                    '<div class="card"><div class="eyebrow">Angebot ' + number + '</div><h1>Wiedervorlage</h1>' + saved + alert +
                    '<p>Datum und Notiz werden in dieser App gespeichert. Es werden keine Nachrichten versendet.</p>'
                    '<form method="post"><input type="hidden" name="account" value="' + clean(account) + '">' +
                    '<input type="hidden" name="csrf" value="' + clean(csrf) + '">' +
                    '<input type="hidden" name="revision" value="' + clean(value.get('revision', '')) + '">' +
                    '<input type="hidden" name="operation" value="' + clean(value.get('operation') or uuid4().hex) + '">' +
                    '<div class="field"><label for="followup-date">Wiedervorlage am</label>'
                    '<input type="date" id="followup-date" name="due_date" min="2000-01-01" max="2100-12-31" value="' + clean(value.get('due_date', '')) + '"></div>' +
                    '<div class="field"><label for="followup-note">Interne Notiz</label><textarea id="followup-note" name="note" maxlength="2000">' + clean(value.get('note', '')) + '</textarea></div>' +
                    '<p class="muted">Zum Aufheben der Wiedervorlage das Datum leeren und speichern. Die Notiz kann erhalten bleiben.</p>'
                    '<button class="btn">Wiedervorlage speichern</button></form>' +
                    ('<a class="btn light" href="' + ingress('offer/' + oid + '/followup') + '">Aktuellen Stand öffnen</a>' if error else '') +
                    '<a class="btn light" href="' + ingress('offer/' + oid) + '">Angebot öffnen</a></div>')
            response = app.make_response((base('Wiedervorlage', body), status))
            response.headers['Cache-Control'] = 'no-store'
            return response

        if request.method == 'POST':
            if not hmac.compare_digest(request.form.get('csrf', '').encode('utf-8'), csrf.encode('utf-8')):
                abort(400, 'Die Formularsitzung ist abgelaufen. Bitte neu öffnen.')
            if request.form.get('account') != account:
                abort(409, 'Das Billomat-Konto wurde geändert. Bitte neu öffnen.')
            try:
                valid_input(request.form)
            except ValueError as exc:
                return form({'id': oid}, request.form, error=str(exc), status=400)
        try:
            offer = client.get_offer(oid)
        except Exception:
            return form({'id': oid}, request.form if request.method == 'POST' else {},
                        error='Das Angebot konnte bei Billomat nicht geprüft werden. Bitte später erneut versuchen.', status=502)
        if not isinstance(offer, dict) or str(offer.get('id', '')) != oid:
            abort(404, 'Angebot in diesem Billomat-Konto nicht gefunden.')
        if request.method == 'POST':
            try:
                save(store, account, offer, request.form)
            except RecordConflict as exc:
                return form(offer, request.form, error=str(exc), status=409)
            return redirect(ingress('offer/' + oid + '/followup') + '?saved=1', code=303)
        value = store.record(account, KIND, oid) or {}
        # A fresh form is a new operation; only retries of the same POST reuse one.
        return form(offer, dict(value, operation=uuid4().hex))
