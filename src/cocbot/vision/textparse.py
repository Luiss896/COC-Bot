"""Parsing del testo di gioco (interfaccia in inglese) in valori strutturati.

Tutto il testo letto con OCR passa da qui: numeri con separatori di migliaia, tempi
("1d", "2h 30m", "30m 0s"), livelli e nomi delle righe del menu Build ("Wall x 284").

Le funzioni sono pure (nessun I/O) e restituiscono ``None`` quando il testo non e'
interpretabile: i chiamanti devono trattare ``None`` come "non noto" e NON indovinare.
"""
from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")
# separatori che l'OCR inserisce/confonde nei numeri: spazi, NBSP, virgola, punto, apostrofo, trattino
_AMOUNT_SEPARATORS = re.compile(r"[\s\u00a0\u2009,.\-']+")
_DURATION_TOKEN = re.compile(r"(\d+)\s*([dhms])")
_LEVEL = re.compile(r"^\d{1,3}$")
_NAME_WITH_COUNT = re.compile(r"^(?P<name>.+?)\s+x\s*(?P<count>\d{1,4})$", re.IGNORECASE)

_UNIT_SECONDS = {"d": 86_400, "h": 3_600, "m": 60, "s": 1}

# nomi delle sezioni del menu Build (righe non cliccabili, da ignorare)
SECTION_HEADERS = frozenset(
    {
        "suggested upgrades",
        "other upgrades",
        "buildings heroes",
        "buildings & heroes",
        "suggested upgrade",
    }
)


def normalize(text: str) -> str:
    """Normalizza per il confronto: minuscole, spazi compattati, niente spazi ai bordi."""
    return _SPACES.sub(" ", (text or "").strip()).lower()


def parse_amount(text: str) -> int | None:
    """Interpreta un numero di gioco (es. ``"2 500 000"`` -> ``2500000``).

    L'OCR a volte perde uno spazio e legge ``"2500 000"``, oppure confonde lo spazio con
    un trattino (``"195-103"``): entrambi vengono normalizzati. Restituisce ``None`` se
    il testo contiene altro (lettere, simboli, unita' di tempo) o se il valore e'
    implausibile (> 9 cifre).
    """
    if not text:
        return None
    cleaned = _AMOUNT_SEPARATORS.sub("", text)
    if not cleaned.isdigit() or len(cleaned) > 9:
        return None
    return int(cleaned)


def parse_duration(text: str) -> int | None:
    """Interpreta una durata di gioco in secondi (``"1d"``, ``"2h 30m"``, ``"30m 0s"``).

    Restituisce ``None`` se il testo non e' composto *solo* da token <numero><unita'>
    (d/h/m/s), quindi anche per testi misti tipo "2H 30M + 10%".
    """
    if not text:
        return None
    compact = normalize(text).replace(" ", "")
    if not compact:
        return None
    position = 0
    total = 0
    found = False
    for match in _DURATION_TOKEN.finditer(compact):
        if match.start() != position:
            return None
        found = True
        total += int(match.group(1)) * _UNIT_SECONDS[match.group(2)]
        position = match.end()
    if not found or position != len(compact):
        return None
    return total


def parse_level(text: str) -> int | None:
    """Interpreta il numero del badge livello (1-3 cifre, valore plausibile)."""
    if not text:
        return None
    cleaned = normalize(text).strip("()[] ")
    if not _LEVEL.match(cleaned):
        return None
    value = int(cleaned)
    return value if 0 <= value <= 200 else None


def split_name_count(text: str) -> tuple[str, int]:
    """Separa il nome dall'eventuale quantita' (``"Wall x 284"`` -> ``("wall", 284)``)."""
    normalized = normalize(text)
    match = _NAME_WITH_COUNT.match(normalized)
    if match:
        return normalize(match.group("name")), int(match.group("count"))
    return normalized, 1


def is_section_header(text: str) -> bool:
    """True se il testo e' un'intestazione di sezione del menu Build."""
    normalized = normalize(text)
    return normalized in SECTION_HEADERS


def is_time_text(text: str) -> bool:
    """True se il testo sembra una durata (per classificare i box OCR della riga)."""
    return parse_duration(text) is not None


def is_amount_text(text: str) -> bool:
    """True se il testo sembra un importo (per classificare i box OCR della riga)."""
    return parse_amount(text) is not None


__all__ = [
    "SECTION_HEADERS",
    "is_amount_text",
    "is_section_header",
    "is_time_text",
    "normalize",
    "parse_amount",
    "parse_duration",
    "parse_level",
    "split_name_count",
]
