"""Voice Ingress endpoints reject untrusted identity/framing before upload."""
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    spec = importlib.util.spec_from_file_location('atlas_voice_http_test', ROOT / 'app.py')
    appmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(appmod)
    from submissions_server import _Server
finally:
    sys.path.remove(str(ROOT))


@pytest.fixture
def server(tmp_path):
    (tmp_path / 'options.json').write_text(json.dumps({'voice_enabled': True, 'voice_ha_user_id': 'owner'}))
    app = appmod.App(tmp_path, dev=False)
    base = appmod.make_handler(app)
    class Ingress(base):
        def setup(self):
            super().setup()
            self.client_address = ('172.30.32.2', self.client_address[1])
    server = appmod.ThreadingHTTPServer(('127.0.0.1', 0), Ingress)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, server.server_port
    app.jobs.stop()
    server.shutdown()
    server.server_close()
    thread.join(2)


def request(server, path='/api/voice/transcribe', body=b'audio', user='owner', csrf=True, extra=None, method='POST'):
    app, port = server
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    headers = {'X-Remote-User-Id': user, 'Content-Type': 'audio/webm'}
    if csrf:
        headers['X-Atlas-CSRF'] = app.csrf_token
    headers.update(extra or {})
    try:
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_status_scoped_and_successful_audio(server):
    app, _ = server
    for user, expected in [('owner', True), ('other', False)]:
        code, headers, raw = request(server, '/api/status', body=None, user=user, method='GET')
        assert code == 200
        assert json.loads(raw)['voice']['enabled'] is expected
        assert "media-src 'self' blob:" in headers['Content-Security-Policy']
    with patch.object(app.voice, 'transcribe', return_value={'text': 'Hallo'}) as transcribe:
        code, headers, raw = request(server)
        assert code == 200 and json.loads(raw) == {'text': 'Hallo'}
        transcribe.assert_called_once_with('owner', b'audio', 'audio/webm')
        assert headers['Cache-Control'] == 'no-store'
    with patch.object(app.voice, 'synthesize', return_value=b'RIFF-WAV') as speak:
        code, headers, raw = request(server, '/api/voice/synthesize', json.dumps({'text': 'Hallo'}).encode(), extra={'Content-Type': 'application/json'})
        assert (code, headers['Content-Type'], raw) == (200, 'audio/wav', b'RIFF-WAV')
        speak.assert_called_once_with('owner', 'Hallo')


def test_owner_csrf_and_upload_bounds_before_body(server):
    app, _ = server
    with patch.object(app.voice, 'transcribe') as transcribe:
        assert request(server, body=b'', user='other', extra={'Content-Length': '5000000'})[0] == 403
        assert request(server, body=b'', csrf=False, extra={'Content-Length': '5000000'})[0] == 403
        assert request(server, user='', body=b'')[0] == 403
        assert request(server, body=b'', extra={'Content-Length': str(5 * 1024 * 1024 + 1)})[0] == 413
        assert request(server, body=b'', extra={'Transfer-Encoding': 'chunked'})[0] == 400
        assert request(server, extra={'Content-Type': 'text/plain'})[0] == 415
        assert request(server, extra={'Sec-Fetch-Site': 'cross-site'})[0] == 403
        transcribe.assert_not_called()


@pytest.mark.parametrize('lengths', [[], ['1', '1'], ['1', '2'], ['-1'], ['1,1'], ['+1'], ['99999999999999']])
def test_ambiguous_lengths_rejected_without_body(server, lengths):
    app, port = server
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        conn.putrequest('POST', '/api/voice/transcribe')
        for key, value in [('X-Remote-User-Id', 'owner'), ('X-Atlas-CSRF', app.csrf_token), ('Content-Type', 'audio/webm')]:
            conn.putheader(key, value)
        for length in lengths:
            conn.putheader('Content-Length', length)
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 400
        response.read()
    finally:
        conn.close()


def test_safe_service_errors_and_synth_validation(server):
    app, _ = server
    for exc, expected in [(appmod.VoiceBusyError('Bitte warten.'), 429), (appmod.VoiceError('Lokaler Dienst nicht verfügbar.'), 503), (appmod.VoiceAccessError('Nicht freigegeben.'), 403)]:
        with patch.object(app.voice, 'transcribe', side_effect=exc):
            assert request(server)[0] == expected
    with patch.object(app.voice, 'synthesize') as speak:
        assert request(server, '/api/voice/synthesize', b'{"text":""}', extra={'Content-Type': 'application/json'})[0] == 400
        assert request(server, '/api/voice/synthesize', b'{"text":"Hallo"}', user='other', extra={'Content-Type': 'application/json'})[0] == 403
        speak.assert_not_called()


def test_direct_non_ingress_access_blocked(server):
    app, _ = server
    direct = appmod.ThreadingHTTPServer(('127.0.0.1', 0), appmod.make_handler(app))
    thread = threading.Thread(target=direct.serve_forever, daemon=True)
    thread.start()
    try:
        assert request((app, direct.server_port))[0] == 403
    finally:
        direct.shutdown(); direct.server_close(); thread.join(2)


def test_employee_server_has_no_voice_routes():
    store = Mock()
    server = _Server(('127.0.0.1', 0), store, 'https://upload.example.test', ROOT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ('/api/voice/transcribe', '/api/voice/synthesize'):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            try:
                conn.request('POST', path, b'{}', {'X-Remote-User-Id': 'owner', 'Origin': server.origin, 'Content-Type': 'application/json'})
                response = conn.getresponse()
                assert response.status == 404
                response.read()
            finally:
                conn.close()
        store.submit.assert_not_called()
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
