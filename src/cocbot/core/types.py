from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class GamePoint:
    """Punto in coordinate CANONICHE del gioco (default 1920x1080, 16:9)."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def aspect(self) -> float:
        return self.w / max(1, self.h)

    def contains(self, p: GamePoint) -> bool:
        return self.x <= p.x < self.right and self.y <= p.y < self.bottom

    def intersects(self, other: Rect) -> bool:
        return not (self.right <= other.x or other.right <= self.x or self.bottom <= other.y or other.bottom <= self.y)


@dataclass(frozen=True, slots=True)
class Viewport:
    """Area del frame in cui il gioco disegna, con spazio canonico associato."""

    rect: Rect
    canonical_width: int = 1920
    canonical_height: int = 1080

    @property
    def aspect(self) -> float:
        return self.rect.aspect

    @property
    def scale(self) -> float:
        return self.rect.w / max(1, self.canonical_width)

    def to_frame_point(self, p: GamePoint) -> tuple[int, int]:
        """Coordinate canoniche -> pixel nel frame (relativi al viewport)."""
        return (
            self.rect.x + round(p.x * self.scale),
            self.rect.y + round(p.y * self.scale),
        )


@dataclass(frozen=True, slots=True)
class Frame:
    """Frame BGR (OpenCV) + metadati."""

    image: np.ndarray
    timestamp: float
    viewport: Viewport
    source: str = "unknown"
    stale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int, int]:
        h, w = self.image.shape[:2]
        return h, w, self.image.shape[2] if self.image.ndim == 3 else 1


@dataclass(frozen=True, slots=True)
class CaptureHealth:
    fps: float = 0.0
    frames: int = 0
    black_frames: int = 0
    stale_frames: int = 0
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class AttachResult:
    ok: bool
    backend: str = ""
    process: str | None = None
    title_masked: str | None = None
    client_size: tuple[int, int] | None = None
    dpi: int | None = None
    error: str | None = None


class ScreenState(StrEnum):
    UNKNOWN = "unknown"
    LOADING = "loading"
    HOME = "home"
    POPUP = "popup"
    EVENT_TRAY = "event_tray"
    BATTLE_MENU = "battle_menu"
    ARMY_REVIEW = "army_review"
    PREVIEW = "preview"
    BATTLE = "battle"
    BATTLE_END = "battle_end"
    BUILD_MENU = "build_menu"
    UPGRADE_CONFIRM = "upgrade_confirm"
    WALL_UPGRADER = "wall_upgrader"
    SHOP = "shop"  # da evitare: GemGuard
    NETWORK_ERROR = "network_error"
    MAINTENANCE = "maintenance"
    UPDATE_REQUIRED = "update_required"
    TUTORIAL = "tutorial"


# Aree in cui NON si deve mai cliccare (GemGuard G1); vengono caricate dal profilo UI.
FORBIDDEN_TAP_ZONES: tuple[Rect, ...] = ()
