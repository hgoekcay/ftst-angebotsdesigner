"""Dedicated public OAuth callback only; never expose ATLAS/Ingress routes here."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl
import threading


class CallbackServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, oauth):
        self.oauth = oauth
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, CallbackHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class CallbackHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # Authorization codes and state must not enter access logs.

    def reply(self, code, text):
        body = ('<!doctype html><html lang="de"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>ATLAS Google Kalender</title><h1>ATLAS Google Kalender</h1><p>'
                + text + '</p></html>').encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if len(self.path) > 8192:
            return self.reply(400, 'Anfrage ungültig. Bitte in ATLAS neu verbinden.')
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            return self.reply(400, 'Anfrage ungültig.')
        if parsed.path != '/oauth/google/callback' or parsed.fragment:
            return self.reply(404, 'Nicht gefunden.')
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=16)
            if len({key for key, _ in pairs}) != len(pairs):
                raise ValueError()
            self.server.oauth.callback(dict(pairs))
        except Exception:
            return self.reply(400, 'Google-Verbindung nicht abgeschlossen. Bitte in ATLAS neu beginnen und die Google-Freigabe prüfen.')
        self.reply(200, 'Google-Freigabe empfangen. Kehre zu ATLAS → System → Google Kalender zurück und drücke „Verbindung übernehmen“. Erst danach ist die Verbindung aktiv. Dieses Fenster kannst du schließen.')

    def do_POST(self):
        self.reply(405, 'Nur die Google-Rückleitung ist hier erreichbar.')


def start_callback_server(oauth):
    # Config validity checked by OAuth module. No listener for default-off mode.
    if not oauth.status(oauth.owner).get('configured'):
        return None
    server = CallbackServer(('0.0.0.0', 8101), oauth)
    threading.Thread(target=server.serve_forever, daemon=True, name='atlas-google-callback').start()
    return server
