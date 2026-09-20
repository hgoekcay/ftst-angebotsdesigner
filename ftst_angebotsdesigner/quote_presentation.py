"""Customer-facing text and photographs for a revision-bound local quote draft."""
import uuid

from flask import abort, redirect, request
from asset_library import catalog
from materials import account, image_groups
from storage import RecordConflict
from reference_selection import MAX_REFERENCE_IMAGES


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
            if len(selected) > MAX_REFERENCE_IMAGES or any(k not in images for k in selected):
                abort(400, 'Höchstens vier vorhandene Projekt- oder Symbolbilder für eine Referenzseite auswählen.')
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
        available = list(dict.fromkeys(k for k in chosen if isinstance(k, str) and k in images))
        selected = available[:MAX_REFERENCE_IMAGES]
        missing = any(not isinstance(k, str) or k not in images for k in chosen)
        notice = '<p class="success">Kundendarstellung gespeichert. Öffnen Sie die PDF aus der aktuellen Kalkulation neu.</p>' if request.args.get('saved') else ''
        if missing:
            notice += '<p role="alert">Ein ausgewähltes Bild ist nicht mehr verfügbar. Bitte Auswahl prüfen und speichern.</p>'
        if len(available) > MAX_REFERENCE_IMAGES:
            notice += '<p role="status">In Ihrer bisherigen Auswahl sind mehr als vier Bilder. Für die PDF werden die ersten vier verfügbaren Bilder auf einer Referenzseite verwendet. Bitte diese Auswahl prüfen und bei Bedarf ändern.</p>'
        content = image_groups(images, ingress, escape, selected)
        counter = f'''<script>
(function(){{
const form=document.getElementById('project-reference-selection');
const boxes=Array.from(form.querySelectorAll('input[name="images"]'));
const count=document.getElementById('project-reference-count');
const note=document.getElementById('project-reference-limit');
function update(){{
  const selected=boxes.filter(box=>box.checked).length;
  count.textContent=String(selected);
  note.textContent=selected>={MAX_REFERENCE_IMAGES}?'Vier Bilder ausgewählt. Zum Wechseln zuerst ein Bild abwählen.':'';
  boxes.forEach(box=>{{box.disabled=!box.checked&&selected>={MAX_REFERENCE_IMAGES};}});
}}
boxes.forEach(box=>box.addEventListener('change',update));
update();
}})();
</script>'''
        back = ingress('projects/' + key + '/quote')
        return base('Kundendarstellung', f'<div class="back"><a href="{back}">← Zur Kalkulation</a></div>'
                    '<div class="card"><h1>Kundendarstellung & Bilder</h1>'
                    f'{notice}<p>Texte und Bilder für den PDF-Entwurf. Preise bleiben unverändert; '
                    'der Entwurf ist weiterhin nicht freigegeben.</p><p>Leere Textfelder verwenden '
                    'die bisherige Entwurfsdarstellung. Maximal vier Bilder gemeinsam auf einer Referenzseite.</p>'
                    f'<form method="post" id="project-reference-selection"><input type="hidden" name="revision" value="{escape(draft.get("revision", ""))}">'
                    f'{"".join(fields)}{content}<div class="material-actions"><p><strong><span id="project-reference-count" aria-live="polite">{len(selected)}</span> von {MAX_REFERENCE_IMAGES} Bildern ausgewählt</strong></p>'
                    '<p id="project-reference-limit" role="status"></p><button class="btn">Darstellung speichern</button>'
                    f'<a class="btn light" href="{back}">Zur Kalkulation</a></div></form></div>{counter}')
