"""Test del loop attacco v1: loot policy (pura), pulsante "Find a Match", stato menu Battle."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from cocbot.app.attack_engine import DEFAULT_WEIGHTS, evaluate_loot

FULLSCREEN_DATASET = Path(__file__).resolve().parents[1] / "dataset" / "raw-20261103-1408"
_HAS_DATASET = (FULLSCREEN_DATASET / "03_battle_menu.png").is_file()
dataset = pytest.mark.skipif(not _HAS_DATASET, reason="dataset locale assente (screenshot gitignored)")


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(FULLSCREEN_DATASET / name))
    assert image is not None, f"frame assente: {name}"
    return image


THRESHOLDS = {"gold_min": 350_000, "elixir_min": 350_000, "dark_min": 2_000, "score_min": 800_000}


def test_evaluate_loot_good_base() -> None:
    decision = evaluate_loot(400_000, 450_000, 3_000, thresholds=THRESHOLDS)
    assert decision.should_attack
    assert decision.score == 400_000 + 450_000 + 300_000  # dark pesato 100x
    assert "bottino buono" in decision.reason


def test_evaluate_loot_below_thresholds() -> None:
    decision = evaluate_loot(100_000, 900_000, 3_000, thresholds=THRESHOLDS)
    assert not decision.should_attack
    assert "oro" in decision.reason


def test_evaluate_loot_score_below_minimum() -> None:
    # oro/elisir sopra soglia ma score aggregato insufficiente (score_min 800k)
    decision = evaluate_loot(360_000, 360_000, 0, thresholds=THRESHOLDS)
    assert not decision.should_attack
    assert "score" in decision.reason


def test_evaluate_loot_unreadable_never_attacks() -> None:
    assert not evaluate_loot(None, 900_000, 3_000, thresholds=THRESHOLDS).should_attack
    assert not evaluate_loot(900_000, None, None, thresholds=THRESHOLDS).should_attack


def test_evaluate_loot_dark_missing_is_not_blocking() -> None:
    decision = evaluate_loot(400_000, 400_000, None, thresholds=THRESHOLDS)
    assert decision.should_attack  # dark non controllato; score 800k >= minimo


def test_evaluate_loot_weights_from_config() -> None:
    from cocbot.config.models import Config

    loot = Config().loot
    thresholds = {
        "gold_min": loot.thresholds.gold_min,
        "elixir_min": loot.thresholds.elixir_min,
        "dark_min": loot.thresholds.dark_min,
        "score_min": loot.thresholds.score_min,
    }
    decision = evaluate_loot(400_000, 400_000, 3_000, thresholds=thresholds, weights=loot.weights)
    assert decision.should_attack
    assert DEFAULT_WEIGHTS["dark"] == 100.0


@dataset
def test_battle_menu_frame_is_classified() -> None:
    from cocbot.core.types import ScreenState
    from cocbot.vision import states

    assert states.classify(_load("03_battle_menu.png")) is ScreenState.BATTLE_MENU


@dataset
def test_find_match_button_geometry() -> None:
    from cocbot.vision import ui

    image = _load("03_battle_menu.png")
    rect = ui.find_find_match_button(image)
    assert rect is not None
    h, w = image.shape[:2]
    assert 0.03 < rect.x / w < 0.30
    assert 0.58 < rect.y / h < 0.76
    assert rect.aspect > 2.2  # pulsante largo e basso
    assert 0.10 < rect.w / w < 0.30


@dataset
def test_find_match_absent_outside_battle_menu() -> None:
    from cocbot.vision import ui

    assert ui.find_find_match_button(_load("01_home.png")) is None
    assert ui.find_find_match_button(_load("02_build_menu.png")) is None


@dataset
def test_home_frame_still_classified_home() -> None:
    from cocbot.core.types import ScreenState
    from cocbot.vision import states

    assert states.classify(_load("01_home.png")) is ScreenState.HOME
