"""Cattura per-finestra via Windows Graphics Capture (WGC).

Vantaggi rispetto a ``mss``:
- cattura la **finestra** del gioco anche se coperta da altre finestre (a patto che non sia
  minimizzata: WGC non cattura finestre minimizzate);
- nessun movimento del cursore/focus (il bot non deve interferire con l'utente).

Richiede il pacchetto ``windows-capture`` (extra opzionale ``wgc``) e **integrita' media**:
un processo sandboxato a bassa integrita' riceve ``Failed to convert item to GraphicsCaptureItem``.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from cocbot.capture.window import GameWindow
from cocbot.core.types import CaptureHealth, Frame, Rect, Viewport


def client_crop_box(frame_size: tuple[int, int], client_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Rettangolo (x, y, w, h) dell'area client dentro il frame WGC.

    Il frame WGC di una finestra include il bordo/titolo (DWM frame): l'area client e'
    centrata orizzontalmente e allineata in basso (il titolo sta in alto).
    """
    frame_w, frame_h = frame_size
    client_w, client_h = client_size
    if client_w <= 0 or client_h <= 0:
        raise ValueError(f"client size non valida: {client_size}")
    if client_w > frame_w or client_h > frame_h:
        raise ValueError(f"client {client_size} piu' grande del frame {frame_size}")
    x = (frame_w - client_w) // 2
    y = frame_h - client_h
    return x, y, client_w, client_h


def _import_windows_capture():
    try:
        import windows_capture  # noqa: PLC0415 - import opzionale/lazy

        return windows_capture
    except ImportError:
        # fallback di sviluppo: wheel scompattata in <repo>/.deps (vedi tools/poc_wgc.py)
        deps = Path(__file__).resolve().parents[3] / ".deps"
        if deps.is_dir():
            import sys

            sys.path.insert(0, str(deps))
            import windows_capture  # noqa: PLC0415

            return windows_capture
        raise RuntimeError(
            "windows-capture non installato: `python -m pip install windows-capture` "
            "(extra: `pip install -e .[wgc]`)"
        ) from None


class WgcScreenSource:
    """ScreenSource WGC per la finestra del gioco (consumer GPGPC)."""

    def __init__(
        self,
        window: GameWindow,
        *,
        target_fps: int = 10,
        black_luma_threshold: float = 8.0,
        grab_timeout_s: float = 1.0,
    ) -> None:
        self.window = window
        self.target_fps = max(1, target_fps)
        # Throttle lato WGC: senza questo il sistema consegna ~50 frame/s (CPU alta anche
        # quando il bot ne usa 5-10). minimum_update_interval è in millisecondi.
        self._min_update_interval_ms = max(16, int(1000 / self.target_fps))
        self.black_luma_threshold = black_luma_threshold
        self.grab_timeout_s = grab_timeout_s

        self._capture = None
        self._control = None
        self._thread: threading.Thread | None = None
        self._cond = threading.Condition()
        self._latest: np.ndarray | None = None
        self._latest_counter = 0
        self._read_counter = 0
        self._frame_times: list[float] = []
        self._frames = 0
        self._black_frames = 0
        self._stale_frames = 0
        self._last_error: str | None = None
        self._closed = False
        self._crop_box: tuple[int, int, int, int] | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._capture is not None:
            return
        wc = _import_windows_capture()
        capture = wc.WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=self.window.hwnd,
            minimum_update_interval=self._min_update_interval_ms,
        )
        self._capture = capture

        @capture.event
        def on_frame_arrived(frame, capture_control) -> None:  # noqa: N802
            try:
                image = frame.convert_to_bgr().frame_buffer  # vista BGRA->BGR
                frame_h, frame_w = image.shape[:2]
                client = (self.window.client_width, self.window.client_height)
                ox, oy, cw, ch = client_crop_box((frame_w, frame_h), client)
                image = np.ascontiguousarray(image[oy : oy + ch, ox : ox + cw])
                now = time.monotonic()
                # luma su un downsample: il mean() a piena risoluzione per frame costa CPU
                luma = float(image[::6, ::6].mean())
                with self._cond:
                    self._latest = image
                    self._latest_counter += 1
                    self._frames += 1
                    if luma < self.black_luma_threshold:
                        self._black_frames += 1
                    self._frame_times.append(now)
                    if len(self._frame_times) > 120:
                        self._frame_times.pop(0)
                    self._cond.notify_all()
            except Exception as exc:  # pragma: no cover - diagnostica
                with self._cond:
                    self._last_error = repr(exc)
                    self._cond.notify_all()

        @capture.event
        def on_closed() -> None:  # noqa: N802
            with self._cond:
                self._last_error = "finestra di cattura chiusa"
                self._cond.notify_all()

        self._control = capture.start_free_threaded()

    def _ensure_started(self) -> None:
        if self._capture is None:
            self.start()

    # ---------------------------------------------------------------- grab
    def grab(self) -> Frame:
        self._ensure_started()
        deadline = time.monotonic() + self.grab_timeout_s
        with self._cond:
            if self._latest is None and self._last_error is None:
                self._cond.wait(max(0.05, deadline - time.monotonic()))
            if self._latest is None:
                raise RuntimeError(f"cattura WGC non disponibile: {self._last_error or 'nessun frame'}")
            if self._latest_counter == self._read_counter:
                self._stale_frames += 1
                stale = True
            else:
                self._read_counter = self._latest_counter
                stale = False
            image = self._latest
            luma = float(image.mean())
        return Frame(
            image=image,
            timestamp=time.monotonic(),
            viewport=self.viewport(),
            source="wgc",
            stale=stale,
            metadata={"luma": luma, "black": luma < self.black_luma_threshold},
        )

    # ---------------------------------------------------------------- interface
    def viewport(self) -> Viewport:
        return Viewport(Rect(0, 0, self.window.client_width, self.window.client_height))

    def health(self) -> CaptureHealth:
        with self._cond:
            fps = 0.0
            if len(self._frame_times) >= 2:
                span = self._frame_times[-1] - self._frame_times[0]
                if span > 0:
                    fps = (len(self._frame_times) - 1) / span
            return CaptureHealth(
                fps=round(fps, 2),
                frames=self._frames,
                black_frames=self._black_frames,
                stale_frames=self._stale_frames,
                last_error=self._last_error,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        control = self._control
        if control is not None:
            try:
                control.stop()
                control.wait()
            except Exception:  # pragma: no cover - best effort
                pass
        self._capture = None
        self._control = None


def save_frame_png(frame: Frame, path: str | Path) -> Path:
    """Salva un frame come PNG (OpenCV)."""
    import cv2

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), frame.image):  # pragma: no cover
        raise RuntimeError(f"salvataggio frame fallito: {out}")
    return out
