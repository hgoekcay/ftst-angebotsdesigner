"""Explicit, revision-bound offer creation with durable at-most-once submission."""
import hashlib
import json
import os
import secrets
import time
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import abort, redirect, request, session
from asset_library import catalog
from billomat_client import BillomatClient, OfferWriteUncertain, OfferReadError
from materials import account
from quote_drafts import calculate, catalog_snapshot, fingerprint, display_money
from reference_selection import suggest
from storage import RecordConflict, StorageError

REVIEW_SECONDS = 900


def marker(key):
    return 'FTST-' + hashlib.sha256(key.encode()).hexdigest()[:32]


def api():
    bid, token = os.getenv('BILLOMAT_ID', '').strip(), os.getenv('BILLOMAT_API_KEY', '').strip()
    if not bid or not token:
        raise ValueError('Billomat ist noch nicht eingerichtet.')
    return BillomatClient(bid, token)


def saved(store, identity, key):
    project = store.record(identity, 'project', key)
    draft = store.record(identity, 'quote', key)
    if not project or not draft:
        raise ValueError('Bitte zuerst einen Angebotsentwurf speichern.')
    if project.get('offer_id'):
        raise ValueError('Dieses Projekt ist bereits mit einem Billomat-Angebot verknüpft.')
    if (not draft.get('revision') or not draft.get('reviewed')
            or draft.get('source') != fingerprint(project)):
        raise ValueError('Bitte die aktuellen Anforderungen und Positionen prüfen und speichern.')
    result = calculate(draft)
    if result.get('problems') or not result.get('total'):
        raise ValueError('Die Kalkulation enthält noch offene Angaben.')
    return project, draft, result


def commercial(result):
    return {key: result.get(key) for key in ('total', 'currency', 'reduction', 'group')} | {
        'lines': [{key: line.get(key) for key in ('quantity', 'unit', 'price', 'net', 'tax_rate')}
                  for line in result['lines']]}


def fresh_payload(project, draft, original, key, client_api, on_date):
    fresh = deepcopy(draft)
    fresh['catalog'] = catalog_snapshot(client_api.draft_catalog())
    result = calculate(fresh)
    if result.get('problems') or not result.get('total') or commercial(result) != commercial(original):
        raise ValueError('Billomat-Stammdaten oder Konditionen haben sich geändert. Bitte im Entwurf '
                         '„Artikel und Kunden aus Billomat laden“, erneut prüfen und speichern.')
    customer = next(c for c in fresh['catalog']['clients'] if str(c['id']) == draft['client_id'])
    articles = {str(a['id']): a for a in fresh['catalog']['articles']}
    presentation = draft.get('presentation') or {}
    title = str(presentation.get('title') or project.get('title') or 'Angebot').strip()
    intro, note = str(presentation.get('intro') or ''), str(presentation.get('summary') or '')
    if not title or len(title) > 240 or len(intro) > 4000 or len(note) > 6000:
        raise ValueError('Bitte Kundentitel, Einleitung und Projektbeschreibung prüfen.')
    rows = []
    for source, line in zip(draft['rows'], result['lines']):
        article = articles[str(source['article_id'])]
        rows.append(dict(article_id=str(source['article_id']), title=str(line['title'] or ''),
                         description=str(article.get('description') or ''), unit=line['unit'],
                         quantity=line['quantity'], unit_price=line['price'], tax_rate=line['tax_rate'],
                         reduction=result['reduction'] + '%', optional='0'))
    payload = dict(client_id=draft['client_id'], date=on_date, title=title, intro=intro, note=note,
                   label=marker(key), currency_code=result['currency'], net_gross='NET', reduction='0%',
                   **{'offer-items': {'offer-item': rows}})
    BillomatClient.validate_offer_payload(payload)
    return payload, customer, result


def prepare(store, identity, key, client_api, infer_type):
    previous = store.record(identity, 'quote_transfer', key)
    if previous:
        raise RecordConflict('Für dieses Projekt besteht bereits eine Übertragung. Bitte den Status prüfen.')
    project, draft, original = saved(store, identity, key)
    payload, customer, result = fresh_payload(project, draft, original, key, client_api, date.today().isoformat())
    kind = infer_type({'items': payload['offer-items']['offer-item']})
    images = catalog(store, identity)
    chosen = draft.get('presentation', {}).get('images')
    if chosen is None:
        chosen = suggest(images, kind)
    if not isinstance(chosen, list) or len(chosen) > 8 or any(i not in images for i in chosen):
        raise ValueError('Bitte die ausgewählten Referenzbilder prüfen und speichern.')
    review = dict(token=uuid.uuid4().hex, prepared_at=time.time(), project=deepcopy(project),
                  draft=deepcopy(draft), payload=payload, customer=customer, calculation=result,
                  images=list(chosen), offer_type=kind)

    def write(current, db):
        assert_unchanged(db, identity, key, project, draft)
        if db.execute('SELECT 1 FROM records WHERE account=? AND kind=? AND id=?',
                      (identity, 'quote_transfer', key)).fetchone():
            raise RecordConflict('Eine Übertragung wurde bereits begonnen. Bitte Status öffnen.')
        return review
    return store.transact_record(identity, 'quote_transfer_review', key, write)


def assert_unchanged(db, identity, key, project, draft):
    for kind, expected in (('project', project), ('quote', draft)):
        row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                         (identity, kind, key)).fetchone()
        if row is None or json.loads(row[0]) != expected:
            raise RecordConflict('Der Entwurf oder das Projekt wurde geändert. Bitte die Übergabe neu prüfen.')


def decimal(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Zahl fehlt')
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError('Ungültige Zahl')
    return value


def same_reduction(actual, expected):
    # Bare Billomat reductions are absolute amounts, never implicitly percentages.
    text, expected = str(actual or '0').strip(), str(expected).strip()
    if decimal(expected.rstrip('%')) == 0:
        return decimal(text.rstrip('%')) == 0
    return text.endswith('%') and decimal(text[:-1]) == decimal(expected[:-1])


def verify(offer, transfer):
    """Only complete, still-unreleased, financially identical offers pass."""
    expected, totals = transfer['payload'], transfer['calculation']['total']
    problems = []
    try:
        if str(offer.get('id', '')) != str(transfer.get('offer_id', '')):
            problems.append('Angebotskennung')
        for key in ('client_id', 'label', 'currency_code', 'net_gross'):
            if str(offer.get(key, '')) != str(expected[key]):
                problems.append({'client_id': 'Kunde', 'label': 'Referenz', 'currency_code': 'Währung',
                                 'net_gross': 'Preisbasis'}[key])
        if offer.get('status') != 'DRAFT':
            problems.append('Angebot ist kein Billomat-Entwurf mehr')
        for key in ('title', 'intro', 'note'):
            if str(offer.get(key) or '').replace('\r\n', '\n').strip() != expected[key].replace('\r\n', '\n').strip():
                problems.append('Kundentext ' + key)
        if not same_reduction(offer.get('reduction'), expected['reduction']):
            problems.append('Angebotsrabatt')
        for key, target in (('total_net', 'net'), ('total_gross', 'gross')):
            if decimal(offer.get(key)) != decimal(totals[target]):
                problems.append('Gesamtsumme ' + target)
        received, intended = offer.get('items'), expected['offer-items']['offer-item']
        if not isinstance(received, list) or len(received) != len(intended):
            problems.append('Anzahl der Positionen')
        else:
            ordered = sorted(received, key=lambda item: decimal(item.get('position')))
            if [decimal(item.get('position')) for item in ordered] != list(range(1, len(intended) + 1)):
                problems.append('Reihenfolge der Positionen')
            for i, (actual, item) in enumerate(zip(ordered, intended), 1):
                if (str(actual.get('article_id')) != item['article_id']
                        or str(actual.get('unit', '')) != item['unit']
                        or any(str(actual.get(k) or '').replace('\r\n', '\n').strip()
                               != item[k].replace('\r\n', '\n').strip() for k in ('title', 'description'))
                        or str(actual.get('optional', '0')) != '0'
                        or any(decimal(actual.get(k)) != decimal(item[k])
                               for k in ('quantity', 'unit_price', 'tax_rate'))
                        or not same_reduction(actual.get('reduction'), item['reduction'])
                        or decimal(actual.get('total_net')) != decimal(transfer['calculation']['lines'][i-1]['net'])):
                    problems.append('Position ' + str(i))
    except (ValueError, TypeError, KeyError, InvalidOperation):
        problems.append('Unvollständige oder ungültige Billomat-Rückmeldung')
    return list(dict.fromkeys(problems))


def finish(store, identity, key, transfer, offer=None, error=None):
    problems = verify(offer, transfer) if offer is not None else [error or 'Billomat-Rücklesen noch offen']
    status = 'created' if not problems else ('review' if transfer.get('offer_id') else 'unknown')

    def write(current, db):
        if not current or current.get('token') != transfer['token']:
            raise RecordConflict('Übertragungsstatus wurde geändert. Bitte neu laden.')
        if current.get('offer_id') and transfer.get('offer_id') and current['offer_id'] != transfer['offer_id']:
            raise RecordConflict('Mehrdeutige Billomat-Angebotskennung. Bitte Angebote in Billomat prüfen.')
        if current.get('status') == 'created' or (current.get('offer_id') and not transfer.get('offer_id')):
            return current  # A late, incomplete result cannot erase a confirmed remote outcome.
        updated = dict(current, status=status, offer_id=transfer.get('offer_id', ''), problems=problems,
                       checked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        if offer is not None:
            updated['offer_number'] = str(offer.get('offer_number') or '')
        if status == 'created':
            oid = transfer['offer_id']
            row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                             (identity, 'project', key)).fetchone()
            project = json.loads(row[0]) if row else None
            if project and project.get('offer_id') and project['offer_id'] != oid:
                return dict(updated, status='review', problems=['Das Projekt wurde inzwischen mit einem anderen Billomat-Angebot verknüpft. Bitte die Projektverknüpfung prüfen.'])
            payload = transfer['payload']
            source = dict(customer_title=payload['title'], customer_intro=payload['intro'],
                          project_summary=payload['note'], offer_type=transfer['offer_type'])
            # Reconciliation must never replace later manual presentation edits.
            db.execute('INSERT OR IGNORE INTO presentations(account,offer_id,payload) VALUES(?,?,?)',
                       (identity, oid, json.dumps(source, ensure_ascii=False)))
            db.execute('INSERT OR IGNORE INTO records(account,kind,id,payload) VALUES(?,?,?,?)',
                       (identity, 'offer_images', oid, json.dumps({'mode': 'manual', 'ids': transfer['images']})))
            if project is not None:
                if not project.get('offer_id') or project['offer_id'] == oid:
                    project['offer_id'] = oid
                    db.execute('UPDATE records SET payload=? WHERE account=? AND kind=? AND id=?',
                               (json.dumps(project, ensure_ascii=False), identity, 'project', key))
            # Leave the cache payload alone; the background refresh will pick up the draft.
        return updated
    return store.transact_record(identity, 'quote_transfer', key, write)


def submit(store, identity, key, review_token, client_api):
    previous = store.record(identity, 'quote_transfer', key)
    if previous:
        return previous  # One project can never submit another POST, even after edits/restarts.
    review = store.record(identity, 'quote_transfer_review', key)
    if (not review or not secrets.compare_digest(str(review.get('token', '')).encode(), str(review_token).encode())
            or not 0 <= time.time() - review['prepared_at'] <= REVIEW_SECONDS):
        raise RecordConflict('Die Vorschau ist abgelaufen. Bitte Übergabe erneut prüfen.')
    project, draft, result = saved(store, identity, key)
    if project != review['project'] or draft != review['draft']:
        raise RecordConflict('Das Projekt oder der Entwurf wurde geändert. Bitte erneut prüfen.')
    payload, customer, _ = fresh_payload(project, draft, result, key, client_api, review['payload']['date'])
    if payload != review['payload'] or customer != review['customer']:
        raise RecordConflict('Die Billomat-Daten wurden nach der Vorschau geändert. Bitte erneut prüfen.')
    images = catalog(store, identity)
    if any(i not in images for i in review['images']):
        raise RecordConflict('Ein Referenzbild fehlt. Bitte die Bildauswahl prüfen.')
    existing = client_api.find_offers_by_reference(payload['label'], payload['client_id'])
    token = uuid.uuid4().hex

    def claim(current, db):
        if current:
            raise RecordConflict('Die Übertragung wurde bereits begonnen. Bitte Status neu laden.')
        assert_unchanged(db, identity, key, project, draft)
        row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                         (identity, 'quote_transfer_review', key)).fetchone()
        if not row or json.loads(row[0]).get('token') != review_token:
            raise RecordConflict('Eine neuere Vorschau liegt vor. Bitte erneut prüfen.')
        return dict(review, token=token, status='sending', started_at=datetime.now(timezone.utc).isoformat(),
                    offer_id='', problems=[])
    transfer = store.transact_record(identity, 'quote_transfer', key, claim)
    if len(existing) > 1:
        return finish(store, identity, key, transfer, error='Mehrere Billomat-Angebote mit dieser Referenz gefunden. Bitte dort prüfen.')
    try:
        response = existing[0] if existing else client_api.create_offer_draft(payload)
        oid = str(response['id'])
        if not oid.isdigit() or int(oid) <= 0:
            raise OfferWriteUncertain('Ungültige Angebotskennung')
    except OfferWriteUncertain:
        return finish(store, identity, key, transfer, error='Übertragung nicht eindeutig bestätigt. Status in Billomat prüfen; keine erneute Anlage.')
    # Persist the known remote id before another network call. Crash recovery can read it.
    def remember(current, db):
        if not current or current.get('token') != token:
            raise RecordConflict('Übertragungsstatus geändert.')
        if current.get('offer_id') and current['offer_id'] != oid:
            raise RecordConflict('Mehrdeutige Billomat-Angebotskennung. Bitte Status prüfen.')
        return dict(current, offer_id=oid)
    transfer = store.transact_record(identity, 'quote_transfer', key, remember)
    try:
        offer = client_api.get_offer_for_verification(oid)
    except (OfferReadError, RuntimeError):
        return finish(store, identity, key, transfer)
    return finish(store, identity, key, transfer, offer)


def reconcile(store, identity, key, client_api):
    transfer = store.record(identity, 'quote_transfer', key)
    if not transfer:
        raise ValueError('Für dieses Projekt besteht noch keine Übertragung.')
    if transfer.get('offer_id'):
        offer = client_api.get_offer_for_verification(transfer['offer_id'])
    else:
        matches = client_api.find_offers_by_reference(transfer['payload']['label'], transfer['payload']['client_id'])
        if len(matches) != 1:
            return finish(store, identity, key, transfer, error=(
                'Noch kein eindeutiger Treffer in Billomat. Später erneut Status prüfen; die Anlage bleibt gesperrt.'))
        transfer = dict(transfer, offer_id=str(matches[0]['id']))
        offer = client_api.get_offer_for_verification(transfer['offer_id'])
    return finish(store, identity, key, transfer, offer)


def register(app, base, ingress, escape, get_store, infer_type):
    def csrf():
        session.setdefault('quote_transfer_csrf', secrets.token_urlsafe(32))
        return '<input type="hidden" name="csrf" value="' + escape(session['quote_transfer_csrf']) + '">'

    @app.route('/projects/<key>/quote/transfer', methods=['GET', 'POST'])
    def quote_transfer(key):
        store, identity = get_store(), account()
        if not store.record(identity, 'project', key):
            abort(404)
        notice, status = '', 200
        if request.method == 'POST':
            expected_csrf = session.get('quote_transfer_csrf')
            if not expected_csrf or not secrets.compare_digest(request.form.get('csrf', '').encode(), expected_csrf.encode()):
                abort(400, 'Formular abgelaufen. Bitte neu öffnen.')
            try:
                action = request.form.get('action')
                if action == 'prepare':
                    prepare(store, identity, key, api(), infer_type)
                elif action == 'confirm':
                    if request.form.get('confirm') != 'yes':
                        raise ValueError('Bitte die angezeigte Übernahme ausdrücklich bestätigen.')
                    submit(store, identity, key, request.form.get('review', ''), api())
                elif action == 'reconcile':
                    reconcile(store, identity, key, api())
                else:
                    abort(400)
                return redirect(ingress('projects/' + key + '/quote/transfer'))
            except StorageError:
                raise
            except (ValueError, RecordConflict) as exc:
                notice, status = '<p role="alert">' + escape(str(exc)) + '</p>', 409
            except RuntimeError:
                notice, status = '<p role="alert">Billomat ist derzeit nicht erreichbar. Gespeicherter Stand bleibt erhalten; bitte den Status erneut prüfen.</p>', 503
        token_field = csrf()
        transfer = store.record(identity, 'quote_transfer', key)
        back = ingress('projects/' + key + '/quote')
        body = f'<div class="back"><a href="{back}">← Zur Kalkulation</a></div><div class="card"><h1>Angebot an Billomat übergeben</h1>{notice}'
        if transfer:
            labels = {'sending': 'Übertragung begonnen – Bestätigung noch offen', 'unknown': 'Übertragung noch nicht eindeutig bestätigt',
                      'review': 'Angebot angelegt – Rückmeldung prüfen', 'created': 'Billomat-Entwurf angelegt und Beträge geprüft'}
            body += '<h2>' + escape(labels.get(transfer['status'], 'Status prüfen')) + '</h2>'
            body += '<ul>' + ''.join('<li>' + escape(p) + '</li>' for p in transfer.get('problems', [])) + '</ul>'
            if transfer.get('offer_id'):
                oid = transfer['offer_id']
                body += f'<p>Billomat-ID: {escape(oid)} · Angebotsnummer: {escape(transfer.get("offer_number") or "Noch nicht vergeben (Entwurf)")}</p>'
                if transfer['status'] == 'created':
                    body += f'<a class="btn" href="{ingress("offer/"+oid)}">Billomat-Entwurf in der App öffnen</a>'
            body += f'<form method="post">{token_field}<button class="btn light" name="action" value="reconcile">Status in Billomat prüfen</button></form>'
            body += '<p>Dieser Vorgang legt kein zweites Angebot an. Freigabe und Versand erfolgen weiterhin bewusst in Billomat.</p>'
        else:
            review = store.record(identity, 'quote_transfer_review', key)
            project, draft = store.record(identity, 'project', key), store.record(identity, 'quote', key)
            valid = bool(review and project == review['project'] and draft == review['draft']
                         and 0 <= time.time() - review['prepared_at'] <= REVIEW_SECONDS)
            if valid:
                p, result = review['payload'], review['calculation']
                customer = review['customer']
                name = str(customer.get('name') or '') + ' ' + ' '.join(str(customer.get(k) or '') for k in ('first_name', 'last_name'))
                body += '<h2>Übernahme prüfen</h2><p><strong>Kunde:</strong> ' + escape(name.strip() or customer['id']) + '</p>'
                body += '<p>Kundennummer: ' + escape(customer.get('client_number') or customer['id']) + '</p>'
                body += '<h3>' + escape(p['title']) + '</h3><p>' + escape(p['intro']) + '</p><p>' + escape(p['note']) + '</p>'
                rows = ''
                for line in p['offer-items']['offer-item']:
                    rows += '<tr>' + ''.join('<td data-label="' + label + '">' + escape(value) + '</td>' for label, value in (
                        ('Artikel', line['title']), ('Beschreibung', line['description']), ('Menge', line['quantity'] + ' ' + line['unit']),
                        ('Einzelpreis netto', display_money(line['unit_price']) + ' ' + result['currency']), ('Rabatt', line['reduction']),
                        ('Steuer', line['tax_rate'] + ' %'))) + '</tr>'
                body += '<table><thead><tr><th>Artikel</th><th>Beschreibung</th><th>Menge</th><th>Einzelpreis netto</th><th>Rabatt</th><th>Steuer</th></tr></thead><tbody>' + rows + '</tbody></table>'
                body += '<p class="success">' + ' · '.join(label + ' ' + display_money(result['total'][k]) for label, k in (
                    ('Netto', 'net'), ('Steuer', 'tax'), ('Brutto', 'gross'))) + ' ' + escape(result['currency']) + '</p>'
                images = catalog(store, identity)
                body += '<h3>Referenzbilder für die FTST-PDF</h3><div class="grid">' + ''.join(
                    '<figure><img class="material-preview" src="' + ingress('materials/' + i) + '" alt="' + escape(images[i]['title']) + '"><figcaption>' + escape(images[i]['title']) + '</figcaption></figure>'
                    for i in review['images'] if i in images) + '</div>'
                if len(review['images']) < 4:
                    body += '<p>Es sind ' + str(len(review['images'])) + ' passende Referenzbilder verfügbar. Weitere Fotos können über die Kundendarstellung ausgewählt werden.</p>'
                body += '<p>Fotos und FTST-Gestaltung bleiben beim Angebot in dieser App. In Billomat werden Kunde, Texte und Positionen als Entwurf angelegt. Es erfolgt kein Kundenversand.</p>'
                body += f'<form method="post">{token_field}<input type="hidden" name="review" value="{escape(review["token"])}"><label><input type="checkbox" name="confirm" value="yes" required> Kunde, Positionen und Beträge geprüft – diesen Entwurf in Billomat anlegen.</label><button class="btn" name="action" value="confirm">Als Entwurf in Billomat anlegen</button></form>'
            else:
                body += '<p>Die Übergabe prüft die aktuellen Billomat-Stammdaten und zeigt alle zu übernehmenden Angaben zur Bestätigung.</p>'
            body += f'<form method="post">{token_field}<button class="btn light" name="action" value="prepare">Aktuelle Übergabevorschau laden</button></form>'
        response = app.make_response((base('Billomat-Übergabe', body + '</div>'), status))
        response.headers['Cache-Control'] = 'no-store'
        return response
