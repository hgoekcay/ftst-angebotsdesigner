"""Bounded, local-only voice transcription using Home Assistant Whisper."""

import json
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

MAX_UPLOAD = 12 * 1024 * 1024
MAX_SECONDS = 120
MAX_PCM = MAX_SECONDS * 16000 * 2
SERVICE = ("core-whisper", 10300)
_BUSY = threading.BoundedSemaphore(1)


class VoiceError(ValueError):
    """Safe German error suitable for display; never includes audio or logs."""


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VoiceError("Die Spracherkennung hat zu lange gedauert. Bitte erneut versuchen.")
    return remaining


def _decode(content, deadline):
    with tempfile.TemporaryDirectory(prefix="ftst-voice-") as directory:
        source = Path(directory) / "input"
        target = Path(directory) / "audio.pcm"
        source.write_bytes(content)
        # Only actual audio containers; playlist/network demuxers are excluded.
        # Decode one second beyond the limit so oversized recordings are rejected,
        # never silently transcribed as a truncated 120-second recording.
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
            "-threads", "1", "-max_alloc", "67108864",
            "-protocol_whitelist", "file", "-format_whitelist",
            "mov,matroska,webm,ogg,wav,mp3,flac,aac", "-i", str(source),
            "-map", "0:a:0", "-vn", "-sn", "-dn", "-threads", "1",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-t", "121", "-fs", str(MAX_PCM + 64000), "-f", "s16le", str(target),
        ]
        try:
            subprocess.run(command, check=True, timeout=min(45, _remaining(deadline)),
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, shell=False)
        except FileNotFoundError:
            raise VoiceError("Die lokale Audioverarbeitung ist noch nicht eingerichtet.") from None
        except subprocess.TimeoutExpired:
            raise VoiceError("Die Audiodatei konnte nicht rechtzeitig verarbeitet werden.") from None
        except subprocess.CalledProcessError:
            raise VoiceError("Die Datei ist keine lesbare Sprachaufnahme oder ist beschädigt.") from None
        if not target.exists() or target.stat().st_size == 0:
            raise VoiceError("Die Datei enthält keine lesbare Tonspur.")
        if target.stat().st_size > MAX_PCM:
            raise VoiceError("Sprachnotizen dürfen höchstens 120 Sekunden lang sein.")
        pcm = target.read_bytes()
        if len(pcm) % 2:
            raise VoiceError("Die Tonspur ist beschädigt. Bitte neu aufnehmen.")
        return pcm


def _send(connection, deadline, kind, data=None, payload=b""):
    header = {"type": kind, "data": data or {}}
    if payload:
        header["payload_length"] = len(payload)
    connection.settimeout(_remaining(deadline))
    connection.sendall(json.dumps(header).encode("utf-8") + b"\n" + payload)


def _receive(connection, deadline):
    def exact(size):
        result = bytearray()
        while len(result) < size:
            connection.settimeout(_remaining(deadline))
            chunk = connection.recv(size - len(result))
            if not chunk:
                raise ValueError("closed")
            result.extend(chunk)
        return bytes(result)

    line = bytearray()
    while len(line) < 8192:
        byte = exact(1)
        if byte == b"\n":
            break
        line.extend(byte)
    else:
        raise ValueError("header limit")
    header = json.loads(line)
    if not isinstance(header, dict) or not isinstance(header.get("type"), str):
        raise TypeError("header")
    lengths = [header.get("data_length", 0), header.get("payload_length", 0)]
    if any(type(value) is not int or value < 0 or value > 65536 for value in lengths):
        raise ValueError("frame limit")
    data = header.get("data", {})
    if not isinstance(data, dict):
        raise TypeError("data")
    if lengths[0]:
        extra = json.loads(exact(lengths[0]))
        if not isinstance(extra, dict):
            raise ValueError("data")
        data.update(extra)
    if lengths[1]:
        exact(lengths[1])
    return header["type"], data


def transcribe(filename: str, content: bytes) -> str:
    """Return German text, or raise VoiceError. Filename is never used as a path.

    Requires ffmpeg and the existing local core-whisper:10300 service only.
    Audio is temporary; this helper neither logs nor persists recordings.
    """
    del filename
    if not isinstance(content, bytes) or not content:
        raise VoiceError("Bitte eine Sprachaufnahme hochladen.")
    if len(content) > MAX_UPLOAD:
        raise VoiceError("Die Sprachaufnahme darf höchstens 12 MB groß sein.")
    if not _BUSY.acquire(blocking=False):
        raise VoiceError("Eine Sprachaufnahme wird bereits verarbeitet. Bitte kurz warten.")
    deadline = time.monotonic() + 180
    try:
        pcm = _decode(content, deadline)
        with socket.create_connection(SERVICE, timeout=min(10, _remaining(deadline))) as connection:
            audio_format = {"rate": 16000, "width": 2, "channels": 1}
            _send(connection, deadline, "transcribe", {"language": "de"})
            _send(connection, deadline, "audio-start", audio_format)
            for offset in range(0, len(pcm), 32000):
                _send(connection, deadline, "audio-chunk", audio_format, pcm[offset:offset + 32000])
            _send(connection, deadline, "audio-stop")
            for _ in range(32):
                kind, data = _receive(connection, deadline)
                if kind == "transcript":
                    text = data.get("text")
                    if not isinstance(text, str) or len(text) > 12000:
                        raise ValueError("transcript")
                    if not text.strip():
                        raise VoiceError("Es wurde keine Sprache erkannt. Bitte deutlicher aufnehmen.")
                    return text.strip()
                if kind == "error":
                    raise ValueError("service error")
            raise ValueError("event limit")
    except VoiceError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise VoiceError("Die lokale Spracherkennung ist nicht erreichbar oder hat keine gültige Antwort geliefert. Bitte Whisper prüfen oder Text eingeben.") from None
    finally:
        _BUSY.release()

