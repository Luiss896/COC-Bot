"""Test dei nuovi moduli di cattura/input del backend consumer non invasivo."""
from __future__ import annotations

import pytest

from cocbot.capture import win32
from cocbot.capture.input_winmsg import WinMsgSink
from cocbot.capture.screen_wgc import client_crop_box
from cocbot.capture.window import GameWindow
from cocbot.core.types import GamePoint, Rect


def _game_window(client_size: tuple[int, int] = (1733, 975)) -> GameWindow:
    info = win32.WindowInfo(
        hwnd=0x60A04,
        pid=27680,
        process="crosvm.exe",
        title="Clash of Clans - <account>",
        class_name="CROSVM_1",
        visible=True,
        minimized=False,
        window_rect=(324, 167, 2057, 1156),
        client_size=client_size,
        dpi=120,
    )
    return GameWindow(info)


def test_client_crop_box_windowed() -> None:
    # misure reali misurate sul PC: frame WGC 1735x1014, client 1733x975
    assert client_crop_box((1735, 1014), (1733, 975)) == (1, 39, 1733, 975)


def test_client_crop_box_fullscreen_borderless() -> None:
    # in fullscreen borderless frame e client coincidono
    assert client_crop_box((2560, 1440), (2560, 1440)) == (0, 0, 2560, 1440)


def test_client_crop_box_invalid() -> None:
    with pytest.raises(ValueError):
        client_crop_box((100, 100), (200, 50))


def test_winmsg_maps_canonical_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _game_window()
    calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(win32, "is_window", lambda hwnd: True)
    monkeypatch.setattr(
        win32,
        "post_mouse_click",
        lambda hwnd, x, y: calls.append((hwnd, x, y)) or True,
    )
    sink = WinMsgSink(window, jitter_ms=(0, 0))
    sink.tap_canonical(GamePoint(960, 540))
    assert calls == [(0x60A04, 866, 487)]


def test_winmsg_respects_forbidden_zones(monkeypatch: pytest.MonkeyPatch) -> None:
    window = _game_window()
    monkeypatch.setattr(win32, "is_window", lambda hwnd: True)
    sink = WinMsgSink(window, jitter_ms=(0, 0), forbidden_zones=(Rect(900, 500, 200, 100),))
    with pytest.raises(PermissionError):
        sink.tap_canonical(GamePoint(960, 540))


def test_winmsg_requires_foreground_false() -> None:
    assert WinMsgSink.requires_foreground is False
