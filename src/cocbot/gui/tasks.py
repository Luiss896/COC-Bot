"""Esecuzione dei comandi CLI ``python -m cocbot ...`` in background per la GUI.

La GUI non esegue logica di gioco in-process: lancia le CLI in un sottoprocesso e mostra
l'output nel registro. Questo modulo isola il sottoprocesso in un thread, emette eventi in
una coda thread-safe e garantisce che un task possa essere **annullato** (kill switch,
chiusura finestra): senza questo, chiudere la GUI durante un raid lascerebbe il processo
in esecuzione senza controllo.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TaskEventKind = Literal["started", "line", "finished", "cancelled", "error"]

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class TaskEvent:
    """Evento emesso dal runner verso la GUI (consumato sul thread tkinter)."""

    kind: TaskEventKind
    label: str = ""
    line: str = ""
    exit_code: int | None = None
    duration_s: float = 0.0
    command: tuple[str, ...] = ()
    arguments: tuple[str, ...] = ()


class CliTaskRunner:
    """Esegue una CLI alla volta in un thread; output e stato passano da ``queue``."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        python: str | None = None,
        process_factory: Callable[..., subprocess.Popen[str]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.python = python or sys.executable
        self.queue: queue.Queue[TaskEvent] = queue.Queue()
        self._process_factory = process_factory or subprocess.Popen
        self._clock = clock
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._label = ""
        self._command: tuple[str, ...] = ()
        self._cancel_requested = False
        self._started_at = 0.0

    # ------------------------------------------------------------------ stato
    @property
    def running(self) -> bool:
        with self._lock:
            thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def label(self) -> str:
        return self._label

    @property
    def command(self) -> tuple[str, ...]:
        return self._command

    def command_for(self, extra: Sequence[str]) -> tuple[str, ...]:
        """Comando completo (debug/log): ``python -u -m cocbot <extra>``.

        ``-u`` è essenziale: senza, l'output del figlio arriva a blocchi e la GUI sembra
        bloccata finché il processo non termina (osservato nei log dell'utente).
        """
        return (self.python, "-u", "-m", "cocbot", *extra)

    def preview_for(self, extra: Sequence[str]) -> str:
        """Riga compatta da mostrare nella GUI (senza percorso assoluto dell'interprete)."""
        return "python -m cocbot " + " ".join(extra)

    # ------------------------------------------------------------------ esecuzione
    def start(self, extra: Sequence[str], label: str, *, cwd: str | Path | None = None) -> bool:
        """Avvia un task; ritorna ``False`` se uno è già in esecuzione."""
        if self.running:
            return False
        command = self.command_for(extra)
        self._label = label
        self._command = command
        self._cancel_requested = False
        self._started_at = self._clock()
        self.queue.put(
            TaskEvent(
                "started",
                label=label,
                command=command,
                arguments=tuple(str(argument) for argument in extra),
            )
        )
        thread = threading.Thread(
            target=self._worker,
            args=(command, str(cwd or self.repo_root)),
            name="cocbot-cli-task",
            daemon=True,
        )
        with self._lock:
            self._thread = thread
            self._process = None
        thread.start()
        return True

    def _worker(self, command: tuple[str, ...], cwd: str) -> None:
        started = self._clock()
        process: subprocess.Popen[str] | None = None
        try:
            try:
                process = self._process_factory(
                    list(command),
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_CREATE_NO_WINDOW,
                )
            except OSError as exc:
                self.queue.put(
                    TaskEvent(
                        "error",
                        label=self._label,
                        line=f"avvio non riuscito: {exc}",
                        exit_code=-1,
                        duration_s=self._clock() - started,
                        command=command,
                    )
                )
                return
            with self._lock:
                self._process = process
            assert process.stdout is not None
            for line in process.stdout:
                self.queue.put(TaskEvent("line", label=self._label, line=line.rstrip()))
            exit_code = process.wait()
            cancelled = self._cancel_requested
            self.queue.put(
                TaskEvent(
                    "cancelled" if cancelled else "finished",
                    label=self._label,
                    exit_code=exit_code,
                    duration_s=self._clock() - started,
                    command=command,
                )
            )
        finally:
            with self._lock:
                self._process = None
                self._thread = None

    def cancel(self, *, timeout_s: float = 2.0) -> bool:
        """Termina il processo del task (e attende). ``True`` se c'era un task attivo."""
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return False
        self._cancel_requested = True
        try:
            process.terminate()
        except OSError:  # pragma: no cover - processo già morto
            return True
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=timeout_s)
            except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
                pass
        return True


__all__ = ["CliTaskRunner", "TaskEvent", "TaskEventKind"]
