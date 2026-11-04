"""Test parser della schermata risultati di battaglia (puro + frame reali live)."""
from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from cocbot.vision.ocr import TextItem
from cocbot.vision.textparse import parse_percent

ROOT = Path(__file__).resolve().parents[1]
BUILD_DATASET = ROOT / "dataset" / "build-win-20261103"
HAS_BUILD_DATASET = (BUILD_DATASET / "battle-end-victory-window.png").is_file()
build_dataset = pytest.mark.skipif(
    not HAS_BUILD_DATASET,
    reason="dataset build-win-20261103 assente (frame reali, gitignored)",
)


def _load_build(name: str):
    image = cv2.imread(str(BUILD_DATASET / name))
    assert image is not None, f"frame mancante: {name}"
    return image


def _item(text: str, y: int, *, x: int = 800, height: int = 20) -> TextItem:
    return TextItem(text=text, x0=x, y0=y, x1=x + 120, y1=y + height, score=0.9)


def test_parse_percent() -> None:
    assert parse_percent("15%") == 15
    assert parse_percent(" 9 % ") == 9
    assert parse_percent("Victory") is None
    assert parse_percent("150%") is None


def test_parse_result_items_pure() -> None:
    from cocbot.vision.battle_result import parse_result_items

    items = [
        _item("Total damage:", 121),
        _item("15%", 157),
        _item("VictoRY", 283),
        _item("You got:", 404),
        _item("59 023", 448),
        _item("53271", 513),
        _item("1296", 577),
        _item("Troops expended:", 639),
        _item("x13", 671),
    ]
    result = parse_result_items(items, frame_height=975)
    assert result.outcome == "victory"
    assert result.damage_pct == 15
    assert (result.loot_gold, result.loot_elixir, result.loot_dark) == (59_023, 53_271, 1_296)
    assert result.troops_expended == 13
    assert result.notes == ()


def test_parse_result_items_defeat_two_loot_rows() -> None:
    from cocbot.vision.battle_result import parse_result_items

    items = [
        _item("Total damage:", 121),
        _item("9%", 157),
        _item("Defeat", 283),
        _item("You got:", 404),
        _item("126 794", 448),
        _item("402 741", 513),
    ]
    result = parse_result_items(items, frame_height=975)
    assert result.outcome == "defeat"
    assert result.damage_pct == 9
    assert (result.loot_gold, result.loot_elixir, result.loot_dark) == (126_794, 402_741, None)
    # due importi su tre e' normale se il dark non e' mostrato: nessuna nota
    assert result.notes == ()


def test_parse_result_items_garbage_returns_none() -> None:
    from cocbot.vision.battle_result import parse_result_items

    items = [_item("Buildings & Heroes", 300), _item("Attack", 500)]
    result = parse_result_items(items, frame_height=975)
    assert result.outcome is None
    assert result.damage_pct is None
    assert result.loot_gold is None
    assert len(result.notes) >= 2


@build_dataset
def test_read_result_victory_real_frame() -> None:
    from cocbot.vision.battle_result import read_result

    result = read_result(_load_build("battle-end-victory-window.png"))
    assert result.outcome == "victory"
    assert result.damage_pct == 15
    assert (result.loot_gold, result.loot_elixir, result.loot_dark) == (59_023, 53_271, 1_296)
    assert result.troops_expended == 13


@build_dataset
def test_read_result_defeat_real_frame() -> None:
    from cocbot.vision.battle_result import read_result

    result = read_result(_load_build("battle-results-loot-window.png"))
    assert result.outcome == "defeat"
    assert result.damage_pct == 14
    assert (result.loot_gold, result.loot_elixir, result.loot_dark) == (112_000, 58_510, 154)
    assert result.troops_expended == 6


@build_dataset
def test_read_result_on_home_frame_no_false_positive() -> None:
    from cocbot.vision.battle_result import read_result

    result = read_result(_load_build("home-after-panels.png"))
    assert result.outcome is None
    assert result.damage_pct is None
