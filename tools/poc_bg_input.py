"""POC input NON invasivo sulla finestra del gioco GPGPC.

Obiettivo: verificare se il gioco accetta click inviati come messaggi Win32 alla finestra
(``WM_MOUSEMOVE``/``WM_LBUTTONDOWN``/``WM_LBUTTONUP``) SENZA portare la finestra in foreground,
senza muovere il cursore e senza toccare mouse/tastiera dell'utente.

Solo un click, su un punto centrale del villaggio (apre un pannello informativo, non spende nulla).
Salva i frame prima/dopo per verifica e misura delta frame, foreground e posizione cursore.

Richiede integrita' media (WGC + messaggi cross-integrity) e ``windows-capture`` in ``<repo>/.deps``.
Uso:
    python tools/poc_bg_input.py
    python tools/poc_bg_input.py --dry-run
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPS_DIR = REPO_ROOT / ".deps"
if DEPS_DIR.is_dir() and str(DEPS_DIR) not in sys.path:
    sys.path.insert(0, str(DEPS_DIR))

# DPI awareness PRIMA di cv2/windows-capture (altrimenti misure logiche sbagliate).
from cocbot.capture import win32 as _win32  # noqa: E402

_win32.set_dpi_awareness()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from windows_capture import Frame, InternalCaptureControl, WindowsCapture  # noqa: E402

from cocbot.capture.window import GameWindow, canonical_to_client, find_game_window  # noqa: E402

USER32 = _win32.user32
HWND = ctypes.c_void_p

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001
VK_ESCAPE = 0x1B
SMTO_ABORTIFHUNG = 0x0002

USER32.SendMessageTimeoutW.argtypes = [
    HWND,
    ctypes.c_uint,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_size_t),
]
USER32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, ctypes.c_void_p)
USER32.EnumChildWindows.argtypes = [HWND, WNDENUMPROC, ctypes.c_void_p]
USER32.EnumChildWindows.restype = ctypes.c_bool


def _make_lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def grab_frame(hwnd: int, timeout_s: float = 4.0) -> np.ndarray | None:
    """Cattura un singolo frame BGR della finestra con WGC."""
    holder: dict[str, np.ndarray] = {}
    done = threading.Event()

    capture = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)

    @capture.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl) -> None:  # noqa: N802
        holder["image"] = frame.convert_to_bgr().frame_buffer.copy()
        done.set()
        control.stop()

    @capture.event
    def on_closed() -> None:  # noqa: N802
        done.set()

    try:
        control = capture.start_free_threaded()
        done.wait(timeout_s)
        if not control.is_finished():
            control.stop()
        control.wait()
    except Exception as exc:
        print(f"  [warn] cattura fallita: {exc!r}")
        return None
    return holder.get("image")


def frame_delta(before: np.ndarray | None, after: np.ndarray | None) -> dict:
    if before is None or after is None:
        return {"ok": False, "reason": "frame mancante"}
    if before.shape != after.shape:
        return {"ok": False, "reason": f"shape diversa {before.shape} vs {after.shape}"}
    a = before.astype(np.int16)
    b = after.astype(np.int16)
    diff = np.abs(a - b).mean(axis=2)
    return {
        "ok": True,
        "mean_abs_diff": float(diff.mean()),
        "frac_changed_25": float((diff > 25).mean()),
        "max_diff": int(diff.max()),
    }


def post_click(hwnd: int, x: int, y: int) -> None:
    lp = _make_lparam(x, y)
    USER32.PostMessageW(HWND(hwnd), WM_MOUSEMOVE, 0, lp)
    time.sleep(0.05)
    USER32.PostMessageW(HWND(hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.08)
    USER32.PostMessageW(HWND(hwnd), WM_LBUTTONUP, 0, lp)


def send_click(hwnd: int, x: int, y: int) -> None:
    """Variante sincrona con SendMessageTimeout (bloccante, con timeout)."""
    lp = _make_lparam(x, y)
    for msg, wparam in ((WM_MOUSEMOVE, 0), (WM_LBUTTONDOWN, MK_LBUTTON), (WM_LBUTTONUP, 0)):
        result = ctypes.c_size_t(0)
        USER32.SendMessageTimeoutW(HWND(hwnd), msg, wparam, lp, SMTO_ABORTIFHUNG, 500, ctypes.byref(result))


def post_escape(hwnd: int) -> None:
    USER32.PostMessageW(HWND(hwnd), WM_KEYDOWN, VK_ESCAPE, 0)
    time.sleep(0.05)
    USER32.PostMessageW(HWND(hwnd), WM_KEYUP, VK_ESCAPE, 0)


def child_hwnds(hwnd: int) -> list[int]:
    children: list[int] = []

    def _collect(h, _p) -> bool:
        children.append(int(h or 0))
        return True

    proc = WNDENUMPROC(_collect)
    USER32.EnumChildWindows(HWND(hwnd), proc, None)
    return children


def attempt(label: str, hwnd: int, target_client: tuple[int, int], out_dir: Path) -> bool:
    print(f"\n-- tentativo: {label} --")
    before = grab_frame(hwnd)
    fg_before = _win32.foreground_window()
    cursor_before = _win32.cursor_pos()
    print(f"   foreground prima: 0x{fg_before:X} | cursore prima: {cursor_before} | target client: {target_client}")
    if before is not None:
        cv2.imwrite(str(out_dir / f"{label.replace(' ', '_')}-before.png"), before)

    if label.startswith("post"):
        post_click(hwnd, *target_client)
    else:
        send_click(hwnd, *target_client)
    time.sleep(1.2)

    after = grab_frame(hwnd)
    if after is not None:
        cv2.imwrite(str(out_dir / f"{label.replace(' ', '_')}-after.png"), after)
    fg_after = _win32.foreground_window()
    cursor_after = _win32.cursor_pos()
    delta = frame_delta(before, after)
    print(f"   delta frame: {delta}")
    print(f"   foreground dopo: 0x{fg_after:X} | cursore dopo: {cursor_after}")
    print(f"   interferenza: focus cambiato={fg_before != fg_after} cursore mosso={cursor_before != cursor_after}")
    changed = bool(delta.get("ok")) and delta["mean_abs_diff"] > 0.5 and delta["frac_changed_25"] > 0.002
    print(f"   ESITO tentativo: {'REAZIONE RILEVATA' if changed else 'nessuna reazione'}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="POC input non invasivo (messaggi Win32) sulla finestra del gioco")
    parser.add_argument("--dry-run", action="store_true", help="stampa solo finestra/target, nessun click")
    parser.add_argument("--target", choices=["centro", "battle"], default="centro")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "out" / "captures" / "input")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    info = find_game_window()
    if info is None:
        print("Finestra di gioco non trovata: avviala manualmente da GPGPC.")
        return 1
    window = GameWindow(info)
    print(f"finestra: {window}")
    print(f"in foreground: {window.is_foreground} (False = test di non interferenza)")

    canonical = (960, 540) if args.target == "centro" else (127, 968)
    target_client = canonical_to_client(canonical, window.client_width, window.client_height)
    origin = window.client_origin()
    print(f"target canonico {canonical} -> client {target_client} (origin screen {origin})")

    if args.dry_run:
        print("dry-run: nessun click inviato")
        return 0

    if attempt("post top-level", window.hwnd, target_client, args.out):
        print("\nRIEPILOGO: il gioco reagisce a messaggi POST senza focus -> input non invasivo possibile")
        post_escape(window.hwnd)
        time.sleep(0.6)
        final = grab_frame(window.hwnd)
        if final is not None:
            cv2.imwrite(str(args.out / "post_escape.png"), final)
        print("inviato ESC (back) per chiudere; se il pannello resta aperto chiudilo manualmente.")
        return 0

    if attempt("send top-level", window.hwnd, target_client, args.out):
        print("\nRIEPILOGO: il gioco reagisce solo a SendMessage (sincrono), non a PostMessage")
        post_escape(window.hwnd)
        return 0

    kids = child_hwnds(window.hwnd)
    print(f"\nfigli della finestra: {[hex(k) for k in kids[:10]]}")
    for child in kids[:5]:
        if attempt(f"post child {child:X}", child, target_client, args.out):
            print("\nRIEPILOGO: il gioco reagisce via messaggi ai figli della finestra")
            post_escape(child)
            return 0

    print("\nRIEPILOGO: NESSUNA reazione rilevata ai messaggi Win32 senza focus.")
    print("Il backend consumer richiederebbe focus (interferenza) -> valutare Developer Emulator + ADB.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
