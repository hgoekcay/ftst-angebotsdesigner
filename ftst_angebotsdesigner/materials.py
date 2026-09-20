"""Company identity and reusable real project photographs."""
import io
import base64
import hmac
import json
import material_uploads
import os
import uuid
import re
import secrets
from pathlib import Path
from asset_library import catalog, DEFAULT_LOGO
from reference_selection import suggest, MAX_REFERENCE_IMAGES

from flask import abort, redirect, request, send_file, session, Response
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError
from reportlab.platypus import Image, Paragraph, Spacer, PageBreak
from reportlab.lib.units import mm

PROFILE_FIELDS = {'company': 'Firmenname', 'owner': 'Geschäftsinhaber', 'contact': 'Ansprechpartner',
                  'street': 'Straße', 'city': 'PLZ / Ort', 'phone': 'Telefon', 'email': 'E-Mail',
                  'website': 'Website', 'bank_name': 'Bank', 'iban': 'IBAN', 'bic': 'BIC'}


def valid_iban(value):
    if not value:
        return True
    if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}', value):
        return False
    if value.startswith('DE') and len(value) != 22:
        return False
    digits = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in value[4:] + value[:4])
    return int(digits) % 97 == 1


def account():
    return os.environ.get('BILLOMAT_ID', 'local').strip().lower() or 'local'


def enrich(offer, store):
    identity = account()
    offer['company_profile'] = store.records(identity, 'profile').get('company', {})
    images = catalog(store, identity)
    selection = store.records(identity, 'offer_images').get(str(offer['id']))
    automatic = selection is None or selection.get('mode') == 'auto'
    chosen = suggest(images, offer.get('offer_type')) if automatic else selection.get('ids', [])
    chosen = list(dict.fromkeys(key for key in chosen if isinstance(key, str) and key in images))
    offer['reference_selection_limited'] = len(chosen) > MAX_REFERENCE_IMAGES
    chosen = chosen[:MAX_REFERENCE_IMAGES]
    offer['reference_selection_auto'] = automatic
    offer['reference_image_ids'] = chosen
    offer['reference_images'] = [images[key] for key in chosen if key in images]
    logo = offer['company_profile'].get('logo', DEFAULT_LOGO)
    offer.pop('logo_path', None)
    offer.pop('logo_crop', None)
    if logo in images:
        offer['logo_path'] = images[logo]['path']
        if images[logo].get('logo_crop'):
            offer['logo_crop'] = images[logo]['logo_crop']
    return offer


def pdf_materials(story, offer, styles, escape):
    profile = offer.get('company_profile', {})
    lines = [profile.get(k) for k in PROFILE_FIELDS if profile.get(k)]
    if lines:
        story.extend([Spacer(1, 5*mm), Paragraph('Ihr Kontakt bei FT Sicherheitstechnik', styles['Heading2']),
                      Paragraph('<br/>'.join(escape(v) for v in lines), styles['BodyText'])])
    for item in offer.get('reference_images', []):
        heading = item.get('kind') or 'Projekt / Referenz'
        story.extend([PageBreak(), Paragraph(escape(heading), styles['Heading2']),
                      Paragraph(escape(item.get('title')), styles['Title'])])
        picture = Image(item['path'])
        picture._restrictSize(170*mm, 170*mm)
        story.extend([picture, Spacer(1, 5*mm),
                      Paragraph(escape(' · '.join(item[k] for k in ('place', 'object_type') if item.get(k))), styles['BodyText']),
                      Paragraph(escape(item.get('description')), styles['BodyText'])])



MATERIAL_STYLE = """<style>
.material-group{margin:30px 0}.material-group h2{font-size:22px;margin-bottom:6px}
.material-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}
.material-tile{display:block;border:1px solid #dce1e5;border-radius:14px;overflow:hidden;background:white;min-width:0}
.material-tile:has(input:checked){border:2px solid #c9141b;box-shadow:0 0 0 2px #fce9ea}
.material-tile:focus-within{outline:3px solid #1f6aa5;outline-offset:3px}
.material-preview{width:100%;height:190px;object-fit:contain;background:#f5f6f7;display:block}
.material-details{display:block;padding:16px}.material-title{font-weight:700;display:block;margin:8px 0}
.material-kind{display:inline-block;font-size:12px;background:#f0f2f4;border-radius:5px;padding:4px 8px;color:#454d57}
.material-actions{position:sticky;bottom:12px;background:#fff;border:1px solid #dce1e5;border-radius:12px;padding:16px;margin-top:24px;box-shadow:0 4px 24px #00000012;z-index:2}
.material-actions p{margin:0 0 10px}.material-tile input[type=checkbox]{width:20px;height:20px;vertical-align:middle;margin-right:8px}
</style>"""


def image_groups(images, ingress, escape, selected=None):
    """Render the same catalog consistently in the library and offer selector."""
    grouped = {}
    for key, item in images.items():
        category = item.get('category') or 'Weitere Bilder'
        if selected is not None and category == 'Logo' and key not in selected:
            continue
        grouped.setdefault(category, []).append((key, item))
    sections = []
    for category, items in grouped.items():
        cards = []
        for key, item in items:
            title = item.get('title') or 'Bild ohne Titel'
            source = {'FTST-Originalfoto': 'Eigene Montage · FTST',
                      'Symbolfoto': 'Symbolbild · Adobe Stock',
                      'Hinweisgrafik': 'Hinweisgrafik',
                      'Firmenlogo': 'FT Sicherheitstechnik · Firmenlogo',
                      'Produktlogo': 'FTronics · Produktmarke'}.get(item.get('kind'), item.get('kind') or 'Eigener Upload')
            checkbox = '' if selected is None else (f'<input type="checkbox" name="images" value="{escape(key)}" '
                       f'{"checked" if key in selected else ""}><span>Für dieses Angebot auswählen</span>')
            tag = 'article' if selected is None else 'label'
            cards.append(f'<{tag} class="material-tile"><img class="material-preview" loading="lazy" src="{ingress("materials/"+key)}" alt="{escape(title)}">'
                         f'<span class="material-details"><span class="material-kind">{escape(source)}</span>'
                         f'<span class="material-title">{escape(title)}</span><span class="muted">{escape(item.get("description") or "")}</span>'
                         f'<span style="display:block;margin-top:12px">{checkbox}</span></span></{tag}>')
        label = 'Logos & Marken' if category == 'Logo' else category
        sections.append(f'<section class="material-group"><h2>{escape(label)}</h2><p class="muted">{len(items)} Motive verfügbar</p><div class="material-grid">{"".join(cards)}</div></section>')
    return MATERIAL_STYLE + ''.join(sections)

def register(app, base, ingress, escape, get_store, types, get_offer=None):
    app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
    material_uploads.register(app, get_store, account, types)

    def field(name, label, value='', multiline=False):
        if multiline:
            widget = f'<textarea id="{name}" name="{name}">{escape(value)}</textarea>'
        else:
            widget = f'<input id="{name}" name="{name}" value="{escape(value)}" maxlength="500">'
        return f'<div class="field"><label for="{name}">{label}</label>{widget}</div>'

    @app.route('/company', methods=['GET', 'POST'])
    def company():
        store = get_store()
        profile = store.records(account(), 'profile').get('company', {})
        images = catalog(store, account())
        csrf = session.setdefault('company_csrf', secrets.token_urlsafe(32))
        error = ''
        if request.method == 'POST':
            if not hmac.compare_digest(request.form.get('csrf', '').encode(), csrf.encode()):
                abort(400, 'Bitte Firmendaten neu öffnen und erneut speichern.')
            profile = dict(profile, **{k: request.form.get(k, '').strip() for k in PROFILE_FIELDS})
            profile['iban'] = re.sub(r'\s+', '', profile['iban']).upper()
            profile['bic'] = re.sub(r'\s+', '', profile['bic']).upper()
            logo = request.form.get('logo', '')
            if logo and logo not in images:
                abort(400)
            profile['logo'] = logo
            if any(len(profile[k]) > 500 for k in PROFILE_FIELDS):
                error = 'Bitte je Feld höchstens 500 Zeichen eingeben.'
            elif not valid_iban(profile['iban']):
                error = 'Die IBAN ist nicht gültig. Bitte mit Ihrer Bankverbindung vergleichen.'
            elif profile['bic'] and not re.fullmatch(r'[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?', profile['bic']):
                error = 'Die BIC muss aus 8 oder 11 gültigen Zeichen bestehen.'
            if not error:
                store.put_record(account(), 'profile', 'company', profile)
                return redirect(ingress('company') + '?saved=1')
        fields = ''.join(field(k, label, profile.get(k, '')) for k, label in PROFILE_FIELDS.items())
        options = '<option value="" ' + ('selected' if profile.get('logo') == '' else '') + '>Ohne Logo</option>' + ''.join(
            f'<option value="{key}" {"selected" if profile.get("logo", DEFAULT_LOGO)==key else ""}>{escape(img.get("title"))}</option>' for key, img in images.items())
        notice = '<p class="success">Firmendaten gespeichert.</p>' if request.args.get('saved') else ''
        if error:
            notice = '<p role="alert">' + escape(error) + '</p>'
        return base('Firmendaten', f'<div class="back"><a href="{ingress()}">← Startseite</a></div><div class="card"><h1>Firmendaten & Logo</h1>{notice}<p>Adresse, Kontakt und Bankverbindung erscheinen in der Fußzeile jeder PDF-Seite. Bitte die Bankdaten vor der Verwendung prüfen. Das FT-Firmenlogo mit ® ist hinterlegt; FTronics steht als Produktmarke bereit.</p><form method="post"><input type="hidden" name="csrf" value="{escape(csrf)}">{fields}<label for="logo">Logo</label><select name="logo" id="logo">{options}</select><p><button class="btn">Speichern</button><a class="btn light" href="{ingress("materials")}">Fotos verwalten</a></p></form></div>'), (400 if error else 200)

    @app.route('/materials', methods=['GET', 'POST'])
    def materials():
        store = get_store()
        if request.method == 'POST':
            upload = request.files.get('image')
            if not upload:
                abort(400, 'Bitte ein Bild auswählen.')
            try:
                picture = PILImage.open(upload.stream)
                if picture.width * picture.height > 25_000_000:
                    abort(400, 'Bild zu groß. Bitte auf höchstens 25 Megapixel verkleinern.')
                picture = ImageOps.exif_transpose(picture).convert('RGBA')
                picture.thumbnail((2400, 2400))
                buffer = io.BytesIO()
                picture.save(buffer, format='PNG')
            except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError):
                abort(400, 'Bitte ein gültiges PNG-, JPEG- oder WebP-Bild verwenden.')
            key = uuid.uuid4().hex
            folder = store.directory / 'images'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (key + '.png')).write_bytes(buffer.getvalue())
            record = {k: request.form.get(k, '').strip()[:2000] for k in ('title', 'place', 'object_type', 'description', 'category')}
            if record['category'] not in types:
                record['category'] = 'Kombination'
            store.put_record(account(), 'image', key, record)
            return redirect(ingress('materials'))
        cards = image_groups(catalog(store, account()), ingress, escape)
        categories = escape(json.dumps(list(types), ensure_ascii=False))
        upload = f'''<div class="card"><h1>Fotos & Referenzen</h1><p>Bis zu 20 Fotos gemeinsam auswählen. Die lokale Bilderkennung schlägt Titel und Kategorien vor. Vorschläge vor dem Speichern prüfen; unsichere Bilder selbst zuordnen.</p>
        <form id="photo-batch" data-endpoint="{ingress('materials/batch')}" data-library="{ingress('materials')}" data-categories="{categories}">
        <label for="photo-files">Fotos auswählen</label><input id="photo-files" type="file" accept="image/png,image/jpeg,image/webp" multiple>
        <p>JPG, PNG oder WebP, maximal 12 MB je Foto. HEIC bitte vorher als JPG exportieren. Die Fotos bleiben auf Ihrem Server.</p>
        <button class="btn">Fotos hochladen & erkennen</button></form><p id="photo-progress" role="status" aria-live="polite"></p></div>
        <div id="photo-review" class="material-grid"></div><div class="material-actions"><button id="photo-commit" class="btn" hidden>Geprüfte Fotos gemeinsam speichern</button></div>
        <noscript><p>Für den Mehrfachupload bitte JavaScript aktivieren.</p></noscript>
        <style>#photo-commit[hidden]{{display:none}}.photo-review-card{{min-width:0;padding:16px}}.photo-review-card label{{margin-top:14px}}.photo-review-card p{{overflow-wrap:anywhere}}</style>
        <script defer src="{ingress('static/material-upload.js')}"></script>'''
        return base('Fotos & Referenzen', f'<div class="back"><a href="{ingress()}">← Startseite</a></div>{upload}{cards}')

    @app.get('/materials/<key>')
    def material(key):
        store = get_store()
        images = catalog(store, account())
        if key not in images:
            abort(404)
        if images[key].get('bundled') and images[key].get('logo_crop'):
            x, y, width, height = images[key]['logo_crop']
            payload = base64.b64encode(Path(images[key]['path']).read_bytes()).decode('ascii')
            with PILImage.open(images[key]['path']) as original:
                iw, ih = original.size
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {width} {height}" '
                   f'width="{width}" height="{height}" role="img" aria-label="FT Sicherheitstechnik ®">'
                   f'<image href="data:image/jpeg;base64,{payload}" width="{iw}" height="{ih}"/></svg>')
            return Response(svg, mimetype='image/svg+xml', headers={'X-Content-Type-Options': 'nosniff'})
        return send_file(images[key]['path'])

    @app.route('/offer/<oid>/references', methods=['GET', 'POST'])
    def references(oid):
        store = get_store()
        images = catalog(store, account())
        selected = store.records(account(), 'offer_images').get(oid, {}).get('ids', [])
        if request.method == 'POST':
            if request.form.get('action') == 'auto':
                store.put_record(account(), 'offer_images', oid, {'mode': 'auto'})
                return redirect(ingress('offer/'+oid+'/references'))
            selected = list(dict.fromkeys(request.form.getlist('images')))
            if len(selected) > MAX_REFERENCE_IMAGES or any(key not in images for key in selected):
                abort(400, 'Höchstens vier vorhandene Bilder auswählen. Alle Bilder erscheinen auf einer Seite.')
            store.put_record(account(), 'offer_images', oid, {'ids':selected})
            return redirect(ingress('offer/'+oid)+'?saved=1')
        offer = get_offer(oid) if get_offer else {}
        if offer:
            selected = offer['reference_image_ids']
        automatic = offer.get('reference_selection_auto', False)
        explanation = (f'Automatisch passend zu {escape(offer.get("offer_type"))}: {len(selected)} von 4 Referenzfotos. '
                       'Diese Bilder werden direkt in der PDF verwendet. ' if automatic else 'Ihre gespeicherte Bildauswahl hat Vorrang. ')
        if automatic and len(selected) < 4:
            explanation += 'Für vier passende Fotos bitte weitere Referenzen dieser Angebotsart hochladen. '
        if offer.get('reference_selection_limited'):
            explanation += 'Ihre ältere Auswahl enthält mehr als vier Bilder. Für die PDF werden die ersten vier vorhandenen Bilder verwendet. Hier können Sie die Auswahl ändern. '
        selected = list(dict.fromkeys(key for key in selected if key in images))[:MAX_REFERENCE_IMAGES]
        options = image_groups(images, ingress, escape, selected)
        counter_script = """<script>
(function(){
const form=document.getElementById('reference-selection');
const boxes=Array.from(form.querySelectorAll('input[name="images"]'));
const counter=document.getElementById('selection-count');
const message=document.getElementById('selection-limit');
function update(){const count=boxes.filter(box=>box.checked).length;
counter.textContent=count;
message.textContent=count>4?'Bitte reduzieren Sie die Auswahl auf höchstens 4 Bilder.':count===4?'Vier Bilder ausgewählt. Zum Wechseln zuerst ein Bild abwählen.':'';
boxes.forEach(box=>box.disabled=count>=4&&!box.checked);
form.querySelector('button[type="submit"]').disabled=count>4;
}
boxes.forEach(box=>box.addEventListener('change',update));update();
})();</script>"""
        return base('Referenzen wählen', f'<div class="back"><a href="{ingress("offer/"+oid)}">← Zurück zum Angebot</a></div><div class="card"><h1>Bilder für Ihr Angebot</h1><p>{explanation}</p><p>Wählen Sie insgesamt höchstens vier Montagefotos oder Symbolbilder aus. Alle Bilder erscheinen gemeinsam auf einer einzigen Referenzseite. Lange Bildtexte werden in der PDF gekürzt. Ohne Auswahl entfällt die Referenzseite.</p><p class="muted">Das Firmenlogo wird separat in den Firmendaten festgelegt.</p><form method="post" id="reference-selection">{options}<div class="material-actions"><p><strong><span id="selection-count" aria-live="polite">{len(selected)}</span> von maximal 4 Bildern ausgewählt</strong></p><p id="selection-limit" role="status"></p><button class="btn" type="submit">Auswahl speichern</button><button class="btn light" name="action" value="auto">Automatisch 4 Bilder wählen</button><a class="btn light" href="{ingress("materials")}">Eigenes Foto hochladen</a></div></form></div>{counter_script}')
