"""Test delle primitive vision contro il dataset locale (skip se il dataset non c'e').

Il dataset contiene screenshot dell'account dell'utente: e' gitignored e resta solo locale.
Questi test servono a evitare regressioni nella lettura OCR del menu Build reale; in CI
(o su un checkout senza dataset) vengono saltati.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from cocbot.capture import win32
from cocbot.capture.window import GameWindow
from cocbot.config.models import Config

DATASET = Path(__file__).resolve().parents[1] / "dataset" / "build-win-20261103"
FULLSCREEN_DATASET = Path(__file__).resolve().parents[1] / "dataset" / "raw-20261103-1408"

pytestmark = pytest.mark.skipif(
    not (DATASET / "build-menu-top.png").is_file(),
    reason="dataset locale assente (screenshot gitignored): test saltati",
)


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(DATASET / name))
    assert image is not None, f"frame assente: {name}"
    return image


def _rows_by_name(image: np.ndarray) -> dict[str, object]:
    from cocbot.vision import build_menu

    rows = build_menu.read_rows(image)
    return {row.name: row for row in rows}


def test_read_rows_windowed_top() -> None:
    rows = _rows_by_name(_load("build-menu-top.png"))
    assert len(rows) >= 8

    king = rows["barbarian king"]
    assert king.level == 53
    assert king.cost == 44_000
    assert king.currency == "dark"
    assert king.time_s == 64_800

    castle = rows["clan castle"]
    assert castle.level == 8
    assert castle.cost == 2_500_000
    assert castle.currency == "elixir"

    collector = rows["elixir collector"]
    assert collector.count == 7
    assert collector.level == 15
    assert collector.cost == 600_000
    assert collector.currency == "gold"

    workshop = rows["workshop"]
    assert workshop.is_new
    assert workshop.cost == 1_200_000
    assert workshop.currency == "elixir"


def test_read_rows_windowed_bottom() -> None:
    rows = _rows_by_name(_load("build-menu-bottom.png"))
    tower = rows["archer tower"]
    assert tower.count == 8
    assert tower.level == 16
    assert tower.cost == 800_000
    assert tower.currency == "gold"
    # righe con sottotitolo: il nome resta quello dell'edificio
    assert not any("damage" in name for name in rows)


def test_read_rows_fullscreen_proportional() -> None:
    frame = cv2.imread(str(FULLSCREEN_DATASET / "02_build_menu.png"))
    if frame is None:
        pytest.skip("frame fullscreen del dataset precedente assente")
    from cocbot.vision import build_menu

    rows = build_menu.read_rows(frame)
    by_name = {row.name: row for row in rows}
    assert len(rows) >= 8
    assert by_name["barbarian king"].level == 53
    assert by_name["barbarian king"].cost == 44_000
    assert by_name["elixir collector"].count == 7


def test_read_dialog_upgrade_confirm() -> None:
    from cocbot.vision import build_menu

    dialog = build_menu.read_dialog(_load("upgrade-info-clan-castle.png"))
    assert dialog.name == "clan castle"
    assert dialog.target_level == 8
    assert dialog.cost == 2_500_000
    assert dialog.time_s == 86_400
    assert dialog.confirm_rect is not None
    assert dialog.close_point is not None
    assert 0.85 * 1733 < dialog.close_point[0] < 0.92 * 1733


def test_catalog_row_level_is_target_level() -> None:
    """La riga del catalogo mostra il livello di DESTINAZIONE, non quello attuale.

    Il dialogo di conferma dice "Upgrade <X> to Level <level>?" con lo stesso numero della
    riga (verificato su frame reali: clan castle 8/8, gold mine 15/15). L'executor deve
    quindi confrontare ``dialog.target_level`` con ``row.level``, non con ``row.level + 1``.
    """
    from cocbot.vision import build_menu

    castle = _rows_by_name(_load("build-menu-top.png"))["clan castle"]
    castle_dialog = build_menu.read_dialog(_load("upgrade-info-clan-castle.png"))
    assert castle.level == castle_dialog.target_level == 8
    assert castle.cost == castle_dialog.cost

    mine = _rows_by_name(_load("build-menu-mid.png"))["gold mine"]
    mine_dialog = build_menu.read_dialog(_load("upgrade-info-gold-mine.png"))
    assert mine.level == mine_dialog.target_level == 15
    assert mine.cost == mine_dialog.cost


def test_network_error_modal_real_frame() -> None:
    """Il modal di disconnessione reale e' riconosciuto e il pulsante RELOAD GAME localizzato."""
    from cocbot.core.types import ScreenState
    from cocbot.vision import states, ui

    frame = _load("network-error-inactivity.png")
    assert states.classify(frame) is ScreenState.NETWORK_ERROR
    point = ui.find_inactivity_modal(frame)
    assert point is not None
    h, w = frame.shape[:2]
    assert 0.20 < point[0] / w < 0.60
    assert 0.40 < point[1] / h < 0.75


def test_read_wall_panel() -> None:
    from cocbot.vision import build_menu

    info = build_menu.read_wall_panel(_load("wall-upgrader-panel.png"))
    assert info.ok
    assert info.selected_level == 12
    assert info.select_row_point is not None
    buttons = {(button.cost, button.currency) for button in info.buttons}
    assert (750_000, "gold") in buttons
    assert (750_000, "elixir") in buttons
    for button in info.buttons:
        assert 0 < button.point[0] < 1733
        assert 0 < button.point[1] < 975


def test_classify_real_frames() -> None:
    from cocbot.core.types import ScreenState
    from cocbot.vision import states

    assert states.classify(_load("home-after-panels.png")) is ScreenState.HOME
    assert states.classify(_load("build-menu-top.png")) is ScreenState.BUILD_MENU
    assert states.classify(_load("upgrade-info-clan-castle.png")) is ScreenState.UPGRADE_CONFIRM
    assert states.classify(_load("new-building-workshop.png")) is ScreenState.PLACEMENT


class _DummySource:
    """Source fittizia: questi test leggono solo frame salvati, non catturano."""

    def grab(self):  # pragma: no cover - mai usata
        raise AssertionError("read_hud non deve catturare: riceve il frame come argomento")

    def close(self) -> None:
        return None


def test_read_hud_from_home_frame() -> None:
    from cocbot.app.upgrade_engine import HudRead, UpgradeEngine

    info = win32.WindowInfo(
        hwnd=1,
        pid=1,
        process="crosvm.exe",
        title="Clash of Clans - test",
        class_name="CROSVM_1",
        visible=True,
        minimized=False,
        window_rect=(0, 0, 1733, 975),
        client_size=(1733, 975),
        dpi=120,
    )
    window = GameWindow(info)
    engine = UpgradeEngine(window, Config(), source=_DummySource(), sink=object())  # type: ignore[arg-type]
    try:
        hud = engine.read_hud(_load("home-after-panels.png"))
    finally:
        engine.close()
    assert isinstance(hud, HudRead)
    assert hud.gold == 7_089_459
    assert hud.elixir == 7_500_945
    assert hud.dark == 195_103
    assert hud.gems == 1_925
    assert (hud.builders_available, hud.builders_total) == (5, 5)

