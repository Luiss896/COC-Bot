from __future__ import annotations

from typing import Protocol, runtime_checkable

from cocbot.core.types import CaptureHealth, Frame, GamePoint, Rect, Viewport


@runtime_checkable
class ScreenSource(Protocol):
    """Sorgente di frame: WGC/DXGI (consumer) o ADB (Developer Emulator)."""

    def grab(self) -> Frame: ...

    def viewport(self) -> Viewport: ...

    def health(self) -> CaptureHealth: ...

    def close(self) -> None: ...


@runtime_checkable
class InputSink(Protocol):
    """Destinazione dell'input; coordinate sempre canoniche per i metodi *canonical*."""

    def tap_canonical(self, point: GamePoint, *, jitter: bool = True) -> None: ...

    def tap_pixels(self, x: int, y: int) -> None: ...

    def key(self, vk: int) -> None: ...

    def focus_game(self) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class Device(Protocol):
    """Combinazione finestra/emulatore + cattura + input."""

    source: ScreenSource
    sink: InputSink
    screen: ScreenSource
    input: InputSink

    def attach(self) -> bool: ...

    def close(self) -> None: ...


def assert_tap_allowed(point: GamePoint, forbidden: tuple[Rect, ...]) -> None:
    """GemGuard G1: rifiuta i tap nelle aree proibite (gemme/shop/offerte)."""
    for zone in forbidden:
        if zone.contains(point):
            raise PermissionError(f"tap in area proibita (GemGuard): {point}")
