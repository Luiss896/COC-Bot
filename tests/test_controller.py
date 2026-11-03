"""Test controller: stati base e tap a vuoto umanizzato (senza gioco reale)."""
from __future__ import annotations

import random
import time
import types

from cocbot.app import controller as controller_module
from cocbot.app.controller import BotController, BotState
from cocbot.config.models import Config
from cocbot.core.types import GamePoint


class FakeSink:
    def __init__(self) -> None:
        self.taps: list[GamePoint] = []

    def tap_canonical(self, point, *, jitter: bool = True) -> None:
        self.taps.append(point)

    def close(self) -> None:
        return None


def test_controller_waits_when_game_absent(monkeypatch) -> None:
    monkeypatch.setattr(controller_module, "find_game_window", lambda: None)
    controller = BotController(Config(), poll_s=0.05)
    controller.start()
    time.sleep(0.3)
    snapshot = controller.snapshot()
    controller.stop()
    assert snapshot.state is BotState.WAITING_GAME
    assert "apri" in snapshot.message.lower() or "attesa" in snapshot.message.lower()


def test_controller_stop_sets_stopped_state(monkeypatch) -> None:
    monkeypatch.setattr(controller_module, "find_game_window", lambda: None)
    controller = BotController(Config(), poll_s=0.05)
    controller.start()
    time.sleep(0.15)
    controller.stop()
    assert controller.snapshot().state is BotState.STOPPED
    assert controller.is_running is False


def test_idle_tap_records_action(monkeypatch) -> None:
    point = GamePoint(500, 500)
    monkeypatch.setattr(controller_module, "find_safe_tap_point", lambda image, **kwargs: point)
    config = Config()
    config.humanize.action_delay_ms = (0, 0)
    config.humanize.min_seconds_between_actions = 0.0
    sink = FakeSink()
    controller = BotController(config, rng=random.Random(0))
    controller._idle_tap(sink, types.SimpleNamespace(image=None))
    assert sink.taps == [point]
    assert controller.monitor.actions == 1
