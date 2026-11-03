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

# margini UI (pixel del frame client): barra risorse in alto, pulsanti in basso, icone ai lati
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


def grass_mask(image: np.ndarray, *, apply_ui_margins: bool = False) -> np.ndarray:
    """Maschera dell'erba chiara della mappa (uint8 0/255)."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"atteso frame BGR HxWx3, ricevuto {image.shape}")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GRASS_HSV_LOW, GRASS_HSV_HIGH)
    if apply_ui_margins:
        h, w = mask.shape[:2]
        mask[:UI_MARGIN_TOP, :] = 0
        mask[h - UI_MARGIN_BOTTOM :, :] = 0
        mask[:, :UI_MARGIN_LEFT] = 0
        mask[:, w - UI_MARGIN_RIGHT :] = 0
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
    grass_frac = float((grass_mask(image) > 0).mean())
    left = image[h - 140 :, :200]
    right = image[h - 140 :, w - 220 :]
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
    """Sceglie un punto sul quale un tap e' sicuro (erba vuota, lontano da UI/zone proibite).

    Ritorna coordinate CANONICHE (1920x1080) o ``None`` se non trova un punto affidabile.
    """
    mask = grass_mask(image, apply_ui_margins=True)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    if int(mask.sum()) == 0:
        return None
    h, w = mask.shape[:2]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    components = sorted(
        ((int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)),
        reverse=True,
    )
    candidates: list[tuple[int, int]] = []
    for area, idx in components:
        if area < MIN_COMPONENT_AREA:
            continue
        comp = (labels == idx).astype(np.uint8)
        dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
        _, _, _, (cx, cy) = cv2.minMaxLoc(dist)
        r = PATCH_RADIUS
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
