"""Test delle funzioni pure per attacco cap-aware e telemetria (round 7)."""
from __future__ import annotations

import json

from cocbot.app.attack_engine import (
    LootPreview,
    apply_capacity,
    save_attack_report,
    usable_capacity,
)
from cocbot.app.upgrade_engine import HudRead


def _hud(**kwargs) -> HudRead:
    return HudRead(**kwargs)


def test_usable_capacity_known_values() -> None:
    hud = _hud(gold=9_000_000, elixir=10_000_000, dark=170_000, builders_available=4)
    gold, elixir = usable_capacity(hud, cap_gold=10_000_000, cap_elixir=10_000_000)
    assert gold == 1_000_000
    assert elixir == 0


def test_usable_capacity_unknown_resource() -> None:
    hud = _hud(gold=None, elixir=5_000_000, dark=None, builders_available=None)
    gold, elixir = usable_capacity(hud, cap_gold=10_000_000, cap_elixir=10_000_000)
    assert gold is None
    assert elixir == 5_000_000


def test_usable_capacity_overflow_clamped_to_zero() -> None:
    hud = _hud(gold=11_000_000, elixir=10_500_000, dark=None, builders_available=3)
    gold, elixir = usable_capacity(hud, cap_gold=10_000_000, cap_elixir=10_000_000)
    assert gold == 0
    assert elixir == 0


def test_apply_capacity_clamps_loot() -> None:
    loot = LootPreview(gold=800_000, elixir=900_000, dark=5_000)
    effective = apply_capacity(loot, usable_gold=300_000, usable_elixir=None)
    assert effective.gold == 300_000
    assert effective.elixir == 900_000  # capacita' elisir ignota: non tocca
    assert effective.dark == 5_000


def test_apply_capacity_no_op_when_capacity_unknown() -> None:
    loot = LootPreview(gold=800_000, elixir=900_000, dark=None)
    effective = apply_capacity(loot, usable_gold=None, usable_elixir=None)
    assert (effective.gold, effective.elixir, effective.dark) == (800_000, 900_000, None)


def test_save_attack_report_roundtrip(tmp_path) -> None:
    report = {"action": "attacked", "searches": 1, "result": {"outcome": "victory"}}
    path = save_attack_report(report, out_dir=tmp_path)
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == report
