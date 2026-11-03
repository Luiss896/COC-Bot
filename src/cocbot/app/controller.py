"""Controller del bot: ciclo di vita start/stop, cattura, health e humanization.

MVP attuale (fase F0/F1): non c'è ancora l'engine di gioco (attacco/upgrade/mura).
Il loop:
1. rileva la finestra del gioco (avvio manuale dell'utente) e attende se manca;
2. cattura con WGC e monitora FPS/frame neri/stale;
3. applica humanization/anti-ban: pause casuali brevi, pause lunghe periodiche, tap a vuoto
   su erba vuota (solo in home, mai su gemme/shop), rate limit;
4. va in pausa se la finestra è minimizzata o il frame non è valido.

Il motore vero (FSM + attacco + upgrade) si innesta al posto della sezione "idle".
"""
from __future__ import annotations

import random
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from cocbot.capture import win32
from cocbot.capture.input_winmsg import WinMsgSink
from cocbot.capture.screen_wgc import WgcScreenSource
from cocbot.capture.window import GameWindow, find_game_window
from cocbot.config.models import Config
from cocbot.core.types import Frame
from cocbot.safety.humanize import AntiBanMonitor, Humanizer
from cocbot.vision.safe_tap import find_safe_tap_point, looks_like_home


class BotState(StrEnum):
    IDLE = "idle"
    WAITING_GAME = "waiting_game"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True)
class BotSnapshot:
    state: BotState
    message: str
    fps: float = 0.0
    frames: int = 0
    session_s: float = 0.0
    actions: int = 0
    breaks: int = 0
    warnings: tuple[str, ...] = ()
    home_detected: bool = False


class _Source(Protocol):
    def grab(self) -> Frame: ...
    def health(self): ...
    def close(self) -> None: ...


class _Sink(Protocol):
    def tap_canonical(self, point, *, jitter: bool = True) -> None: ...
    def close(self) -> None: ...


class BotController:
    """Ciclo start/stop + stato thread-safe, senza rubare focus all'utente."""

    def __init__(
        self,
        config: Config,
        *,
        log: Callable[[str], None] | None = None,
        source_factory: Callable[[GameWindow], _Source] | None = None,
        sink_factory: Callable[[GameWindow], _Sink] | None = None,
        poll_s: float = 0.4,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.log = log or (lambda _message: None)
        self._source_factory = source_factory or (
            lambda window: WgcScreenSource(window, target_fps=config.capture.target_fps)
        )
        self._sink_factory = sink_factory or (
            lambda window: WinMsgSink(window, jitter_ms=tuple(config.input.jitter_ms))
        )
        self.poll_s = poll_s
        self._rng = rng or random.Random()
        self.humanizer = Humanizer(config.humanize, rng=self._rng)
        self.monitor = AntiBanMonitor(config.humanize)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = BotSnapshot(BotState.IDLE, "pronto")

    # ---------------------------------------------------------------- stato
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> BotSnapshot:
        with self._lock:
            base = self._snapshot
        anti = self.monitor.snapshot()
        return BotSnapshot(
            state=base.state,
            message=base.message,
            fps=base.fps,
            frames=base.frames,
            session_s=anti.session_s,
            actions=anti.actions,
            breaks=anti.breaks,
            warnings=anti.warnings,
            home_detected=base.home_detected,
        )

    def _update(self, state: BotState | None = None, message: str | None = None, **kwargs) -> None:
        with self._lock:
            changes = dict(kwargs)
            if state is not None:
                changes["state"] = state
            if message is not None:
                changes["message"] = message
            self._snapshot = replace(self._snapshot, **changes)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        if self.is_running:
            return False
        self._stop.clear()
        self.monitor = AntiBanMonitor(self.config.humanize)
        self.humanizer = Humanizer(self.config.humanize, rng=self._rng)
        self._thread = threading.Thread(target=self._run, name="cocbot-controller", daemon=True)
        self._thread.start()
        self.log("bot avviato")
        return True

    def stop(self, join_timeout_s: float = 3.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(join_timeout_s)
        self._thread = None
        self._update(BotState.STOPPED, "fermato")
        self.log("bot fermato")

    def toggle(self) -> bool:
        if self.is_running:
            self.stop()
            return False
        self.start()
        return True

    def _wait(self, seconds: float) -> None:
        if seconds > 0:
            self._stop.wait(seconds)

    # ---------------------------------------------------------------- loop
    def _run(self) -> None:
        win32.set_dpi_awareness()
        try:
            while not self._stop.is_set():
                info = find_game_window()
                if info is None:
                    self._update(BotState.WAITING_GAME, "in attesa: apri GPGPC e avvia il gioco")
                    self._wait(2.0)
                    continue
                window = GameWindow(info)
                if win32.is_minimized(window.hwnd):
                    self._update(BotState.PAUSED, "pausa: finestra del gioco minimizzata")
                    self._wait(2.0)
                    continue
                self._loop_window(window)
            self._update(BotState.STOPPED, "fermato")
        except Exception as exc:  # pragma: no cover - diagnostica runtime
            self.log(f"ERRORE controller: {exc!r}")
            self._update(BotState.ERROR, f"errore: {exc}")

    def _loop_window(self, window: GameWindow) -> None:
        source: _Source | None = None
        sink: _Sink | None = None
        try:
            source = self._source_factory(window)
            sink = self._sink_factory(window)
            self._update(BotState.RUNNING, "bot in esecuzione")
            self.log(f"agganciato: {window}")
            while not self._stop.is_set():
                if not win32.is_window(window.hwnd):
                    self.log("finestra di gioco chiusa: attendo l'avvio manuale")
                    return
                if win32.is_minimized(window.hwnd):
                    self._update(BotState.PAUSED, "pausa: finestra del gioco minimizzata")
                    self._wait(1.5)
                    continue
                try:
                    frame = source.grab()
                except RuntimeError as exc:
                    self.log(f"cattura non disponibile: {exc}")
                    self._update(BotState.PAUSED, "cattura non disponibile")
                    self._wait(1.0)
                    continue
                health = source.health()
                home = looks_like_home(frame.image)
                self._update(
                    BotState.RUNNING,
                    "in esecuzione (home)" if home else "in esecuzione (stato non riconosciuto: solo monitor)",
                    fps=health.fps,
                    frames=health.frames,
                    home_detected=home,
                )
                if self._apply_breaks():
                    continue
                if home and self.humanizer.maybe_idle_tap():
                    self._idle_tap(sink, frame)
                self._wait(self.poll_s)
        finally:
            if source is not None:
                source.close()
            if sink is not None:
                sink.close()

    def _apply_breaks(self) -> bool:
        """Applica pause umanizzate; ritorna True se ha dormito (ciclo da ripetere)."""
        session_min = self.monitor.session_seconds() / 60.0
        long_break = self.humanizer.long_break_due(session_min)
        if long_break > 0:
            self.monitor.record_break(long_break)
            self.log(f"pausa lunga programmata: {long_break:.0f}s")
            self._update(BotState.PAUSED, f"pausa programmata ({long_break:.0f}s)")
            self._wait(long_break)
            self._update(BotState.RUNNING, "bot in esecuzione")
            return True
        short_break = self.humanizer.maybe_break_s()
        if short_break > 0:
            self.monitor.record_break(short_break)
            self.log(f"pausa breve: {short_break:.0f}s")
            self._update(BotState.PAUSED, f"pausa breve ({short_break:.0f}s)")
            self._wait(short_break)
            self._update(BotState.RUNNING, "bot in esecuzione")
            return True
        return False

    def _idle_tap(self, sink: _Sink, frame: Frame) -> None:
        point = find_safe_tap_point(frame.image, rng=self._rng)
        if point is None:
            return
        delay = max(self.humanizer.next_action_delay_s(), self.monitor.next_delay_s())
        self._wait(delay)
        if self._stop.is_set():
            return
        try:
            sink.tap_canonical(point)
        except RuntimeError as exc:
            self.log(f"tap non inviato: {exc}")
            return
        self.monitor.record_action(point)
        self.log(f"tap a vuoto su erba (canonico {point.x},{point.y})")
