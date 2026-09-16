"""Service lifecycle tests without Docker, network or a model download."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ftst_local_service", Path(__file__).parents[1] / "ftst_local_ai" / "service.py"
)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


def test_download_is_opt_in_and_once_per_attempt(tmp_path):
    assert not service.preparation_needed(tmp_path, False, 1, [])
    assert service.preparation_needed(tmp_path, True, 1, [])
    assert not service.preparation_needed(tmp_path, True, 1, [])
    assert service.preparation_needed(tmp_path, True, 2, [])


def test_existing_model_never_downloads_again(tmp_path):
    assert not service.preparation_needed(tmp_path, True, 99, [{"name": service.MODEL}])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("options", [
    {"prepare_model": "false"}, {"download_attempt": True},
    {"download_attempt": 0}, {"download_attempt": 1001},
])
def test_options_reject_ambiguous_or_unbounded_downloads(tmp_path, options):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    with pytest.raises(ValueError):
        service.read_options(path)


def test_stuck_process_is_killed_after_grace_period():
    class Process:
        killed = False
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired("fake", timeout)
    process = Process()
    service.stop_process(process)
    assert process.terminated and process.killed


def test_sigterm_during_download_stops_both_children_and_preserves_attempt(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_model":true,"download_attempt":1}')
    handlers, children = {}, []

    class Process:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    def spawn(*args, **kwargs):
        process = Process()
        children.append(process)
        return process

    monkeypatch.setattr(service.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    monkeypatch.setattr(service, "tags", list)
    monkeypatch.setattr(service.time, "sleep", lambda _: handlers[service.signal.SIGTERM](15, None))
    assert service.main(tmp_path) == 0
    assert len(children) == 2
    assert all(p.returncode == -15 for p in children)
    assert not service.preparation_needed(tmp_path, True, 1, [])


def test_failed_server_is_cleaned_up_without_starting_download(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_model":true}')

    class Failed:
        returncode = 9

        def poll(self):
            return self.returncode

    calls = []
    monkeypatch.setattr(service.signal, "signal", lambda *_: None)
    monkeypatch.setattr(service.subprocess, "Popen", lambda *a, **k: calls.append(a) or Failed())
    assert service.main(tmp_path) == 1
    assert len(calls) == 1
    assert not list(tmp_path.glob("download-attempt*"))
