"""Test del runner CLI in background della GUI (processo finto, nessun subprocess reale)."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

from cocbot.gui.tasks import CliTaskRunner, TaskEvent

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self, lines: tuple[str, ...] = (), exit_code: int = 0) -> None:
        self.stdout = iter([line + "\n" for line in lines])
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False
        self._finished = False

    def wait(self, timeout: float | None = None) -> int:
        self._finished = True
        return self.exit_code

    def poll(self) -> int | None:
        return self.exit_code if self._finished else None

    def terminate(self) -> None:
        self.terminated = True
        self._finished = True

    def kill(self) -> None:
        self.killed = True
        self._finished = True


def wait_for_terminal(runner: CliTaskRunner, timeout: float = 5.0) -> list[TaskEvent]:
    events: list[TaskEvent] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = runner.queue.get(timeout=0.1)
        except queue.Empty:
            continue
        events.append(event)
        if event.kind in ("finished", "cancelled", "error"):
            return events
    raise AssertionError(f"timeout: eventi ricevuti {[event.kind for event in events]}")


def test_runner_streams_output_and_finishes() -> None:
    created: dict[str, Any] = {}

    def factory(command: list[str], **kwargs: Any) -> FakeProcess:
        process = FakeProcess(("riga 1", "riga 2"))
        created.update(command=command, kwargs=kwargs, process=process)
        return process

    runner = CliTaskRunner(REPO_ROOT, python="python-test", process_factory=factory)
    assert runner.start(["probe", "--json"], "Rilevamento") is True
    events = wait_for_terminal(runner)

    assert [event.kind for event in events][0] == "started"
    assert events[-1].kind == "finished"
    assert events[-1].exit_code == 0
    lines = [event.line for event in events if event.kind == "line"]
    assert lines == ["riga 1", "riga 2"]
    assert created["command"][:3] == ["python-test", "-m", "cocbot"]
    assert created["command"][3:] == ["probe", "--json"]
    assert created["kwargs"]["cwd"] == str(REPO_ROOT)
    assert created["kwargs"]["text"] is True
    assert created["kwargs"]["encoding"] == "utf-8"
    assert created["kwargs"]["errors"] == "replace"
    assert runner.preview_for(["hud", "--json"]) == "python -m cocbot hud --json"
    assert runner.command_for(["hud"]) == ("python-test", "-m", "cocbot", "hud")


def test_runner_reports_start_error() -> None:
    def factory(command: list[str], **kwargs: Any) -> FakeProcess:
        raise OSError("interprete non trovato")

    runner = CliTaskRunner(REPO_ROOT, process_factory=factory)
    assert runner.start(["probe"], "Rilevamento") is True
    events = wait_for_terminal(runner)
    assert events[-1].kind == "error"
    assert "avvio non riuscito" in events[-1].line
    assert events[-1].exit_code == -1


class _BlockingStdout:
    def __init__(self, release: threading.Event) -> None:
        self.release = release

    def __iter__(self):
        yield "prima riga\n"
        self.release.wait(5.0)


class _BlockingProcess:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.stdout = _BlockingStdout(self.release)
        self.terminated = False
        self.killed = False
        self._finished = False

    def wait(self, timeout: float | None = None) -> int:
        self._finished = True
        return 0

    def poll(self) -> int | None:
        return 0 if self._finished else None

    def terminate(self) -> None:
        self.terminated = True
        self.release.set()

    def kill(self) -> None:
        self.killed = True
        self.release.set()


def test_runner_single_task_and_cancel_terminates_process() -> None:
    process = _BlockingProcess()
    runner = CliTaskRunner(REPO_ROOT, process_factory=lambda command, **kwargs: process)
    assert runner.start(["attack-run", "--allow-spend"], "Raid reale") is True

    deadline = time.monotonic() + 5.0
    while runner.queue.empty() and time.monotonic() < deadline:
        time.sleep(0.01)
    first = runner.queue.get(timeout=1.0)
    assert first.kind == "started"

    assert runner.running is True
    assert runner.label == "Raid reale"
    assert runner.start(["upgrade-run"], "doppio") is False

    assert runner.cancel() is True
    assert process.terminated is True
    events = wait_for_terminal(runner)
    assert events[-1].kind == "cancelled"
    assert runner.cancel() is False


def test_cancel_without_task_returns_false() -> None:
    def factory(command: list[str], **kwargs: Any) -> FakeProcess:
        raise AssertionError("nessun processo deve essere avviato")

    runner = CliTaskRunner(REPO_ROOT, process_factory=factory)
    assert runner.cancel() is False


def test_task_event_defaults() -> None:
    event = TaskEvent(kind="line", line="ciao")
    assert event.label == ""
    assert event.exit_code is None
    assert event.command == ()
