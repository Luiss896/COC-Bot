"""Test delle primitive UI e del classificatore stati su frame sintetici (nessun gioco)."""
from __future__ import annotations

import cv2
import numpy as np

from cocbot.core.types import ScreenState
from cocbot.vision import states, ui

WIDTH, HEIGHT = 1733, 975
GRASS_BGR = (40, 170, 60)  # verde erba (H~64 in OpenCV, dentro la maschera grass)
DARK_PANEL_BGR = (55, 90, 125)
YELLOW_BGR = (30, 220, 240)
RED_BGR = (30, 30, 220)


def _noisy(fill: tuple[int, int, int], *, noise: int = 12) -> np.ndarray:
    base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.int16)
    base[:, :] = fill
    rng = np.random.default_rng(42)
    base += rng.integers(-noise, noise + 1, size=base.shape, dtype=np.int16)
    return np.clip(base, 0, 255).astype(np.uint8)


def _rect(image: np.ndarray, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
    image[y : y + h, x : x + w] = color


def _scene_home() -> np.ndarray:
    image = _noisy(GRASS_BGR)
    _rect(image, 20, 816, 147, 138, YELLOW_BGR)  # Battle
    _rect(image, 1565, 816, 147, 138, YELLOW_BGR)  # Build
    return image


def _scene_build_menu() -> np.ndarray:
    image = _scene_home()
    panel_x = int(WIDTH * 0.735)
    _rect(image, panel_x, 0, WIDTH - panel_x, HEIGHT, DARK_PANEL_BGR)
    for y in range(120, HEIGHT - 80, 78):  # righe/separatori per la texture del pannello
        _rect(image, panel_x + 10, y, WIDTH - panel_x - 20, 3, (45, 70, 100))
    cv2.circle(image, (int(WIDTH * 0.983), int(HEIGHT * 0.031)), 22, RED_BGR, -1)  # X menu
    return image


def _scene_dialog() -> np.ndarray:
    image = _scene_build_menu()
    _rect(image, int(WIDTH * 0.09), int(HEIGHT * 0.045), int(WIDTH * 0.72), int(HEIGHT * 0.68), (150, 150, 150))
    cv2.circle(image, (int(WIDTH * 0.883), int(HEIGHT * 0.077)), 26, RED_BGR, -1)  # X dialogo
    return image


def _scene_placement() -> np.ndarray:
    image = _scene_home()
    x, y = int(WIDTH * 0.469), int(HEIGHT * 0.286)
    cv2.circle(image, (x, y), 36, RED_BGR, -1)  # X piazzamento (~72 px come il reale)
    cv2.circle(image, (x + int(WIDTH * 0.067), y), 30, (235, 235, 235), -1)  # spunta chiara grande
    return image


def _scene_home_with_red_decoration() -> np.ndarray:
    """Home con una decorazione rossa dove starebbe la X: NON deve sembrare piazzamento."""
    image = _scene_home()
    cv2.circle(image, (int(WIDTH * 0.469), int(HEIGHT * 0.286)), 36, RED_BGR, -1)
    return image


def _scene_inactivity_modal() -> np.ndarray:
    image = _scene_home()
    # modal scuro centrale
    _rect(image, int(WIDTH * 0.28), int(HEIGHT * 0.40), int(WIDTH * 0.44), int(HEIGHT * 0.20), (32, 30, 28))
    # testo azzurro "RELOAD GAME" in basso a sinistra del modal (H~105, S~170, V~240)
    blue = (240, 160, 80)
    cv2.putText(image, "RELOAD GAME", (int(WIDTH * 0.30), int(HEIGHT * 0.565)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, blue, 3)
    return image


def test_classify_home_synthetic() -> None:
    assert states.classify(_scene_home()) is ScreenState.HOME


def test_red_decoration_is_not_placement() -> None:
    assert states.classify(_scene_home_with_red_decoration()) is ScreenState.HOME


def test_classify_inactivity_modal_synthetic() -> None:
    image = _scene_inactivity_modal()
    assert states.classify(image) is ScreenState.NETWORK_ERROR
    point = ui.find_inactivity_modal(image)
    assert point is not None
    # il punto da tappare e' sopra il testo RELOAD GAME
    assert 0.27 * WIDTH < point[0] < 0.44 * WIDTH
    assert 0.49 * HEIGHT < point[1] < 0.61 * HEIGHT


def test_classify_build_menu_synthetic() -> None:
    image = _scene_build_menu()
    assert states.classify(image) is ScreenState.BUILD_MENU
    panel = ui.find_build_panel(image)
    assert panel is not None
    assert 0.70 <= panel.x / WIDTH <= 0.78
    close = ui.find_menu_close(image)
    assert close is not None


def test_classify_dialog_synthetic() -> None:
    image = _scene_dialog()
    assert states.classify(image) is ScreenState.UPGRADE_CONFIRM
    close = ui.find_dialog_close(image)
    assert close is not None
    # la X del menu non deve essere confusa con quella del dialogo
    assert ui.find_menu_close(image) is None or ui.find_menu_close(image)[0] > 0.95 * WIDTH


def test_classify_placement_synthetic() -> None:
    image = _scene_placement()
    assert states.classify(image) is ScreenState.PLACEMENT
    point = ui.find_placement_exit(image)
    assert point is not None
    assert 0.40 * WIDTH < point[0] < 0.55 * WIDTH


def test_unknown_state_on_blank_frame() -> None:
    blank = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    assert states.classify(blank) is ScreenState.UNKNOWN


def test_hud_regions_inside_frame() -> None:
    image = _scene_home()
    for region in (ui.resources_region(image), ui.builders_region(image)):
        assert region.x >= 0 and region.y >= 0
        assert region.right <= WIDTH and region.bottom <= HEIGHT


def test_find_build_panel_none_on_home() -> None:
    assert ui.find_build_panel(_scene_home()) is None
