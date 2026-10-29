"""Local voice authorization, protocol bounds and real ffmpeg decoding."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import wave
from unittest.mock import patch

import pytest

_spec = importlib.util.spec_from_file_location("atlas_voice_under_test", Path(__file__).resolve().parents[2] / "ftst_atlas/voice.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def client(**options):
    return v.VoiceClient({"voice_enabled": True, "voice_ha_user_id": "owner", **options})


def event(kind, data=None, payload=b"", **header):
    return json.dumps({"type": kind, "data": data or {}, "payload_length": len(payload), **header}).encode() + b"\n" + payload


class FakeSocket:
    def __init__(self, response):
        self.response = io.BytesIO(response)
        self.sent = []
        self.timeouts = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def settimeout(self, timeout):
        self.timeouts.append(timeout)
    def recv(self, count):
        return self.response.read(min(count, 97))
    def sendall(self, value):
        self.sent.append(value)


def test_authorization_and_host_validation():
    assert client().status("owner")["enabled"]
    for options in ({"voice_enabled": False}, {"voice_ha_user_id": ""}, {"voice_ha_user_id": []},
                    {"voice_whisper_host": "evil.example"}, {"voice_piper_host": "127.0.0.1"},
                    {"voice_piper_host": ["core-piper"]}):
        c = client(**options)
        assert not c.status("owner")["enabled"]
        with pytest.raises(v.VoiceAccessError):
            c.transcribe("owner", b"x", "audio/wav")
    with patch.object(v.socket, "create_connection") as connect:
        for user in (None, "other", {"id": "owner"}):
            with pytest.raises(v.VoiceAccessError):
                client().synthesize(user, "Hallo")
        connect.assert_not_called()
    assert v.VoiceClient({"voice_enabled": True, "voice_ha_user_id": "owner", "voice_piper_host": "localhost"}, dev=True).status("owner")["enabled"]


def test_transcribe_exact_local_protocol():
    sock = FakeSocket(event("transcript", {"text": "  Guten Morgen  "}))
    with patch.object(v, "_decode", return_value=b"\0" * 64000), patch.object(v.socket, "create_connection", return_value=sock) as connect:
        assert client().transcribe("owner", b"audio", "audio/webm;codecs=opus") == {"text": "Guten Morgen"}
    assert connect.call_args.args == (("core-whisper", 10300),)
    headers = [json.loads(value.split(b"\n", 1)[0]) for value in sock.sent]
    assert [x["type"] for x in headers] == ["transcribe", "audio-start", "audio-chunk", "audio-chunk", "audio-stop"]
    assert headers[0]["data"] == {"language": "de"}
    assert headers[1]["data"] == {"rate": 16000, "width": 2, "channels": 1}
    assert all(0 < timeout <= 150 for timeout in sock.timeouts)


def test_synthesize_wav():
    fmt = {"rate": 22050, "width": 2, "channels": 1}
    pcm = b"\x01\x00" * 2205
    sock = FakeSocket(event("audio-start", fmt) + event("audio-chunk", fmt, pcm) + event("audio-stop"))
    with patch.object(v.socket, "create_connection", return_value=sock) as connect:
        output = client().synthesize("owner", "Hallo")
    assert connect.call_args.args == (("core-piper", 10200),)
    with wave.open(io.BytesIO(output)) as audio:
        assert audio.getframerate() == 22050
        assert audio.getnchannels() == 1
        assert audio.readframes(2205) == pcm
    assert json.loads(sock.sent[0])["data"] == {"text": "Hallo", "text_format": "text"}


@pytest.mark.parametrize("response", [
    b"x" * 8192, b"not-json\n", b"[]\n", b'{"type":"transcript","type":"error"}\n',
    event("transcript", data_length=True), event("transcript", payload_length=-1),
    event("transcript", payload_length=1048577), event("transcript", data_length=32769),
    event("transcript", data_length=3) + b"[] ", event("transcript", {"text": "x" * 2001}),
    event("transcript", {"text": "ok"}, b"unexpected"), event("error", {"text": "SECRET backend failure"}), b"",
])
def test_malformed_transcription_is_safe(response):
    with patch.object(v, "_decode", return_value=b"\0\0"), patch.object(v.socket, "create_connection", return_value=FakeSocket(response)):
        with pytest.raises(v.VoiceError) as error:
            client().transcribe("owner", b"audio", "audio/wav")
    assert "SECRET" not in str(error.value)


def test_extra_protocol_data_and_event_limit():
    extra = json.dumps({"text": "Hallo"}).encode()
    stream = v._Stream(FakeSocket(event("transcript", data_length=len(extra)) + extra), time.monotonic() + 10)
    assert stream.receive() == ("transcript", {"text": "Hallo"}, b"")
    with patch.object(v, "_decode", return_value=b"\0\0"), patch.object(v.socket, "create_connection", return_value=FakeSocket(event("ignored") * 33)):
        with pytest.raises(v.VoiceError):
            client().transcribe("owner", b"audio", "audio/wav")


@pytest.mark.parametrize("response", [
    event("audio-stop"), event("audio-chunk", {"rate": 16000, "width": 2, "channels": 1}, b"\0\0"),
    event("audio-start", {"rate": 192000, "width": 2, "channels": 1}),
    event("audio-start", {"rate": 16000, "width": 2, "channels": 1}) + event("audio-chunk", {"rate": 22050, "width": 2, "channels": 1}, b"\0\0"),
    event("audio-start", {"rate": 16000, "width": 2, "channels": 1}) + event("audio-chunk", {"rate": 16000, "width": 2, "channels": 1}, b"\0"),
    event("error", {"text": "SECRET"}),
])
def test_invalid_synthesis(response):
    with patch.object(v.socket, "create_connection", return_value=FakeSocket(response)):
        with pytest.raises(v.VoiceError) as error:
            client().synthesize("owner", "Hallo")
    assert "SECRET" not in str(error.value)


def test_size_limits_timeout_and_busy():
    with patch.object(v.socket, "create_connection") as connect:
        with pytest.raises(v.VoiceError):
            client().transcribe("owner", b"x" * (v.MAX_UPLOAD + 1), "audio/wav")
        with pytest.raises(v.VoiceError):
            client().synthesize("owner", "x" * 2001)
        v._BUSY.acquire()
        try:
            with pytest.raises(v.VoiceBusyError):
                client().synthesize("owner", "Hallo")
        finally:
            v._BUSY.release()
        connect.assert_not_called()
    with patch.object(v.socket, "create_connection", side_effect=socket.timeout("SECRET")):
        with pytest.raises(v.VoiceError) as error:
            client().synthesize("owner", "Hallo")
        assert "SECRET" not in str(error.value)
    stream = v._Stream(FakeSocket(b"x"), time.monotonic() - 1)
    with pytest.raises(v.VoiceError):
        stream.receive()
    stream = v._Stream(FakeSocket(b"x"), time.monotonic() + 10)
    with pytest.raises(ValueError):
        stream.exact(v.MAX_RESPONSE + 1)


def wav(seconds, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * int(rate * seconds))
    return output.getvalue()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
def test_real_ffmpeg_valid_and_overlong_audio():
    pcm = v._decode(wav(.1, 22050), "audio/wav", time.monotonic() + 30)
    assert len(pcm) == 3200
    with pytest.raises(v.VoiceError, match="60 Sekunden"):
        v._decode(wav(61), "audio/wav", time.monotonic() + 30)
    with pytest.raises(v.VoiceError):
        v._decode(b"invalid", "audio/webm", time.monotonic() + 30)
    with pytest.raises(v.VoiceError):
        v._decode(b"http://evil.example", "application/x-mpegurl", time.monotonic() + 30)


def test_ffmpeg_timeout_is_safe():
    with patch.object(v.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 25)):
        with pytest.raises(v.VoiceError, match="rechtzeitig"):
            v._decode(wav(.1), "audio/wav", time.monotonic() + 30)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg unavailable")
@pytest.mark.parametrize("mime,flags", [
    ("audio/webm;codecs=opus", ["-c:a", "libopus", "-f", "webm"]),
    ("audio/ogg;codecs=opus", ["-c:a", "libopus", "-f", "ogg"]),
    ("audio/mp4", ["-c:a", "aac", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4"]),
])
def test_real_browser_containers_through_transcription(mime, flags):
    encoded = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", *flags, "pipe:1"],
                             input=wav(.2), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True).stdout
    sock = FakeSocket(event("transcript", {"text": "Testaufnahme"}))
    with patch.object(v.socket, "create_connection", return_value=sock):
        assert client().transcribe("owner", encoded, mime) == {"text": "Testaufnahme"}
    chunks = [part.split(b"\n", 1)[1] for part in sock.sent if json.loads(part.split(b"\n", 1)[0])["type"] == "audio-chunk"]
    assert 5000 < sum(map(len, chunks)) < 12000
