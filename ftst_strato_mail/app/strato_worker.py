"""Short-lived mailbox workers keep DNS and IMAP stalls away from the HTTP loop."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

OPERATIONS = frozenset({"list_mail_folders", "mailbox_status", "search_mail", "read_mail", "bridge_checkpoint", "bridge_batch"})
TIMEOUT_SECONDS = 75
CAPACITY = threading.BoundedSemaphore(3)
MAX_REQUEST = 16384


class BridgeUIDValidityChanged(ValueError):
    pass


def run_mail_operation(operation: str, arguments: dict) -> dict:
    if operation not in OPERATIONS or not isinstance(arguments, dict):
        raise ValueError("Ungültige Mailoperation.")
    request = json.dumps({"operation": operation, "arguments": arguments}, ensure_ascii=True)
    if len(request.encode()) > MAX_REQUEST:
        raise ValueError("Mailanfrage ist zu groß.")
    if not CAPACITY.acquire(blocking=False):
        raise ValueError("Maildienst ist ausgelastet. Bitte kurz warten und erneut versuchen.")
    try:
        result = subprocess.run([sys.executable, "-m", "strato_worker", "--child"],
                                input=request, text=True, capture_output=True,
                                timeout=TIMEOUT_SECONDS, check=False,
                                env={**os.environ, "PYTHONUNBUFFERED": "1"})
        if result.returncode != 0:
            raise ValueError("Mailoperation fehlgeschlagen. Verbindung und Konfiguration auf dem Server prüfen.")
        try:
            payload = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise ValueError("Ungültige Antwort des lokalen Mailprozesses.") from None
        if isinstance(payload, dict) and payload.get("error_code") == "UIDVALIDITY_CHANGED":
            raise BridgeUIDValidityChanged("Postfachkennung geändert.")
        if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
            raise ValueError("Mailoperation fehlgeschlagen. Verbindung, Suchbereich und Nachrichtengröße prüfen.")
        return payload["result"]
    except subprocess.TimeoutExpired:
        raise ValueError("Mailoperation nach 75 Sekunden beendet. Bitte später erneut versuchen.") from None
    except OSError:
        raise ValueError("Lokaler Mailprozess konnte nicht gestartet werden.") from None
    finally:
        CAPACITY.release()


def select_bridge_account(account_id):
    """Executed only in the short-lived child, never mutates the service environment."""
    if not isinstance(account_id, str):
        raise ValueError('Ungültige Postfach-ID.')
    accounts = json.loads(os.environ.get('STRATO_ACCOUNTS_JSON', '[]'))
    matches = [a for a in accounts if a.get('id') == account_id and a.get('enabled') is True]
    if len(matches) != 1:
        raise ValueError('Postfach nicht verfügbar.')
    account = matches[0]
    os.environ['STRATO_EMAIL'] = account['email']
    os.environ['STRATO_PASSWORD'] = account['password']
    os.environ['STRATO_BRIDGE_FOLDER'] = account['folder']
    # Other mailbox credentials are no longer needed by this process.
    os.environ.pop('STRATO_ACCOUNTS_JSON', None)


def main():
    if sys.argv[1:] != ["--child"]:
        raise SystemExit("Interner Mailprozess; über strato-mail-service starten.")
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ValueError()
        request = json.loads(raw)
        if (not isinstance(request, dict) or request.get("operation") not in OPERATIONS
                or not isinstance(request.get("arguments"), dict)):
            raise ValueError()
        import strato_mail
        import strato_bridge_transport
        bridge = request['operation'].startswith('bridge_')
        if bridge:
            select_bridge_account(request['arguments'].pop('account_id', 'primary'))
        module = strato_bridge_transport if bridge else strato_mail
        result = getattr(module, request["operation"])(**request["arguments"])
        response = {"ok": True, "result": result}
    except Exception as exc:
        # Never echo server responses, supplied message text, options or subprocess stderr.
        response = {"ok": False, "error_code": "UIDVALIDITY_CHANGED" if
                    type(exc).__name__ == "UIDValidityChanged" else "MAIL_OPERATION_FAILED"}
    sys.stdout.write(json.dumps(response, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
