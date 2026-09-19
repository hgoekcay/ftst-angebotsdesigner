"""Small PID 1 supervisor. No model prompts, credentials or user data logged."""
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

MODEL = "qwen3:4b"
VISION_MODEL = "gemma3:4b"
BASE = "http://127.0.0.1:11434"
GIB = 1024 ** 3
MIN_DOWNLOAD_FREE = 6 * GIB
MIN_REMAINING_FREE = 2 * GIB
MAX_DOWNLOAD_GROWTH = 5 * GIB
DOWNLOAD_SECONDS = 2700


def log(message):
    print(f"[FTST Lokale KI] {message}", flush=True)


def read_options(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    prepare = value.get("prepare_model", False)
    attempt = value.get("download_attempt", 1)
    vision_prepare = value.get("prepare_vision_model", False)
    vision_attempt = value.get("vision_download_attempt", 1)
    for enabled, number in ((prepare, attempt), (vision_prepare, vision_attempt)):
        if not isinstance(enabled, bool) or type(number) is not int or not 1 <= number <= 1000:
            raise ValueError("Ungültige Modellvorbereitungsoptionen")
    return prepare, attempt, vision_prepare, vision_attempt


def tags():
    with urlopen(BASE + "/api/tags", timeout=3) as response:
        return json.load(response).get("models", [])


def preparation_needed(data, prepare, attempt, models, *, model=MODEL):
    if model not in (MODEL, VISION_MODEL):
        raise ValueError("Nicht unterstütztes lokales Modell")
    vision = model == VISION_MODEL
    option = "prepare_vision_model" if vision else "prepare_model"
    attempt_option = "vision_download_attempt" if vision else "download_attempt"
    if any(item.get("name") == model for item in models):
        log(f"Modell {model} vorhanden; kein Download.")
        return False
    if not prepare:
        log(f"Modell {model} fehlt. Zur einmaligen Vorbereitung {option} einschalten und App neu starten.")
        return False
    prefix = "vision-download-attempt" if vision else "download-attempt"
    marker = data / f"{prefix}-{attempt}.json"
    if marker.exists():
        log(f"Dieser Downloadversuch wurde bereits gestartet. Für bewusste Wiederholung {attempt_option} erhöhen.")
        return False
    # Persist BEFORE download: a crash/restart never triggers an automatic retry.
    with marker.open("x", encoding="utf-8") as handle:
        json.dump({"model": model, "started_at": int(time.time())}, handle)
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
    prepare, attempt, vision_prepare, vision_attempt = read_options(data / "options.json")
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
        for model, enabled, number, size, retry_option in (
            (MODEL, prepare, attempt, "2,5", "download_attempt"),
            (VISION_MODEL, vision_prepare, vision_attempt, "3,3", "vision_download_attempt"),
        ):
            if stopping or server.poll() is not None:
                break
            if not preparation_needed(data, enabled, number, models, model=model):
                continue
            # Each explicit attempt is consumed even if storage is insufficient.
            free_before = shutil.disk_usage(data).free
            if free_before < MIN_DOWNLOAD_FREE:
                log(f"Vorbereitung {model} benötigt mindestens 6 GiB freien Speicher. Nach Bereinigung {retry_option} erhöhen.")
                continue
            log(f"Einmaliger Downloadversuch {number}: {model}, ungefähr {size} GB.")
            # CLI checks downloaded blob integrity. Limit total download to 45 minutes.
            env = dict(os.environ, OLLAMA_HOST=BASE)
            pull = subprocess.Popen(["ollama", "pull", model], env=env)
            deadline = time.monotonic() + DOWNLOAD_SECONDS
            while not stopping and server.poll() is None and pull.poll() is None and time.monotonic() < deadline:
                free_now = shutil.disk_usage(data).free
                if free_now < MIN_REMAINING_FREE or free_before - free_now > MAX_DOWNLOAD_GROWTH:
                    log("Speichergrenze erreicht: 2 GiB Reserve oder höchstens 5 GiB Verbrauch je Downloadversuch.")
                    break
                time.sleep(0.5)
            if stopping:
                return 0
            if pull.poll() is None:
                stop_process(pull)
                log(f"Download {model} abgebrochen oder Grenze erreicht; keine automatische Wiederholung. Für neuen Versuch {retry_option} erhöhen.")
            elif pull.returncode == 0:
                log(f"Modell {model} vorbereitet. Jetzt im AngebotsDesigner lokal testen.")
            else:
                log(f"Download fehlgeschlagen; Verbindung/Speicher prüfen, dann {retry_option} bewusst erhöhen.")
        while not stopping and server.poll() is None:
            time.sleep(0.5)
        return 0 if stopping else (server.returncode or 1)
    finally:
        log("Stoppe Download und Ollama; gespeicherte Modelle bleiben erhalten.")
        stop_process(pull)
        stop_process(server)


if __name__ == "__main__":
    raise SystemExit(main())
