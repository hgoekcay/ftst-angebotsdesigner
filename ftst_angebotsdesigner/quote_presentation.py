"""Customer-facing text and photographs for a revision-bound local quote draft."""
import uuid

from flask import abort, redirect, request
from asset_library import catalog
from materials import account, image_groups
from storage import RecordConflict


FIELDS = {'title': ('Kundentitel', 240), 'intro': ('Einleitung', 4000),
          'summary': ('Projektbeschreibung', 6000)}


def register(app, base, ingress, escape, get_store):
    @app.route('/projects/<key>/quote/presentation', methods=['GET', 'POST'])
    def quote_presentation(key):
        store, identity = get_store(), account()
        project = store.record(identity, 'project', key)
        draft = store.record(identity, 'quote', key)
        if project is None or draft is None:
            abort(404, 'Bitte zuerst eine Projektkalkulation speichern.')
        images = {k: v for k, v in catalog(store, identity).items()
                  if v.get('category') != 'Logo'}
        presentation = draft.get('presentation') or {}
        if request.method == 'POST':
            expected = request.form.get('revision', '')
            if not expected or expected != draft.get('revision'):
                abort(409, 'Der Entwurf wurde inzwischen geändert. Bitte neu laden.')
            presentation = {}
            for name, (label, limit) in FIELDS.items():
                value = request.form.get(name, '').strip()
                if len(value) > limit:
                    abort(400, f'{label}: höchstens {limit} Zeichen verwenden.')
                presentation[name] = value
            selected = list(dict.fromkeys(request.form.getlist('images')))
            if len(selected) > 8 or any(k not in images for k in selected):
                abort(400, 'Höchstens acht vorhandene Projekt- oder Symbolbilder auswählen.')
            presentation['images'] = selected
            updated = dict(draft, presentation=presentation, revision=uuid.uuid4().hex)
            try:
                store.put_revision(identity, 'quote', key, updated, expected)
            except RecordConflict as exc:
                abort(409, str(exc))
            return redirect(ingress('projects/' + key + '/quote/presentation') + '?saved=1')
        fields = []
        for name, (label, limit) in FIELDS.items():
            value = presentation.get(name, project.get('title', '') if name == 'title' else '')
            if name == 'title':
                widget = f'<input id="{name}" name="{name}" maxlength="{limit}" value="{escape(value)}">'
            else:
                widget = f'<textarea id="{name}" name="{name}" maxlength="{limit}">{escape(value)}</textarea>'
            fields.append(f'<div class="field"><label for="{name}">{label}</label>{widget}</div>')
        chosen = presentation.get('images', [])
        missing = any(k not in images for k in chosen)
        notice = '<p class="success">Kundendarstellung gespeichert. Öffnen Sie die PDF aus der aktuellen Kalkulation neu.</p>' if request.args.get('saved') else ''
        if missing:
            notice += '<p role="alert">Ein ausgewähltes Bild ist nicht mehr verfügbar. Bitte Auswahl prüfen und speichern.</p>'
        content = image_groups(images, ingress, escape, [k for k in chosen if k in images])
        back = ingress('projects/' + key + '/quote')
        return base('Kundendarstellung', f'<div class="back"><a href="{back}">← Zur Kalkulation</a></div>'
                    '<div class="card"><h1>Kundendarstellung & Bilder</h1>'
                    f'{notice}<p>Texte und Bilder für den PDF-Entwurf. Preise bleiben unverändert; '
                    'der Entwurf ist weiterhin nicht freigegeben.</p><p>Leere Textfelder verwenden '
                    'die bisherige Entwurfsdarstellung. Maximal acht Bilder, bis zu vier je Bildseite.</p>'
                    f'<form method="post"><input type="hidden" name="revision" value="{escape(draft.get("revision", ""))}">'
                    f'{"".join(fields)}{content}<div class="material-actions"><button class="btn">Darstellung speichern</button>'
                    f'<a class="btn light" href="{back}">Zur Kalkulation</a></div></form></div>')
