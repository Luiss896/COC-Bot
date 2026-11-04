"""Primitive visive per la UI di Clash of Clans (GPGPC): pulsanti, pannelli, dialoghi.

Queste primitive sono **geometriche e cromatiche**, senza OCR: sono veloci (pochi ms) e
servono a classificare lo stato dello schermo e a localizzare gli elementi da toccare.
Le posizioni sono espresse come frazioni del frame: la UI del gioco scala in modo
proporzionale alla risoluzione del client (verificato windowed 1733x975 <-> fullscreen
2452x1379), quindi le stesse frazioni valgono per entrambi i casi.

Regola di sicurezza: nessuna funzione qui invia input; i riquadri restituiti vanno sempre
usati con guardie di stato (vedi ``cocbot.vision.states``).
"""
from __future__ import annotations

import cv2
import numpy as np

from cocbot.core.types import Rect

# --- colori (HSV OpenCV: H 0-180, S/V 0-255) ---------------------------------
YELLOW_LOW = (18, 120, 150)
YELLOW_HIGH = (35, 255, 255)
RED_RANGES = (((0, 120, 120), (8, 255, 255)), ((172, 120, 120), (180, 255, 255)))
# verde dei pulsanti del dialogo (CONFIRM): misurato sui frame reali H~40 S~120 V~240
GREEN_BUTTON_LOW = (32, 85, 165)
GREEN_BUTTON_HIGH = (58, 200, 255)

# --- soglie (frazioni del frame) ---------------------------------------------
_BUTTON_MIN_AREA = 0.0035  # area minima di un pulsante HUD giallo (frazione w*h)
_CLOSE_MIN_AREA = 0.0004  # area minima di una X rossa (frazione w*h)
_CONFIRM_MIN_AREA = 0.0030  # area minima del pulsante CONFIRM verde (frazione w*h)

# regioni HUD (frazioni del frame, misurate su finestra 1733x975)
RESOURCES_REGION = (0.865, 0.012, 0.130, 0.240)  # (x, y, w, h)
BUILDERS_REGION = (0.875, 0.755, 0.120, 0.095)


def _hsv(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2HSV)


def _components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int, int, int]]:
    """Componenti connesse: (area, cx, cy, x, y, w, h) ordinate per area decrescente."""
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        found.append(
            (
                area,
                int(centroids[index][0]),
                int(centroids[index][1]),
                int(stats[index, cv2.CC_STAT_LEFT]),
                int(stats[index, cv2.CC_STAT_TOP]),
                int(stats[index, cv2.CC_STAT_WIDTH]),
                int(stats[index, cv2.CC_STAT_HEIGHT]),
            )
        )
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def _rect_from_component(component: tuple[int, int, int, int, int, int, int]) -> Rect:
    _area, _cx, _cy, x, y, w, h = component
    return Rect(x, y, w, h)


def _valid(image: np.ndarray) -> bool:
    return image is not None and image.ndim == 3 and image.shape[0] >= 120 and image.shape[1] >= 200


# ---------------------------------------------------------------------------
# Pulsanti HUD in home: Battle (sinistra) e Build (destra), giallo + icona.
# ---------------------------------------------------------------------------
def _yellow_components(image: np.ndarray) -> list[tuple[int, int, int, int, int, int, int]]:
    hsv = _hsv(image)
    mask = cv2.inRange(hsv, YELLOW_LOW, YELLOW_HIGH)
    h, w = mask.shape[:2]
    return _components(mask, min_area=int(_BUTTON_MIN_AREA * w * h))


def find_build_button(image: np.ndarray) -> Rect | None:
    """Riquadro del pulsante Build (HUD in basso a destra), o ``None``."""
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    candidates = [
        component
        for component in _yellow_components(image)
        if component[1] > w * 0.80 and component[2] > h * 0.78
    ]
    return _rect_from_component(candidates[0]) if candidates else None


def find_battle_button(image: np.ndarray) -> Rect | None:
    """Riquadro del pulsante Battle (HUD in basso a sinistra), o ``None``."""
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    candidates = [
        component
        for component in _yellow_components(image)
        if component[1] < w * 0.20 and component[2] > h * 0.78
    ]
    return _rect_from_component(candidates[0]) if candidates else None


# regione del pulsante "Find a Match" nel pannello Battle (frazioni del frame)
BATTLE_MATCH_REGION = (0.03, 0.58, 0.30, 0.25)  # (x, y, w, h)


def find_find_match_button(image: np.ndarray) -> Rect | None:
    """Riquadro del pulsante "Find a Match" del menu Battle (arancione), o ``None``.

    Geometria verificata sul frame fullscreen del dataset: pulsante largo ~0.19 W e alto
    ~0.10 H nella parte bassa del pannello sinistro. I filtri di aspetto/dimensione evitano
    i blob gialli della mappa (oro, decorazioni) quando la stessa regione e' visibile.
    """
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    x0 = int(w * BATTLE_MATCH_REGION[0])
    y0 = int(h * BATTLE_MATCH_REGION[1])
    x1 = int(w * (BATTLE_MATCH_REGION[0] + BATTLE_MATCH_REGION[2]))
    y1 = int(h * (BATTLE_MATCH_REGION[1] + BATTLE_MATCH_REGION[3]))
    for component in _yellow_components(image):
        _area, cx, cy, _x, _y, cw, ch = component
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            continue
        if not (0.10 <= cw / w <= 0.30 and 0.06 <= ch / h <= 0.14):
            continue
        if cw / max(1, ch) < 2.2:  # pulsante largo e basso, non un edificio
            continue
        return _rect_from_component(component)
    return None


# ---------------------------------------------------------------------------
# Manutenzione del gioco ("MAINTENANCE BREAK"): banner a strisce gialle in alto.
# ---------------------------------------------------------------------------
MAINTENANCE_BANNER_HEIGHT = 0.075  # fascia alta (frazione H) con le strisce gialle
_MAINTENANCE_MIN_YELLOW = 0.22  # frazione minima della fascia che deve essere gialla


def find_maintenance_banner(image: np.ndarray) -> bool:
    """True se il frame e' la schermata "MAINTENANCE BREAK" (banner a strisce gialle).

    Misure sui frame reali (fascia alta 7,5%): schermata manutenzione 0,33; tutte le altre
    schermate del dataset <= 0,15 (barre risorse piccole). Nessun input: sola lettura.
    """
    if not _valid(image):
        return False
    h, w = image.shape[:2]
    band = max(1, int(h * MAINTENANCE_BANNER_HEIGHT))
    mask = cv2.inRange(_hsv(image)[:band], YELLOW_LOW, YELLOW_HIGH)
    yellow_fraction = float(mask.sum() / 255) / max(1, band * w)
    return yellow_fraction >= _MAINTENANCE_MIN_YELLOW


# ---------------------------------------------------------------------------
# Chiusura menu Build / dialoghi / piazzamento.
# ---------------------------------------------------------------------------
def _red_components(image: np.ndarray) -> list[tuple[int, int, int, int, int, int, int]]:
    hsv = _hsv(image)
    mask = cv2.inRange(hsv, RED_RANGES[0][0], RED_RANGES[0][1]) | cv2.inRange(hsv, RED_RANGES[1][0], RED_RANGES[1][1])
    h, w = mask.shape[:2]
    return _components(mask, min_area=int(_CLOSE_MIN_AREA * w * h))


def find_menu_close(image: np.ndarray) -> tuple[int, int] | None:
    """Centro della X del menu Build (in alto a destra del pannello), o ``None``."""
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    for component in _red_components(image):
        _area, cx, cy = component[0], component[1], component[2]
        if cx > w * 0.955 and cy < h * 0.065:
            return cx, cy
    return None


def find_dialog_close(image: np.ndarray) -> tuple[int, int] | None:
    """Centro della X di un dialogo centrale (conferma upgrade), o ``None``.

    La X del dialogo sta a ~0.88 della larghezza e ~0.08 dell'altezza: posizione
    distinta sia dalla X del menu (~0.98, ~0.03) sia dai pulsanti della mappa.
    """
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    for component in _red_components(image):
        _area, cx, cy = component[0], component[1], component[2]
        if 0.835 * w < cx < 0.945 * w and 0.040 * h < cy < 0.120 * h:
            return cx, cy
    return None


def find_placement_exit(image: np.ndarray) -> tuple[int, int] | None:
    """Centro della X rossa della modalita' piazzamento edificio, o ``None``.

    In modalita' piazzamento ci sono DUE pulsanti affiancati al centro-alto: X rossa a
    sinistra e spunta chiara (cerchio grigio con check bianco) a destra. La sola X rossa
    non basta: la mappa contiene decorazioni rosse (misurati falsi positivi), quindi si
    richiede che la X abbia dimensioni/forma da pulsante e che a destra ci sia una zona
    chiara estesa (la spunta). Geometria misurata sul frame reale: X ~72x69 px (0.041 W),
    spunta a +0.065 W, frazione chiara nella zona destra ~0.39-0.43 (controllo sinistro ~0.17).
    """
    if not _valid(image):
        return None
    hsv = _hsv(image)
    mask = cv2.inRange(hsv, RED_RANGES[0][0], RED_RANGES[0][1]) | cv2.inRange(hsv, RED_RANGES[1][0], RED_RANGES[1][1])
    h, w = mask.shape[:2]
    area_min = int(0.0013 * w * h)
    area_max = int(0.0035 * w * h)
    for component in _components(mask, min_area=area_min):
        area, cx, cy, _x, _y, cw, ch = component
        if area > area_max or not (0.40 * w < cx < 0.55 * w and 0.20 * h < cy < 0.36 * h):
            continue
        if ch <= 0 or not (0.85 <= cw / ch <= 1.35):
            continue
        if not (0.030 * w <= cw <= 0.050 * w):
            continue
        if _white_fraction_right_of(image, cx, cy) >= 0.30:
            return cx, cy
    return None


def _white_fraction_right_of(image: np.ndarray, red_cx: int, red_cy: int) -> float:
    """Frazione di pixel chiari/poco saturi a destra della X (dove sta la spunta)."""
    h, w = image.shape[:2]
    x0 = min(w - 2, int(red_cx + 0.030 * w))
    x1 = min(w - 1, int(red_cx + 0.090 * w))
    y0 = max(0, int(red_cy - 0.035 * h))
    y1 = min(h - 1, int(red_cy + 0.035 * h))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return 0.0
    hsv = _hsv(image)
    region_sat = hsv[y0:y1, x0:x1, 1]
    region_val = hsv[y0:y1, x0:x1, 2]
    bright_neutral = (region_sat < 60) & (region_val > 170)
    return float(bright_neutral.mean())


def find_inactivity_modal(image: np.ndarray) -> tuple[int, int] | None:
    """Centro del pulsante azzurro del modal di disconnessione, o ``None``.

    Riconosce le due varianti osservate su questa versione del gioco:
    - "Connection lost" con "TRY AGAIN";
    - "Anyone there?" con "RELOAD GAME".
    Il modal e' un rettangolo molto scuro al centro dello schermo con, in basso a sinistra,
    la scritta azzurra del pulsante d'azione. La mappa attorno e' luminosa: questo distingue
    il modal dallo splash screen di caricamento (schermo nero con logo Supercell).
    """
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    modal = gray[int(h * 0.42) : int(h * 0.58), int(w * 0.30) : int(w * 0.68)]
    if modal.size == 0 or float(modal.mean()) >= 60.0 or float(modal.std()) >= 45.0:
        return None
    surroundings = gray[int(h * 0.05) : int(h * 0.20), int(w * 0.30) : int(w * 0.70)]
    if surroundings.size == 0 or float(surroundings.mean()) < 90.0:
        return None
    # testo azzurro "RELOAD GAME" in basso a sinistra del modal
    hsv = _hsv(image)
    text_region = hsv[int(h * 0.49) : int(h * 0.61), int(w * 0.27) : int(w * 0.44)]
    blue_text = cv2.inRange(text_region, (92, 40, 110), (118, 170, 255))
    if int(blue_text.sum()) < 200:
        return None
    ys, xs = np.where(blue_text > 0)
    if xs.size == 0:
        return None
    x = int(w * 0.27) + int(xs.mean())
    y = int(h * 0.49) + int(ys.mean())
    return x, y


# ---------------------------------------------------------------------------
# Pulsante CONFIRM del dialogo (verde) e riquadri HUD.
# ---------------------------------------------------------------------------
def find_confirm_button(image: np.ndarray) -> Rect | None:
    """Riquadro del pulsante verde CONFIRM nel dialogo di upgrade, o ``None``.

    Va chiamata solo quando lo stato e' un dialogo di conferma (vedi ``states.classify``):
    in home la stessa fascia contiene erba verde.
    """
    if not _valid(image):
        return None
    hsv = _hsv(image)
    mask = cv2.inRange(hsv, GREEN_BUTTON_LOW, GREEN_BUTTON_HIGH)
    h, w = mask.shape[:2]
    mask[: int(h * 0.74), :] = 0
    mask[int(h * 0.94):, :] = 0
    mask[:, : int(w * 0.45)] = 0
    mask[:, int(w * 0.90):] = 0
    components = _components(mask, min_area=int(_CONFIRM_MIN_AREA * w * h))
    return _rect_from_component(components[0]) if components else None


def find_hammer_button(image: np.ndarray) -> Rect | None:
    """Riquadro del pulsante "Hammer of Building" (grigio, a sinistra di CONFIRM).

    Usato solo per verifica/diagnostica: il bot NON deve mai premerlo (consuma un oggetto).
    """
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # pulsante grigio chiaro, uniforme, nella stessa fascia del CONFIRM ma piu' a sinistra
    mask = cv2.inRange(gray, 150, 215)
    mask[: int(h * 0.78), :] = 0
    mask[int(h * 0.93):, :] = 0
    mask[:, : int(w * 0.42)] = 0
    mask[:, int(w * 0.62):] = 0
    components = _components(mask, min_area=int(_CONFIRM_MIN_AREA * w * h))
    return _rect_from_component(components[0]) if components else None


def resources_region(image: np.ndarray) -> Rect:
    """Riquadro (frame) della colonna risorse in home: oro, elisir, elisir nero, gemme."""
    h, w = image.shape[:2]
    x, y, width, height = RESOURCES_REGION
    return Rect(int(x * w), int(y * h), int(width * w), int(height * h))


def builders_region(image: np.ndarray) -> Rect:
    """Riquadro (frame) della riga builder/laboratorio in home ("5/5", "1/1")."""
    h, w = image.shape[:2]
    x, y, width, height = BUILDERS_REGION
    return Rect(int(x * w), int(y * h), int(width * w), int(height * h))


# ---------------------------------------------------------------------------
# Pannello destro del menu Build.
# ---------------------------------------------------------------------------
def find_build_panel(image: np.ndarray) -> Rect | None:
    """Riquadro del pannello destro del menu Build, o ``None`` se non c'e'.

    Il confine mappa/pannello e' una linea verticale netta (grande gradiente orizzontale
    lungo quasi tutta l'altezza): si cerca il picco del profilo di gradiente x nella
    fascia destra. Il picco deve essere molto piu' forte del gradiente di fondo
    (mappa variegata/HUD), altrimenti non c'e' pannello.

    Frazione misurata: bordo a ~0.730 della larghezza sia in windowed (1733x975) sia in
    fullscreen (2452x1379), quindi la frazione e' stabile.
    """
    if not _valid(image):
        return None
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    band = gray[int(h * 0.10) : int(h * 0.92), :].astype(np.float32)
    gradient_x = np.abs(cv2.Sobel(band, cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0)
    gradient_x = np.convolve(gradient_x, np.ones(5, dtype=np.float32) / 5.0, mode="same")
    x0, x1 = int(w * 0.62), int(w * 0.88)
    if x1 <= x0:
        return None
    peak_x = x0 + int(np.argmax(gradient_x[x0:x1]))
    peak = float(gradient_x[peak_x])
    background = float(np.median(gradient_x[x0:x1]))
    if peak < max(2.6 * background, 15.0):
        return None
    left = peak_x + int(round(0.004 * w))
    width = w - left
    if not (0.20 <= width / w <= 0.35):
        return None
    return Rect(left, 0, width, h)


def find_row_bands(
    image: np.ndarray,
    panel: Rect,
    *,
    min_height_frac: float = 0.045,
    max_height_frac: float = 0.20,
) -> list[Rect]:
    """Bande orizzontali delle righe della lista Build (separatori scuri tra le card).

    I separatori tra una card e l'altra sono fasce di righe molto piu' scure del fondo
    del pannello. Si usa una baseline (mediana mobile) sul profilo di luminanza per riga:
    le righe sotto la baseline sono separatori; run scuri vicini vengono fusi e il centro
    del run e' il confine tra due righe. Le bande di altezza plausibile sono le righe
    (una riga normale e' ~0.08 dell'altezza frame; quelle con descrizione fino a ~0.14;
    le intestazioni di sezione sono piu' basse e vengono scartate dal filtro altezza e,
    a valle, dal fatto che non contengono ne' tempo ne' costo).
    """
    if not _valid(image) or panel.w <= 0 or panel.h <= 0:
        return []
    h, w = image.shape[:2]
    x0 = max(0, panel.x + int(panel.w * 0.02))
    x1 = min(w, panel.right - int(panel.w * 0.02))
    y0 = max(0, panel.y)
    y1 = min(h, panel.bottom)
    if x1 - x0 < 20 or y1 - y0 < 40:
        return []
    region = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    profile = region.mean(axis=1)
    count = profile.shape[0]
    # baseline: mediana mobile (~61 righe); il separatore e' ~30+ livelli sotto
    window = max(21, int(0.06 * h) | 1)
    half = window // 2
    baseline = np.empty_like(profile)
    for y in range(count):
        baseline[y] = float(np.median(profile[max(0, y - half) : min(count, y + half + 1)]))
    dark = profile < baseline - 20.0
    runs: list[tuple[int, int]] = []
    start = None
    for y in range(count):
        if dark[y] and start is None:
            start = y
        elif not dark[y] and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, count - 1))
    # fondi run vicini (bordo card = 2 linee scure ravvicinate) e prendi il centro
    merge_gap = max(4, int(0.012 * h))
    merged: list[tuple[int, int]] = []
    for run_start, run_end in runs:
        if merged and run_start - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], run_end)
        else:
            merged.append((run_start, run_end))
    separators: list[int] = []
    for run_start, run_end in merged:
        length = run_end - run_start + 1
        if length > int(0.025 * h):  # troppo alto per essere un separatore: area scura
            continue
        center = y0 + (run_start + run_end) // 2
        if center < y0 + 0.02 * h or center > y0 + 0.985 * h:
            continue
        separators.append(center)
    min_height = max(8, int(min_height_frac * h))
    max_height = max(min_height + 1, int(max_height_frac * h))
    bands: list[Rect] = []
    for top, bottom in zip(separators, separators[1:], strict=False):
        height = bottom - top
        if min_height <= height <= max_height:
            bands.append(Rect(panel.x, top, panel.w, height))
    return bands


def center(rect: Rect) -> tuple[int, int]:
    """Centro di un riquadro (pixel frame)."""
    return rect.x + rect.w // 2, rect.y + rect.h // 2


__all__ = [
    "BUILDERS_REGION",
    "RESOURCES_REGION",
    "builders_region",
    "center",
    "find_battle_button",
    "find_build_button",
    "find_build_panel",
    "find_confirm_button",
    "find_dialog_close",
    "find_hammer_button",
    "find_inactivity_modal",
    "find_menu_close",
    "find_placement_exit",
    "find_row_bands",
    "resources_region",
]
