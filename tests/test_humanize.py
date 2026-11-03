"""Test humanization/anti-ban e hotkey."""
from __future__ import annotations

import random

import pytest

from cocbot.config.models import HumanizeConfig
from cocbot.core.types import GamePoint
from cocbot.gui.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey
from cocbot.safety.humanize import AntiBanMonitor, Humanizer


def test_parse_hotkey_ctrl_alt_l() -> None:
    assert parse_hotkey("ctrl+alt+l") == (MOD_CONTROL | MOD_ALT, ord("L"))


def test_parse_hotkey_shift_f12() -> None:
    assert parse_hotkey("shift+f12") == (MOD_SHIFT, 0x7B)


def test_parse_hotkey_invalid() -> None:
    with pytest.raises(ValueError):
        parse_hotkey("ctrl+foo")
    with pytest.raises(ValueError):
        parse_hotkey("")


def test_action_delay_within_range() -> None:
    config = HumanizeConfig(action_delay_ms=(300, 900), min_seconds_between_actions=0.2)
    humanizer = Humanizer(config, rng=random.Random(1))
    delays = [humanizer.next_action_delay_s() for _ in range(300)]
    assert all(0.2 <= delay <= 0.9 + 1e-9 for delay in delays)
    assert len(set(delays)) > 10  # non è un ritardo fisso


def test_break_probability() -> None:
    never = Humanizer(HumanizeConfig(break_probability=0.0), rng=random.Random(1))
    assert never.maybe_break_s() == 0.0
    half = Humanizer(
        HumanizeConfig(break_probability=0.5, break_duration_s=(10, 20)),
        rng=random.Random(1),
    )
    values = [half.maybe_break_s() for _ in range(80)]
    assert any(value > 0 for value in values)
    assert all(value == 0 or 10.0 <= value <= 20.0 for value in values)


def test_long_break_schedule() -> None:
    config = HumanizeConfig(long_break_every_min=25, long_break_duration_s=(60, 90))
    humanizer = Humanizer(config, rng=random.Random(2))
    assert humanizer.long_break_due(10.0) == 0.0
    due = humanizer.long_break_due(26.0)
    assert 60.0 <= due <= 90.0
    assert humanizer.long_break_due(30.0) == 0.0  # non si ripete subito


def test_anti_ban_rate_limit() -> None:
    now = [0.0]
    monitor = AntiBanMonitor(HumanizeConfig(max_actions_per_minute=3), clock=lambda: now[0])
    for _ in range(3):
        monitor.record_action(GamePoint(10, 10))
        now[0] += 1.0
    assert monitor.next_delay_s() > 0.0
    assert any("ritmo" in warning or "ripetuto" in warning for warning in monitor.warnings())


def test_anti_ban_same_target_warning() -> None:
    monitor = AntiBanMonitor(HumanizeConfig(max_same_target_repeats=3), clock=lambda: 0.0)
    for _ in range(3):
        monitor.record_action(GamePoint(10, 10))
    assert any("ripetuto" in warning for warning in monitor.warnings())


def test_anti_ban_snapshot_fields() -> None:
    monitor = AntiBanMonitor(HumanizeConfig(), clock=lambda: 0.0)
    monitor.record_action(GamePoint(1, 2))
    monitor.record_break(5.0)
    snapshot = monitor.snapshot()
    assert snapshot.actions == 1
    assert snapshot.breaks == 1
    assert snapshot.unique_targets == 1
