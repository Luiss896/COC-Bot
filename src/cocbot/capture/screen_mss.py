"""Cattura schermo via ``mss`` (foreground/visibile).

Nota: questa sorgente cattura i pixel effettivamente sullo schermo; se la finestra è coperta o
minimizzata la cattura non è valida. Serve come fallback/diagnostica in attesa di WGC (per-finestra).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from cocbot.capture.window import GameWindow
from cocbot.core.types import CaptureHealth, Frame, Rect, Viewport


class MssScreenSource:
    """ScreenSource basata su ``mss``, limitata al client della finestra di gioco."""

    def __init__(
        self,
        window: GameWindow,
        *,
        target_fps: int = 10,
        black_luma_threshold: float = 8.0,
    ) -> None:
        self.window = window
        self.target_fps = target_fps
        self.black_luma_threshold = black_luma_threshold
        self._sct = None
        self._frames = 0
        self._black_frames = 0
        self._stale_frames = 0
        self._last_small: np.ndarray | None = None
        self._last_frame_time: float | None = None
        self._fps = 0.0

    def _ensure_sct(self):
        if self._sct is None:
            import mss  # import lazy

            self._sct = mss.mss()
        return self._sct

    def grab(self) -> Frame:
        sct = self._ensure_sct()
        origin_x, origin_y = self.window.client_origin()
        monitor = {
            "left": origin_x,
            "top": origin_y,
            "width": self.window.client_width,
            "height": self.window.client_height,
        }
        shot = sct.grab(monitor)
        image = np.asarray(shot)[:, :, :3].copy()  # BGRA -> BGR
        timestamp = time.monotonic()

        now = timestamp
        if self._last_frame_time is not None:
            delta = max(1e-6, now - self._last_frame_time)
            self._fps = 0.85 * self._fps + 0.15 * (1.0 / delta) if self._fps else 1.0 / delta
        self._last_frame_time = now

        luma = float(image.mean())
        is_black = luma < self.black_luma_threshold
        if is_black:
            self._black_frames += 1

        # rilevamento "frame congelato": confronto su un downsample per non sprecare CPU
        small = image[::8, ::8]
        stale = False
        if self._last_small is not None and self._last_small.shape == small.shape:
            stale = bool(np.array_equal(self._last_small, small))
        self._last_small = small
        if stale:
            self._stale_frames += 1

        self._frames += 1
        viewport = Viewport(Rect(0, 0, self.window.client_width, self.window.client_height))
        return Frame(
            image=image,
            timestamp=timestamp,
            viewport=viewport,
            source="mss",
            stale=stale,
            metadata={"luma": luma, "black": is_black},
        )

    def viewport(self) -> Viewport:
        return Viewport(Rect(0, 0, self.window.client_width, self.window.client_height))

    def health(self) -> CaptureHealth:
        return CaptureHealth(
            fps=round(self._fps, 2),
            frames=self._frames,
            black_frames=self._black_frames,
            stale_frames=self._stale_frames,
        )

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


def save_frame_png(frame: Frame, path: str | Path) -> Path:
    """Salva un frame come PNG (OpenCV)."""
    import cv2

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out), frame.image)
    if not ok:  # pragma: no cover
        raise RuntimeError(f"salvataggio frame fallito: {out}")
    return out
