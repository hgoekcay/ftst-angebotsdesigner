"""Isolated upload-only HTTP surface; never trusts Home Assistant identity headers.

Expose behind an HTTPS reverse proxy at the configured dedicated origin. This
listener has no owner routes, document reads, mail, chat or financial operations.
"""
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
import json
import re
import threading
import time
from urllib.parse import urlsplit

from submissions import SubmissionError

MAX_BODY = 12 * 1024 * 1024
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'"


class SubmissionsServerError(ValueError):
    pass


def _origin(url, dev=False):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        if (not isinstance(url, str) or not host or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/', '/submit') or any(ord(c) < 33 or ord(c) > 126 for c in url)):
            raise ValueError()
        if parsed.scheme != 'https' and not (dev and parsed.scheme == 'http' and host in ('127.0.0.1', 'localhost', '::1')):
            raise ValueError()
        rendered = '[' + host + ']' if ':' in host else host
        return parsed.scheme + '://' + rendered + (':' + str(port) if port and port != (443 if parsed.scheme == 'https' else 80) else '')
    except (ValueError, TypeError, AttributeError):
        raise SubmissionsServerError('Öffentliche Upload-Adresse muss eine gültige HTTPS-Adresse ohne Zugangsdaten sein.') from None


class _Limiter:
    def __init__(self):
        self.lock, self.entries = threading.Lock(), OrderedDict()

    def allow(self, ip, upload=False):
        now = time.monotonic()
        with self.lock:
            # At most 1024 peer addresses. Proxy headers never select the bucket.
            while self.entries and next(iter(self.entries.values()))[0] <= now - 60:
                self.entries.popitem(last=False)
            if ip not in self.entries and len(self.entries) >= 1024:
                return False
            _, reads, writes = self.entries.pop(ip, (now, deque(), deque()))
            for events in (reads, writes):
                while events and events[0] <= now - 60:
                    events.popleft()
            allowed = len(reads) < 120 and (not upload or len(writes) < 20)
            if allowed:
                reads.append(now)
                if upload:
                    writes.append(now)
            self.entries[ip] = (now, reads, writes)
            return allowed


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8

    def __init__(self, address, submissions, origin, assets):
        self.submissions, self.origin, self.assets = submissions, origin, Path(assets)
        self.slots, self.limiter = threading.BoundedSemaphore(4), _Limiter()
        super().__init__(address, _Handler)

    def process_request(self, request, client_address):
        request.settimeout(5)
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # No tracebacks with submitted bytes, invitation tokens or headers.


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'ATLAS Upload'
    sys_version = ''

    def log_message(self, format, *args):
        pass  # URLs may carry invitation tokens; no access logging here.

    def _send(self, code, value, mime='application/json; charset=utf-8', extra=None):
        raw = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Connection', 'close')
        for key, item in (extra or {}).items():
            self.send_header(key, item)
        self.end_headers()
        self.close_connection = True
        self.wfile.write(raw)

    def send_error(self, code, message=None, explain=None):
        # Base class otherwise reflects requested method/URI in an HTML error.
        self._send(code, {'error': 'Anfrage konnte nicht angenommen werden.'})

    def _guard(self, upload=False, require_origin=False):
        if not self.server.limiter.allow(self.client_address[0], upload):
            self._send(429, {'error': 'Zu viele Anfragen. Bitte später erneut versuchen.'}, extra={'Retry-After': '60'})
            return False
        origins = self.headers.get_all('Origin', [])
        if len(origins) > 1 or (origins and origins[0] != self.server.origin) or (require_origin and not origins):
            self._send(403, {'error': 'Upload nur über den persönlichen Einreichungslink erlaubt.'})
            return False
        if (upload or self.path.startswith('/api/')) and self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._send(403, {'error': 'Anfrage von dieser Webseite nicht erlaubt.'})
            return False
        return True

    def do_GET(self):
        try:
            if not self._guard():
                return
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or len(self.path) > 2048:
                self._send(400, {'error': 'Ungültige Adresse.'})
                return
            path = parsed.path
            if path == '/submit/':
                # Fragment/query invitation survives this same-origin normalization.
                self._send(302, b'', extra={'Location': '/submit' + ('?' + parsed.query if parsed.query else '')})
            elif path in ('/submit', '/app.js', '/style.css'):
                name, mime = {'/submit': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
                self._send(200, (self.server.assets / name).read_bytes(), mime)
            else:
                self._send(404, {'error': 'Nicht gefunden.'})
        except (ValueError, SubmissionError):
            self._send(400, {'error': 'Ungültige Anfrage.'})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            pass
        except Exception:
            self._send(503, {'error': 'Upload-Dienst vorübergehend nicht verfügbar.'})

    def do_POST(self):
        try:
            if not self._guard(upload=self.path == '/api/submissions', require_origin=True):
                return
            if self.path not in ('/api/submissions', '/api/submissions/access'):
                self._send(404, {'error': 'Nicht gefunden.'})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get('Transfer-Encoding') is not None or len(lengths) != 1
                    or not re.fullmatch(r'[0-9]{1,9}', lengths[0])):
                self._send(400, {'error': 'Gültige Dateigröße erforderlich.'})
                return
            length = int(lengths[0])
            if not 1 <= length <= (1024 if self.path == '/api/submissions/access' else MAX_BODY):
                self._send(413, {'error': 'Upload überschreitet das Größenlimit.'})
                return
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                self._send(415, {'error': 'JSON-Upload erforderlich.'})
                return
            deadline, chunks, remaining = time.monotonic() + 30, [], length
            while remaining:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    raise TimeoutError()
                self.connection.settimeout(min(5, wait))
                block = self.rfile.read1(min(65536, remaining))
                if not block:
                    raise ValueError()
                chunks.append(block)
                remaining -= len(block)
            body = json.loads(b''.join(chunks).decode('utf-8'), object_pairs_hook=_unique)
            if self.path == '/api/submissions/access':
                if not isinstance(body, dict) or set(body) != {'token'}:
                    raise ValueError()
                access = self.server.submissions.validate_access(body['token'])
                self._send(200 if access.get('valid') is True else 403, access if access.get('valid') is True else {'error': 'Upload-Link ungültig oder gesperrt.'})
                return
            allowed = {'token', 'filename', 'mime', 'data_base64', 'project', 'note'}
            if not isinstance(body, dict) or set(body) - allowed or not {'token', 'filename', 'mime', 'data_base64'} <= set(body):
                raise ValueError()
            # Token authorization happens before any base64 decoding or file work.
            if self.server.submissions.validate_access(body['token']).get('valid') is not True:
                self._send(403, {'error': 'Upload-Link ungültig oder gesperrt.'})
                return
            result = self.server.submissions.submit(**body)
            self._send(201, result)
        except SubmissionError as exc:
            self._send(400, {'error': str(exc)})
        except (ValueError, TypeError, UnicodeError):
            self._send(400, {'error': 'Ungültige Upload-Daten.'})
        except (BrokenPipeError, ConnectionError):
            pass
        except TimeoutError:
            self._send(408, {'error': 'Übertragung hat zu lange gedauert.'})
        except Exception:
            self._send(503, {'error': 'Upload-Dienst vorübergehend nicht verfügbar. Bitte vor erneutem Hochladen den Eingang im Betrieb prüfen.'})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def start_server(app, options):
    """Start the separate production listener only after explicit activation."""
    if options.get('submissions_enabled') is not True:
        return None
    origin = _origin(options.get('submissions_public_url') or '', dev=getattr(app, 'dev', False) is True)
    server = _Server(('0.0.0.0', 8100), app.submissions, origin, Path(__file__).parent)
    thread = threading.Thread(target=server.serve_forever, name='atlas-public-uploads', daemon=True)
    thread.start()
    return server
