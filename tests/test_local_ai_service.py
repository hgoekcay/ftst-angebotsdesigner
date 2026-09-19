"""Service lifecycle tests without Docker, network or a model download."""
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ftst_local_service", Path(__file__).parents[1] / "ftst_local_ai" / "service.py"
)
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


@pytest.fixture(autouse=True)
def ample_model_storage(monkeypatch):
    # Do not let the test machine's free disk space decide lifecycle behavior.
    monkeypatch.setattr(service.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * service.GIB))


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
    {"prepare_vision_model": "false"}, {"vision_download_attempt": True},
    {"vision_download_attempt": 0}, {"vision_download_attempt": 1001},
])
def test_options_reject_ambiguous_or_unbounded_downloads(tmp_path, options):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    with pytest.raises(ValueError):
        service.read_options(path)


def test_old_options_never_enable_vision_download(tmp_path):
    path = tmp_path / "options.json"
    path.write_text('{"prepare_model":false,"download_attempt":2}')
    assert service.read_options(path) == (False, 2, False, 1)


def test_vision_attempts_are_independent_and_existing_model_is_retained(tmp_path):
    assert service.preparation_needed(tmp_path, True, 1, [])
    assert service.preparation_needed(tmp_path, True, 1, [], model=service.VISION_MODEL)
    assert not service.preparation_needed(tmp_path, True, 1, [], model=service.VISION_MODEL)
    assert service.preparation_needed(tmp_path, True, 2, [], model=service.VISION_MODEL)
    assert not service.preparation_needed(tmp_path, True, 3,
        [{"name": service.VISION_MODEL}], model=service.VISION_MODEL)
    assert json.loads((tmp_path / "vision-download-attempt-1.json").read_text())["model"] == service.VISION_MODEL
    assert not (tmp_path / "vision-download-attempt-3.json").exists()


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


def lifecycle_fakes(monkeypatch, *, complete_pulls=False):
    handlers, children = {}, []

    class Process:
        def __init__(self, command):
            self.command = command
            self.returncode = 0 if complete_pulls and "pull" in command else None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    def spawn(command, **kwargs):
        process = Process(command)
        children.append(process)
        return process

    monkeypatch.setattr(service.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    monkeypatch.setattr(service, "tags", list)
    monkeypatch.setattr(service.time, "sleep", lambda _: handlers[service.signal.SIGTERM](15, None))
    return children


def test_both_models_prepare_sequentially_once(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_model":true,"prepare_vision_model":true}')
    children = lifecycle_fakes(monkeypatch, complete_pulls=True)
    assert service.main(tmp_path) == 0
    assert [p.command for p in children[1:]] == [
        ["ollama", "pull", service.MODEL], ["ollama", "pull", service.VISION_MODEL],
    ]
    assert len(list(tmp_path.glob("*download-attempt-1.json"))) == 2
    children.clear()
    assert service.main(tmp_path) == 0
    assert len(children) == 1


def test_vision_download_requires_explicit_enable(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_model":false}')
    children = lifecycle_fakes(monkeypatch)
    assert service.main(tmp_path) == 0
    assert len(children) == 1
    assert not list(tmp_path.glob("*download-attempt*"))


def test_insufficient_storage_consumes_vision_attempt_without_pulling(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_vision_model":true}')
    children = lifecycle_fakes(monkeypatch)
    monkeypatch.setattr(service.shutil, "disk_usage", lambda _: SimpleNamespace(free=5 * service.GIB))
    assert service.main(tmp_path) == 0
    assert len(children) == 1
    assert (tmp_path / "vision-download-attempt-1.json").exists()


@pytest.mark.parametrize("remaining", [1 * service.GIB, 3 * service.GIB])
def test_running_vision_download_stops_at_storage_limit(tmp_path, monkeypatch, remaining):
    (tmp_path / "options.json").write_text('{"prepare_vision_model":true}')
    children = lifecycle_fakes(monkeypatch)
    spaces = iter([10 * service.GIB, remaining])
    monkeypatch.setattr(service.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(spaces)))
    assert service.main(tmp_path) == 0
    assert children[1].command == ["ollama", "pull", service.VISION_MODEL]
    assert all(p.returncode == -15 for p in children)
    assert (tmp_path / "vision-download-attempt-1.json").exists()


def test_vision_download_stops_at_deadline(tmp_path, monkeypatch):
    (tmp_path / "options.json").write_text('{"prepare_vision_model":true}')
    children = lifecycle_fakes(monkeypatch)
    ticks = iter(range(0, 1000, 2))
    monkeypatch.setattr(service.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(service, "DOWNLOAD_SECONDS", 1)
    assert service.main(tmp_path) == 0
    assert all(p.returncode == -15 for p in children)
    assert len(children) == 2
