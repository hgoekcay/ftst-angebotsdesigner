"""Single-user OAuth 2.1 transport for the read-only STRATO MCP server.

Uses the pinned MCP SDK for OAuth request validation, PKCE and bearer enforcement.
The local provider handles owner consent and durable opaque token state. Run one
worker behind the configured HTTPS reverse proxy; do not publish the HTTP port.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizeError,
    ProviderTokenVerifier, RefreshToken, RegistrationError, TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

SCOPE = "mail:read"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
COOKIE = "__Host-strato-login"
ACCESS_SECONDS = 900
BODY_READ_SECONDS = 10
REFRESH_SECONDS = 30 * 24 * 3600


@dataclass(frozen=True)
class HTTPSettings:
    public_url: str
    login_password: str = field(repr=False)
    data_dir: Path = Path("/data")
    allowed_redirect_uris: tuple[str, ...] = (CALLBACK,)
    allowed_origins: tuple[str, ...] = ("https://chatgpt.com",)
    health_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")

    def __post_init__(self):
        parsed = urlsplit(self.public_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("public_url must be an HTTPS origin without a path or credentials.")
        if not 24 <= len(self.login_password) <= 1024:
            raise ValueError("Use a separate connection password of 24 to 1024 characters.")
        if not self.allowed_redirect_uris:
            raise ValueError("At least one exact ChatGPT redirect URI is required.")
        for value in self.allowed_redirect_uris:
            target = urlsplit(value)
            if (target.scheme != "https" or target.netloc != "chatgpt.com" or target.query or
                    target.fragment or not (value == CALLBACK or
                    re.fullmatch(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]+", value))):
                raise ValueError("Only exact documented ChatGPT callback URIs are allowed.")
        object.__setattr__(self, "public_url", str(AnyHttpUrl(self.public_url)).rstrip("/"))
        object.__setattr__(self, "data_dir", Path(self.data_dir))

    @property
    def resource(self):
        return self.public_url + "/mcp"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def opaque() -> str:
    return secrets.token_urlsafe(32)


class OAuthStore:
    """Stores only SHA-256 hashes of codes, nonces and opaque bearer tokens."""
    def __init__(self, settings: HTTPSettings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = settings.data_dir / "oauth.sqlite"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    kind TEXT NOT NULL, hash TEXT NOT NULL, data TEXT NOT NULL,
                    expires INTEGER NOT NULL, client_id TEXT NOT NULL DEFAULT '',
                    family TEXT NOT NULL DEFAULT '', used INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (kind, hash));
                CREATE INDEX IF NOT EXISTS objects_family ON objects(family);
                CREATE INDEX IF NOT EXISTS objects_expiry ON objects(expires);
                CREATE TABLE IF NOT EXISTS rates (
                    name TEXT NOT NULL, stamp REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS rate_name ON rates(name, stamp);
                CREATE TABLE IF NOT EXISTS configuration (
                    name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            # Changing origin/password/callback trust invalidates previously issued grants.
            salt = db.execute("SELECT value FROM configuration WHERE name='salt'").fetchone()
            salt = salt[0] if salt else secrets.token_hex(16)
            password_hash = hashlib.scrypt(settings.login_password.encode(), salt=bytes.fromhex(salt),
                                          n=16384, r=8, p=1).hex()
            fingerprint = digest(json.dumps([settings.public_url, password_hash,
                                             sorted(settings.allowed_redirect_uris)]))
            previous = db.execute("SELECT value FROM configuration WHERE name='fingerprint'").fetchone()
            if previous and previous[0] != fingerprint:
                db.execute("DELETE FROM objects")
            db.execute("INSERT OR REPLACE INTO configuration VALUES ('salt',?)", (salt,))
            db.execute("INSERT OR REPLACE INTO configuration VALUES ('fingerprint',?)", (fingerprint,))
        self.salt = bytes.fromhex(salt)
        self.password_hash = password_hash

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def cleanup(db):
        db.execute("DELETE FROM objects WHERE expires > 0 AND expires < ?", (int(time.time()),))
        db.execute("DELETE FROM rates WHERE stamp < ?", (time.time() - 3600,))

    def rate(self, name: str, limit: int, seconds: int) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.cleanup(db)
            count = db.execute("SELECT COUNT(*) FROM rates WHERE name=? AND stamp>?",
                               (name, time.time() - seconds)).fetchone()[0]
            if count >= limit:
                return False
            db.execute("INSERT INTO rates VALUES (?,?)", (name, time.time()))
            return True

    @staticmethod
    def put(db, kind, raw, data, expires, client_id="", family=""):
        db.execute("INSERT INTO objects(kind,hash,data,expires,client_id,family) VALUES (?,?,?,?,?,?)",
                   (kind, digest(raw), json.dumps(data), expires, client_id, family))

    def lookup(self, kind, raw):
        if not isinstance(raw, str) or not 1 <= len(raw) <= 4096:
            return None
        with self.connect() as db:
            self.cleanup(db)
            return db.execute("SELECT * FROM objects WHERE kind=? AND hash=?",
                              (kind, digest(raw))).fetchone()

    def password_matches(self, value):
        if not isinstance(value, str) or len(value) > 1024:
            return False
        result = hashlib.scrypt(value.encode(), salt=self.salt, n=16384, r=8, p=1).hex()
        return hmac.compare_digest(result, self.password_hash)


class LocalOAuthProvider:
    def __init__(self, settings: HTTPSettings):
        self.settings = settings
        self.store = OAuthStore(settings)

    async def get_client(self, client_id):
        row = self.store.lookup("client", client_id)
        return OAuthClientInformationFull.model_validate_json(row["data"]) if row else None

    async def register_client(self, client_info):
        if client_info.token_endpoint_auth_method != "none":
            raise RegistrationError("invalid_client_metadata", "Use public-client PKCE authentication (none).")
        if (not client_info.redirect_uris or
                any(str(uri) not in self.settings.allowed_redirect_uris for uri in client_info.redirect_uris)):
            raise RegistrationError("invalid_redirect_uri", "Redirect URI is not allowed.")
        if set((client_info.scope or "").split()) != {SCOPE}:
            raise RegistrationError("invalid_client_metadata", "Only mail:read is available.")
        with self.store.connect() as db:
            self.store.cleanup(db)
            if db.execute("SELECT COUNT(*) FROM objects WHERE kind='client'").fetchone()[0] >= 256:
                raise RegistrationError("invalid_client_metadata", "Client registration capacity reached.")
            self.store.put(db, "client", client_info.client_id,
                           client_info.model_dump(mode="json"), int(time.time()) + 3600, client_info.client_id)

    async def authorize(self, client, params):
        if params.resource != self.settings.resource:
            raise AuthorizeError("invalid_request", "An exact resource indicator is required.")
        if (str(params.redirect_uri) not in self.settings.allowed_redirect_uris or
                not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge)):
            raise AuthorizeError("invalid_request", "Invalid redirect or PKCE challenge.")
        if set(params.scopes or []) != {SCOPE}:
            raise AuthorizeError("invalid_scope", "Only mail:read is available.")
        flow = opaque()
        with self.store.connect() as db:
            self.store.cleanup(db)
            self.store.put(db, "flow", flow, params.model_dump(mode="json"),
                           int(time.time()) + 600, client.client_id)
        return self.settings.public_url + "/login?" + urlencode({"flow": flow})

    async def load_authorization_code(self, client, authorization_code):
        row = self.store.lookup("code", authorization_code)
        if not row or row["client_id"] != client.client_id or row["used"]:
            return None
        return AuthorizationCode(code=authorization_code, **json.loads(row["data"]))

    def issue(self, db, client_id, scopes, family, refresh_expiry):
        access, refresh = opaque(), opaque()
        common = {"client_id": client_id, "scopes": scopes,
                  "resource": self.settings.resource, "subject": "mailbox-owner"}
        now = int(time.time())
        self.store.put(db, "access", access, {**common, "expires_at": now + ACCESS_SECONDS},
                       now + ACCESS_SECONDS, client_id, family)
        self.store.put(db, "refresh", refresh, {**common, "expires_at": refresh_expiry},
                       refresh_expiry, client_id, family)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_SECONDS,
                          refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("DELETE FROM objects WHERE kind='code' AND hash=? AND client_id=? AND expires>=?",
                                (digest(authorization_code.code), client.client_id, int(time.time())))
            if result.rowcount != 1:
                raise TokenError("invalid_grant", "Code expired or already used.")
            return self.issue(db, client.client_id, authorization_code.scopes, opaque(),
                              int(time.time()) + REFRESH_SECONDS)

    async def load_refresh_token(self, client, refresh_token):
        row = self.store.lookup("refresh", refresh_token)
        if not row or row["client_id"] != client.client_id:
            return None
        if row["used"]:
            # Reuse of a rotated refresh token invalidates the entire grant family.
            with self.store.connect() as db:
                db.execute("UPDATE objects SET used=1 WHERE family=?", (row["family"],))
            return None
        return RefreshToken(token=refresh_token, **json.loads(row["data"]))

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        failed = False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM objects WHERE kind='refresh' AND hash=? AND client_id=?",
                             (digest(refresh_token.token), client.client_id)).fetchone()
            if not row or row["expires"] < time.time():
                raise TokenError("invalid_grant", "Refresh token expired or invalid.")
            if row["used"]:
                db.execute("UPDATE objects SET used=1 WHERE family=?", (row["family"],))
                failed = True
            else:
                db.execute("UPDATE objects SET used=1 WHERE family=?", (row["family"],))
                result = self.issue(db, client.client_id, scopes, row["family"], row["expires"])
        if failed:
            raise TokenError("invalid_grant", "Refresh token already used.")
        return result

    async def load_access_token(self, token):
        row = self.store.lookup("access", token)
        if not row or row["used"] or row["expires"] <= time.time():
            return None
        value = AccessToken(token=token, **json.loads(row["data"]))
        if value.resource != self.settings.resource or SCOPE not in value.scopes:
            return None
        return value

    async def revoke_token(self, token):
        kind = "access" if isinstance(token, AccessToken) else "refresh"
        row = self.store.lookup(kind, token.token)
        if row:
            with self.store.connect() as db:
                db.execute("UPDATE objects SET used=1 WHERE family=?", (row["family"],))

    def callback(self, params, **values):
        return construct_redirect_uri(str(params["redirect_uri"]), state=params.get("state"),
                                      iss=self.settings.public_url, **values)

    async def login(self, request: Request):
        if request.method == "GET":
            flow = request.query_params.get("flow", "")
            row = self.store.lookup("flow", flow)
            if not row:
                return HTMLResponse("Verbindung abgelaufen. Bitte in ChatGPT neu verbinden.", status_code=400)
            nonce = opaque()
            values = json.loads(row["data"])
            values["nonce_hash"] = digest(nonce)
            with self.store.connect() as db:
                db.execute("UPDATE objects SET data=? WHERE kind='flow' AND hash=?",
                           (json.dumps(values), digest(flow)))
            page = f'''<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>FTST Mail verbinden</title>
<style>body{{font:17px system-ui;color:#18312d;background:#f1f6f3;margin:0;padding:7vh 24px}}
main{{max-width:480px;margin:auto;padding:32px;background:white;border-radius:20px}}
h1{{font-size:28px}}label,input{{display:block}}input{{box-sizing:border-box;width:100%;padding:14px;margin:12px 0}}
button{{padding:13px 20px;margin:8px 8px 0 0;border:0;border-radius:8px;font-size:16px;cursor:pointer}}
button[value=allow]{{background:#145e4b;color:white}}small{{display:block;color:#52665f;overflow-wrap:anywhere}}</style>
<main><h1>FTST Mail mit ChatGPT verbinden</h1>
<p>Du erlaubst ChatGPT, E-Mails in deinem eingerichteten STRATO-Postfach zu suchen und zu lesen.
Die Verbindung kann keine E-Mails versenden, verschieben oder löschen.</p>
<form method="post" action="/login">
<input type="hidden" name="flow" value="{html.escape(flow, quote=True)}">
<input type="hidden" name="csrf" value="{nonce}">
<label for="password">Verbindungspasswort aus der Home-Assistant-App</label>
<input id="password" name="password" type="password" autocomplete="current-password" maxlength="1024">
<button name="decision" value="allow" type="submit">Zugriff erlauben</button>
<button name="decision" value="deny" type="submit">Abbrechen</button>
</form><small>Rückkehr zu {html.escape(str(values['redirect_uri']))}</small></main></html>'''
            response = HTMLResponse(page)
            response.set_cookie(COOKIE, nonce, secure=True, httponly=True, samesite="lax", max_age=600, path="/")
            return response
        if request.headers.get("origin") != self.settings.public_url:
            return JSONResponse({"error": "invalid_request"}, status_code=403)
        if not self.store.rate("login", 10, 60):
            return JSONResponse({"error": "too_many_attempts"}, status_code=429, headers={"Retry-After": "60"})
        form = await request.form()
        if any(len(form.getlist(key)) > 1 for key in form):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        flow, nonce = form.get("flow", ""), form.get("csrf", "")
        row = self.store.lookup("flow", flow)
        values = json.loads(row["data"]) if row else {}
        cookie = request.cookies.get(COOKIE, "")
        if (not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce) or
                not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie) or not row or
                not hmac.compare_digest(nonce, cookie) or
                not hmac.compare_digest(digest(nonce), values.get("nonce_hash", ""))):
            return JSONResponse({"error": "invalid_request"}, status_code=403)
        with self.store.connect() as db:
            result = db.execute("DELETE FROM objects WHERE kind='flow' AND hash=? AND data=?",
                                (digest(flow), row["data"]))
            if result.rowcount != 1:
                return JSONResponse({"error": "invalid_request"}, status_code=403)
        if form.get("decision") == "deny":
            response = RedirectResponse(self.callback(values, error="access_denied"), status_code=303)
        elif form.get("decision") != "allow" or not await asyncio.to_thread(self.store.password_matches, form.get("password", "")):
            response = HTMLResponse("Verbindung nicht erlaubt. Bitte in ChatGPT neu beginnen und Passwort prüfen.", status_code=403)
        else:
            code = opaque()
            values.pop("nonce_hash", None)
            values.pop("state", None)
            values.update(expires_at=int(time.time()) + 120, client_id=row["client_id"], subject="mailbox-owner")
            with self.store.connect() as db:
                self.store.put(db, "code", code, values, int(time.time()) + 120, row["client_id"])
                # Only owner-approved registrations persist beyond one hour.
                db.execute("UPDATE objects SET expires=0 WHERE kind='client' AND hash=?",
                           (digest(row["client_id"]),))
            response = RedirectResponse(self.callback(json.loads(row["data"]), code=code), status_code=303)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response


class HTTPGuard:
    """Global non-IP-based limits, strict host/origin checks, bounded request bodies."""
    def __init__(self, app, settings, store):
        self.app, self.settings, self.store = app, settings, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope.get("path", "")
        hosts = {urlsplit(self.settings.public_url).netloc.lower()}
        host = request.headers.get("host", "").lower()
        if path == "/healthz" and request.method in {"GET", "HEAD"}:
            # Supervisor's watchdog uses a changing internal container IP. This
            # static public liveness route contains no account or readiness data.
            try:
                health_host = urlsplit("//" + host)
                valid_port = health_host.port is None or 1 <= health_host.port <= 65535
                valid_name = bool(health_host.hostname and
                                  re.fullmatch(r"[a-z0-9_.:\[\]-]+", health_host.hostname))
                if (valid_name and valid_port and not health_host.username and
                        not health_host.password and not health_host.path and
                        not health_host.query and not health_host.fragment):
                    hosts.add(host)
            except ValueError:
                pass
        if host not in hosts:
            return await JSONResponse({"error": "invalid_host"}, status_code=421)(scope, receive, send)
        origin = request.headers.get("origin")
        if origin and origin not in {self.settings.public_url, *self.settings.allowed_origins}:
            return await JSONResponse({"error": "invalid_origin"}, status_code=403)(scope, receive, send)
        limits = {"/register": (20, 3600), "/authorize": (30, 60), "/token": (120, 60), "/revoke": (60, 60)}
        if path in limits and request.method != "OPTIONS" and not self.store.rate(path, *limits[path]):
            return await JSONResponse({"error": "rate_limited"}, status_code=429,
                                      headers={"Retry-After": str(limits[path][1])})(scope, receive, send)
        # Buffer small request bodies once so chunked requests cannot bypass limits.
        content = bytearray()
        try:
            # One deadline covers all chunks; slow uploads cannot reset it by
            # repeatedly sending a byte and occupy every server connection.
            async with asyncio.timeout(BODY_READ_SECONDS):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    content.extend(message.get("body", b""))
                    if len(content) > 256 * 1024:
                        return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await JSONResponse({"error": "request_timeout"}, status_code=408,
                                      headers={"Connection": "close"})(scope, receive, send)
        delivered = False
        async def limited_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(content), "more_body": False}
            return await receive()
        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
                ])
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, limited_receive, secure_send)


def build_http_app(settings: HTTPSettings, mcp_server) -> Starlette:
    """Build ASGI app; call once per FastMCP instance, run a single worker.

    Reverse proxy must preserve the public Host and terminate HTTPS. Uvicorn must
    disable access logs (OAuth query strings are sensitive) and proxy_headers.
    """
    provider = LocalOAuthProvider(settings)
    auth_handler = AuthorizationHandler(provider)
    token_handler = TokenHandler(provider, ClientAuthenticator(provider))

    async def metadata(request):
        return JSONResponse({
            "issuer": settings.public_url,
            "authorization_endpoint": settings.public_url + "/authorize",
            "token_endpoint": settings.public_url + "/token",
            "registration_endpoint": settings.public_url + "/register",
            "revocation_endpoint": settings.public_url + "/revoke",
            "authorization_response_iss_parameter_supported": True,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [SCOPE],
        })

    async def authorize(request):
        params = request.query_params if request.method == "GET" else await request.form()
        if any(len(params.getlist(key)) > 1 for key in params):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        response = await auth_handler.handle(request)
        location = response.headers.get("location", "")
        if location and location.split("?", 1)[0] in settings.allowed_redirect_uris:
            response.headers["location"] = construct_redirect_uri(location, iss=settings.public_url)
        return response

    async def token(request):
        form = await request.form()
        if (any(len(form.getlist(key)) > 1 for key in form) or
                form.get("resource") != settings.resource):
            return JSONResponse({"error": "invalid_request", "error_description": "Exact resource indicator required."}, status_code=400)
        if (form.get("grant_type") == "authorization_code" and
                not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", str(form.get("code_verifier", "")))):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        return await token_handler.handle(request)

    async def registration(request):
        try:
            return await RegistrationHandler(provider, ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])).handle(request)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)

    async def revoke(request):
        try:
            client = await ClientAuthenticator(provider).authenticate_request(request)
        except AuthenticationError:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        form = await request.form()
        raw = form.get("token")
        if (not isinstance(raw, str) or not raw or len(raw) > 4096 or
                any(len(form.getlist(key)) > 1 for key in form)):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        loaded = await provider.load_access_token(raw)
        if loaded is None:
            loaded = await provider.load_refresh_token(client, raw)
        if loaded and loaded.client_id == client.client_id:
            await provider.revoke_token(loaded)
        return Response(status_code=200)

    async def resource_metadata(request):
        return JSONResponse({"resource": settings.resource,
                             "authorization_servers": [settings.public_url],
                             "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]})

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def index(request):
        return HTMLResponse("<!doctype html><html lang='de'><meta charset='utf-8'><title>FTST Mail-Assistent</title><h1>FTST Mail-Assistent</h1><p>Diese Verbindung wird in ChatGPT eingerichtet.</p></html>")

    routes = [
        Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]),
        Route("/authorize", authorize, methods=["GET", "POST"]),
        Route("/token", token, methods=["POST"]),
        Route("/register", registration, methods=["POST"]),
        Route("/revoke", revoke, methods=["POST"]),
        Route("/.well-known/oauth-protected-resource/mcp", resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", resource_metadata, methods=["GET"]),
        Route("/login", provider.login, methods=["GET", "POST"]),
        Route("/healthz", health, methods=["GET"]),
        Route("/", index, methods=["GET"]),
    ]
    # Use the SDK transport's own lifecycle but enforce auth at its ASGI route.
    mcp_server.settings.stateless_http = True
    mcp_server.settings.json_response = True
    mcp_server.settings.streamable_http_path = "/mcp"
    mcp_server.settings.max_request_body_size = 256 * 1024
    mcp_server.settings.transport_security = TransportSecuritySettings(
        allowed_hosts=[urlsplit(settings.public_url).netloc],
        allowed_origins=[settings.public_url, *settings.allowed_origins])
    transport_app = mcp_server.streamable_http_app()
    transport_route = next(route for route in transport_app.routes if route.path == "/mcp")
    routes.append(Route("/mcp", RequireAuthMiddleware(transport_route.app, [SCOPE],
                        AnyHttpUrl(settings.public_url + "/.well-known/oauth-protected-resource/mcp"))))
    app = Starlette(routes=routes, lifespan=lambda app: mcp_server.session_manager.run(), middleware=[
        Middleware(HTTPGuard, settings=settings, store=provider.store),
        Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(
            ProviderTokenVerifier(provider), resource_server_url=AnyHttpUrl(settings.resource))),
        Middleware(AuthContextMiddleware),
    ])
    app.state.oauth_provider = provider
    return app
