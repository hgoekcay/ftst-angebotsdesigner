"""Synthetic local-only browser fixture; never connects to production."""
import os
import sys
import tempfile
from pathlib import Path
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ftst_angebotsdesigner'))
os.environ.update(BILLOMAT_ID='overview-qa', FTST_REQUIRE_INGRESS='0')
with tempfile.TemporaryDirectory() as directory:
    os.environ['FTST_DATA_DIR'] = directory
    import app
    store = app.offer_store()
    store.put_record('overview-qa', 'project', 'new', dict(title='Demo Lagerhalle', notes='', analysis={}, offer_id=''))
    store.put_record('overview-qa', 'project', 'review', dict(title='Demo Büro', notes='', offer_id='', analysis=dict(
        provider='technician-reviewed', user_confirmed=True,
        components=[dict(description='Kamera', quantity=2, user_confirmed=True)])))
    store.put_record('overview-qa', 'project_intake', 'review', dict(status='editing', review_required=True, questions=['Einbauort?']))
    store.put_record('overview-qa', 'project', 'unknown', dict(title='Demo unklare Übertragung', notes='', analysis={}, offer_id=''))
    store.put_record('overview-qa', 'quote_transfer', 'unknown', dict(status='unknown'))
    server = make_server('127.0.0.1', 0, app.app)
    print('READY', server.server_port, flush=True)
    server.serve_forever()
