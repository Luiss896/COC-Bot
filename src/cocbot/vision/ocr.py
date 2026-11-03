"""Lettura del testo su schermo tramite OCR opzionale (``rapidocr`` + ``onnxruntime``).

L'OCR e' una dipendenza opzionale (extra ``ocr``): ``read_texts`` solleva ``OcrUnavailable``
se il pacchetto manca, cosi' i moduli chiamanti possono degradare con un errore chiaro.
Motivo dell'opzionalita': ``rapidocr`` + modelli ONNX pesano ~30 MB e non servono per
cattura/input/GUI.

Misure su questo PC (Python 3.14.8, onnxruntime CPU, finestra di gioco 1733x975):
- pannello Build intero (460x975), scala 1x, senza classificatore di orientamento: ~0.9 s;
- piccoli crop HUD (~200x240): ~0.1-0.2 s.

Regola: chiamare l'OCR solo quando serve leggere testo, mai a ogni frame (la cattura e
l'input non lo richiedono).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


class OcrUnavailable(RuntimeError):
    """``rapidocr``/``onnxruntime`` non installati: ``python -m pip install -e .[ocr]``."""


@dataclass(frozen=True, slots=True)
class TextItem:
    """Testo riconosciuto, con bounding box in pixel del frame (coordinate assolute)."""

    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    score: float

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def cx(self) -> int:
        return (self.x0 + self.x1) // 2

    @property
    def cy(self) -> int:
        return (self.y0 + self.y1) // 2

    def __str__(self) -> str:
        return f"TextItem({self.text!r} @ ({self.x0},{self.y0})-({self.x1},{self.y1}) sc={self.score:.2f})"


_engine: Any | None = None


def _load_engine() -> Any:
    """Carica (una volta sola) il motore OCR; errore esplicito se non installato."""
    global _engine
    if _engine is not None:
        return _engine
    try:
        from rapidocr import RapidOCR  # noqa: PLC0415 - import opzionale/lazy
    except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
        raise OcrUnavailable(
            "OCR non disponibile: installa l'extra OCR con `python -m pip install -e .[ocr]`"
        ) from exc
    _engine = RapidOCR()
    return _engine


def reset_engine() -> None:
    """Scarta il motore OCR (usato dai test / per liberare memoria)."""
    global _engine
    _engine = None


def ocr_available() -> bool:
    """True se il motore OCR e' importabile (senza inizializzarlo)."""
    try:
        import rapidocr  # noqa: F401, PLC0415 - solo check di disponibilita'
    except ImportError:
        return False
    return True


def read_texts(
    image: np.ndarray,
    *,
    use_cls: bool = False,
    min_score: float = 0.35,
    offset: tuple[int, int] = (0, 0),
) -> list[TextItem]:
    """Esegue l'OCR su un frame BGR e restituisce i testi (box in coordinate frame).

    Args:
        image: frame BGR (uint8). Puo' essere un crop: in quel caso passare ``offset`` con
            l'origine del crop nel frame completo, cosi' i box restano in coordinate frame.
        use_cls: classificatore di orientamento del testo. Disattivato (piu' veloce):
            il gioco usa solo testo orizzontale.
        min_score: soglia di confidenza per scartare letture inaffidabili.
        offset: (dx, dy) da sommare ai box restituiti.
    """
    if image is None or image.size == 0:
        return []
    if image.ndim == 2:
        image = np.stack([image] * 3, axis=-1)
    if image.dtype != np.uint8:
        image = image.astype(np.uint8)
    result = _load_engine()(image, use_cls=use_cls)
    texts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    if texts is None or boxes is None:
        return []
    scores = getattr(result, "scores", None)
    if scores is None:
        scores = [1.0] * len(texts)
    dx, dy = offset
    items: list[TextItem] = []
    for text, box, score in zip(texts, boxes, scores, strict=False):
        if float(score) < min_score:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            TextItem(
                text=str(text).strip(),
                x0=int(min(xs)) + dx,
                y0=int(min(ys)) + dy,
                x1=int(max(xs)) + dx,
                y1=int(max(ys)) + dy,
                score=float(score),
            )
        )
    return items


__all__ = ["OcrUnavailable", "TextItem", "ocr_available", "read_texts", "reset_engine"]
