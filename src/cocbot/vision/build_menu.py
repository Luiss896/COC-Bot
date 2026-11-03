"""Lettura delle righe del menu Build ("Buildings & Heroes") e dei dialoghi di conferma.

Il menu Build e' la sorgente primaria per gli upgrade (decisione di progetto): mostra il
catalogo nativo con livello, tempo, costo e valuta di edifici ed eroi, senza livelli/costi
hardcoded.

Strategia di lettura (verificata su frame reali windowed 1733x975):
- il pannello destro viene localizzato da ``ui.find_build_panel``;
- le righe sono segmentate geometricamente dai separatori scuri tra le card
  (``ui.find_row_bands``), quindi una riga e' una banda del pannello;
- l'OCR gira **solo sul pannello** (piu' veloce) e i box vengono riportati in coordinate frame;
- dentro ogni banda: nome = primo testo in zona sinistra, badge livello = numero piccolo a
  sinistra, tempo/costo = testi a destra, "New" = etichetta verde, eventuale descrizione o
  sottotitolo = altri testi in zona sinistra;
- una banda e' una riga valida solo se ha tempo o costo leggibile (le intestazioni di
  sezione non li hanno): valori inaffidabili restano ``None`` e il planner scarta la riga.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from cocbot.vision import ocr as ocr_module
from cocbot.vision import textparse, ui
from cocbot.vision.ocr import TextItem

CURRENCIES = ("gold", "elixir", "dark", "gems", "unknown")

# fasce orizzontali del pannello (frazioni della larghezza del pannello)
_LEVEL_ZONE_MAX = 0.10
_META_ZONE_MIN = 0.55

# icona valuta: slot allineato a destra nella riga (misurato: centro ~0.986 della larghezza)
_CURRENCY_ICON_X = (0.972, 0.997)  # frazione della larghezza frame
_CURRENCY_ICON_HALF_H = 0.014  # mezza altezza dello slot, frazione dell'altezza frame

_HEADER_WORDS = ("buildings", "heroes", "upgrades")


@dataclass(frozen=True, slots=True)
class BuildRow:
    """Riga del menu Build letta dal frame."""

    raw_name: str
    name: str  # nome normalizzato senza quantita'
    count: int
    level: int | None
    time_s: int | None
    cost: int | None
    currency: str
    is_new: bool
    description: str  # descrizione/sottotitolo della riga (se presente)
    tap_x: int  # pixel frame (area nome della riga)
    tap_y: int  # pixel frame (centro della banda)
    scroll_index: int | None = None  # posizione di scroll in cui e' stata vista (dal navigator)

    @property
    def time_hours(self) -> float | None:
        return None if self.time_s is None else self.time_s / 3600.0

    def key(self) -> tuple[str, int | None, int | None, str, bool, str]:
        """Chiave di deduplica tra posizioni di scroll consecutive."""
        return (
            self.name,
            self.level,
            self.cost,
            self.currency,
            self.is_new,
            textparse.normalize(self.description),
        )

    def __str__(self) -> str:
        time_txt = "-" if self.time_s is None else f"{self.time_s}s"
        cost_txt = "-" if self.cost is None else f"{self.cost} {self.currency}"
        level_txt = "?" if self.level is None else str(self.level)
        new_txt = " NEW" if self.is_new else ""
        count_txt = f" x{self.count}" if self.count != 1 else ""
        return f"{self.raw_name}{count_txt} [lv {level_txt}] {time_txt} {cost_txt}{new_txt}"


@dataclass
class DialogInfo:
    """Contenuto letto dal dialogo di conferma upgrade."""

    title: str = ""
    name: str | None = None
    target_level: int | None = None
    cost: int | None = None
    time_s: int | None = None
    confirm_rect: ui.Rect | None = None
    close_point: tuple[int, int] | None = None
    texts: list[TextItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Valuta dall'icona accanto al costo.
# ---------------------------------------------------------------------------
def detect_currency(image: np.ndarray, icon_region: ui.Rect) -> str:
    """Classifica la valuta dell'icona accanto al costo: gold | elixir | dark | unknown.

    L'icona occupa uno slot allineato a destra nella riga. Le maschere cromatiche sono
    strette per distinguere le monete dal fondo bruno delle card:
    - oro: giallo brillante (H 18-35, S>130, V>150);
    - elisir: magenta (H 137-175, S>120, V>110);
    - elisir nero: viola scuro (H 100-175, S>50, V<115).

    Le gemme non sono mai un costo di upgrade valido (GemGuard): un'icona non
    riconosciuta restituisce ``unknown`` e la riga viene scartata dal planner.
    """
    x0, y0 = max(0, icon_region.x), max(0, icon_region.y)
    x1, y1 = min(image.shape[1], icon_region.right), min(image.shape[0], icon_region.bottom)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return "unknown"
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].astype(np.int32)
    sat = hsv[:, :, 1].astype(np.int32)
    val = hsv[:, :, 2].astype(np.int32)
    scores = {
        "gold": int(np.count_nonzero((hue >= 18) & (hue <= 35) & (sat > 130) & (val > 150))),
        "elixir": int(np.count_nonzero((hue >= 137) & (hue <= 175) & (sat > 120) & (val > 110))),
        "dark": int(np.count_nonzero((hue >= 100) & (hue <= 175) & (sat > 50) & (val < 115))),
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] >= 25 else "unknown"


# ---------------------------------------------------------------------------
# Lettura righe.
# ---------------------------------------------------------------------------
def _panel_zone(panel: ui.Rect, item: TextItem) -> str:
    """Classifica la posizione orizzontale del box OCR dentro il pannello."""
    if panel.w <= 0:
        return "name"
    rel = (item.x0 - panel.x) / panel.w
    rel_right = (item.x1 - panel.x) / panel.w
    if rel < _LEVEL_ZONE_MAX and item.width < panel.w * 0.09:
        return "level"
    if rel_right > _META_ZONE_MIN and rel > 0.45:
        return "meta"
    return "name"


def _currency_icon_region(image: np.ndarray, cost_item: TextItem) -> ui.Rect:
    h, w = image.shape[:2]
    x0 = int(w * _CURRENCY_ICON_X[0])
    x1 = int(w * _CURRENCY_ICON_X[1])
    half = max(6, int(h * _CURRENCY_ICON_HALF_H))
    y0 = max(0, cost_item.cy - half)
    y1 = min(h - 1, cost_item.cy + half)
    return ui.Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))


def _is_header_text(text: str) -> bool:
    normalized = textparse.normalize(text)
    if not normalized:
        return False
    if textparse.is_section_header(normalized):
        return True
    return any(word in normalized for word in _HEADER_WORDS) and len(normalized) < 40


def _estimate_pitch(items: list[TextItem], panel: ui.Rect) -> float:
    """Stima il passo verticale tra righe dai costi (una riga = un costo)."""
    ys = sorted(item.cy for item in items)
    diffs = [b - a for a, b in zip(ys, ys[1:], strict=False) if b - a > 0]
    if diffs:
        pitch = float(np.median(diffs))
        if 0.03 * panel.h <= pitch <= 0.25 * panel.h:
            return pitch
    return 0.082 * panel.h


def _build_rows_from_items(image: np.ndarray, panel: ui.Rect, items: list[TextItem]) -> list[BuildRow]:
    """Costruisce le righe a partire dai box OCR del pannello.

    Ancora di ogni riga = il nome. Alcune righe hanno un sottotitolo ("Crafting
    Station" + "Hot Candle Damage"): due testi in zona nome molto vicini sono nome +
    sottotitolo, non due righe. Gli altri box vengono assegnati alla riga il cui nome e'
    il piu' vicino sopra (il nome e' il primo elemento della riga).
    """
    name_items: list[TextItem] = []
    level_items: list[TextItem] = []
    time_items: list[TextItem] = []
    cost_items: list[TextItem] = []
    new_items: list[TextItem] = []
    description_items: list[TextItem] = []

    for item in items:
        normalized = textparse.normalize(item.text)
        if not normalized:
            continue
        if _is_header_text(item.text):
            continue
        if normalized == "new":
            new_items.append(item)
            continue
        zone = _panel_zone(panel, item)
        if zone == "level" and textparse.parse_level(item.text) is not None:
            level_items.append(item)
            continue
        if zone == "meta":
            if textparse.is_time_text(item.text):
                time_items.append(item)
                continue
            if textparse.parse_amount(item.text) is not None:
                cost_items.append(item)
                continue
        stripped = item.text.strip()
        if stripped.endswith(".") and len(normalized) > 10:
            description_items.append(item)
            continue
        # frammenti OCR delle icone/badge: troppo piccoli per essere un nome o un sottotitolo
        if item.width < 0.10 * panel.w or item.height < 0.012 * panel.h:
            continue
        name_items.append(item)

    if not name_items:
        return []
    pitch = _estimate_pitch(cost_items, panel)

    # ancore: nome + eventuale sottotitolo della stessa riga
    name_items.sort(key=lambda item: item.y0)
    anchors: list[TextItem] = []
    subtitles: dict[int, list[str]] = {}
    for item in name_items:
        if anchors and (item.y0 - anchors[-1].y0) < 0.55 * pitch:
            subtitles.setdefault(len(anchors) - 1, []).append(item.text.strip())
        else:
            anchors.append(item)
    if not anchors:
        return []

    def owner_index(item: TextItem) -> int:
        """Indice della riga a cui appartiene il box (nome piu' vicino sopra)."""
        best = 0
        for index, anchor in enumerate(anchors):
            if anchor.y0 <= item.y0 + 12:
                best = index
            else:
                break
        return best

    states: list[dict] = [
        {"level": None, "time_s": None, "cost_item": None, "is_new": False, "description": ""}
        for _anchor in anchors
    ]
    for item in level_items:
        states[owner_index(item)]["level"] = textparse.parse_level(item.text)
    for item in time_items:
        index = owner_index(item)
        if states[index]["time_s"] is None:
            states[index]["time_s"] = textparse.parse_duration(item.text)
    for item in cost_items:
        index = owner_index(item)
        if states[index]["cost_item"] is None:
            states[index]["cost_item"] = item
    for item in new_items:
        states[owner_index(item)]["is_new"] = True
    for item in description_items:
        index = owner_index(item)
        if not states[index]["description"]:
            states[index]["description"] = item.text.strip()
    for index, extra in subtitles.items():
        joined = " ".join(text for text in extra if text)
        if states[index]["description"]:
            states[index]["description"] = f"{joined} {states[index]['description']}".strip()
        else:
            states[index]["description"] = joined

    rows: list[BuildRow] = []
    for index, (anchor, state) in enumerate(zip(anchors, states, strict=False)):
        # guardia: una riga vera ha almeno un tempo o un costo (le intestazioni no)
        if state["time_s"] is None and state["cost_item"] is None:
            continue
        if index + 1 < len(anchors):
            tap_y = int((anchor.y0 + anchors[index + 1].y0) / 2)
        else:
            tap_y = int(anchor.y0 + 0.45 * pitch)
        tap_y = max(panel.y + 4, min(panel.bottom - 4, tap_y))
        raw_name = anchor.text.strip()
        name, count = textparse.split_name_count(raw_name)
        cost_item: TextItem | None = state["cost_item"]
        cost = textparse.parse_amount(cost_item.text) if cost_item is not None else None
        currency = (
            detect_currency(image, _currency_icon_region(image, cost_item)) if cost_item is not None else "unknown"
        )
        rows.append(
            BuildRow(
                raw_name=raw_name,
                name=name,
                count=count,
                level=state["level"],
                time_s=state["time_s"],
                cost=cost,
                currency=currency,
                is_new=bool(state["is_new"]),
                description=state["description"],
                tap_x=int(panel.x + 0.35 * panel.w),
                tap_y=tap_y,
            )
        )
    return rows


def read_rows(
    image: np.ndarray,
    *,
    texts: list[TextItem] | None = None,
    use_ocr: bool = True,
) -> list[BuildRow]:
    """Legge le righe visibili del menu Build da un frame (``[]`` se il menu non c'e')."""
    if image is None or image.size == 0:
        return []
    panel = ui.find_build_panel(image)
    if panel is None:
        return []
    items = texts
    if items is None:
        if not use_ocr:
            return []
        items = ocr_module.read_texts(
            image[panel.y : panel.bottom, panel.x : panel.right],
            offset=(panel.x, panel.y),
        )
    if not items:
        return []
    return _build_rows_from_items(image, panel, items)


# ---------------------------------------------------------------------------
# Dialogo di conferma upgrade.
# ---------------------------------------------------------------------------
def _parse_dialog_title(title: str) -> tuple[str | None, int | None]:
    """Estrae nome e livello target da "Upgrade <X> to Level <N>?"."""
    normalized = textparse.normalize(title)
    prefix = "upgrade "
    suffix = " to level "
    start = normalized.find(prefix)
    end = normalized.find(suffix)
    if start != 0 or end <= len(prefix):
        return None, None
    name = normalized[len(prefix) : end].strip()
    tail = normalized[end + len(suffix) :].strip(" ?!.")
    try:
        level = int(tail)
    except ValueError:
        level = None
    return (name or None), level


def read_dialog(
    image: np.ndarray,
    *,
    texts: list[TextItem] | None = None,
    use_ocr: bool = True,
) -> DialogInfo:
    """Legge il dialogo di conferma upgrade ("Upgrade <X> to Level <N>?").

    Va chiamata solo se ``ui.find_dialog_close`` ha rilevato il dialogo. I campi non
    riconosciuti restano ``None``: il chiamante NON deve eseguire l'upgrade se
    titolo/costo non corrispondono all'atteso.

    Costo e tempo sono letti direttamente dentro il pulsante CONFIRM e nel blocco
    "Upgrade time" a destra: cosi' si evita il prezzo barrato del Gold Pass
    (piu' in alto) e il tempo barrato (sotto il tempo corrente).
    """
    info = DialogInfo()
    info.close_point = ui.find_dialog_close(image)
    info.confirm_rect = ui.find_confirm_button(image)
    if not use_ocr:
        return info
    h, w = image.shape[:2]

    # 1) titolo: zona centro-sinistra del dialogo (esclusa la fascia menu Build a destra)
    offset_x, offset_y = int(w * 0.08), int(h * 0.02)
    crop = image[offset_y : int(h * 0.98), offset_x : int(w * 0.80)]
    items = texts
    if items is None:
        items = ocr_module.read_texts(crop, offset=(offset_x, offset_y))
    info.texts = items
    for item in items:
        normalized = textparse.normalize(item.text)
        if "upgrade" in normalized and "level" in normalized and normalized.startswith("upgrade"):
            info.title = item.text.strip()
            info.name, info.target_level = _parse_dialog_title(info.title)
            break

    # 2) costo: numero dentro il pulsante verde CONFIRM
    if info.confirm_rect is not None:
        rect = info.confirm_rect
        button_crop = image[rect.y : rect.bottom, rect.x : rect.right]
        button_items = ocr_module.read_texts(button_crop, offset=(rect.x, rect.y))
        amounts = [textparse.parse_amount(item.text) for item in button_items]
        amounts = [amount for amount in amounts if amount is not None]
        if amounts:
            info.cost = max(amounts)

        # 3) tempo: blocco "Upgrade time" a destra del CONFIRM; il tempo corrente e'
        #    il primo valore (in alto), il barrato del Gold Pass sta sotto
        time_x0 = min(w - 2, rect.right + int(w * 0.006))
        time_y0 = max(0, rect.y - int(h * 0.03))
        time_y1 = min(h - 1, rect.bottom + int(h * 0.04))
        time_crop = image[time_y0:time_y1, time_x0 : int(w * 0.94)]
        time_items = ocr_module.read_texts(time_crop, offset=(time_x0, time_y0))
        durations = [
            (item.cy, textparse.parse_duration(item.text))
            for item in time_items
            if textparse.parse_duration(item.text) is not None
        ]
        if durations:
            durations.sort()
            info.time_s = durations[0][1]
    return info


__all__ = ["BuildRow", "CURRENCIES", "DialogInfo", "detect_currency", "read_dialog", "read_rows"]
