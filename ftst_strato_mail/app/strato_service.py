"""Home Assistant service runner and bounded, read-only mailbox monitoring."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import strato_mail
from strato_worker import run_mail_operation

LOG = logging.getLogger("strato_service")
DEFAULT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


@dataclass(frozen=True, repr=False)
class Settings:
    email: str
    password: str
    public_url: str
    login_password: str
    poll_interval_seconds: int = 300
    folder: str = "INBOX"
    allowed_redirect_uris: tuple[str, ...] = (DEFAULT_REDIRECT,)

    bridge_token: str = ""
    accounts: tuple[dict, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            if path.stat().st_size > 65536:
                raise ValueError("Options file too large.")
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("Konfiguration konnte nicht gelesen werden. Optionen in Home Assistant prüfen.") from None
        return cls.parse(data)

    @classmethod
    def parse(cls, data: dict) -> "Settings":
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("Unbekannte oder ungültige Konfigurationsfelder.")
        for key in ("email", "password", "public_url", "login_password"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError("E-Mail-Adresse, Postfach-Passwort, öffentliche HTTPS-URL und Verbindungs-Passwort sind erforderlich.")
        address = data["email"]
        if "@" not in address or len(address) > 254 or any(ord(c) < 33 or ord(c) > 126 for c in address):
            raise ValueError("Ungültige E-Mail-Adresse.")
        if len(data["password"]) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in data["password"]):
            raise ValueError("Ungültiges Postfach-Passwort.")
        login = data["login_password"]
        if not 24 <= len(login) <= 256 or login == data["password"] or any(ord(c) < 32 for c in login):
            raise ValueError("Eigenes Verbindungs-Passwort mit 24 bis 256 Zeichen verwenden; getrennt vom Postfach-Passwort.")
        url = data["public_url"].rstrip("/")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise ValueError("Ungültige öffentliche HTTPS-Adresse.") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or port not in (None, 443)
                or any(ord(c) < 33 or ord(c) > 126 for c in url)):
            raise ValueError("Öffentliche HTTPS-Adresse ohne Pfad, Zugangsdaten oder abweichenden Port verwenden.")
        interval = data.get("poll_interval_seconds", 300)
        if type(interval) is not int or not 60 <= interval <= 3600:
            raise ValueError("Prüfintervall muss zwischen 60 und 3600 Sekunden liegen.")
        folder = data.get("folder", "INBOX")
        if not isinstance(folder, str):
            raise ValueError("Ungültiger Postfachordner.")
        strato_mail.quoted(folder)
        if folder.casefold() == "inbox":
            folder = "INBOX"
        callbacks = data.get("allowed_redirect_uris", [DEFAULT_REDIRECT])
        if not isinstance(callbacks, (list, tuple)) or not 1 <= len(callbacks) <= 10:
            raise ValueError("Eine bis zehn exakte OAuth-Rücksprungadressen eintragen.")
        for callback in callbacks:
            if not isinstance(callback, str) or len(callback) > 2000:
                raise ValueError("Ungültige OAuth-Rücksprungadresse.")
            try:
                item = urlsplit(callback)
                port = item.port
            except ValueError:
                raise ValueError("Ungültige OAuth-Rücksprungadresse.") from None
            from strato_http import CALLBACK
            import re
            if (callback != CALLBACK and not re.fullmatch(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]+", callback)):
                raise ValueError("Eine exakte, unterstützte ChatGPT-Rücksprungadresse verwenden.")
        token = data.get('bridge_token', '')
        import re
        if not isinstance(token, str) or (token and not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token)):
            raise ValueError('Brückentoken muss 43 bis 128 zufällige URL-sichere Zeichen enthalten.')
        if token and token in (data['password'], login):
            raise ValueError('Separates Brückentoken verwenden.')
        extras = data.get('accounts', [])
        if not isinstance(extras, list) or len(extras) > 20:
            raise ValueError('Höchstens 20 zusätzliche Postfächer konfigurieren.')
        account_ids, mailbox_keys, accounts = {'primary'}, {(address.casefold(), folder)}, []
        for item in extras:
            if not isinstance(item, dict) or set(item) - {'id', 'email', 'password', 'folder', 'enabled'}:
                raise ValueError('Ungültige Postfachkonfiguration.')
            account_id = item.get('id')
            if not isinstance(account_id, str) or not re.fullmatch(r'[a-z0-9_-]{1,40}', account_id) or account_id in account_ids:
                raise ValueError('Postfach-ID muss eindeutig sein; primary ist reserviert.')
            email, password, mailbox = item.get('email'), item.get('password'), item.get('folder', 'INBOX')
            enabled = item.get('enabled', True)
            if (not isinstance(email, str) or '@' not in email or len(email) > 254
                    or any(ord(c) < 33 or ord(c) > 126 for c in email)):
                raise ValueError('Ungültige zusätzliche E-Mail-Adresse.')
            if (not isinstance(password, str) or not password or len(password) > 1024
                    or any(ord(c) < 32 or ord(c) == 127 for c in password)):
                raise ValueError('Ungültiges zusätzliches Postfachpasswort.')
            strato_mail.quoted(mailbox)
            if mailbox.casefold() == 'inbox':
                mailbox = 'INBOX'
            if type(enabled) is not bool or (email.casefold(), mailbox) in mailbox_keys:
                raise ValueError('Doppelte Postfächer oder ungültiger Aktivierungsstatus.')
            if password in (token, login):
                raise ValueError('Postfachpasswort getrennt von Zugangstoken verwenden.')
            account_ids.add(account_id)
            mailbox_keys.add((email.casefold(), mailbox))
            accounts.append(dict(id=account_id, email=email, password=password, folder=mailbox, enabled=enabled))
        return cls(address, data["password"], url, login, interval, folder, tuple(callbacks), token, tuple(accounts))


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class MailboxMonitor:
    """Only aggregate counts are retained. No bodies, senders or subjects are cached."""
    def __init__(self, folder: str, interval: int, data_dir: Path, checker=None):
        self.folder, self.interval = folder, interval
        self.checker = checker or (lambda folder: run_mail_operation("mailbox_status", {"folder": folder}))
        self.status_path = data_dir / "monitor-status.json"
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.last_completed_monotonic = None
        self.state = {"state": "starting", "last_check_at": None, "last_success_at": None,
                      "consecutive_failures": 0, "last_error_code": None,
                      "checks_since_start": 0, "counts": None,
                      "configured_interval_seconds": interval, "next_check_in_seconds": 0,
                      "automatic_mail_changes": False}

    def snapshot(self) -> dict:
        with self.lock:
            result = json.loads(json.dumps(self.state))
            age = None if self.last_completed_monotonic is None else max(0, int(time.monotonic() - self.last_completed_monotonic))
        result["seconds_since_check"] = age
        result["stale"] = age is None or age > max(result["next_check_in_seconds"] + 120, self.interval * 2)
        result["healthy"] = result["state"] == "healthy" and not result["stale"]
        result["monitor_running"] = bool(self.thread and self.thread.is_alive())
        return result

    def _persist(self):
        # Aggregate diagnostic snapshot only, atomically replaced with restrictive rights.
        payload = self.snapshot()
        temp = self.status_path.with_name(".monitor-status.tmp")
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.status_path)
        except OSError:
            LOG.warning("Monitorstatus konnte nicht gespeichert werden.")
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def check_once(self) -> int:
        try:
            raw = self.checker(self.folder)
            # Explicit allowlist: never persist arbitrary data/errors from external input.
            counts = {}
            for key in ("messages", "unseen"):
                value = raw.get(key)
                if type(value) is not int or value < 0:
                    raise ValueError("Invalid aggregate count")
                counts[key] = value
            success = True
        except Exception:
            success, counts = False, None
        with self.lock:
            previous = self.state["state"]
            self.state["checks_since_start"] += 1
            self.state["last_check_at"] = timestamp()
            self.last_completed_monotonic = time.monotonic()
            if success:
                self.state.update(state="healthy", last_success_at=self.state["last_check_at"],
                                  consecutive_failures=0, last_error_code=None, counts=counts)
                wait = self.interval
            else:
                failures = self.state["consecutive_failures"] + 1
                self.state.update(state="degraded", consecutive_failures=failures,
                                  last_error_code="MAILBOX_CHECK_FAILED")
                wait = min(3600, self.interval * 2 ** min(failures - 1, 6))
            self.state["next_check_in_seconds"] = wait
            changed = previous != self.state["state"]
        if changed:
            LOG.info("Postfachprüfung erfolgreich." if success else "Postfachprüfung fehlgeschlagen; erneuter Versuch mit Wartezeit.")
        self._persist()
        return wait

    def _run(self):
        while not self.stop_event.is_set():
            delay = self.check_once()
            if self.stop_event.wait(delay):
                break

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="mailbox-monitor", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)


def build_service(settings: Settings, data_dir: Path):
    from strato_http import HTTPSettings, build_http_app
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        data_dir.chmod(0o700)
    os.environ["STRATO_EMAIL"] = settings.email
    os.environ["STRATO_PASSWORD"] = settings.password
    os.environ["STRATO_BRIDGE_FOLDER"] = settings.folder
    bridge_accounts = [{'id': 'primary', 'email': settings.email, 'password': settings.password,
                        'folder': settings.folder, 'enabled': True}, *settings.accounts]
    os.environ['STRATO_ACCOUNTS_JSON'] = json.dumps(bridge_accounts, ensure_ascii=True)
    public_accounts = [{'id': item['id'], 'email': item['email'], 'folder': item['folder']}
                       for item in bridge_accounts if item['enabled']]
    server = strato_mail.create_mcp(tool_runner=run_mail_operation)
    monitor = MailboxMonitor(settings.folder, settings.poll_interval_seconds, data_dir)

    @server.tool(annotations=strato_mail.READ_ONLY)
    def service_status() -> dict:
        """Read the background mailbox monitor state. healthy=false needs attention; no mail changes performed."""
        return monitor.snapshot()

    http_settings = HTTPSettings(public_url=settings.public_url,
                                 login_password=settings.login_password,
                                 data_dir=data_dir,
                                 allowed_redirect_uris=settings.allowed_redirect_uris)
    app = build_http_app(http_settings, server)
    from strato_internal_bridge import InternalBridge
    return InternalBridge(app, settings.bridge_token, run_mail_operation, accounts=lambda: public_accounts), monitor


def main():
    parser = argparse.ArgumentParser(description="FTST STRATO Mail Home Assistant service")
    parser.add_argument("--options", type=Path, default=Path("/data/options.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--generate-login-password", action="store_true")
    args = parser.parse_args()
    if args.generate_login_password:
        print(secrets.token_urlsafe(32))
        return
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = Settings.load(args.options)
        if args.check_config:
            print("Konfiguration gültig. Postfach- und HTTPS-Verbindung wurden noch nicht getestet.")
            return
        app, monitor = build_service(settings, args.data_dir)
    except (ValueError, OSError):
        LOG.error("Start abgebrochen: lokale Konfiguration, Dateirechte und HTTPS-Adresse prüfen. Keine Zugangsdaten ins Chatfenster kopieren.")
        raise SystemExit(2) from None
    import uvicorn
    monitor.start()
    try:
        uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, access_log=False,
                    limit_concurrency=50, timeout_keep_alive=15)
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
