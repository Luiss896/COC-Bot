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

BUILD_DATASET = Path(__file__).resolve().parents[1] / "dataset" / "build-win-20261103"
_HAS_SCOUT = (BUILD_DATASET / "scout-screen-window.png").is_file()
scout_dataset = pytest.mark.skipif(not _HAS_SCOUT, reason="frame scout locale assente (gitignored)")


def _load_build(name: str) -> np.ndarray:
    image = cv2.imread(str(BUILD_DATASET / name))
    assert image is not None, f"frame assente: {name}"
    return image


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


def test_skip_session_limits() -> None:
    from cocbot.app.attack_engine import SkipSession

    session = SkipSession(max_skip=3, timeout_s=60.0)
    session.start(100.0)
    assert session.can_continue(100.0) == (True, "")
    assert session.record_skip(101.0)[0]
    assert session.record_skip(102.0)[0]
    ok, reason = session.record_skip(105.0)
    assert not ok
    assert "limite di skip" in reason


def test_skip_session_timeout() -> None:
    from cocbot.app.attack_engine import SkipSession

    session = SkipSession(max_skip=40, timeout_s=90.0)
    session.start(0.0)
    assert session.can_continue(89.9)[0]
    ok, reason = session.can_continue(90.0)
    assert not ok
    assert "timeout" in reason
    assert session.elapsed_s(95.0) == 95.0


def test_skip_session_zero_limits_mean_unlimited() -> None:
    from cocbot.app.attack_engine import SkipSession

    session = SkipSession(max_skip=0, timeout_s=0.0)
    session.start(0.0)
    for _ in range(50):
        assert session.record_skip(1.0)[0]


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
def test_battle_menu_close_point_geometry() -> None:
    """Il punto di chiusura del menu Battle e' l'angolo in alto a destra (hit area invisibile)."""
    from cocbot.vision import ui

    image = _load("03_battle_menu.png")
    point = ui.find_battle_menu_close(image)
    assert point is not None
    h, w = image.shape[:2]
    assert 0.96 < point[0] / w <= 1.0
    assert 0 <= point[1] / h < 0.06


def test_parse_loot_items_pure() -> None:
    from cocbot.app.attack_engine import parse_loot_items
    from cocbot.vision.ocr import TextItem

    def item(text: str, cy: int) -> TextItem:
        return TextItem(text=text, x0=0, y0=cy, x1=10, y1=cy + 10, score=0.9)

    items = [
        item("Available Loot:", 10),
        item("225 713", 50),
        item("170 241", 90),
        item("3 313", 130),
    ]
    preview = parse_loot_items(items)
    assert (preview.gold, preview.elixir, preview.dark) == (225_713, 170_241, 3_313)
    assert preview.notes == ()
    empty = parse_loot_items([item("niente", 10)])
    assert empty.gold is None
    assert empty.notes


def test_evaluate_loot_from_config() -> None:
    from cocbot.app.attack_engine import LootPreview, evaluate_loot_from_config
    from cocbot.config.models import Config

    loot = Config().loot
    decision = evaluate_loot_from_config(loot, LootPreview(gold=400_000, elixir=400_000, dark=3_000))
    assert decision.should_attack
    low = evaluate_loot_from_config(loot, LootPreview(gold=100_000, elixir=100_000, dark=100))
    assert not low.should_attack


@scout_dataset
def test_scout_screen_frame_and_buttons() -> None:
    """Frame live dell'anteprima base: stato PREVIEW, End Battle e Next riconosciuti."""
    from cocbot.core.types import ScreenState
    from cocbot.vision import states, ui

    image = _load_build("scout-screen-window.png")
    assert states.classify(image) is ScreenState.PREVIEW
    end = ui.find_end_battle_button(image)
    assert end is not None
    h, w = image.shape[:2]
    assert (end.x + end.w / 2) / w < 0.30
    next_button = ui.find_next_button(image)
    assert next_button is not None
    assert (next_button.x + next_button.w / 2) / w > 0.80
    # nessun falso positivo fuori dall'anteprima
    assert ui.find_end_battle_button(_load_build("home-after-panels.png")) is None
    assert ui.find_next_button(_load_build("battle-menu-window.png")) is None


@scout_dataset
def test_scout_loot_ocr_real_frame() -> None:
    """OCR del bottino sul frame reale dell'anteprima: oro/elisir/dark esatti."""
    from cocbot.app.attack_engine import parse_loot_items
    from cocbot.vision import ocr, ui

    image = _load_build("scout-screen-window.png")
    region = ui.loot_region(image)
    items = ocr.read_texts(
        image[region.y : region.bottom, region.x : region.right],
        offset=(region.x, region.y),
    )
    preview = parse_loot_items(items)
    assert (preview.gold, preview.elixir, preview.dark) == (225_713, 170_241, 3_313)
    assert preview.notes == ()


@dataset
def test_home_frame_still_classified_home() -> None:
    from cocbot.core.types import ScreenState
    from cocbot.vision import states

    assert states.classify(_load("01_home.png")) is ScreenState.HOME
