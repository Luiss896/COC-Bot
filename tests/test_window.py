import pytest

from cocbot.capture.window import (
    canonical_to_client,
    fit_viewport,
    masked_title,
)
from cocbot.core.types import GamePoint, Rect


def test_masked_title_hides_account_name() -> None:
    assert masked_title("Clash of Clans - myAccount123") == "Clash of Clans - <account redatto>"
    # titoli non di gioco restano invariati
    assert masked_title("Google Play Games") == "Google Play Games"


def test_fit_viewport_exact_16_9() -> None:
    scale, off_x, off_y = fit_viewport(1920, 1080)
    assert scale == 1.0
    assert (off_x, off_y) == (0, 0)


def test_fit_viewport_letterbox_4_3() -> None:
    scale, off_x, off_y = fit_viewport(1600, 1200)
    assert scale == pytest.approx(1600 / 1920)
    assert off_x == 0
    assert off_y == pytest.approx(round((1200 - 900) / 2))


def test_canonical_to_client_scaling() -> None:
    # finestra reale osservata: 2452x1379 (16:9)
    assert canonical_to_client((0, 0), 2452, 1379) == (0, 0)
    x, y = canonical_to_client((1920, 1080), 2452, 1379)
    assert x == pytest.approx(2452, abs=1)
    assert y == pytest.approx(1379, abs=1)
    # centro
    cx, cy = canonical_to_client((960, 540), 1920, 1080)
    assert (cx, cy) == (960, 540)


def test_rect_contains() -> None:
    rect = Rect(10, 20, 100, 50)
    assert rect.contains(GamePoint(10, 20))
    assert rect.contains(GamePoint(109, 69))
    assert not rect.contains(GamePoint(110, 70))
    assert not rect.contains(GamePoint(9, 20))
