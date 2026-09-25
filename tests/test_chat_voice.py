import json
import subprocess
import time
from pathlib import Path

import chat_voice as voice
import pytest


class Connection:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = []

    def settimeout(self, timeout):
        assert 0 < timeout <= 180

    def recv(self, count):
        # Force fragmented frames, including multibyte Unicode characters.
        count = min(count, 3)
        result = self.response[:count]
        del self.response[:count]
        return bytes(result)

    def sendall(self, data):
        self.sent.append(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_local_protocol_complete_audio_and_unicode(monkeypatch):
    data = json.dumps({'text': ' Tür für Hüseyin öffnen '}, ensure_ascii=False).encode()
    connection = Connection(json.dumps({'type': 'transcript', 'data_length': len(data)}).encode() + b'\n' + data)
    monkeypatch.setattr(voice, '_decode', lambda *_: b'\0\1' * 20001)
    def connect(address, timeout):
        assert address == ('core-whisper', 10300)
        assert timeout <= 10
        return connection
    monkeypatch.setattr(voice.socket, 'create_connection', connect)
    assert voice.transcribe('../../secret', b'audio') == 'Tür für Hüseyin öffnen'
    events = [json.loads(frame.split(b'\n')[0]) for frame in connection.sent]
    assert [event['type'] for event in events] == ['transcribe', 'audio-start', 'audio-chunk', 'audio-chunk', 'audio-stop']
    assert events[0]['data']['language'] == 'de'
    assert sum(event.get('payload_length', 0) for event in events) == 40002


@pytest.mark.parametrize('frame', [
    b'x' * 8192,
    b'{"type":"transcript","data_length":65537}\n',
    b'{"type":"transcript","payload_length":-1}\n',
    b'{"type":"transcript","data_length":true}\n',
    b'{"type":"transcript","data_length":10}\n{}',
    b'{"type":"transcript","data":[]}\n',
    b'[]\n',
])
def test_framing_rejected(frame):
    with pytest.raises((ValueError, TypeError)):
        voice._receive(Connection(frame), time.monotonic() + 10)


@pytest.mark.parametrize('content', [b'', b'x' * (voice.MAX_UPLOAD + 1)], ids=['empty', 'oversize'])
def test_upload_limits_before_decode(monkeypatch, content):
    monkeypatch.setattr(voice, '_decode', lambda *_: pytest.fail('must not decode'))
    with pytest.raises(voice.VoiceError):
        voice.transcribe('recording.wav', content)


def test_conversion_bounded_and_temporary(monkeypatch):
    paths = []
    def run(command, **kwargs):
        assert kwargs['shell'] is False
        assert kwargs['timeout'] <= 45
        assert kwargs['stderr'] == subprocess.DEVNULL
        assert command[command.index('-protocol_whitelist') + 1] == 'file'
        assert 'hls' not in command[command.index('-format_whitelist') + 1]
        assert command[command.index('-t') + 1] == '121'
        source = Path(command[command.index('-i') + 1])
        assert source.read_bytes() == b'input'
        paths.extend([source, Path(command[-1])])
        Path(command[-1]).write_bytes(b'\0\1' * 16000)
    monkeypatch.setattr(voice.subprocess, 'run', run)
    assert len(voice._decode(b'input', time.monotonic() + 180)) == 32000
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize('size', [0, 3, voice.MAX_PCM + 2])
def test_decode_rejects_empty_corrupt_and_long_without_truncation(monkeypatch, size):
    paths = []
    def run(command, **kwargs):
        path = Path(command[-1])
        paths.append(path)
        path.write_bytes(b'\0' * size)
    monkeypatch.setattr(voice.subprocess, 'run', run)
    with pytest.raises(voice.VoiceError):
        voice._decode(b'input', time.monotonic() + 180)
    assert all(not path.exists() for path in paths)


def test_corrupt_decode_never_connects_and_sanitizes_logs(monkeypatch):
    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr='PRIVATE AUDIO DETAILS')
    monkeypatch.setattr(voice.subprocess, 'run', run)
    monkeypatch.setattr(voice.socket, 'create_connection', lambda *_: pytest.fail('no connection'))
    with pytest.raises(voice.VoiceError) as error:
        voice.transcribe('private.wav', b'corrupt')
    assert 'PRIVATE' not in str(error.value)
    assert voice._BUSY.acquire(blocking=False)
    voice._BUSY.release()


def test_deadline_and_concurrent_limit():
    with pytest.raises(voice.VoiceError):
        voice._remaining(time.monotonic() - 1)
    voice._BUSY.acquire()
    try:
        with pytest.raises(voice.VoiceError, match='bereits'):
            voice.transcribe('x', b'audio')
    finally:
        voice._BUSY.release()

