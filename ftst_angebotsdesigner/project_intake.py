"""Private technician intake with explicitly reviewed, local photo suggestions."""
import hashlib
import io
import json
import secrets
import threading
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import abort, redirect, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError

from materials import account
from project_ai import AIError
from storage import RecordConflict

MAX_PHOTO_BYTES = 20 * 1024 * 1024
KIND = 'project_intake'
MAX_COMPONENTS = 30
LOCATION_LIMIT = 150
AJAX_COMPONENTS = {
    'motion': 'Bewegungsmelder',
    'contact': 'Magnetkontakt',
    'indoor_siren': 'Innensirene',
    'outdoor_siren': 'Außensirene',
    'indoor_keypad': 'Bedienteil innen',
    'outdoor_keypad': 'Bedienteil außen',
    'central': 'Zentrale',
}
TEXT_FIELDS = {'manufacturer': ('Hersteller', 100), 'customer_name': ('Kunde', 200),
               'object_address': ('Objektadresse', 500), 'variant': ('Ajax-Variante / Serie', 200),
               'installation': ('Montage / Arbeitsumfang', 1000), 'travel': ('Anfahrt / Einsatzort', 500),
               'notes': ('Notizen zum Foto / Projekt', 6000)}
CHOICES = {'central': ('Zentrale vorhanden?', {'unknown': 'Unklar', 'yes': 'Ja', 'no': 'Nein'}),
           'siren': ('Sirene vorhanden / gewünscht?', {'unknown': 'Unklar', 'yes': 'Ja', 'no': 'Nein'}),
           'area': ('Bereiche', {'unknown': 'Unklar', 'inside': 'Innen', 'outside': 'Außen', 'both': 'Innen und außen'})}
_guard = threading.Lock()
_active = {}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def initial(project):
    fields = {key: '' for key in TEXT_FIELDS}
    fields.update(manufacturer='Ajax', customer_name=project.get('customer_name', ''),
                  object_address=project.get('object_address', ''), notes=project.get('notes', ''),
                  central='unknown', siren='unknown', area='unknown')
    return {'fields': fields, 'components': [], 'summary': '', 'questions': [], 'revision': '',
            'source_project': fingerprint(project), 'status': 'editing', 'slots': 3}


def quantity(value, required=False):
    text = str(value or '').strip().replace(',', '.')
    if not text and not required:
        return ''
    try:
        number = Decimal(text)
        if len(text) > 20 or not number.is_finite() or not 0 < number <= 100000 or number.as_tuple().exponent < -3:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError('Bitte jede Menge als positive Zahl angeben (höchstens 100000, drei Nachkommastellen).') from None
    return format(number, 'f')


def open_questions(fields, questions=()):
    required = []
    if fields.get('central') == 'unknown':
        required.append('Ist eine Ajax-Zentrale vorhanden oder wird eine neue benötigt?')
    if fields.get('siren') == 'unknown':
        required.append('Ist eine Sirene vorhanden oder gewünscht?')
    if not fields.get('installation', '').strip():
        required.append('Welcher Montageumfang ist vorgesehen?')
    if not fields.get('variant', '').strip():
        required.append('Welche Ajax-Variante / Serie wird benötigt?')
    combined = list(dict.fromkeys([str(q).strip() for q in questions if str(q).strip()] + required))
    if len(combined) > 30 or len('\n'.join(combined)) > 6000:
        raise ValueError('Bitte Rückfragen kürzen: einschließlich offener Pflichtangaben höchstens 30 Zeilen und 6000 Zeichen.')
    return combined


def parse_form(form, current, *, confirm=False):
    value = deepcopy(current)
    fields = {}
    for key, (_, limit) in TEXT_FIELDS.items():
        text = form.get(key, '').strip()
        if len(text) > limit:
            raise ValueError(f'Die Angabe „{TEXT_FIELDS[key][0]}“ ist zu lang.')
        fields[key] = text
    fields['manufacturer'] = fields['manufacturer'] or 'Ajax'
    for key, (label, choices) in CHOICES.items():
        fields[key] = form.get(key, 'unknown')
        if fields[key] not in choices:
            raise ValueError('Bitte „' + label + '“ prüfen.')
    descriptions, quantities, evidence = (form.getlist(key) for key in ('description', 'quantity', 'evidence'))
    locations = form.getlist('location') if 'location' in form else [''] * len(descriptions)
    if not len(descriptions) == len(quantities) == len(evidence) == len(locations) or len(descriptions) > MAX_COMPONENTS:
        raise ValueError('Bitte höchstens 30 vollständige Komponenten verwenden.')
    components = []
    for description, count, proof, location in zip(descriptions, quantities, evidence, locations):
        description, proof, location = description.strip(), proof.strip(), location.strip()
        if not description and not count.strip() and not proof and not location:
            continue
        if not description or len(description) > 300 or len(proof) > 500:
            raise ValueError('Bitte Bezeichnung und Beleg der Komponente prüfen.')
        if len(location) > LOCATION_LIMIT:
            raise ValueError('Bitte „Raum / Montageort“ auf höchstens 150 Zeichen kürzen.')
        components.append({'description': description, 'quantity': quantity(count, confirm),
                           'evidence': proof, 'location': location})
    if confirm and (not components or form.get('reviewed') != 'yes'):
        raise ValueError('Bitte Komponenten ergänzen und Mengen sowie Varianten ausdrücklich bestätigen.')
    summary = form.get('summary', '').strip()
    questions = form.get('questions', '').strip()
    if len(summary) > 4000 or len(questions) > 6000 or len(questions.splitlines()) > 30:
        raise ValueError('Zusammenfassung oder Rückfragen sind zu lang.')
    value.update(fields=fields, components=components, summary=summary,
                 questions=open_questions(fields, questions.splitlines()), status='editing')
    value.pop('error', None)
    return value


def attempted_form(form, current):
    """Keep failed edits visible without treating them as validated saved data."""
    value = deepcopy(current)
    value['fields'] = dict(current['fields'])
    for key in (*TEXT_FIELDS, *CHOICES):
        if key in form:
            value['fields'][key] = form.get(key, '')[:20000]
    value['summary'] = form.get('summary', '')[:20000]
    value['questions'] = form.get('questions', '')[:20000].splitlines()
    descriptions, quantities, proofs, locations = (form.getlist(key) for key in ('description', 'quantity', 'evidence', 'location'))
    value['components'] = [{'description': text[:1000], 'quantity': quantities[i][:100] if i < len(quantities) else '',
                            'evidence': proofs[i][:2000] if i < len(proofs) else '',
                            'location': locations[i][:2000] if i < len(locations) else ''}
                           for i, text in enumerate(descriptions[:30])]
    value['slots'] = min(30, max(3, len(value['components'])))
    return value


def source_notes(value):
    fields = value['fields']
    lines = [label + ': ' + (fields.get(key) or 'Offen') for key, (label, _) in TEXT_FIELDS.items()]
    lines += [label + ' ' + choices[fields.get(key, 'unknown')] for key, (label, choices) in CHOICES.items()]
    lines += ['Offen: ' + question for question in open_questions(fields, value.get('questions', []))]
    return '\n'.join(lines)


def photo_bytes(upload):
    raw = upload.stream.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        raise ValueError('Das Foto darf höchstens 20 MB groß sein.')
    try:
        picture = Image.open(io.BytesIO(raw))
        if picture.format not in ('JPEG', 'PNG', 'WEBP') or picture.width * picture.height > 25_000_000:
            raise ValueError('Bitte JPG, PNG oder WebP mit höchstens 25 Megapixeln auswählen.')
        picture = ImageOps.exif_transpose(picture).convert('RGB')
        picture.thumbnail((2400, 2400))
        output = io.BytesIO()
        picture.save(output, format='JPEG', quality=92)
        return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('Das Foto konnte nicht gelesen werden. Bitte JPG, PNG oder WebP verwenden.') from None


def private_folder(store, identity, key):
    # Hash both identifiers so neither account names nor URL keys become paths.
    return store.directory / 'project-intake' / fingerprint([identity, key])


def extract_photo(image, notes):
    from project_photo import extract_photo as extract
    return extract(image, notes)


def checked_result(result, current):
    if not isinstance(result, dict) or not isinstance(result.get('components'), list) or len(result['components']) > 30:
        raise AIError('Der Fotovorschlag ist unvollständig. Bitte die Angaben manuell ergänzen.')
    rows = []
    for row in result['components']:
        if not isinstance(row, dict) or not isinstance(row.get('description'), str) or not isinstance(row.get('evidence'), str):
            raise AIError('Der Fotovorschlag konnte nicht übernommen werden.')
        if not row['description'].strip() or len(row['description']) > 300 or len(row['evidence']) > 500:
            raise AIError('Bitte die Komponenten des Fotos manuell erfassen.')
        try:
            count = quantity('' if row.get('quantity') is None else row['quantity'])
        except ValueError as exc:
            raise AIError(str(exc)) from exc
        rows.append({'description': row['description'], 'quantity': count, 'evidence': row['evidence']})
    if (not isinstance(result.get('summary'), str) or len(result['summary']) > 4000
            or not isinstance(result.get('questions'), list) or len(result['questions']) > 30
            or any(not isinstance(q, str) or len(q) > 500 for q in result['questions'])):
        raise AIError('Bitte die Angaben des Fotos manuell prüfen.')
    try:
        questions = open_questions(current['fields'], result['questions'])
    except ValueError as exc:
        raise AIError(str(exc)) from exc
    return dict(current, components=rows, summary=result['summary'],
                questions=questions,
                transcript=str(result.get('transcript') or '')[:12000],
                provider=str(result.get('provider') or '')[:100], model=str(result.get('model') or '')[:100],
                status='review', review_required=True, source_changed=False, slots=min(30, max(3, len(rows) + 1)))


def confirmed_components(value):
    manufacturer = value['fields']['manufacturer']
    rows = []
    for row in value['components']:
        description = row['description']
        if manufacturer.casefold() not in description.casefold():
            description = manufacturer + ' ' + description
        if row.get('location'):
            description += ' · Raum / Montageort: ' + row['location']
        if len(description) > 300:
            raise ValueError('Bitte die Komponentenbezeichnung mit Hersteller und Raum / Montageort auf höchstens 300 Zeichen kürzen.')
        rows.append(dict(row, description=description, source_description=row['description'],
                         evidence=row['evidence'] or 'Vom Techniker bestätigt', user_confirmed=True))
    return rows


def job_key(store, identity, key):
    return str(store.path), identity, key


def working(store, identity, key):
    with _guard:
        thread = _active.get(job_key(store, identity, key))
        return bool(thread and thread.is_alive())


def check_source(db, identity, key, expected):
    row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?', (identity, 'project', key)).fetchone()
    if not row:
        abort(404)
    project = json.loads(row[0])
    if fingerprint(project) != expected:
        raise RecordConflict('Das Projekt wurde inzwischen geändert. Bitte neu öffnen und die Angaben prüfen.')
    return project


def run_analysis(store, identity, key, original):
    try:
        try:
            path = private_folder(store, identity, key) / original['photo']['name']
            image = path.read_bytes()
            if hashlib.sha256(image).hexdigest() != original['photo']['sha256']:
                raise AIError('Das gespeicherte Foto wurde geändert. Bitte erneut speichern.')
            result = checked_result(extract_photo(image, source_notes(original)), original)
        except (AIError, OSError) as exc:
            result = dict(original, status='editing', error=str(exc) if isinstance(exc, AIError) else 'Das Foto ist nicht lesbar.')
        except Exception:
            result = dict(original, status='editing', error='Fotoanalyse derzeit nicht verfügbar. Die manuelle Erfassung bleibt möglich.')

        def finish(current, db):
            if not current:
                raise RecordConflict('Die Aufnahme wurde entfernt; Vorschlag verworfen.')
            if current.get('revision') != original['revision']:
                return current
            try:
                check_source(db, identity, key, original['source_project'])
            except RecordConflict:
                return dict(current, status='stale', revision=uuid4().hex,
                            error='Das Projekt wurde während der Analyse geändert. Vorschlag verworfen; bitte Angaben neu speichern.')
            return dict(result, revision=uuid4().hex)
        try:
            store.transact_record(identity, KIND, key, finish)
        except RecordConflict:
            pass
    finally:
        with _guard:
            _active.pop(job_key(store, identity, key), None)


def register(app, base, ingress, escape, get_store):
    def response(key, project, value, identity, *, error='', status=200, form_project_revision=None):
        csrf = session.setdefault('project_intake_csrf', secrets.token_urlsafe(32))
        revision = value.get('revision', '')
        fields = value['fields']
        hidden = (f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
                  f'<input type="hidden" name="account" value="{escape(identity)}">'
                  f'<input type="hidden" name="revision" value="{escape(revision)}">'
                  f'<input type="hidden" name="project_revision" value="{escape(form_project_revision if form_project_revision is not None else fingerprint(project))}">')
        live = working(get_store(), identity, key)
        body = '<meta http-equiv="refresh" content="4">' if live else ''
        body += f'<div class="back"><a href="{ingress("projects/" + key)}">← Projekt</a></div><div class="card"><h1>Technikeraufnahme</h1><p>Foto oder Notizen → Vorschlag prüfen → Kalkulation.</p>'
        body += ('<p><strong>Speichern erstellt noch kein Angebot.</strong> Prüfen Sie unten die erkannten Komponenten, '
                 'tragen Sie die Mengen ein und bestätigen Sie die Übernahme. Danach öffnet sich die Kalkulation für Billomat-Kunde, Artikel und Preise.</p>'
                 '<p>Kundenname und Adresse dürfen bei der Aufnahme noch fehlen. Sie können später ergänzt werden. '
                 'Ein Name in diesem Formular legt keinen Billomat-Kunden an und wählt noch keinen aus.</p>'
                 f'<p><a class="btn light" data-pdf="FTST-Technikeraufnahme-Ajax.pdf" href="{ingress("static/FTST-Technikeraufnahme-Ajax.pdf")}">Checkliste als ausfüllbare PDF</a></p>'
                 '<p class="muted">Vorlage drucken oder digital ausfüllen. In dieser Aufnahme werden JPG, PNG und WebP unterstützt; '
                 'für die Fotoauswertung Seite 1 fotografieren und Ergänzungen von Seite 2 manuell eintragen. Kein PDF-Dateiimport.</p>')
        if error or value.get('error'):
            body += '<p role="alert">' + escape(error or value['error']) + '</p>'
            body += f'<a class="btn light" href="{ingress("projects/" + key + "/intake")}">Aktuellen Stand öffnen</a>'
        if request.args.get('saved'):
            body += '<p class="success">Aufnahme gespeichert. Noch kein Angebot erstellt.</p>'
        if value.get('components') and value.get('status') != 'applied' and not live:
            body += '<p><a class="btn" href="#intake-components">Nächster Schritt: Komponenten prüfen</a></p>'
        if value.get('status') == 'applied':
            body += f'<p class="success">Geprüfte Komponenten ins Projekt übernommen.</p><a class="btn" href="{ingress("projects/" + key + "/quote")}">Kalkulation öffnen</a>'
        if value.get('source_project') != fingerprint(project):
            body += '<p role="alert">Das Projekt hat sich geändert. Angaben prüfen und vor einer Fotoanalyse neu speichern.</p>'
        if value.get('source_changed'):
            body += '<p role="alert">Foto oder Angaben wurden geändert. Vorhandene Komponenten erneut prüfen oder das Foto neu auslesen.</p>'
        if live:
            body += '<p role="status">Foto wird lokal ausgewertet. Diese Seite aktualisiert sich automatisch; bitte anschließend prüfen.</p>'
        elif value.get('photo'):
            if value.get('status') == 'analyzing':
                body += '<p>Die Analyse wurde unterbrochen. Sie können sie erneut starten.</p>'
            body += '<form method="post">' + hidden + '<button class="btn" name="action" value="analyze">Gespeichertes Foto lokal auslesen</button></form>'
        body += '<form id="intake-form" method="post" enctype="multipart/form-data">' + hidden + '<fieldset style="border:0;padding:0;min-width:0"' + (' disabled' if live else '') + '><h2>Foto</h2>'
        body += '<label for="intake-photo">Merkzettel / Objektfoto (optional)</label><input id="intake-photo" type="file" name="photo" accept="image/jpeg,image/png,image/webp"><p class="muted">JPG, PNG oder WebP, höchstens 20 MB und 25 Megapixel. Bleibt beim Projekt; kein Referenzfoto.</p><button class="btn light" name="action" value="upload">Foto und Angaben speichern</button>'
        if value.get('photo'):
            body += f'<img style="max-height:320px;object-fit:contain" src="{ingress("projects/" + key + "/intake/photo")}" alt="Gespeichertes Projektfoto">'
        body += '<h2>Kunde und Objekt</h2><div class="grid">'
        for field, (label, limit) in TEXT_FIELDS.items():
            control = ('<textarea' if field in ('notes', 'installation') else '<input')
            if control == '<textarea':
                control += f' id="intake-{field}" name="{field}" maxlength="{limit}">{escape(fields.get(field, ""))}</textarea>'
            else:
                control += f' id="intake-{field}" name="{field}" maxlength="{limit}" value="{escape(fields.get(field, ""))}">'
            body += f'<div class="field"><label for="intake-{field}">{label}</label>{control}</div>'
        for field, (label, choices) in CHOICES.items():
            options = ''.join(f'<option value="{key}"' + (' selected' if fields.get(field) == key else '') + '>' + title + '</option>' for key, title in choices.items())
            body += f'<div class="field"><label for="intake-{field}">{label}</label><select id="intake-{field}" name="{field}">{options}</select></div>'
        body += '</div>'
        body += '<h2 id="intake-components">Komponenten prüfen</h2><p>Mengen und Varianten prüfen. Leere Zeilen werden ignoriert; maximal 30 Komponenten.</p>'
        rows = value.get('components', [])
        slots = min(30, max(len(rows), value.get('slots', 3)))
        body += '<details><summary>Ajax-Komponente schnell ergänzen</summary><p>Ein Klick ergänzt nur den gewählten Komponententyp. Menge, genaue Variante und Raum tragen Sie anschließend ein.</p><div style="display:flex;flex-wrap:wrap;gap:8px">'
        for component, label in AJAX_COMPONENTS.items():
            disabled = ' disabled' if len(rows) >= MAX_COMPONENTS else ''
            body += f'<button class="btn light" style="flex:1 1 180px;min-width:0;max-width:100%;white-space:normal;overflow-wrap:anywhere" name="action" value="add_component:{component}"{disabled}>{label} ergänzen</button>'
        body += '</div></details>'
        for index in range(slots):
            row = rows[index] if index < len(rows) else {}
            body += f'<fieldset class="field" style="min-width:0;border:1px solid #dfe4e7;border-radius:8px;padding:12px"><legend>Komponente {index + 1}</legend>'
            for field, label, limit in [('description', 'Bezeichnung / Variante', 300), ('quantity', 'Menge', 20),
                                        ('location', 'Raum / Montageort (optional)', LOCATION_LIMIT), ('evidence', 'Beleg / Ihre Ergänzung', 500)]:
                inputmode = ' inputmode="decimal"' if field == 'quantity' else ''
                if field == 'location':
                    inputmode += ' placeholder="z. B. Flur EG"'
                body += f'<label for="{field}-{index}">{label}</label><input id="{field}-{index}" name="{field}" maxlength="{limit}" value="{escape(row.get(field, ""))}"{inputmode}>'
            body += '</fieldset>'
        if slots < 30:
            body += '<button class="btn light" name="action" value="add_row">Weitere Komponente</button>'
        body += f'<label for="intake-summary">Zusammenfassung</label><textarea id="intake-summary" name="summary" maxlength="4000">{escape(value.get("summary", ""))}</textarea>'
        questions = '\n'.join(value.get('questions', []))
        body += f'<label for="intake-questions">Offene Rückfragen (eine pro Zeile)</label><textarea id="intake-questions" name="questions" maxlength="6000">{escape(questions)}</textarea><p class="muted">Montage und Anfahrt bleiben freie Angaben. Preise werden später geprüft; offene Angaben werden nicht geschätzt.</p>'
        body += '<button class="btn light" name="action" value="upload">Foto und Angaben speichern</button><label><input type="checkbox" name="reviewed" value="yes"> Mengen, Bezeichnungen und Ajax-Varianten geprüft. Offene Angaben bleiben als Rückfragen stehen.</label><button class="btn" name="action" value="apply">Geprüfte Angaben übernehmen und zur Kalkulation</button></fieldset></form></div>'
        body += f'<script defer src="{ingress("static/project_intake.js")}"></script>'
        body += '<div class="card"><h2>Lokaler Fotovorschlag</h2><p>Nur das gespeicherte Foto und die gespeicherten Angaben werden lokal ausgewertet. Für die Analyse höchstens 4000 Zeichen einschließlich Feldangaben und Rückfragen; längere Aufnahmen können manuell bearbeitet werden. Der Vorschlag wird erst nach Ihrer Prüfung übernommen.</p>'
        if not value.get('photo'):
            body += '<p>Für einen Fotovorschlag zuerst ein Foto speichern. Manuelle Komponenten sind jederzeit möglich.</p>'
        if value.get('transcript'):
            body += '<details><summary>Erkannter Fototext</summary><p style="white-space:pre-wrap">' + escape(value['transcript']) + '</p></details>'
        result = app.make_response((base('Technikeraufnahme', body + '</div>'), status))
        result.headers['Cache-Control'] = 'no-store'
        return result

    @app.route('/projects/<key>/intake', methods=['GET', 'POST'])
    def project_intake(key):
        request.max_content_length = MAX_PHOTO_BYTES + 1024 * 1024
        store, identity = get_store(), account()
        project = store.record(identity, 'project', key)
        if not project:
            abort(404)
        current = store.record(identity, KIND, key) or initial(project)
        if request.method == 'GET':
            return response(key, project, current, identity)
        token = session.get('project_intake_csrf')
        submitted = request.form.get('csrf', '')
        if not isinstance(token, str) or not submitted or not secrets.compare_digest(token.encode(), submitted.encode()):
            abort(400, 'Formular abgelaufen. Bitte neu öffnen.')
        if request.form.get('account') != identity:
            abort(409, 'Das Konto wurde geändert. Bitte neu öffnen.')
        action = request.form.get('action')
        component = action.removeprefix('add_component:') if action and action.startswith('add_component:') else ''
        if action not in ('upload', 'add_row', 'apply', 'analyze') and component not in AJAX_COMPONENTS:
            abort(400)
        expected = request.form.get('revision', '')
        project_revision = request.form.get('project_revision', '')
        new_file = None
        try:
            if expected != current.get('revision', '') or project_revision != fingerprint(project):
                raise RecordConflict('Die Aufnahme oder das Projekt wurde inzwischen geändert. Bitte neu öffnen.')
            if action == 'analyze':
                if not current.get('photo') or current.get('source_project') != project_revision:
                    raise ValueError('Bitte zuerst das Foto und die aktuellen Angaben speichern.')
                if len(source_notes(current)) > 4000:
                    raise ValueError('Für die Fotoanalyse bitte Notizen und Feldangaben auf insgesamt höchstens 4000 Zeichen kürzen und speichern. Manuelle Übernahme bleibt möglich.')
                with _guard:
                    if any(thread.is_alive() for thread in _active.values()):
                        raise RecordConflict('Eine Fotoanalyse läuft bereits. Bitte kurz warten.')
                    def claim(old, db):
                        if not old or old.get('revision', '') != expected:
                            raise RecordConflict('Die Aufnahme wurde geändert. Bitte neu öffnen.')
                        check_source(db, identity, key, project_revision)
                        return dict(old, revision=uuid4().hex, status='analyzing', error='')
                    claimed = store.transact_record(identity, KIND, key, claim)
                    thread = threading.Thread(target=run_analysis, args=(store, identity, key, claimed), daemon=True, name='project-photo')
                    _active[job_key(store, identity, key)] = thread
                    thread.start()
                return redirect(ingress('projects/' + key + '/intake'), code=303)
            value = parse_form(request.form, current, confirm=action == 'apply')
            if component:
                if len(value['components']) >= MAX_COMPONENTS:
                    raise ValueError('Es sind bereits 30 Komponenten erfasst. Bitte zuerst eine nicht benötigte Zeile vollständig leeren.')
                value['components'].append({'description': 'Ajax ' + AJAX_COMPONENTS[component],
                                            'quantity': '', 'evidence': '', 'location': ''})
                value['slots'] = max(current.get('slots', 3), len(value['components']))
            if current.get('fields') != value['fields']:
                value['source_changed'] = True
            if action == 'add_row':
                value['slots'] = min(30, max(current.get('slots', 3) + 1, len(value['components']) + 1))
            upload = request.files.get('photo')
            if upload and upload.filename:
                content = photo_bytes(upload)
                sha = hashlib.sha256(content).hexdigest()
                folder = private_folder(store, identity, key)
                folder.mkdir(parents=True, exist_ok=True)
                name = uuid4().hex + '.jpg'
                new_file = folder / name
                with new_file.open('xb') as handle:
                    handle.write(content)
                value['photo'] = {'name': name, 'sha256': sha}
                value.pop('transcript', None)
                value['source_changed'] = True
            confirmed = confirmed_components(value) if action == 'apply' else []
            value.update(revision=uuid4().hex, source_project=project_revision, review_required=True)
            def save(old, db):
                if (old or {}).get('revision', '') != expected:
                    raise RecordConflict('Die Aufnahme wurde inzwischen geändert. Bitte neu öffnen.')
                live_project = check_source(db, identity, key, project_revision)
                if action == 'apply':
                    analysis = {'summary': value['summary'] or source_notes(value),
                                'components': confirmed,
                                'questions': value['questions'], 'user_confirmed': True,
                                'provider': 'technician-reviewed', 'source_photo_sha256': value.get('photo', {}).get('sha256', '')}
                    updated = dict(live_project, analysis=analysis, notes=source_notes(value),
                                   customer_name=value['fields']['customer_name'], object_address=value['fields']['object_address'],
                                   intake_fields=value['fields'])
                    db.execute('UPDATE records SET payload=? WHERE account=? AND kind=? AND id=?',
                               (json.dumps(updated, ensure_ascii=False), identity, 'project', key))
                    value.update(status='applied', review_required=False, source_changed=False, source_project=fingerprint(updated))
                return value
            store.transact_record(identity, KIND, key, save)
        except (ValueError, RecordConflict) as exc:
            if new_file:
                new_file.unlink(missing_ok=True)
            attempted = attempted_form(request.form, current) if action != 'analyze' else deepcopy(current)
            attempted['revision'] = expected
            return response(key, project, attempted, identity, error=str(exc),
                            status=409 if isinstance(exc, RecordConflict) else 400,
                            form_project_revision=project_revision)
        except Exception:
            if new_file:
                new_file.unlink(missing_ok=True)
            raise
        if action == 'apply':
            return redirect(ingress('projects/' + key + '/quote') + '?intake_applied=1', code=303)
        fragment = '#intake-components' if component or action == 'add_row' else ''
        return redirect(ingress('projects/' + key + '/intake') + '?saved=1' + fragment, code=303)

    @app.get('/projects/<key>/intake/photo')
    def project_intake_photo(key):
        store, identity = get_store(), account()
        if not store.record(identity, 'project', key):
            abort(404)
        value = store.record(identity, KIND, key) or {}
        photo = value.get('photo') or {}
        if not photo.get('name'):
            abort(404)
        path = private_folder(store, identity, key) / photo['name']
        if not path.is_file():
            abort(404)
        result = send_file(path, mimetype='image/jpeg')
        result.headers['Cache-Control'] = 'no-store'
        return result
