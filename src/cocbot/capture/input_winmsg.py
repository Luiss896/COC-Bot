"""Input NON invasivo per il consumer GPGPC: messaggi Win32 alla finestra di gioco.

A differenza di ``SendInputSink``:
- **non forza il focus** e **non muove il cursore**: l'utente puo' usare il PC mentre il bot gioca;
- i click vengono accodati alla finestra del gioco (``PostMessage``), che su GPGPC/crosvm li
  interpreta come tap anche quando la finestra non e' in primo piano (verificato a runtime).

Limiti noti:
- la finestra non deve essere minimizzata (col minimizzato i messaggi non arrivano al contenuto);
- alcune app ignorano i messaggi sintetici: il backend va validato per ogni cambio di gioco/versione;
- ``key()`` e' best-effort (il gioco puo' ignorare i tasti inviati come messaggi).
"""
from __future__ import annotations

import random
import time

from cocbot.capture import win32
from cocbot.capture.window import GameWindow, canonical_to_client
from cocbot.core.types import GamePoint


class WinMsgSink:
    """InputSink per il backend finestra *senza interferenza* (messaggi Win32)."""

    requires_foreground = False

    def __init__(
        self,
        window: GameWindow,
        *,
        jitter_ms: tuple[int, int] = (60, 220),
        forbidden_zones: tuple = (),
    ) -> None:
        self.window = window
        self.jitter_ms = (max(0, jitter_ms[0]), max(jitter_ms[0], jitter_ms[1]))
        self.forbidden_zones = forbidden_zones

    # ------------------------------------------------------------------ focus
    def focus_game(self) -> bool:
        """Con questo backend il focus NON serve: verifica solo se il gioco e' in foreground."""
        return self.window.is_foreground

    # ------------------------------------------------------------------ click
    def _check_forbidden(self, point: GamePoint) -> None:
        for zone in self.forbidden_zones:
            if zone.contains(point):
                raise PermissionError(f"tap in area proibita (GemGuard): {point}")

    def _jitter_sleep(self) -> None:
        low, high = self.jitter_ms
        if high > 0:
            time.sleep(random.randint(low, high) / 1000.0)

    def tap_canonical(self, point: GamePoint, *, jitter: bool = True) -> None:
        self._check_forbidden(point)
        client_x, client_y = canonical_to_client(
            (point.x, point.y), self.window.client_width, self.window.client_height
        )
        self.tap_pixels(client_x, client_y, jitter=jitter)

    def tap_pixels(self, x: int, y: int, *, jitter: bool = True) -> None:
        if not win32.is_window(self.window.hwnd):
            raise RuntimeError("finestra di gioco non piu' valida (chiusa/ricreata)")
        if jitter:
            time.sleep(random.randint(0, 60) / 1000.0)
        ok = win32.post_mouse_click(self.window.hwnd, int(x), int(y))
        if not ok:
            raise RuntimeError("PostMessage del click rifiutato (finestra non valida)")
        if jitter:
            self._jitter_sleep()

    def key(self, vk: int) -> None:
        if not win32.post_key(self.window.hwnd, int(vk)):
            raise RuntimeError("PostMessage del tasto rifiutato")

    def close(self) -> None:  # nessuna risorsa da liberare
        return None
