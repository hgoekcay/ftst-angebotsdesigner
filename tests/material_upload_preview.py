"""Synthetic local browser fixture; no company data or external integrations."""
import io
import os
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ftst_angebotsdesigner'))
from PIL import Image
from flask import jsonify, request, Response
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


with tempfile.TemporaryDirectory(prefix='ftst-photo-browser-') as folder:
    os.environ.update(FTST_DATA_DIR=folder, BILLOMAT_ID='synthetic-photo-ci',
                      FTST_REQUIRE_INGRESS='0', WEBSITE_PORTAL_ENABLED='false',
                      FLASK_SECRET='synthetic-photo-browser-only')
    import app as designer
    import materials
    import material_uploads
    from asset_library import catalog
    material_uploads.enqueue = lambda *args: True
    materials.catalog = lambda store, identity: {
        key: value for key, value in catalog(store, identity).items()
        if not value.get('bundled') or value.get('category') == 'Logo'
    }

    @designer.app.get('/qa/fixture.png')
    def picture():
        data = io.BytesIO()
        Image.new('RGB', (60, 40), 'white').save(data, format='PNG')
        return Response(data.getvalue(), mimetype='image/png')

    @designer.app.post('/qa/suggest')
    def suggest():
        token = request.get_json()['token']
        store = designer.offer_store()
        row = store.record(materials.account(), 'image_upload', token)
        assert row and row['status'] == 'queued'
        row.update(status='ready', title='KI-Vorschlag', category='Videoüberwachung',
                   description='Dieser KI-Text darf keine eigene Beschreibung ersetzen.')
        store.put_record(materials.account(), 'image_upload', token, row)
        return jsonify(ok=True)

    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))
    with make_server('127.0.0.1', 0, designer.app, threaded=True, request_handler=Quiet) as server:
        print('READY ' + str(server.server_port), flush=True)
        server.serve_forever()
