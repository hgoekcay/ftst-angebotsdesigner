"""Persistent project intake and reviewable AI requirements drafts."""
import io
import hashlib
import json
import os
import uuid
from pathlib import Path
from flask import abort, redirect, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from materials import account
from project_ai import extract, AIError
from storage import RecordConflict
from project_workflow import render as render_workflow


def register(app, base, ingress, escape, get_store):
    def project(key):
        value = get_store().records(account(), 'project').get(key)
        if value is None:
            abort(404)
        return value

    @app.route('/projects', methods=['GET', 'POST'])
    def projects():
        store = get_store()
        if request.method == 'POST':
            key = uuid.uuid4().hex
            value = {'title': request.form.get('title','').strip()[:200] or 'Neues Projekt',
                     'notes':request.form.get('notes','')[:20000], 'offer_id':'', 'analysis':{}}
            store.put_record(account(), 'project', key, value)
            return redirect(ingress('projects/'+key))
        rows = ''.join(f'<div class="card"><a href="{ingress("projects/"+key)}">{escape(value.get("title"))}</a></div>' for key,value in store.records(account(),'project').items())
        return base('Projekte', f'<div class="back"><a href="{ingress()}">← Startseite</a></div><div class="card"><h1>Neues Projekt</h1><p>Notizen, Merkzettel und Sprachnotizen an einem Ort.</p><form method="post"><label for="title">Projekt / Kunde</label><input id="title" name="title" required><label for="notes">Ihre Notizen</label><textarea id="notes" name="notes"></textarea><p><button class="btn">Projekt anlegen</button></p></form></div>{rows}')

    @app.route('/projects/<key>', methods=['GET','POST'])
    def project_detail(key):
        value = project(key)
        store = get_store()
        if request.method == 'POST':
            identity = account()
            value['notes'] = request.form.get('notes','')[:20000]
            oid = request.form.get('offer_id','').strip()
            if oid and not oid.isdigit():
                abort(400, 'Bitte die numerische Billomat-Angebots-ID verwenden.')
            value['offer_id'] = oid
            # A changed source invalidates the previous analysis.
            value['analysis'] = {}
            value.pop('error', None)
            folder = store.directory / 'projects' / key
            attachments = {}
            for field in ('image','audio'):
                upload = request.files.get(field)
                if not upload or not upload.filename:
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                if field == 'image':
                    try:
                        picture = Image.open(upload.stream)
                        if picture.width*picture.height>25_000_000:
                            abort(400, 'Bild zu groß.')
                        picture = ImageOps.exif_transpose(picture).convert('RGB')
                        picture.thumbnail((2400,2400))
                        picture.save(folder/'note.png')
                        value['image'] = 'note.png'
                        attachments['image'] = 'note.png'
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                        abort(400, 'Ungültiges Bild.')
                else:
                    suffix = Path(upload.filename).suffix.lower()
                    if suffix not in ('.mp3','.m4a','.wav','.webm','.mp4','.ogg'):
                        abort(400, 'Nicht unterstützte Audiodatei.')
                    name = 'voice'+suffix
                    upload.save(folder/name)
                    value['audio'] = name
                    attachments['audio'] = name

            def save_project(current, db):
                if current is None:
                    abort(404)
                row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                                 (identity, 'quote_transfer', key)).fetchone()
                transfer = json.loads(row[0]) if row else {}
                linked_id = str(transfer.get('offer_id') or '') if transfer.get('status') == 'created' else ''
                if linked_id and oid and oid != linked_id:
                    raise RecordConflict('Dieses Projekt wurde bereits mit Billomat-Angebot ' + linked_id
                                         + ' verknüpft. Die Angebots-ID kann hier nicht geändert werden.')
                # Read the completed transfer and write the project under one lock:
                # a stale form must not erase a link created by finish() meanwhile.
                updated = dict(current, notes=value['notes'], offer_id=linked_id or oid, analysis={})
                updated.update(attachments)
                updated.pop('error', None)
                return updated

            try:
                store.transact_record(identity, 'project', key, save_project)
            except RecordConflict as exc:
                abort(409, str(exc))
            return redirect(ingress('projects/'+key)+'?saved=1')
        workflow = render_workflow(value, key, store, account(), ingress)
        result = value.get('analysis', {})
        rows = ''.join(f'<tr><td data-label="Komponente">{escape(row.get("description"))}</td><td data-label="Menge">{escape(row.get("quantity") if row.get("quantity") is not None else "Offen")}</td><td data-label="Beleg">{escape(row.get("evidence"))}</td></tr>' for row in result.get('components',[]))
        questions = ''.join(f'<li>{escape(q)}</li>' for q in result.get('questions',[]))
        summary = f'<div class="card"><h2>Anforderungsentwurf · bitte prüfen</h2><p>{escape(result.get("summary"))}</p><table><tr><th>Komponente</th><th>Menge</th><th>Beleg</th></tr>{rows}</table><h3>Offene Angaben</h3><ul>{questions}</ul><p>Artikelzuordnung und Preise müssen anschließend aus Billomat übernommen und geprüft werden.</p><a class="btn dark" target="_blank" rel="noopener" href="{ingress("projects/"+key+"/pdf")}">Projektentwurf als PDF</a></div>' if result else ''
        error = f'<p>{escape(value.get("error"))}</p>' if value.get('error') else ''
        local = os.getenv('AI_PROVIDER','openai') == 'ollama'
        state = 'Lokale Text-KI ausgewählt. Maximal 4000 Zeichen; Bilder und Audio werden noch nicht lokal ausgewertet. Kein automatischer Cloud-Aufruf.' if local else ('KI ist eingerichtet.' if os.getenv('OPENAI_API_KEY') else 'KI noch nicht eingerichtet: OpenAI-API-Schlüssel in der Home-Assistant-App-Konfiguration hinterlegen.')
        disclosure = 'Gespeicherte Textnotizen werden auf dem lokalen KI-Dienst ausgewertet. Ergebnisse bitte prüfen.' if local else 'Beim Analysieren werden die gespeicherten Notizen, das Merkzettelfoto und die Sprachnotiz an OpenAI übertragen. Es können API-Kosten entstehen.'
        link = f'<a class="btn" href="{ingress("offer/"+value["offer_id"])}">Billomat-Angebot öffnen</a>' if value.get('offer_id') else ''
        saved = '<p class="success">Projekt gespeichert.</p>' if request.args.get('saved') else ''
        intake_link = f'<a class="btn" href="{ingress("projects/"+key+"/intake")}">Technikeraufnahme: Foto & Komponenten</a>'
        attachments = ' · '.join(label for field,label in [('image','Merkzettelfoto vorhanden'),('audio','Sprachnotiz vorhanden')] if value.get(field))
        return base('Projekt', f'<div class="back"><a href="{ingress("projects")}">← Projekte</a></div><div class="card"><h1>{escape(value["title"])}</h1>{saved}</div>{workflow}<div class="card"><h2>Projektangaben</h2>{intake_link}<form method="post" enctype="multipart/form-data"><label for="notes">Notizen / Anforderungen</label><textarea id="notes" name="notes">{escape(value["notes"])}</textarea><label for="image">Merkzettel / Objektfoto</label><input id="image" type="file" name="image" accept="image/png,image/jpeg,image/webp"><label for="audio">Sprachnotiz hochladen</label><input id="audio" type="file" name="audio" accept="audio/*"><p>{attachments}</p><label for="offer_id">Billomat-Angebots-ID (falls vorhanden)</label><input id="offer_id" name="offer_id" value="{escape(value.get("offer_id"))}"><p><button class="btn">Eingaben speichern</button>{link}</p></form></div><div class="card"><h2>FTST Projektassistent</h2><p>{state}</p>{error}<form method="post" action="{ingress("projects/"+key+"/analyze")}"><p>{disclosure}</p><p><a href="{ingress("ai")}">KI-Status und Funktionstest</a></p><p><label><input style="width:auto" type="checkbox" name="force" value="yes"> Bewusst neu analysieren (sonst gespeichertes lokales Ergebnis wiederverwenden)</label></p><button class="btn">Gespeicherte Eingaben analysieren</button></form></div>{summary}<div class="card"><h2>Artikel und Preise</h2><p>Aus den Notizen einen lokalen Angebotsentwurf mit Billomat-Artikeln vorbereiten.</p><a class="btn" href="{ingress("projects/"+key+"/quote")}">Angebotsentwurf vorbereiten</a><a class="btn light" href="{ingress("projects/"+key+"/operations")}">Material & Termine</a></div>')

    @app.post('/projects/<key>/analyze')
    def analyze(key):
        value = project(key)
        store = get_store()
        folder = store.directory / 'projects' / key
        original = json.loads(json.dumps(value))
        try:
            image = (folder/value['image']).read_bytes() if value.get('image') else None
            audio = (value['audio'], (folder/value['audio']).read_bytes()) if value.get('audio') else None
            if not value['notes'].strip() and not image and not audio:
                raise AIError('Bitte zuerst Notizen, ein Bild oder eine Sprachnotiz speichern.')
            from local_ai import VERSION, MODEL, model_digest
            provider = os.getenv('AI_PROVIDER','openai')
            installed = model_digest() if provider=='ollama' and not image and not audio else ''
            digest = hashlib.sha256(json.dumps([VERSION,provider,MODEL,installed,os.getenv('OLLAMA_URL',''),value['notes']],ensure_ascii=False).encode()).hexdigest()
            cache = store.record(account(),'local_ai_cache',key) if provider=='ollama' and not image and not audio else None
            if cache and cache.get('fingerprint')==digest and request.form.get('force')!='yes':
                value['analysis'] = cache['analysis']
            else:
                value['analysis'] = extract(value['notes'], image, audio)
                if provider=='ollama':
                    store.put_record(account(),'local_ai_cache',key,dict(fingerprint=digest,analysis=value['analysis']))
            value.pop('error', None)
        except (AIError, OSError) as exc:
            value['error'] = str(exc) if isinstance(exc,AIError) else 'Anhang derzeit nicht lesbar.'
        def save_analysis(current, db):
            if current != original:
                raise RecordConflict('Projekt wurde während der Analyse geändert. Aktuellen Stand neu laden; Ergebnis wurde nicht darübergeschrieben.')
            return value
        try:
            store.transact_record(account(),'project',key,save_analysis)
        except RecordConflict as exc:
            abort(409,str(exc))
        return redirect(ingress('projects/'+key))

    @app.get('/projects/<key>/pdf')
    def project_pdf(key):
        value = project(key)
        result = value.get('analysis', {})
        styles = getSampleStyleSheet()
        story = [Paragraph('PROJEKTENTWURF – ZUR PRÜFUNG', styles['Title']),
                 Paragraph(escape(value['title']), styles['Heading2']),
                 Paragraph('Kein freigegebenes Angebot. Artikel, Preise und technische Planung sind noch zu prüfen.', styles['BodyText']),
                 Spacer(1,12), Paragraph(escape(result.get('summary') or value['notes']), styles['BodyText'])]
        for row in result.get('components',[]):
            story.append(Paragraph(escape(str(row.get('quantity') or 'Menge offen')+' × '+row['description']),styles['BodyText']))
        for q in result.get('questions',[]):
            story.append(Paragraph(escape('Offen: '+q),styles['BodyText']))
        output = io.BytesIO()
        SimpleDocTemplate(output,pagesize=A4).build(story)
        output.seek(0)
        return send_file(output,mimetype='application/pdf',download_name='FTST-Projektentwurf.pdf')
