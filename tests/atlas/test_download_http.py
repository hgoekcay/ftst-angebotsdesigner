"""Download writes get a bounded longer timeout; upload reads do not."""
import http.client
import importlib.util
import io
from pathlib import Path
import socket
import sys
import threading
import time
from unittest.mock import Mock
import zipfile

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    spec = importlib.util.spec_from_file_location('atlas_download_http_test', ROOT / 'app.py')
    appmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(appmod)
finally:
    sys.path.remove(str(ROOT))


def test_slow_reader_gets_complete_declared_zip_and_timeout_restored():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('synthetic.bin', b'0123456789abcdef' * (256 * 1024))
    payload = out.getvalue()
    seen = []
    base = appmod.make_handler(Mock())
    class Handler(base):
        def setup(self):
            super().setup()
            seen.append(('initial', self.connection.gettimeout()))
            # Shorten the ordinary deadline to reproduce a slow receiver in a
            # subsecond test. Small send buffer guarantees backpressure.
            self.connection.settimeout(.1)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        def do_GET(self):
            self.send(200, payload, 'application/zip', download='test.zip')
            seen.append(('restored', self.connection.gettimeout()))
    server = appmod.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        conn.request('GET', '/download')
        response = conn.getresponse()
        time.sleep(.3)  # Longer than ordinary read/write timeout, below download timeout.
        actual = response.read()
        assert response.status == 200
        assert int(response.getheader('Content-Length')) == len(payload) == len(actual)
        assert actual == payload
        with zipfile.ZipFile(io.BytesIO(actual)) as archive:
            assert archive.testzip() is None
            assert archive.namelist() == ['synthetic.bin']
    finally:
        conn.close()
        server.shutdown(); server.server_close(); thread.join(2)
    assert seen == [('initial', 15.0), ('restored', .1)]


def handler_with_writer(fail=False):
    handler = object.__new__(appmod.make_handler(Mock()))
    handler.connection = Mock()
    handler.connection.gettimeout.return_value = 15
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock()
    if fail:
        handler.wfile.write.side_effect = socket.timeout('synthetic disconnect')
    return handler


def test_only_attachment_response_extends_timeout():
    handler = handler_with_writer()
    handler.send(200, {'ok': True})
    handler.connection.settimeout.assert_not_called()
    handler.send(200, b'WAV', 'audio/wav')
    handler.connection.settimeout.assert_not_called()
    handler.send(200, b'ZIP', 'application/zip', download='test.zip')
    assert [call.args for call in handler.connection.settimeout.call_args_list] == [(120,), (15,)]


def test_failed_download_restores_timeout_and_never_appends_error():
    handler = handler_with_writer(fail=True)
    handler.send(200, b'ZIP', 'application/zip', download='test.zip')
    assert handler.close_connection is True
    handler.wfile.write.assert_called_once_with(b'ZIP')
    handler.send_response.assert_called_once_with(200)
    assert [call.args for call in handler.connection.settimeout.call_args_list] == [(120,), (15,)]
