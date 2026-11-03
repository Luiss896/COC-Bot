"""Hotkey globale (``RegisterHotKey``) senza rubare il focus.

Usata dalla GUI per start/stop del bot (`Ctrl+Alt+L`) e kill switch (`F12`).
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes as wt

from cocbot.capture import win32

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
VK_F12 = 0x7B
VK_ESCAPE = 0x1B

_MOD_NAMES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}
_SPECIAL_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "tab": 0x09,
}

_user32 = win32.user32
_kernel32 = win32.kernel32
_MSG = wt.MSG

_user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
_user32.RegisterHotKey.restype = wt.BOOL
_user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wt.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wt.HWND, wt.UINT, wt.UINT]
_user32.GetMessageW.restype = wt.BOOL
_user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.PostThreadMessageW.restype = wt.BOOL


def parse_hotkey(text: str) -> tuple[int, int]:
    """Converte ``"ctrl+alt+l"`` in (modificatori, virtual-key).

    Supporta ctrl/alt/shift/win, lettere, cifre, F1-F24 e alcuni tasti speciali.
    """
    parts = [part.strip().lower() for part in text.split("+") if part.strip()]
    if len(parts) < 1:
        raise ValueError(f"hotkey non valida: {text!r}")
    mods = 0
    for part in parts[:-1]:
        if part not in _MOD_NAMES:
            raise ValueError(f"modificatore non valido: {part!r}")
        mods |= _MOD_NAMES[part]
    key = parts[-1]
    if len(key) == 1 and key.isalpha():
        vk = ord(key.upper())
    elif len(key) == 1 and key.isdigit():
        vk = ord(key)
    elif key in _SPECIAL_KEYS:
        vk = _SPECIAL_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError(f"tasto non valido: {key!r}")
    return mods, vk


class GlobalHotkey:
    """Registra hotkey globali in un thread dedicato; gli eventi finiscono in una coda."""

    def __init__(self, bindings: dict[int, tuple[int, int]]) -> None:
        self.bindings = dict(bindings)
        self.events: queue.Queue[int] = queue.Queue()
        self.errors: list[str] = []
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._worker, name="cocbot-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self._thread.is_alive()

    def _worker(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        for hotkey_id, (mods, vk) in self.bindings.items():
            if not _user32.RegisterHotKey(None, hotkey_id, mods, vk):
                self.errors.append(f"hotkey {hotkey_id} (mods={mods}, vk=0x{vk:X}) non registrata: forse in uso")
        self._ready.set()
        msg = _MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                self.events.put(int(msg.wParam))
        for hotkey_id in self.bindings:
            _user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(2.0)
            self._thread = None
