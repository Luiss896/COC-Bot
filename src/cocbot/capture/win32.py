"""Wrapper ctypes minimali per Win32 (finestre, DPI, cursore, input).

Nessuna dipendenza esterna: funziona con la sola stdlib. Tutte le coordinate sono in pixel reali
(processo DPI-aware: chiamare ``set_dpi_awareness()`` all'avvio).
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


HWND = wt.HWND
DWORD = wt.DWORD
BOOL = wt.BOOL

EnumWindowsProc = ctypes.WINFUNCTYPE(BOOL, HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.EnumWindows.restype = BOOL
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindowVisible.restype = BOOL
user32.IsIconic.argtypes = [HWND]
user32.IsIconic.restype = BOOL
user32.GetWindowTextW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = BOOL
user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = BOOL
user32.ClientToScreen.argtypes = [HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = HWND
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = BOOL
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.ShowWindow.restype = BOOL
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = BOOL
user32.mouse_event.argtypes = [DWORD, DWORD, DWORD, DWORD, ctypes.c_size_t]
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, DWORD, ctypes.c_size_t]
user32.PostMessageW.argtypes = [HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = BOOL
user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
user32.AttachThreadInput.restype = BOOL
user32.BringWindowToTop.argtypes = [HWND]
user32.BringWindowToTop.restype = BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = DWORD

_get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
if _get_dpi_for_window is not None:
    _get_dpi_for_window.argtypes = [HWND]
    _get_dpi_for_window.restype = wt.UINT

kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, DWORD, wt.LPWSTR, ctypes.POINTER(DWORD)]
kernel32.QueryFullProcessImageNameW.restype = BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = BOOL

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002

VK_F12 = 0x7B
VK_ESCAPE = 0x1B


def set_dpi_awareness() -> None:
    """Abilita DPI awareness Per-Monitor V2 (fallback: system aware). Idempotente."""
    if hasattr(user32, "SetProcessDpiAwarenessContext"):
        try:
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = BOOL
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except OSError:
            pass
    with contextlib.suppress(OSError):  # pragma: no cover - fallback sistemi datati
        user32.SetProcessDPIAware()


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "?"
    try:
        size = DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return "?"
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    pid: int
    process: str
    title: str
    class_name: str
    visible: bool
    minimized: bool
    window_rect: tuple[int, int, int, int]  # left, top, right, bottom
    client_size: tuple[int, int]  # width, height
    dpi: int

    @property
    def client_width(self) -> int:
        return self.client_size[0]

    @property
    def client_height(self) -> int:
        return self.client_size[1]

    @property
    def aspect(self) -> float:
        return self.client_size[0] / max(1, self.client_size[1])

    @property
    def area(self) -> int:
        return self.client_size[0] * self.client_size[1]


def window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _client_size(hwnd: int) -> tuple[int, int]:
    rect = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def client_origin(hwnd: int) -> tuple[int, int]:
    """Origine (screen) dell'area client della finestra."""
    point = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def get_dpi(hwnd: int) -> int:
    if _get_dpi_for_window is None:  # pragma: no cover
        return 96
    return int(_get_dpi_for_window(hwnd)) or 96


def list_windows(visible_only: bool = True) -> list[WindowInfo]:
    """Elenca le finestre visibili (top-level) con metadati utili."""
    found: list[WindowInfo] = []
    names: dict[int, str] = {}

    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if visible_only and not user32.IsWindowVisible(hwnd):
                return True
            pid = DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == 0:
                return True
            if pid.value not in names:
                names[pid.value] = _process_name(pid.value)
            left, top, right, bottom = _window_rect(hwnd)
            if right - left <= 0 or bottom - top <= 0:
                return True
            found.append(
                WindowInfo(
                    hwnd=int(hwnd),
                    pid=int(pid.value),
                    process=names[pid.value],
                    title=window_text(hwnd),
                    class_name=window_class(hwnd),
                    visible=bool(user32.IsWindowVisible(hwnd)),
                    minimized=bool(user32.IsIconic(hwnd)),
                    window_rect=(left, top, right, bottom),
                    client_size=_client_size(hwnd),
                    dpi=get_dpi(hwnd),
                )
            )
        except OSError:  # pragma: no cover
            return True
        return True

    user32.EnumWindows(EnumWindowsProc(_callback), 0)
    return found


def foreground_window() -> int:
    return int(user32.GetForegroundWindow())


def is_foreground(hwnd: int) -> bool:
    return foreground_window() == hwnd


def is_window(hwnd: int) -> bool:
    """True se l'HWND identifica ancora una finestra esistente."""
    return bool(user32.IsWindow(HWND(hwnd)))


def focus_window(hwnd: int, restore_sleep_s: float = 0.15) -> bool:
    """Riporta la finestra in primo piano (ripristinandola se minimizzata).

    Windows blocca il ``SetForegroundWindow`` da processi non in foreground: si usa
    ``AttachThreadInput`` al thread della finestra attualmente attiva per aggirare il lock
    (tecnica standard, non invasiva). Se fallisce, il bot deve mettersi in pausa, non cliccare.
    """
    foreground = user32.GetForegroundWindow()
    foreground_pid = DWORD(0)
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid)) if foreground else 0
    )
    current_thread = kernel32.GetCurrentThreadId()
    attached = False
    if foreground_thread and foreground_thread != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    time.sleep(restore_sleep_s)
    return is_foreground(hwnd)


def close_window(hwnd: int) -> bool:
    """Invia WM_CLOSE. Non usare durante una battaglia (spam attack prevention)."""
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def cursor_pos() -> tuple[int, int]:
    point = POINT(0, 0)
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def move_cursor(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def mouse_down() -> None:
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)


def mouse_up() -> None:
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def click_at(x: int, y: int, hold_ms: int = 40) -> None:
    """Click sinistro in coordinate screen assolute (pixel reali)."""
    move_cursor(x, y)
    time.sleep(0.02)
    mouse_down()
    time.sleep(hold_ms / 1000.0)
    mouse_up()


def key_tap(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------------------
# Input NON invasivo: messaggi Win32 alla finestra (nessun focus, nessun cursore).
# Verificato su GPGPC consumer: la finestra crosvm del gioco accetta i messaggi anche
# se non e' in foreground. Usato dal backend ``winmsg``.
# ---------------------------------------------------------------------------
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001


def _make_lparam(x: int, y: int) -> int:
    """Impacchetta le coordinate client in un LPARAM (low word x, high word y)."""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def post_mouse_click(hwnd: int, client_x: int, client_y: int, hold_ms: int = 40) -> bool:
    """Click sinistro alla finestra via ``PostMessage`` (senza focus e senza muovere il cursore).

    Le coordinate sono relative all'area client della finestra. Ritorna False se il
    messaggio non e' stato accodato (finestra chiusa/non valida).
    """
    lp = _make_lparam(client_x, client_y)
    ok_move = bool(user32.PostMessageW(HWND(hwnd), WM_MOUSEMOVE, 0, lp))
    time.sleep(0.02)
    ok_down = bool(user32.PostMessageW(HWND(hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lp))
    time.sleep(hold_ms / 1000.0)
    ok_up = bool(user32.PostMessageW(HWND(hwnd), WM_LBUTTONUP, 0, lp))
    time.sleep(0.02)
    return ok_move and ok_down and ok_up


def post_mouse_drag(
    hwnd: int,
    client_x0: int,
    client_y0: int,
    client_x1: int,
    client_y1: int,
    *,
    steps: int = 10,
    hold_ms: int = 80,
) -> bool:
    """Drag sinistro via ``PostMessage`` (nessun focus, nessun cursore reale).

    Utile in gioco per pannare la camera: pressione, movimento a passi, rilascio.
    Ritorna False se un messaggio non e' stato accodato.
    """
    lp_start = _make_lparam(client_x0, client_y0)
    ok = bool(user32.PostMessageW(HWND(hwnd), WM_MOUSEMOVE, 0, lp_start))
    time.sleep(0.02)
    ok = bool(user32.PostMessageW(HWND(hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lp_start)) and ok
    time.sleep(hold_ms / 1000.0)
    lp_end = lp_start
    for index in range(1, steps + 1):
        x = client_x0 + (client_x1 - client_x0) * index // steps
        y = client_y0 + (client_y1 - client_y0) * index // steps
        lp_end = _make_lparam(x, y)
        ok = bool(user32.PostMessageW(HWND(hwnd), WM_MOUSEMOVE, MK_LBUTTON, lp_end)) and ok
        time.sleep(0.03)
    ok = bool(user32.PostMessageW(HWND(hwnd), WM_LBUTTONUP, 0, lp_end)) and ok
    time.sleep(0.02)
    return ok


def post_key(hwnd: int, vk: int) -> bool:
    """Invia un tasto alla finestra via ``PostMessage`` (non tutte le app lo accettano)."""
    ok_down = bool(user32.PostMessageW(HWND(hwnd), WM_KEYDOWN, vk, 0))
    time.sleep(0.03)
    ok_up = bool(user32.PostMessageW(HWND(hwnd), WM_KEYUP, vk, 0))
    return ok_down and ok_up


def is_minimized(hwnd: int) -> bool:
    """True se la finestra è minimizzata (WGC non cattura finestre minimizzate)."""
    return bool(user32.IsIconic(HWND(hwnd)))


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("PageFaultCount", DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_psapi.GetProcessMemoryInfo.argtypes = [
    wt.HANDLE,
    ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
    DWORD,
]
_psapi.GetProcessMemoryInfo.restype = BOOL
kernel32.GetCurrentProcess.restype = wt.HANDLE


def process_memory_mb() -> float:
    """Working set del processo corrente in MB (per misurare l'impatto del bot)."""
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    if not _psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return 0.0
    return counters.WorkingSetSize / (1024.0 * 1024.0)
