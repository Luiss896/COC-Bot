"""POC Windows Graphics Capture (WGC) sulla finestra del gioco GPGPC.

Solo lettura: cattura la finestra, nessun input simulato. Misura FPS, frame neri,
frame identici e freschezza, e salva alcuni frame di esempio.

Richiede ``windows-capture``. Se il pacchetto e' stato scompattato a mano in
``<repo>/.deps`` (per aggirare il sandbox), lo script lo aggiunge al sys.path.

Uso:
    python tools/poc_wgc.py --seconds 5
    python tools/poc_wgc.py --seconds 10 --out out/captures/wgc
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPS_DIR = REPO_ROOT / ".deps"
if DEPS_DIR.is_dir() and str(DEPS_DIR) not in sys.path:
    sys.path.insert(0, str(DEPS_DIR))

# Il DPI awareness va impostato PRIMA di importare cv2/windows-capture, altrimenti
# GetClientRect restituisce misure logiche (es. 1386x780 invece di 1733x975).
from cocbot.capture import win32 as _win32  # noqa: E402

_win32.set_dpi_awareness()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from windows_capture import Frame, InternalCaptureControl, WindowsCapture  # noqa: E402

from cocbot.capture.window import GameWindow, find_game_window  # noqa: E402

BLACK_LUMA_THRESHOLD = 8.0
SAME_FRAME_THRESHOLD = 0.6
SIGNATURE_SIZE = (96, 54)


def frame_signature(frame: Frame) -> np.ndarray:
    """Firma ridotta (grigio 96x54) per confrontare frame consecutivi."""
    bgr = frame.frame_buffer[:, :, :3]
    return cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), SIGNATURE_SIZE, interpolation=cv2.INTER_AREA)


def run_capture(hwnd: int, seconds: float, out_dir: Path, save_every_s: float) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "frames": 0,
        "black": 0,
        "identical": 0,
        "first_ts": None,
        "last_ts": None,
        "intervals": [],
        "prev_sig": None,
        "saved": [],
        "closed": False,
        "error": None,
    }

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        window_hwnd=hwnd,
    )

    start = time.monotonic()
    next_save = start

    @capture.event
    def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl) -> None:  # noqa: N802
        nonlocal next_save
        try:
            now = time.monotonic()
            if stats["frames"] == 0:
                stats["first_ts"] = now
            sig = frame_signature(frame)
            luma = float(sig.mean())
            if luma < BLACK_LUMA_THRESHOLD:
                stats["black"] += 1
            if stats["prev_sig"] is not None:
                diff = float(np.abs(sig.astype(np.int16) - stats["prev_sig"].astype(np.int16)).mean())
                if diff < SAME_FRAME_THRESHOLD:
                    stats["identical"] += 1
                stats["intervals"].append(now - stats["last_ts"])
            stats["prev_sig"] = sig
            stats["last_ts"] = now
            stats["frames"] += 1
            if now >= next_save:
                path = out_dir / f"wgc-{stats['frames']:04d}.png"
                frame.convert_to_bgr().save_as_image(str(path))
                stats["saved"].append(str(path))
                next_save = now + save_every_s
            if now - start >= seconds:
                capture_control.stop()
        except Exception as exc:  # pragma: no cover - diagnostica POC
            stats["error"] = f"callback: {exc!r}"
            capture_control.stop()

    @capture.event
    def on_closed() -> None:  # noqa: N802
        stats["closed"] = True

    control = capture.start_free_threaded()
    # rete di sicurezza: se i callback non arrivano, non restare appeso
    while not control.is_finished() and time.monotonic() - start < seconds + 5.0:
        time.sleep(0.1)
    if not control.is_finished():
        control.stop()
    control.wait()

    elapsed = max(1e-6, (stats["last_ts"] - stats["first_ts"])) if stats["first_ts"] and stats["last_ts"] else 0.0
    fps = stats["frames"] / elapsed if elapsed > 0 else 0.0
    mean_interval = float(np.mean(stats["intervals"])) if stats["intervals"] else 0.0

    print("== POC WGC (sola lettura) ==")
    print(f"hwnd=0x{hwnd:X} | durata richiesta={seconds:.1f}s")
    print(f"frame acquisiti: {stats['frames']} | FPS (su intervallo frame): {fps:.2f}")
    print(
        f"intervallo medio: {mean_interval * 1000:.2f} ms | frame neri: {stats['black']} | "
        f"frame identici consecutivi: {stats['identical']}"
    )
    print(f"chiusura finestra durante il test: {stats['closed']} | errori: {stats['error']}")
    print(f"frame salvati: {len(stats['saved'])} in {out_dir}")
    for path in stats["saved"]:
        print(f"  - {path}")
    if stats["frames"] == 0:
        print("ESITO: FALLITO (nessun frame)")
        return 2
    if stats["black"] == stats["frames"]:
        print("ESITO: FALLITO (tutti i frame neri)")
        return 3
    if stats["error"]:
        print("ESITO: FALLITO (errore callback)")
        return 4
    print("ESITO: OK (frame acquisiti)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="POC cattura WGC della finestra di gioco")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "out" / "captures" / "wgc")
    parser.add_argument("--save-every", type=float, default=1.0)
    args = parser.parse_args()

    info = find_game_window()
    if info is None:
        print("Finestra di gioco non trovata: avvia manualmente il gioco da GPGPC.")
        return 1
    window = GameWindow(info)
    print(f"finestra: {window}")
    print(f"in foreground all'avvio: {window.is_foreground} (se False stiamo testando la cattura 'coperta')")
    return run_capture(window.hwnd, args.seconds, args.out, args.save_every)


if __name__ == "__main__":
    raise SystemExit(main())
