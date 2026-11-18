"""Funzioni di formattazione pure usate dalla GUI (testabili senza tkinter)."""
from __future__ import annotations

import json
from typing import Any

GOLD_PER_SEARCH = 1_100  # costo indicativo di una ricerca base / "Next" (validato a runtime)

_PLACEHOLDER = "—"

_GAME_STATE_LABELS = {
    "home": "Home",
    "loading": "Caricamento",
    "unknown": "Sconosciuto",
    "popup": "Pop-up aperto",
    "event_tray": "Eventi",
    "battle_menu": "Menu Battaglia",
    "army_review": "Esercito (My Army)",
    "preview": "Anteprima base",
    "battle": "Battaglia in corso",
    "battle_end": "Risultati battaglia",
    "build_menu": "Menu Costruzioni",
    "upgrade_confirm": "Conferma upgrade",
    "wall_upgrader": "Mura",
    "placement": "Piazzamento",
    "shop": "Shop (da evitare)",
    "network_error": "Errore di rete",
    "maintenance": "Manutenzione",
    "update_required": "Aggiornamento richiesto",
    "tutorial": "Tutorial",
}


def format_number(value: Any, *, placeholder: str = _PLACEHOLDER) -> str:
    """Intero con separatore migliaia italiano (punto): ``9670273`` -> ``9.670.273``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return placeholder
    return f"{number:,}".replace(",", ".")


def format_builder(available: Any, total: Any) -> str:
    """Coppia builder leggibile: ``(3, 6)`` -> ``3/6``; sconosciuta -> ``—``."""
    if available is None or total is None:
        return _PLACEHOLDER
    return f"{format_number(available)}/{format_number(total)}"


def format_duration(seconds: Any) -> str:
    """Durata compatta: ``75`` -> ``1m 15s``; ``3725`` -> ``1h 02m``."""
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return _PLACEHOLDER
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def estimate_attack_gold(searches: Any, *, per_search: int = GOLD_PER_SEARCH) -> int:
    """Stima massima dell'oro speso per le ricerche di un raid (tetto prudente)."""
    try:
        count = max(0, int(searches))
    except (TypeError, ValueError):
        count = 0
    return count * max(0, int(per_search))


def format_gold_estimate(searches: Any, *, per_search: int = GOLD_PER_SEARCH) -> str:
    """Testo breve del costo stimato di un raid: ``~2.200 oro``."""
    return f"~{format_number(estimate_attack_gold(searches, per_search=per_search))} oro"


def format_farm_estimate(cycles: Any, searches: Any, *, per_search: int = GOLD_PER_SEARCH) -> str:
    """Costo stimato complessivo del farm (cicli × ricerche × ~1.100 oro)."""
    try:
        cycle_count = max(0, int(cycles))
    except (TypeError, ValueError):
        cycle_count = 0
    return format_gold_estimate(cycle_count * max(1, int(searches or 1)), per_search=per_search)


def game_state_label(state: Any) -> str:
    """Traduce lo stato del gioco (ScreenState/str) in una etichetta italiana leggibile."""
    value = getattr(state, "value", state)
    return _GAME_STATE_LABELS.get(str(value), str(value) if value else "Sconosciuto")


def parse_last_json_object(text: str) -> dict[str, Any] | None:
    """Estrae l'ultimo oggetto JSON da un output testuale (riga per riga, dall'ultima).

    Serve a interpretare ``probe --json``/``hud --json`` anche quando la CLI stampa prima
    messaggi informativi. Ritorna ``None`` se non trova JSON valido.
    """
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def truncate(text: str, limit: int = 120) -> str:
    """Accorcia un testo mantenendo l'ellissi entro ``limit`` caratteri."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def clamp_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Converte una casella di testo in intero entro i limiti (default se non valido).

    Accetta anche i separatori delle migliaia ("2.200" -> 2200) perché vengono digitati
    spontaneamente nei campi budget.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    cleaned = text.replace(".", "").replace(",", "").replace(" ", "").replace("\u00a0", "")
    try:
        number = int(cleaned)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


__all__ = [
    "GOLD_PER_SEARCH",
    "clamp_int",
    "estimate_attack_gold",
    "format_builder",
    "format_duration",
    "format_farm_estimate",
    "format_gold_estimate",
    "format_number",
    "game_state_label",
    "parse_last_json_object",
    "truncate",
]
