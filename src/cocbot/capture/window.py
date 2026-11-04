"""Scoperta della finestra di gioco GPGPC e conversione coordinate canoniche.

GPGPC consumer:
- client/launcher: processo ``client.exe``, finestra CEF "Google Play Games";
- gioco: processo ``crosvm.exe``, finestra "Clash of Clans - <account>" (16:9).

Il titolo contiene il nome account: viene sempre mascherato prima di log/presentazione.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from cocbot.capture import win32

GAME_PROCESS = "crosvm.exe"
GAME_TITLE_PREFIX = "Clash of Clans"
LAUNCHER_PROCESS = "client.exe"
LAUNCHER_TITLE = "Google Play Games"

CANONICAL_WIDTH = 1920
CANONICAL_HEIGHT = 1080


def masked_title(title: str) -> str:
    """Maschera il nome account nel titolo della finestra di gioco."""
    if title.startswith(GAME_TITLE_PREFIX):
        return f"{GAME_TITLE_PREFIX} - <account redatto>"
    return title


def is_game_window(info: win32.WindowInfo) -> bool:
    return info.process.lower() == GAME_PROCESS and info.title.startswith(GAME_TITLE_PREFIX)


def is_launcher_window(info: win32.WindowInfo) -> bool:
    return info.process.lower() == LAUNCHER_PROCESS and info.title == LAUNCHER_TITLE


def find_windows() -> list[win32.WindowInfo]:
    return [w for w in win32.list_windows(visible_only=True) if w.client_width > 0 and w.client_height > 0]


def find_game_windows() -> list[win32.WindowInfo]:
    return sorted((w for w in find_windows() if is_game_window(w)), key=lambda w: w.area, reverse=True)


def find_game_window(*, restore_minimized: bool = True) -> win32.WindowInfo | None:
    """Finestra del gioco se visibile; se e' **minimizzata** la ripristina (SW_RESTORE).

    GPGPC puo' minimizzare la finestra del gioco (es. per inattivita' del sistema): il processo
    resta vivo ma la finestra non ha area client, quindi ``find_windows`` non la vede. In quel
    caso la si ripristina automaticamente (comportamento voluto: i comandi CLI funzionano anche
    se l'utente/il sistema ha minimizzato il gioco).
    """
    windows = find_game_windows()
    if windows:
        return windows[0]
    if not restore_minimized:
        return None
    minimized = [
        w
        for w in win32.list_windows(visible_only=False)
        if is_game_window(w) and win32.is_minimized(w.hwnd)
    ]
    for candidate in minimized:
        win32.user32.ShowWindow(win32.HWND(candidate.hwnd), win32.SW_RESTORE)
        time.sleep(0.8)
        restored = find_game_windows()
        if restored:
            return restored[0]
    return None


def find_launcher_window() -> win32.WindowInfo | None:
    candidates = [w for w in find_windows() if is_launcher_window(w)]
    candidates.sort(key=lambda w: w.area, reverse=True)
    return candidates[0] if candidates else None


def wait_for_game_window(timeout_s: float = 120.0, poll_s: float = 2.0) -> win32.WindowInfo | None:
    """Attende che la finestra di gioco compaia (avvio partita manuale/da launcher)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        window = find_game_window()
        if window is not None:
            return window
        time.sleep(poll_s)
    return None


def fit_viewport(
    client_w: int,
    client_h: int,
    canonical_w: int = CANONICAL_WIDTH,
    canonical_h: int = CANONICAL_HEIGHT,
) -> tuple[float, int, int]:
    """Adatta il rettangolo canonico 16:9 dentro il client (letterbox).

    Returns:
        (scale, offset_x, offset_y): pixel = offset + canonical * scale.
    """
    scale = min(client_w / canonical_w, client_h / canonical_h)
    width = canonical_w * scale
    height = canonical_h * scale
    return scale, int(round((client_w - width) / 2.0)), int(round((client_h - height) / 2.0))


def canonical_to_client(point: tuple[int, int], client_w: int, client_h: int) -> tuple[int, int]:
    scale, off_x, off_y = fit_viewport(client_w, client_h)
    return off_x + int(round(point[0] * scale)), off_y + int(round(point[1] * scale))


@dataclass(frozen=True, slots=True)
class GameWindow:
    """Finestra di gioco + mapping coordinate canoniche -> screen."""

    info: win32.WindowInfo
    canonical_width: int = CANONICAL_WIDTH
    canonical_height: int = CANONICAL_HEIGHT

    @property
    def hwnd(self) -> int:
        return self.info.hwnd

    @property
    def client_width(self) -> int:
        return self.info.client_width

    @property
    def client_height(self) -> int:
        return self.info.client_height

    @property
    def dpi(self) -> int:
        return self.info.dpi

    @property
    def title_masked(self) -> str:
        return masked_title(self.info.title)

    @property
    def is_16_9(self) -> bool:
        return abs(self.client_width / max(1, self.client_height) - 16 / 9) <= 0.02

    @property
    def is_foreground(self) -> bool:
        return win32.is_foreground(self.hwnd)

    def client_origin(self) -> tuple[int, int]:
        return win32.client_origin(self.hwnd)

    def canonical_to_screen(self, point: tuple[int, int]) -> tuple[int, int]:
        cx, cy = canonical_to_client(point, self.client_width, self.client_height)
        ox, oy = self.client_origin()
        return ox + cx, oy + cy

    def pixels_to_screen(self, x: int, y: int) -> tuple[int, int]:
        ox, oy = self.client_origin()
        return ox + x, oy + y

    def focus(self) -> bool:
        return win32.focus_window(self.hwnd)

    def is_alive(self) -> bool:
        return self.info.hwnd in {w.hwnd for w in find_windows()}

    def refresh(self) -> GameWindow | None:
        info = find_game_window()
        return GameWindow(info, self.canonical_width, self.canonical_height) if info else None

    def __str__(self) -> str:
        return (
            f"GameWindow(hwnd=0x{self.hwnd:X}, client={self.client_width}x{self.client_height}, "
            f"dpi={self.dpi}, aspect={self.client_width / max(1, self.client_height):.4f}, "
            f"title='{self.title_masked}')"
        )
