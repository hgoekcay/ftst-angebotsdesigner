"""Company identity and reusable real project photographs."""
import io
import os
import uuid
from pathlib import Path
from asset_library import catalog, DEFAULT_LOGO

from flask import abort, redirect, request, send_file
from PIL import Image as PILImage, ImageOps, UnidentifiedImageError
from reportlab.platypus import Image, Paragraph, Spacer, PageBreak
from reportlab.lib.units import mm

PROFILE_FIELDS = {'company': 'Firmenname', 'contact': 'Ansprechpartner', 'street': 'Straße',
                  'city': 'PLZ / Ort', 'phone': 'Telefon', 'email': 'E-Mail', 'website': 'Website'}


def account():
    return os.environ.get('BILLOMAT_ID', 'local').strip().lower() or 'local'


def enrich(offer, store):
    identity = account()
    offer['company_profile'] = store.records(identity, 'profile').get('company', {})
    images = catalog(store, identity)
    chosen = store.records(identity, 'offer_images').get(str(offer['id']), {}).get('ids', [])
    offer['reference_images'] = [images[key] for key in chosen if key in images]
    logo = offer['company_profile'].get('logo', DEFAULT_LOGO)
    offer.pop('logo_path', None)
    if logo in images:
        offer['logo_path'] = images[logo]['path']
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


def register(app, base, ingress, escape, get_store, types):
    app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024

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
        if request.method == 'POST':
            profile = {k: request.form.get(k, '').strip()[:500] for k in PROFILE_FIELDS}
            logo = request.form.get('logo', '')
            if logo and logo not in images:
                abort(400)
            profile['logo'] = logo
            store.put_record(account(), 'profile', 'company', profile)
            return redirect(ingress('company') + '?saved=1')
        fields = ''.join(field(k, label, profile.get(k, '')) for k, label in PROFILE_FIELDS.items())
        options = '<option value="" ' + ('selected' if profile.get('logo') == '' else '') + '>Ohne Logo</option>' + ''.join(
            f'<option value="{key}" {"selected" if profile.get("logo", DEFAULT_LOGO)==key else ""}>{escape(img.get("title"))}</option>' for key, img in images.items())
        notice = '<p class="success">Firmendaten gespeichert.</p>' if request.args.get('saved') else ''
        return base('Firmendaten', f'<div class="back"><a href="{ingress()}">← Startseite</a></div><div class="card"><h1>Firmendaten & Logo</h1>{notice}<p>Hier hinterlegte Angaben erscheinen im PDF. Das FT-Firmenlogo ist bereits hinterlegt. FTronics steht als Produktmarke bereit. Eigene Logos können unter Fotos ergänzt werden.</p><form method="post">{fields}<label for="logo">Logo</label><select name="logo" id="logo">{options}</select><p><button class="btn">Speichern</button><a class="btn light" href="{ingress("materials")}">Fotos verwalten</a></p></form></div>')

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
        cards = ''.join(f'<div class="card"><img src="{ingress("materials/"+key)}" style="max-width:100%;max-height:230px" alt="{escape(img.get("title"))}"><h2>{escape(img.get("title"))}</h2><p>{escape(img.get("category"))} · {escape(img.get("kind") or "Eigenes Bild")}</p><p>{escape(img.get("description"))}</p></div>' for key, img in catalog(store, account()).items())
        fields = ''.join(field(k, label, multiline=k=='description') for k, label in {'title':'Bildtitel', 'place':'Ort', 'object_type':'Objektart', 'description':'Beschreibung'}.items())
        options = ''.join(f'<option>{k}</option>' for k in types)
        return base('Fotos & Referenzen', f'<div class="back"><a href="{ingress()}">← Startseite</a></div><div class="card"><h1>Fotos & Referenzen</h1><p>Eure Originalfotos, Logos und Symbolbilder sind fest hinterlegt. Weitere Bilder hochladen und je Angebot auswählen.</p><form method="post" enctype="multipart/form-data"><label for="image">Bild</label><input id="image" name="image" type="file" accept="image/png,image/jpeg,image/webp" required>{fields}<label for="category">Angebotsart</label><select id="category" name="category">{options}</select><p><button class="btn">Bild speichern</button></p></form></div><div class="grid">{cards}</div>')

    @app.get('/materials/<key>')
    def material(key):
        store = get_store()
        images = catalog(store, account())
        if key not in images:
            abort(404)
        return send_file(images[key]['path'])

    @app.route('/offer/<oid>/references', methods=['GET', 'POST'])
    def references(oid):
        store = get_store()
        images = catalog(store, account())
        selected = store.records(account(), 'offer_images').get(oid, {}).get('ids', [])
        if request.method == 'POST':
            selected = list(dict.fromkeys(request.form.getlist('images')))
            if len(selected)>8 or any(key not in images for key in selected):
                abort(400, 'Höchstens acht vorhandene Bilder auswählen.')
            store.put_record(account(), 'offer_images', oid, {'ids':selected})
            return redirect(ingress('offer/'+oid)+'?saved=1')
        options = ''.join(f'<label class="card"><img src="{ingress("materials/"+key)}" alt="{escape(img.get("title"))}" style="width:100%;height:160px;object-fit:contain"><input style="width:auto" type="checkbox" name="images" value="{key}" {"checked" if key in selected else ""}> {escape(img.get("title"))}<br><span class="muted">{escape(img.get("category"))} · {escape(img.get("kind") or "Eigenes Bild")}</span></label>' for key, img in images.items() if img.get("category") != "Logo" or key in selected)
        return base('Referenzen wählen', f'<div class="back"><a href="{ingress("offer/"+oid)}">← Angebot</a></div><div class="card"><h1>Fotos für dieses Angebot</h1><p>Jedes ausgewählte Bild ergänzt eine eigene PDF-Seite. Ohne Auswahl bleibt die kompakte Grundstruktur erhalten.</p><form method="post"><div class="grid">{options}</div><p><button class="btn">Auswahl speichern</button><a class="btn light" href="{ingress("materials")}">Foto hinzufügen</a></p></form></div>')
