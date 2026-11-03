"""Euristiche visive minime per tap *sicuri* e riconoscimento "siamo in home".

Queste euristiche **non** sostituiscono il classifier stati (fase successiva): sono un gate
conservativo per l'umanizzazione. I tap "casuali" del humanizer vengono fatti **solo su erba
vuota**, cioe' punti che:
- hanno colore d'erba su un intorno ampio (niente edifici/pulsanti),
- stanno lontani dalle aree UI (barre risorse, pulsanti in basso, colonne laterali),
- non cadono nelle zone proibite (GemGuard).

Un tap su erba in home non seleziona nulla (o chiude un pannello): e' l'equivalente di un
"tap a vuoto" di un giocatore distratto, senza rischio di spendere risorse/gemme.
"""
from __future__ import annotations

import random

import cv2
import numpy as np

from cocbot.core.types import GamePoint, Rect

CANONICAL_WIDTH = 1920
CANONICAL_HEIGHT = 1080

# riferimento di taratura (finestra windowed del PC di sviluppo, DPI 120)
REF_WIDTH = 1733
REF_HEIGHT = 975

# margini UI (pixel del frame di riferimento): barra risorse in alto, pulsanti in basso, icone ai lati
UI_MARGIN_TOP = 95
UI_MARGIN_BOTTOM = 175
UI_MARGIN_LEFT = 120
UI_MARGIN_RIGHT = 190

GRASS_HSV_LOW = (32, 80, 90)
GRASS_HSV_HIGH = (58, 220, 215)

YELLOW_HSV_LOW = (18, 120, 150)
YELLOW_HSV_HIGH = (35, 255, 255)

MIN_COMPONENT_AREA = 3000
PATCH_RADIUS = 7
MIN_PATCH_GRASS = 0.95


def _scale_factors(width: int, height: int) -> tuple[float, float]:
    """Fattori di scala rispetto al frame di riferimento (windowed 1733x975)."""
    return width / REF_WIDTH, height / REF_HEIGHT


def scaled_ui_margins(width: int, height: int) -> tuple[int, int, int, int]:
    """Margini UI (top, bottom, left, right) scalati alla dimensione effettiva del frame."""
    sx, sy = _scale_factors(width, height)
    return (
        round(UI_MARGIN_TOP * sy),
        round(UI_MARGIN_BOTTOM * sy),
        round(UI_MARGIN_LEFT * sx),
        round(UI_MARGIN_RIGHT * sx),
    )


def grass_mask(image: np.ndarray, *, apply_ui_margins: bool = False) -> np.ndarray:
    """Maschera dell'erba chiara della mappa (uint8 0/255)."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"atteso frame BGR HxWx3, ricevuto {image.shape}")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GRASS_HSV_LOW, GRASS_HSV_HIGH)
    if apply_ui_margins:
        h, w = mask.shape[:2]
        top, bottom, left, right = scaled_ui_margins(w, h)
        mask[:top, :] = 0
        mask[h - bottom :, :] = 0
        mask[:, :left] = 0
        mask[:, w - right :] = 0
    return mask


def _yellow_fraction(image: np.ndarray, region: np.ndarray) -> float:
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, YELLOW_HSV_LOW, YELLOW_HSV_HIGH)
    return float((mask > 0).mean())


def looks_like_home(
    image: np.ndarray,
    *,
    yellow_min_fraction: float = 0.05,
    grass_min_fraction: float = 0.15,
) -> bool:
    """Euristica conservativa: home village = molto verde + pulsanti gialli in basso (Battle/Build)."""
    if image.ndim != 3 or image.shape[2] != 3:
        return False
    h, w = image.shape[:2]
    if h < 200 or w < 300:
        return False
    sx, sy = _scale_factors(w, h)
    grass_frac = float((grass_mask(image) > 0).mean())
    strip_h = max(20, round(140 * sy))
    left = image[h - strip_h :, : max(40, round(200 * sx))]
    right = image[h - strip_h :, w - max(40, round(220 * sx)) :]
    yellow_left = _yellow_fraction(image, left)
    yellow_right = _yellow_fraction(image, right)
    return (
        grass_frac >= grass_min_fraction
        and yellow_left >= yellow_min_fraction
        and yellow_right >= yellow_min_fraction
    )


def find_safe_tap_point(
    image: np.ndarray,
    *,
    forbidden_zones: tuple[Rect, ...] = (),
    rng: random.Random | None = None,
    max_candidates: int = 6,
) -> GamePoint | None:
    """Sceglie un punto CANONICO sul quale un tap e' sicuro (erba vuota, lontano da UI/zone proibite)."""
    mask = grass_mask(image, apply_ui_margins=True)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    if int(mask.sum()) == 0:
        return None
    h, w = mask.shape[:2]
    sx, sy = _scale_factors(w, h)
    min_area = MIN_COMPONENT_AREA * sx * sy
    patch_radius = max(3, round(PATCH_RADIUS * max(sx, sy)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    components = sorted(
        ((int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)),
        reverse=True,
    )
    candidates: list[tuple[int, int]] = []
    for area, idx in components:
        if area < min_area:
            continue
        comp = (labels == idx).astype(np.uint8)
        dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
        _, _, _, (cx, cy) = cv2.minMaxLoc(dist)
        r = patch_radius
        patch = mask[max(0, cy - r) : cy + r + 1, max(0, cx - r) : cx + r + 1]
        if patch.size == 0 or float((patch > 0).mean()) < MIN_PATCH_GRASS:
            continue
        candidates.append((int(cx), int(cy)))
        if len(candidates) >= max_candidates:
            break
    if not candidates:
        return None
    rng = rng or random
    px, py = rng.choice(candidates)
    point = GamePoint(
        x=round(px * CANONICAL_WIDTH / w),
        y=round(py * CANONICAL_HEIGHT / h),
    )
    for zone in forbidden_zones:
        if zone.contains(point):
            return None
    return point


# Zona del pannello info (basso-centro) nel frame di riferimento 1733x975: se un pannello è
# aperto, la zona diventa grigio scuro (bassa saturazione) invece di erba/villaggio.
PANEL_REGION_REF = (700, 750, 1010, 870)
PANEL_S_MAX = 105.0


def panel_region_saturation(image: np.ndarray) -> float:
    """Saturazione media della zona pannello (bassa = pannello probabile)."""
    h, w = image.shape[:2]
    sx, sy = _scale_factors(w, h)
    x0, y0, x1, y1 = PANEL_REGION_REF
    region = image[round(y0 * sy) : round(y1 * sy), round(x0 * sx) : round(x1 * sx)]
    if region.size == 0:
        return 255.0
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


def panel_likely_open(image: np.ndarray, *, s_max: float = PANEL_S_MAX) -> bool:
    """Euristica conservativa: True se nella zona basso-centro sembra esserci un pannello aperto."""
    if image.ndim != 3 or image.shape[2] != 3:
        return False
    return panel_region_saturation(image) < s_max
