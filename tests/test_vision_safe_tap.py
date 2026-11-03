"""Test euristiche vision: rilevamento home e scelta di un punto tap sicuro (erba)."""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from cocbot.vision.safe_tap import find_safe_tap_point, looks_like_home, panel_likely_open

WIDTH, HEIGHT = 1733, 975


def make_home_frame() -> np.ndarray:
    image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    image[:, :] = (60, 160, 80)  # BGR: erba (H_OpenCV~54, S~159, V~160)
    # pulsanti gialli in basso (Battle a sx, Build a dx) -> H_OpenCV~23, S=255, V=255
    image[HEIGHT - 130 : HEIGHT - 40, 20:190] = (0, 200, 255)
    image[HEIGHT - 130 : HEIGHT - 40, WIDTH - 210 : WIDTH - 20] = (0, 200, 255)
    return image


def test_looks_like_home_true() -> None:
    assert looks_like_home(make_home_frame()) is True


def test_looks_like_home_false_on_dark() -> None:
    assert looks_like_home(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)) is False


def test_safe_tap_point_is_in_canonical_range() -> None:
    point = find_safe_tap_point(make_home_frame(), rng=random.Random(1))
    assert point is not None
    assert 0 <= point.x < 1920
    assert 0 <= point.y < 1080
    # il punto deve stare lontano dai margini UI
    assert 100 < point.x < 1920 - 150


def test_safe_tap_point_none_without_grass() -> None:
    assert find_safe_tap_point(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)) is None


def test_safe_tap_point_fullscreen_scaled() -> None:
    # fullscreen 2452x1379: margini/aree devono scalare rispetto al riferimento 1733x975
    fw, fh = 2452, 1379
    image = np.zeros((fh, fw, 3), dtype=np.uint8)
    image[:, :] = (60, 160, 80)
    image[fh - round(130 * fh / HEIGHT) : fh - round(40 * fh / HEIGHT), 20 : round(190 * fw / WIDTH)] = (0, 200, 255)
    image[fh - round(130 * fh / HEIGHT) : fh - round(40 * fh / HEIGHT), fw - round(210 * fw / WIDTH) : fw - 20] = (
        0,
        200,
        255,
    )
    assert looks_like_home(image) is True
    point = find_safe_tap_point(image, rng=random.Random(2))
    assert point is not None
    # in fullscreen il punto canonico deve stare nei margini scalati (non sotto la UI in basso)
    assert 0 <= point.x < 1920
    assert 0 <= point.y < 1080
    assert point.y < 1080 - round(175 * fh / HEIGHT) + 5


def test_panel_detection_synthetic() -> None:
    home = make_home_frame()
    assert panel_likely_open(home) is False
    with_panel = home.copy()
    with_panel[750:870, 700:1010] = (60, 60, 60)  # pannello grigio scuro in basso-centro
    assert panel_likely_open(with_panel) is True


def test_real_wgc_frame_heuristics() -> None:
    frame_path = Path(__file__).resolve().parents[1] / "out" / "captures" / "wgc-cli" / "frame-0003.png"
    if not frame_path.is_file():
        pytest.skip("frame di test non disponibile (out/captures/wgc-cli)")
    import cv2

    image = cv2.imread(str(frame_path))
    assert image is not None
    assert looks_like_home(image) is True
    point = find_safe_tap_point(image, rng=random.Random(3))
    assert point is not None
