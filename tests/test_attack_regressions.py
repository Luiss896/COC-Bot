"""Regressioni dei bug engine confermati dall'audit (fix 18 nov 2026).

I test usano engine costruiti con ``__new__`` e funzioni UI/classificatore monkeypatched:
niente gioco reale, ma coprono le condizioni che hanno causato i bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import cocbot.__main__ as main_module
from cocbot.app import attack_engine, upgrade_engine
from cocbot.app.attack_engine import LootPreview, dark_fallback_decision
from cocbot.config.models import Config
from cocbot.core.types import Rect, ScreenState

_THRESHOLDS = {"gold_min": 350_000, "elixir_min": 350_000, "dark_min": 2_000}


def _attack_engine(monkeypatch: pytest.MonkeyPatch) -> tuple[attack_engine.AttackEngine, dict]:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    monitor: dict = {"logs": [], "taps": []}
    engine.log = lambda message: monitor["logs"].append(message)
    engine._tap = lambda point, wait_s=None: monitor["taps"].append(point)
    engine._wait_state = lambda expected, timeout_s=3.0: None
    engine.grab = lambda: "frame"
    monkeypatch.setattr(attack_engine.time, "sleep", lambda seconds: None)
    return engine, monitor


def test_end_battle_early_never_taps_confirm_while_in_battle(monkeypatch: pytest.MonkeyPatch) -> None:
    """In BATTLE la barra truppe ha elementi verdi: mai cercare/tappare CONFIRM."""
    engine, monitor = _attack_engine(monkeypatch)
    monkeypatch.setattr(attack_engine.states, "classify", lambda image: ScreenState.BATTLE)
    monkeypatch.setattr(
        attack_engine.ui, "find_end_battle_button", lambda image: Rect(10, 10, 20, 20)
    )

    def fail_confirm(image):
        raise AssertionError("find_confirm_button non deve essere chiamato in BATTLE")

    monkeypatch.setattr(attack_engine.ui, "find_confirm_button", fail_confirm)
    assert engine.end_battle_early(confirm_timeout_s=0.01) is False


def test_end_battle_early_confirms_only_on_upgrade_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, monitor = _attack_engine(monkeypatch)
    states = iter([ScreenState.BATTLE, ScreenState.UPGRADE_CONFIRM, ScreenState.BATTLE_END])
    monkeypatch.setattr(
        attack_engine.states, "classify", lambda image: next(states, ScreenState.BATTLE_END)
    )
    monkeypatch.setattr(
        attack_engine.ui, "find_end_battle_button", lambda image: Rect(10, 10, 20, 20)
    )
    confirm_rect = Rect(100, 100, 40, 40)
    monkeypatch.setattr(attack_engine.ui, "find_confirm_button", lambda image: confirm_rect)
    assert engine.end_battle_early(confirm_timeout_s=2.0) is True
    assert (120, 120) in monitor["taps"]


def test_dark_fallback_not_applied_when_base_loot_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capacità ampia ma base povera: la policy normale scarta, niente raid 'solo dark'."""
    loot = LootPreview(gold=100_000, elixir=100_000, dark=9_000)
    decision = dark_fallback_decision(
        loot,
        usable_gold=5_000_000,
        usable_elixir=5_000_000,
        thresholds=_THRESHOLDS,
        weights={"gold": 1.0, "elixir": 1.0, "dark": 100.0},
    )
    assert decision is None


def test_run_farm_never_exceeds_max_gold_spend(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.log = lambda message: None
    calls: list[dict] = []

    def fake_run_attack(**kwargs):
        calls.append(kwargs)
        return {"action": "attacked", "searches": kwargs["max_searches"]}

    engine.run_attack = fake_run_attack
    monkeypatch.setattr(
        attack_engine, "save_attack_report", lambda report, out_dir="out/attack", prefix="attack": Path("report.json")
    )
    monkeypatch.setattr(attack_engine.time, "sleep", lambda seconds: None)

    report = engine.run_farm(cycles=3, allow_spend=True, max_searches=3, max_gold_spend=1_100)

    assert calls[0]["max_searches"] == 1
    assert report["spent_gold"] <= report["max_gold_spend"]
    assert report["spent_gold"] == 1_100
    assert len(report["reports"]) == 1
    assert "tetto spesa" in report["stopped"]


def test_hud_text_returns_none_when_grab_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)

    def failing_grab():
        raise upgrade_engine.UpgradeEngineError("finestra minimizzata")

    engine.grab = failing_grab
    assert engine._hud_text() is None


def test_recover_home_never_taps_build_outside_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In PREVIEW senza End Battle il fallback Build potrebbe cadere su 'Next' (~1100 oro)."""
    engine = upgrade_engine.UpgradeEngine.__new__(upgrade_engine.UpgradeEngine)
    monitor: dict = {"taps": [], "logs": []}
    engine.log = lambda message: monitor["logs"].append(message)
    engine._tap = lambda point, wait_s=None: monitor["taps"].append(point)
    engine.grab = lambda: "frame"
    monkeypatch.setattr(upgrade_engine.states, "classify", lambda image: ScreenState.PREVIEW)
    monkeypatch.setattr(upgrade_engine.ui, "find_end_battle_button", lambda image: None)

    def fail_build(image):
        raise AssertionError("il fallback Build non deve essere usato in PREVIEW")

    monkeypatch.setattr(upgrade_engine.ui, "find_build_button", fail_build)
    assert engine.recover_home(max_attempts=2) is False
    assert monitor["taps"] == []


def test_recover_home_unknown_still_uses_build_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = upgrade_engine.UpgradeEngine.__new__(upgrade_engine.UpgradeEngine)
    monitor: dict = {"taps": [], "logs": []}
    engine.log = lambda message: monitor["logs"].append(message)
    engine._tap = lambda point, wait_s=None: monitor["taps"].append(point)
    engine.grab = lambda: "frame"
    monkeypatch.setattr(upgrade_engine.states, "classify", lambda image: ScreenState.UNKNOWN)
    monkeypatch.setattr(
        upgrade_engine.ui, "find_build_button", lambda image: Rect(600, 800, 100, 100)
    )
    monkeypatch.setattr(upgrade_engine.ui, "find_menu_close", lambda image: None)

    assert engine.recover_home(max_attempts=1) is False
    assert (650, 850) in monitor["taps"]


class _FailingEngine:
    def run_attack(self, **kwargs):
        raise upgrade_engine.UpgradeEngineError("finestra del gioco minimizzata")

    def run_farm(self, **kwargs):
        raise upgrade_engine.UpgradeEngineError("finestra del gioco minimizzata")

    def close(self) -> None:
        return None


@pytest.mark.parametrize("command", ("attack-run", "attack-farm"))
def test_attack_cli_catches_upgrade_engine_errors(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        main_module, "_load_engine", lambda config, engine_class=None: (Config(), _FailingEngine())
    )
    code = main_module.main([command])
    output = capsys.readouterr().out
    assert code == 1
    assert "ERRORE engine" in output
    assert "minimizzata" in output
