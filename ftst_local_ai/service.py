"""Small PID 1 supervisor. No model prompts, credentials or user data logged."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

MODEL = "qwen3:4b"
BASE = "http://127.0.0.1:11434"


def log(message):
    print(f"[FTST Lokale KI] {message}", flush=True)


def read_options(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    prepare = value.get("prepare_model", False)
    attempt = value.get("download_attempt", 1)
    if not isinstance(prepare, bool) or type(attempt) is not int or not 1 <= attempt <= 1000:
        raise ValueError("Ungültige Modellvorbereitungsoptionen")
    return prepare, attempt


def tags():
    with urlopen(BASE + "/api/tags", timeout=3) as response:
        return json.load(response).get("models", [])


def preparation_needed(data, prepare, attempt, models):
    if any(model.get("name") == MODEL for model in models):
        log(f"Modell {MODEL} vorhanden; kein Download.")
        return False
    if not prepare:
        log("Modell fehlt. Zur einmaligen Vorbereitung prepare_model einschalten und App neu starten.")
        return False
    marker = data / f"download-attempt-{attempt}.json"
    if marker.exists():
        log("Dieser Downloadversuch wurde bereits gestartet. Für bewusste Wiederholung download_attempt erhöhen.")
        return False
    # Persist BEFORE download: a crash/restart never triggers an automatic retry.
    with marker.open("x", encoding="utf-8") as handle:
        json.dump({"model": MODEL, "started_at": int(time.time())}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def main(data=Path("/data")):
    data.mkdir(parents=True, exist_ok=True)
    prepare, attempt = read_options(data / "options.json")
    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    server = None
    pull = None
    try:
        log("Starte Ollama 0.34.1; nur internes App-Netzwerk, Cloud deaktiviert.")
        # Lower CPU scheduling priority for HA responsiveness; no extra capability needed.
        server = subprocess.Popen(["nice", "-n", "10", "ollama", "serve"])
        deadline = time.monotonic() + 60
        models = None
        while not stopping and server.poll() is None and time.monotonic() < deadline:
            try:
                models = tags()
                break
            except (URLError, OSError, ValueError):
                time.sleep(0.5)
        if stopping:
            return 0
        if models is None:
            log("Ollama wurde nicht innerhalb 60 Sekunden bereit.")
            return 1
        log("API bereit auf internem Port 11434.")
        if preparation_needed(data, prepare, attempt, models):
            log(f"Einmaliger Downloadversuch {attempt}: {MODEL}, ungefähr 2,5 GB.")
            # CLI checks downloaded blob integrity. Limit total download to 45 minutes.
            env = dict(os.environ, OLLAMA_HOST=BASE)
            pull = subprocess.Popen(["ollama", "pull", MODEL], env=env)
            deadline = time.monotonic() + 2700
            while not stopping and server.poll() is None and pull.poll() is None and time.monotonic() < deadline:
                time.sleep(0.5)
            if stopping:
                return 0
            if pull.poll() is None:
                stop_process(pull)
                log("Download abgebrochen oder Zeitlimit erreicht; keine automatische Wiederholung.")
            elif pull.returncode == 0:
                log(f"Modell {MODEL} vorbereitet. Jetzt im AngebotsDesigner lokal testen.")
            else:
                log("Download fehlgeschlagen; Verbindung/Speicher prüfen, dann download_attempt bewusst erhöhen.")
        while not stopping and server.poll() is None:
            time.sleep(0.5)
        return 0 if stopping else (server.returncode or 1)
    finally:
        log("Stoppe Download und Ollama; gespeicherte Modelle bleiben erhalten.")
        stop_process(pull)
        stop_process(server)


if __name__ == "__main__":
    raise SystemExit(main())
