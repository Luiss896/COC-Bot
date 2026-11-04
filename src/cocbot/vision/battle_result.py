"""Lettura della schermata risultati di battaglia ("Victory"/"Defeat" + bottino).

Layout verificato sui frame reali (4 nov, finestra 1733×975):
- "Total damage:" in alto (~0,124 H) con la percentuale subito sotto (~0,161 H);
- banner "Victory"/"Defeat" al centro (~0,29 H);
- "You got:" (~0,414 H) e poi i tre importi in ordine **oro, elisir, dark** (~0,46/0,53/0,59 H);
- "Troops expended:" (~0,655 H) con le card truppa (testo "xN").

Il parser e' **puro** (``parse_result_items``) + un wrapper OCR (``read_result``); come sempre
i campi non riconosciuti restano ``None`` (non si indovina).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cocbot.vision import ocr as ocr_module
from cocbot.vision import textparse

# regione OCR della schermata risultati (frazioni del frame): banner, danno, bottino, truppe
RESULT_OCR_REGION = (0.22, 0.08, 0.56, 0.64)  # (x, y, w, h)
# regione OCR del "Overall Damage: N%" in basso a destra durante la battaglia
BATTLE_DAMAGE_REGION = (0.86, 0.72, 0.13, 0.10)  # (x, y, w, h)


@dataclass(frozen=True, slots=True)
class BattleResult:
    """Esito letto dalla schermata risultati di battaglia."""

    outcome: str | None  # "victory" | "defeat" | None
    damage_pct: int | None
    loot_gold: int | None
    loot_elixir: int | None
    loot_dark: int | None
    troops_expended: int | None
    notes: tuple[str, ...] = ()


def parse_result_items(items, *, frame_height: int | None = None) -> BattleResult:
    """Estrae esito/danno/bottino/truppe dai testi OCR della schermata risultati.

    Ordine dei testi: banner (Victory/Defeat), "Total damage: N%", "You got:" con 3 importi
    (oro, elisir, dark), "Troops expended:" con card "xN". Funzione pura e testabile.
    ``frame_height`` (pixel) limita la ricerca del bottino alle righe vicine a "You got:".
    """
    notes: list[str] = []
    outcome: str | None = None
    damage_pct: int | None = None
    loot: list[int] = []
    troops: int | None = None

    for item in items:
        normalized = textparse.normalize(item.text)
        if normalized in ("victory", "defeat"):
            outcome = normalized
        percent = textparse.parse_percent(item.text)
        if percent is not None and damage_pct is None:
            damage_pct = percent

    # bottino: importi sotto "You got:" (in ordine oro, elisir, dark)
    max_gap = (0.30 * frame_height) if frame_height else 0.30 * 300
    you_got = next(
        (item for item in items if "you got" in textparse.normalize(item.text)),
        None,
    )
    if you_got is not None:
        amounts = []
        for item in items:
            if item.cy <= you_got.cy or (item.cy - you_got.cy) > max_gap:
                continue
            amount = textparse.parse_amount(item.text)
            if amount is not None:
                amounts.append((item.cy, amount))
        amounts.sort()
        loot = [amount for _cy, amount in amounts][:3]
        if len(loot) < 2:
            notes.append(f"bottino: letti {len(loot)} importi su 3")
    else:
        # fallback: alcuni risultati (es. vittoria) non mostrano l'etichetta "You got:":
        # si cercano gli importi nella fascia centrale, sotto il danno e sopra le truppe.
        notes.append("etichetta 'You got:' assente: importi stimati per posizione")
        if frame_height:
            low = 0.33 * frame_height
            high = 0.72 * frame_height
            amounts = []
            for item in items:
                if not (low < item.cy < high):
                    continue
                amount = textparse.parse_amount(item.text)
                if amount is not None and amount >= 1_000:
                    amounts.append((item.cy, amount))
            amounts.sort()
            loot = [amount for _cy, amount in amounts][:3]

    # truppe: somma dei contatori "xN" sotto "Troops expended:"
    troops_label = next(
        (item for item in items if "troops expended" in textparse.normalize(item.text)),
        None,
    )
    if troops_label is not None:
        counters = [
            textparse.parse_level(textparse.normalize(item.text).lstrip("x"))
            for item in items
            if item.cy > troops_label.cy and textparse.normalize(item.text).startswith("x")
        ]
        values = [value for value in counters if value is not None]
        if values:
            troops = sum(values)

    if outcome is None:
        notes.append("banner Victory/Defeat non riconosciuto")
    if damage_pct is None:
        notes.append("percentuale danno non riconosciuta")

    gold, elixir, dark = (loot + [None, None, None])[:3]
    return BattleResult(
        outcome=outcome,
        damage_pct=damage_pct,
        loot_gold=gold,
        loot_elixir=elixir,
        loot_dark=dark,
        troops_expended=troops,
        notes=tuple(notes),
    )


def result_region(image: np.ndarray) -> tuple[int, int, int, int]:
    """Rettangolo (x, y, w, h) in pixel della regione OCR della schermata risultati."""
    h, w = image.shape[:2]
    x, y, width, height = RESULT_OCR_REGION
    return int(x * w), int(y * h), int(width * w), int(height * h)


def read_result(image: np.ndarray, *, texts=None) -> BattleResult:
    """Legge la schermata risultati (OCR ~0,9 s) e ne estrae esito/danno/bottino/truppe."""
    x, y, width, height = result_region(image)
    items = texts
    if items is None:
        items = ocr_module.read_texts(
            image[y : y + height, x : x + width],
            offset=(x, y),
        )
    return parse_result_items(items, frame_height=int(image.shape[0]))


def read_overall_damage(image: np.ndarray) -> int | None:
    """Legge "Overall Damage: N%" mostrato in basso a destra durante la battaglia.

    OCR su regione piccola (~0,15 s); ``None`` se la percentuale non e' leggibile (es. frame
    non di battaglia). Usata per l'early-exit quando il danno obiettivo e' raggiunto.
    """
    h, w = image.shape[:2]
    x, y, width, height = BATTLE_DAMAGE_REGION
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int((x + width) * w), int((y + height) * h)
    items = ocr_module.read_texts(image[y0:y1, x0:x1], offset=(x0, y0))
    for item in items:
        percent = textparse.parse_percent(item.text)
        if percent is not None:
            return percent
    return None


__all__ = [
    "BATTLE_DAMAGE_REGION",
    "RESULT_OCR_REGION",
    "BattleResult",
    "parse_result_items",
    "read_overall_damage",
    "read_result",
    "result_region",
]
