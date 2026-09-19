"""Staged, account-bound photo imports with a bounded local analysis queue."""
import hashlib
import io
import json
import queue
import re
import threading
import time
from pathlib import Path

from flask import abort, jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
import image_classification

MAX_FILES = 20
_jobs = queue.Queue(maxsize=MAX_FILES)
_pending = set()
_guard = threading.Lock()
_worker = None


def _run():
    while True:
        store, account, token, categories = _jobs.get()
        key = (str(store.path), account, token)
        try:
            row = store.record(account, 'image_upload', token)
            if row and row['status'] == 'queued':
                try:
                    result = image_classification.classify((store.directory / 'images' / (token + '.png')).read_bytes(), categories)
                    row.update({k: result.get(k, '') for k in ('title', 'category', 'description')})
                    row['message'] = 'Lokal erkannt – bitte Titel und Zuordnung prüfen.'
                    if not row['category']:
                        row['message'] = 'Zuordnung unsicher – bitte Kategorie auswählen.'
                except image_classification.Unavailable as exc:
                    row['message'] = str(exc)
                except Exception:
                    row['message'] = 'Bilderkennung derzeit nicht verfügbar. Bitte selbst zuordnen.'
                row['status'] = 'ready'
                store.put_record(account, 'image_upload', token, row)
        except Exception:
            # A temporary database failure must not kill the worker for later uploads.
            pass
        finally:
            with _guard:
                _pending.discard(key)
            _jobs.task_done()


def enqueue(store, account, token, categories):
    global _worker
    key = (str(store.path), account, token)
    with _guard:
        if key in _pending:
            return
        if len(_pending) >= MAX_FILES:
            abort(429, 'Es werden bereits 20 Fotos verarbeitet. Bitte später erneut versuchen.')
        _pending.add(key)
        _jobs.put_nowait((store, account, token, categories))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True, name='reference-photos')
            _worker.start()


def token_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        abort(400, 'Ungültiger Upload.')
    return value


def normalize_image(upload):
    try:
        raw = upload.stream.read(12 * 1024 * 1024 + 1)
        if len(raw) > 12 * 1024 * 1024:
            abort(413, 'Je Foto höchstens 12 MB.')
        picture = Image.open(io.BytesIO(raw))
        if picture.format not in ('JPEG', 'PNG', 'WEBP'):
            abort(400, 'Bitte JPG, PNG oder WebP verwenden. HEIC vorher als JPG exportieren.')
        if picture.width * picture.height > 25_000_000:
            abort(400, 'Je Foto höchstens 25 Megapixel.')
        picture = ImageOps.exif_transpose(picture).convert('RGB')
        picture.thumbnail((2400, 2400))
        result = io.BytesIO()
        picture.save(result, format='PNG')
        return result.getvalue(), hashlib.sha256(raw).hexdigest()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        abort(400, 'Dieses Foto konnte nicht gelesen werden. Bitte JPG, PNG oder WebP verwenden.')


def public(row):
    return {key: row.get(key, '') for key in ('token', 'status', 'title', 'category', 'description', 'message')}


def register(app, get_store, account, types):
    categories = tuple(types)

    @app.post('/materials/batch/prepare')
    def photo_prepare():
        store, identity = get_store(), account()
        token = token_value(request.form.get('token'))
        upload = request.files.get('image')
        if not upload:
            abort(400, 'Bitte Fotos auswählen.')
        content, digest = normalize_image(upload)
        existing = store.record(identity, 'image_upload', token)
        if existing:
            if existing.get('digest') != digest:
                abort(409, 'Dieser Upload gehört zu einem anderen Bild.')
            if existing['status'] == 'queued':
                enqueue(store, identity, token, categories)
            return jsonify(public(existing))
        name = Path(upload.filename.replace('\\', '/')).stem[:160]
        row = dict(token=token, digest=digest, status='queued', title=name or 'Referenzfoto',
                   category='', description='', message='Lokale Bilderkennung läuft …', created=time.time())
        # Bytes are stored once, but not exposed in the catalog until explicit confirmation.
        folder = store.directory / 'images'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (token + '.png')
        try:
            with path.open('xb') as stream:
                stream.write(content)
        except FileExistsError:
            abort(409, 'Upload-ID bereits belegt. Bitte diese Datei erneut auswählen.')
        try:
            store.put_record(identity, 'image_upload', token, row)
        except Exception:
            # SQLite rolls back a failed put. Remove only the file this request
            # created, so retrying the same upload does not become a permanent 409.
            path.unlink(missing_ok=True)
            raise
        enqueue(store, identity, token, categories)
        return jsonify(public(row)), 202

    @app.get('/materials/batch/<token>')
    def photo_status(token):
        store, identity = get_store(), account()
        row = store.record(identity, 'image_upload', token_value(token))
        if not row:
            abort(404)
        if row['status'] == 'queued':
            enqueue(store, identity, token, categories)
        return jsonify(public(row))

    @app.get('/materials/batch/<token>/preview')
    def photo_preview(token):
        store = get_store()
        if not store.record(account(), 'image_upload', token_value(token)):
            abort(404)
        return send_file(store.directory / 'images' / (token + '.png'), mimetype='image/png')

    @app.post('/materials/batch/commit')
    def photo_commit():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400)
        batch = token_value(value.get('batch'))
        rows = value.get('items')
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
            abort(400, 'Bitte 1 bis 20 Fotos auswählen.')
        checked, tokens = [], set()
        for row in rows:
            if not isinstance(row, dict):
                abort(400)
            token = token_value(row.get('token'))
            if token in tokens:
                abort(400)
            tokens.add(token)
            if row.get('category') not in categories:
                abort(400, 'Bitte für jedes ausgewählte Foto eine Kategorie angeben.')
            if any(not isinstance(row.get(k, ''), str) or len(row.get(k, '')) > limit
                   for k, limit in (('title', 200), ('description', 2000))):
                abort(400, 'Bildtitel oder Beschreibung zu lang.')
            if not row.get('title', '').strip():
                abort(400, 'Bitte einen Bildtitel angeben.')
            checked.append((token, {k: row.get(k, '').strip() for k in ('title', 'category', 'description')}))
        store, identity = get_store(), account()

        def commit(current, db):
            ready = []
            for token, record in checked:
                found = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                                   (identity, 'image_upload', token)).fetchone()
                row = json.loads(found[0]) if found else None
                if not row or row['status'] not in ('ready', 'committed'):
                    abort(409, 'Die Bilder sind noch nicht bereit. Bitte warten oder erneut laden.')
                if not (store.directory / 'images' / (token + '.png')).is_file():
                    abort(409, 'Bilddatei fehlt. Bitte erneut hochladen.')
                if row['status'] == 'committed':
                    saved = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                                       (identity, 'image', token)).fetchone()
                    if not saved or json.loads(saved[0]) != record:
                        abort(409, 'Dieses Foto wurde bereits mit anderen Angaben gespeichert. Bitte in der Referenzbibliothek bearbeiten.')
                ready.append((token, record, row))
            for token, record, row in ready:
                if row['status'] == 'committed':
                    continue
                db.execute('INSERT INTO records(account,kind,id,payload) VALUES(?,?,?,?)',
                           (identity, 'image', token, json.dumps(record, ensure_ascii=False)))
                row['status'] = 'committed'
                db.execute('UPDATE records SET payload=? WHERE account=? AND kind=? AND id=?',
                           (json.dumps(row, ensure_ascii=False), identity, 'image_upload', token))
            return {'count': len(ready)}

        result = store.transact_record(identity, 'image_upload_batch', batch, commit)
        return jsonify(result)
