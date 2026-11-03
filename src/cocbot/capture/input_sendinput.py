"""Input consumer GPGPC: SendInput (mouse) + focus forzato.

Vincoli:
- l'input va alla finestra in foreground: si forza il focus prima di ogni tap;
- non si clicca mai in aree proibite (GemGuard), se il chiamante le fornisce;
- jitter e tempi casuali per non avere pattern perfettamente regolari (NON garanzia anti-ban).
"""
from __future__ import annotations

import random
import time

from cocbot.capture import win32
from cocbot.capture.window import GameWindow
from cocbot.core.types import GamePoint


class SendInputSink:
    """InputSink per il backend finestra (consumer GPGPC)."""

    def __init__(
        self,
        window: GameWindow,
        *,
        jitter_ms: tuple[int, int] = (60, 220),
        restore_cursor: bool = True,
        forbidden_zones: tuple = (),
    ) -> None:
        self.window = window
        self.jitter_ms = (max(0, jitter_ms[0]), max(jitter_ms[0], jitter_ms[1]))
        self.restore_cursor = restore_cursor
        self.forbidden_zones = forbidden_zones

    # ------------------------------------------------------------------ focus
    def focus_game(self) -> bool:
        if not self.window.focus():
            return False
        return self.window.is_foreground

    def _ensure_focus(self) -> None:
        if self.window.is_foreground:
            return
        if not self.focus_game():
            raise RuntimeError("impossibile portare in primo piano la finestra di gioco (focus negato)")

    # ------------------------------------------------------------------ click
    def _check_forbidden(self, point: GamePoint) -> None:
        for zone in self.forbidden_zones:
            if zone.contains(point):
                raise PermissionError(f"tap in area proibita (GemGuard): {point}")

    def tap_canonical(self, point: GamePoint, *, jitter: bool = True) -> None:
        self._check_forbidden(point)
        self._ensure_focus()
        screen_x, screen_y = self.window.canonical_to_screen((point.x, point.y))
        self._click_screen(screen_x, screen_y, jitter=jitter)

    def tap_pixels(self, x: int, y: int) -> None:
        """Click in pixel del client (utile per launcher/store, non per la UI di gioco)."""
        self._ensure_focus()
        screen_x, screen_y = self.window.pixels_to_screen(x, y)
        self._click_screen(screen_x, screen_y, jitter=False)

    def _click_screen(self, screen_x: int, screen_y: int, *, jitter: bool) -> None:
        previous = win32.cursor_pos() if self.restore_cursor else None
        if jitter:
            time.sleep(self._rand_ms(0, 60) / 1000.0)
        win32.move_cursor(screen_x, screen_y)
        time.sleep(0.02)
        win32.mouse_down()
        hold_ms = self._rand_ms(25, 80) if jitter else 40
        time.sleep(hold_ms / 1000.0)
        win32.mouse_up()
        if jitter:
            time.sleep(self._rand_ms(*self.jitter_ms) / 1000.0)
        if previous is not None:
            win32.move_cursor(*previous)

    def key(self, vk: int) -> None:
        self._ensure_focus()
        win32.key_tap(vk)

    def _rand_ms(self, low: int, high: int) -> int:
        return random.randint(low, max(low, high))

    def close(self) -> None:  # interfaccia Device; nessuna risorsa da liberare
        return None
