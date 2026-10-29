"""Owner-only, bounded local Wyoming speech. Audio is never persisted or logged."""
import io
import json
import socket
import subprocess
import threading
import time
import wave

MAX_UPLOAD = 5 * 1024 * 1024
MAX_SECONDS = 60
MAX_PCM = MAX_SECONDS * 16000 * 2
MAX_TEXT = 2000
MAX_RESPONSE = 8 * 1024 * 1024
_BUSY = threading.BoundedSemaphore(1)
_FORMATS = {"audio/webm": "matroska", "audio/ogg": "ogg", "audio/mp4": "mov", "audio/wav": "wav", "audio/x-wav": "wav"}


class VoiceError(ValueError):
    """Safe user-facing error, with no service details or private content."""


class VoiceAccessError(VoiceError):
    pass


class VoiceBusyError(VoiceError):
    pass


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise VoiceError("Die lokale Sprachverarbeitung hat zu lange gedauert.")
    return left


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


class _Stream:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        self.total = 0

    def exact(self, count):
        self.total += count
        if self.total > MAX_RESPONSE:
            raise ValueError("response limit")
        value = bytearray()
        while len(value) < count:
            self.sock.settimeout(_remaining(self.deadline))
            part = self.sock.recv(count - len(value))
            if not part:
                raise ValueError("closed")
            value.extend(part)
        return bytes(value)

    def receive(self):
        line = bytearray()
        for _ in range(8192):
            char = self.exact(1)
            if char == b"\n":
                break
            line.extend(char)
        else:
            raise ValueError("header limit")
        header = json.loads(line, object_pairs_hook=_object)
        if not isinstance(header, dict) or not isinstance(header.get("type"), str):
            raise ValueError("header")
        lengths = [header.get("data_length", 0), header.get("payload_length", 0)]
        if any(type(n) is not int or n < 0 or n > limit for n, limit in zip(lengths, (32768, 1048576))):
            raise ValueError("frame limit")
        data = header.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("data")
        if lengths[0]:
            extra = json.loads(self.exact(lengths[0]), object_pairs_hook=_object)
            if not isinstance(extra, dict):
                raise ValueError("extra data")
            data.update(extra)
        return header["type"], data, self.exact(lengths[1])

    def send(self, kind, data=None, payload=b""):
        header = {"type": kind, "data": data or {}}
        if payload:
            header["payload_length"] = len(payload)
        self.sock.settimeout(_remaining(self.deadline))
        self.sock.sendall(json.dumps(header).encode() + b"\n" + payload)


def _decode(raw, mime, deadline):
    mime = mime.partition(";")[0].strip().lower()
    if mime not in _FORMATS:
        raise VoiceError("Bitte eine Aufnahme als WebM, Ogg, MP4 oder WAV verwenden.")
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
               "-threads", "1", "-max_alloc", "67108864", "-protocol_whitelist", "pipe",
               "-f", _FORMATS[mime], "-i", "pipe:0", "-map", "0:a:0", "-vn", "-sn", "-dn",
               "-threads", "1", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
               "-t", "61", "-fs", str(MAX_PCM + 64000), "-f", "s16le", "pipe:1"]
    try:
        result = subprocess.run(command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=min(25, _remaining(deadline)), check=True, shell=False)
    except FileNotFoundError:
        raise VoiceError("Die lokale Audioverarbeitung ist noch nicht eingerichtet.") from None
    except subprocess.TimeoutExpired:
        raise VoiceError("Die Aufnahme konnte nicht rechtzeitig verarbeitet werden.") from None
    except subprocess.CalledProcessError:
        raise VoiceError("Die Aufnahme ist beschädigt oder enthält keine lesbare Tonspur.") from None
    pcm = result.stdout
    if len(pcm) > MAX_PCM:
        raise VoiceError("Die Aufnahme darf höchstens 60 Sekunden lang sein.")
    if not pcm or len(pcm) % 2:
        raise VoiceError("Die Aufnahme enthält keine gültige Tonspur.")
    return pcm


class VoiceClient:
    def __init__(self, options, dev=False):
        self.enabled = options.get("voice_enabled", False) is True
        self.owner = options.get("voice_ha_user_id", "")
        self.whisper = options.get("voice_whisper_host", "core-whisper")
        self.piper = options.get("voice_piper_host", "core-piper")
        local = {"localhost", "127.0.0.1", "::1"} if dev else set()
        self.valid = (isinstance(self.owner, str) and bool(self.owner.strip()) and len(self.owner) <= 128
                      and isinstance(self.whisper, str) and self.whisper in ({"core-whisper"} | local)
                      and isinstance(self.piper, str) and self.piper in ({"core-piper"} | local))

    def status(self, user=None):
        permitted = self.enabled and self.valid and isinstance(user, str) and user == self.owner
        reason = "" if permitted else ("Sprachfunktionen sind deaktiviert." if not self.enabled else
                  "Die lokale Sprachkonfiguration ist unvollständig oder ungültig." if not self.valid else
                  "Sprachfunktionen sind nur für den eingerichteten Eigentümer verfügbar.")
        return {"enabled": permitted, "reason": reason, "local": True, "max_seconds": MAX_SECONDS,
                "max_upload_bytes": MAX_UPLOAD, "max_text_chars": MAX_TEXT}

    def _authorize(self, user):
        status = self.status(user)
        if not status["enabled"]:
            raise VoiceAccessError(status["reason"])

    def transcribe(self, user, raw, mime):
        self._authorize(user)
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_UPLOAD or not isinstance(mime, str):
            raise VoiceError("Bitte eine Sprachaufnahme bis höchstens 5 MiB hochladen.")
        if not _BUSY.acquire(blocking=False):
            raise VoiceBusyError("Eine Sprachaufnahme oder Sprachausgabe wird bereits verarbeitet. Bitte kurz warten.")
        try:
            deadline = time.monotonic() + 150
            pcm = _decode(raw, mime, deadline)
            with socket.create_connection((self.whisper, 10300), timeout=10) as sock:
                stream = _Stream(sock, deadline)
                fmt = {"rate": 16000, "width": 2, "channels": 1}
                stream.send("transcribe", {"language": "de"})
                stream.send("audio-start", fmt)
                for offset in range(0, len(pcm), 32000):
                    stream.send("audio-chunk", fmt, pcm[offset:offset + 32000])
                stream.send("audio-stop")
                for _ in range(32):
                    kind, data, payload = stream.receive()
                    if payload or kind == "error":
                        raise ValueError("unexpected event")
                    if kind == "transcript":
                        text = data.get("text")
                        if not isinstance(text, str) or len(text) > MAX_TEXT:
                            raise ValueError("transcript")
                        if not text.strip():
                            raise VoiceError("Es wurde keine Sprache erkannt. Bitte deutlicher aufnehmen.")
                        return {"text": text.strip()}
                raise ValueError("event limit")
        except VoiceError:
            raise
        except (OSError, ValueError, TypeError, RecursionError):
            raise VoiceError("Die lokale Spracherkennung ist nicht erreichbar oder hat keine gültige Antwort geliefert. Bitte Whisper prüfen.") from None
        finally:
            _BUSY.release()

    def synthesize(self, user, text):
        self._authorize(user)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise VoiceError("Die Sprachausgabe benötigt einen Text mit höchstens 2000 Zeichen.")
        if not _BUSY.acquire(blocking=False):
            raise VoiceBusyError("Eine Sprachaufnahme oder Sprachausgabe wird bereits verarbeitet. Bitte kurz warten.")
        try:
            deadline = time.monotonic() + 120
            with socket.create_connection((self.piper, 10200), timeout=10) as sock:
                stream = _Stream(sock, deadline)
                stream.send("synthesize", {"text": text.strip(), "text_format": "text"})
                fmt, pcm = None, bytearray()
                for _ in range(1024):
                    kind, data, payload = stream.receive()
                    if kind == "audio-start" and fmt is None and not payload:
                        fmt = tuple(data.get(key) for key in ("rate", "width", "channels"))
                        if any(type(n) is not int for n in fmt) or not 8000 <= fmt[0] <= 48000 or fmt[1] != 2 or fmt[2] not in (1, 2):
                            raise ValueError("audio format")
                    elif kind == "audio-chunk" and fmt is not None:
                        if tuple(data.get(key) for key in ("rate", "width", "channels")) != fmt or len(payload) % (fmt[1] * fmt[2]):
                            raise ValueError("audio chunk")
                        pcm.extend(payload)
                        if len(pcm) > MAX_RESPONSE or len(pcm) > fmt[0] * fmt[1] * fmt[2] * 120:
                            raise ValueError("audio duration")
                    elif kind == "audio-stop" and fmt is not None and pcm and not payload:
                        output = io.BytesIO()
                        with wave.open(output, "wb") as audio:
                            audio.setframerate(fmt[0])
                            audio.setsampwidth(fmt[1])
                            audio.setnchannels(fmt[2])
                            audio.writeframes(pcm)
                        return output.getvalue()
                    else:
                        raise ValueError("unexpected event")
                raise ValueError("event limit")
        except VoiceError:
            raise
        except (OSError, ValueError, TypeError, RecursionError, wave.Error):
            raise VoiceError("Die lokale Sprachausgabe ist nicht erreichbar oder hat keine gültige Antwort geliefert. Bitte Piper prüfen.") from None
        finally:
            _BUSY.release()
