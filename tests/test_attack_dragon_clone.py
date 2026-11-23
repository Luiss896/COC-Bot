"""Test della strategia DRAGON CLONE (deploy veloce, cloni, eroi) e nuovi argomenti CLI."""
from __future__ import annotations

import numpy as np
import pytest

import cocbot.__main__ as main_module
from cocbot.app import attack_engine
from cocbot.config.models import Config
from cocbot.vision import ui

IMAGE = np.zeros((975, 1733, 3), dtype=np.uint8)


def _fake_engine() -> tuple[attack_engine.AttackEngine, list[tuple[tuple[int, int], float | None]]]:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    taps: list[tuple[tuple[int, int], float | None]] = []
    engine._tap = lambda point, wait_s=None: taps.append((point, wait_s))
    return engine, taps


def test_attack_config_defaults() -> None:
    """Default attuali (23 nov 2026): strategia DRAGON CORNER + Invisibility Spell."""
    config = Config()
    assert config.attack.strategy == "dragon_corner"
    assert config.attack.corner == "random"
    assert config.attack.corner_pan is True
    assert config.attack.invisibility_spells == 5
    assert config.attack.invisibility_card_slot == 0
    # la strategia storica dragon_clone resta selezionabile (config invariata)
    assert config.attack.clone_spells == 2
    assert config.attack.clone_card_slot == 0
    assert config.attack.deploy_interval_s == 0.15


def test_battle_spell_card_positions() -> None:
    first = ui.battle_spell_card(0)
    second = ui.battle_spell_card(1)
    assert first == ui.BATTLE_SPELL_CARD
    assert pytest.approx(second[0] - first[0], abs=1e-3) == ui.BATTLE_CARD_STEP
    assert ui.battle_spell_card(-3) == ui.BATTLE_SPELL_CARD


def test_deploy_dragon_clone_same_point_then_clones_then_heroes(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "find_deploy_candidates", lambda image, limit=1: [(500, 700)]
    )
    count = engine.deploy_dragon_clone(IMAGE, dragons=13, heroes=True, clones=2)

    assert count == 1 + 13 + 1 + 2 + 4
    assert len(taps) == count
    # tutti i draghi nello stesso punto, subito dopo la selezione della card
    assert taps[0][0] == ui.battle_card_point(IMAGE, ui.BATTLE_DRAGON_CARD)
    dragon_taps = taps[1:14]
    assert {point for point, _wait in dragon_taps} == {(500, 700)}
    # poi la card clone e due lanci sullo stesso punto dei draghi
    assert taps[14][0] == ui.battle_card_point(IMAGE, ui.battle_spell_card(0))
    assert taps[15][0] == (500, 700)
    assert taps[16][0] == (500, 700)
    # infine gli eroi, subito dopo, con tap spostato dietro ai draghi
    assert taps[17][0] == ui.battle_card_point(IMAGE, ui.BATTLE_QUEEN_CARD)
    assert taps[18][0] != (500, 700)
    assert taps[19][0] == ui.battle_card_point(IMAGE, ui.BATTLE_WARDEN_CARD)


def test_deploy_dragon_clone_custom_clone_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "find_deploy_candidates", lambda image, limit=1: [(300, 500)]
    )
    engine.deploy_dragon_clone(IMAGE, dragons=2, heroes=False, clones=1, clone_card_slot=2)
    assert taps[3][0] == ui.battle_card_point(IMAGE, ui.battle_spell_card(2))


def test_deploy_dragon_clone_without_clones_or_heroes(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "find_deploy_candidates", lambda image, limit=1: [(400, 600)]
    )
    count = engine.deploy_dragon_clone(IMAGE, dragons=3, heroes=False, clones=0)
    assert count == 1 + 3
    assert len(taps) == 4


def test_deploy_dragon_clone_without_deploy_point(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(attack_engine.ui, "find_deploy_candidates", lambda image, limit=1: [])
    monkeypatch.setattr(attack_engine.ui, "battle_field_grid", lambda image: [])
    assert engine.deploy_dragon_clone(IMAGE, dragons=5, heroes=True, clones=2) == 0
    assert taps == []
    assert any("nessun punto" in line for line in engine.logs)


def test_cli_parser_dragon_clone_options() -> None:
    parser = main_module.build_parser()
    args = parser.parse_args(
        ["attack-run", "--clones", "3", "--strategy", "dragon_spam", "--clone-card-slot", "1"]
    )
    assert args.clones == 3
    assert args.strategy == "dragon_spam"
    assert args.clone_card_slot == 1

    defaults = parser.parse_args(["attack-run"])
    assert defaults.clones is None
    assert defaults.strategy is None
    assert defaults.clone_card_slot is None

    farm = parser.parse_args(["attack-farm", "--clones", "4"])
    assert farm.clones == 4
