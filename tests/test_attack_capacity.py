"""Test delle funzioni pure per attacco cap-aware e telemetria (round 7)."""
from __future__ import annotations

import json

from cocbot.app.attack_engine import (
    LootPreview,
    apply_capacity,
    dark_fallback_decision,
    save_attack_report,
    usable_capacity,
    usable_dark_capacity,
)
from cocbot.app.upgrade_engine import HudRead

_THRESHOLDS = {"gold_min": 350_000, "elixir_min": 350_000, "dark_min": 2_000}


def test_dark_fallback_when_capacity_limited() -> None:
    """Storage quasi piene: oro/elisir non incassabili, ma il dark basta → attacca."""
    loot = LootPreview(gold=800_000, elixir=800_000, dark=9_000)
    decision = dark_fallback_decision(
        loot,
        usable_gold=50_000,
        usable_elixir=45_000,
        thresholds=_THRESHOLDS,
        weights={"gold": 1.0, "elixir": 1.0, "dark": 100.0},
    )
    assert decision is not None
    assert decision.should_attack
    assert decision.dark == 9_000
    assert "solo dark" in decision.reason
    assert decision.score == 900_000


def test_dark_fallback_not_applied_when_dark_low() -> None:
    loot = LootPreview(gold=800_000, elixir=800_000, dark=500)
    assert (
        dark_fallback_decision(
            loot,
            usable_gold=50_000,
            usable_elixir=45_000,
            thresholds=_THRESHOLDS,
        )
        is None
    )


def test_dark_fallback_not_applied_with_capacity() -> None:
    """Con capacita' sufficiente la policy normale decide: niente fallback."""
    loot = LootPreview(gold=800_000, elixir=800_000, dark=9_000)
    assert (
        dark_fallback_decision(
            loot,
            usable_gold=5_000_000,
            usable_elixir=5_000_000,
            thresholds=_THRESHOLDS,
        )
        is None
    )


def test_dark_fallback_not_applied_unreadable_loot() -> None:
    loot = LootPreview(gold=None, elixir=None, dark=9_000)
    assert (
        dark_fallback_decision(
            loot,
            usable_gold=0,
            usable_elixir=0,
            thresholds=_THRESHOLDS,
        )
        is None
    )


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


def test_usable_dark_capacity() -> None:
    hud = _hud(gold=10_000_000, elixir=10_000_000, dark=194_775)
    assert usable_dark_capacity(hud, cap_dark=200_000) == 5_225
    assert usable_dark_capacity(_hud(dark=200_000), cap_dark=200_000) == 0
    assert usable_dark_capacity(_hud(dark=None), cap_dark=200_000) is None


def test_dark_fallback_disabled_when_dark_full() -> None:
    """Dark al cap (usable_dark == 0): il fallback non deve autorizzare raid inutili."""
    loot = LootPreview(gold=800_000, elixir=800_000, dark=9_000)
    assert (
        dark_fallback_decision(
            loot,
            usable_gold=0,
            usable_elixir=0,
            usable_dark=0,
            thresholds=_THRESHOLDS,
        )
        is None
    )


def test_farm_stop_reason() -> None:
    """Dopo un raid attaccato il farm continua; un ciclo senza attacco lo ferma con motivo."""
    from cocbot.app.attack_engine import farm_stop_reason

    assert farm_stop_reason({"action": "attacked"}) is None
    storage_reason = farm_stop_reason({"action": "storage_full"})
    assert storage_reason is not None and "storage" in storage_reason
    skip_reason = farm_stop_reason({"action": "skip_limit"})
    assert skip_reason is not None and "skip" in skip_reason
    unknown = farm_stop_reason({"action": "azione_boh"})
    assert unknown is not None and "non prevista" in unknown


def test_save_attack_report_roundtrip(tmp_path) -> None:
    report = {"action": "attacked", "searches": 1, "result": {"outcome": "victory"}}
    path = save_attack_report(report, out_dir=tmp_path)
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == report
