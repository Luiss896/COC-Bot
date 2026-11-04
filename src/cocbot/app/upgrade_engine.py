"""Engine upgrade dal menu Build: scansione catalogo, pianificazione, esecuzione verificata.

Flusso (decisione di progetto: il menu Build e' il flusso primario, eroi inclusi):
1. ``read_hud`` legge oro/elisir/elisir nero/gemme e i builder liberi dalla home (OCR);
2. ``scan`` apre il menu Build, scorre la lista fino in fondo, legge ogni riga
   (``build_menu.read_rows``) e chiude il menu, senza mai premere righe;
3. ``plan`` filtra le righe (nome riconosciuto, niente "New", costo/tempo/valuta noti,
   risorse sufficienti, builder libero) e ordina per priorita' di categoria;
4. ``execute`` (solo con ``dry_run=False``) naviga alla riga, apre il dialogo di conferma,
   **verifica** nome/livello/costo letti dal dialogo e solo allora preme il pulsante verde
   CONFIRM; poi verifica che il builder sia stato consumato e chiude il menu.

Sicurezza (GemGuard / regole di progetto):
- ``dry_run`` e' il default: nessuna spesa;
- il pulsante "Hammer of Building" non viene mai premuto (si preme solo il CONFIRM verde);
- se un dialogo non corrisponde all'atteso (nome/livello/costo) l'esecuzione si ferma;
- gli edifici "New" (piazzamento) e le mura sono esclusi dalla v1 (flussi non validati);
- nessun tap sulla mappa: la chiusura usa solo X di menu/dialogo e il pulsante Build.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np

from cocbot.capture import win32
from cocbot.capture.input_winmsg import WinMsgSink
from cocbot.capture.screen_wgc import WgcScreenSource
from cocbot.capture.window import GameWindow, find_game_window
from cocbot.config.models import Config, WallMode
from cocbot.core.types import ScreenState
from cocbot.vision import build_menu, states, textparse, ui
from cocbot.vision import ocr as ocr_module

WM_MOUSEWHEEL = 0x020A

# priorita' predefinita scelta dall'utente (3 nov 2026): mura -> difese -> offensiva -> eroi
DEFAULT_PRIORITY = ("walls", "defense", "army", "heroes", "resources", "other")

# categorie per parola chiave nel nome (minuscolo). "other" = riconosciuto ma non prioritario.
CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "heroes",
        (
            "barbarian king",
            "archer queen",
            "grand warden",
            "royal champion",
            "minion prince",
            "dragon duke",
        ),
    ),
    ("walls", ("wall",)),
    (
        "army",
        (
            "army camp",
            "barracks",
            "dark barracks",
            "spell factory",
            "dark spell factory",
            "laboratory",
            "workshop",
            "blacksmith",
            "pet house",
            "siege workshop",
        ),
    ),
    (
        "resources",
        (
            "gold mine",
            "elixir collector",
            "gold storage",
            "elixir storage",
            "dark elixir drill",
            "dark elixir storage",
            "gem mine",
            "builder's hut",
            "builders hut",
        ),
    ),
    (
        "defense",
        (
            "cannon",
            "archer tower",
            "mortar",
            "air defense",
            "wizard tower",
            "inferno tower",
            "x-bow",
            "x bow",
            "eagle artillery",
            "hidden tesla",
            "bomb tower",
            "giant bomb",
            "air bomb",
            "seeking air mine",
            "spring trap",
            "tornado trap",
            "skeleton trap",
            "bomb",
            "scattershot",
            "monolith",
            "spell tower",
            "multi-archer tower",
            "multi mortar",
            "firespitter",
            "town hall",
            "clan castle",
        ),
    ),
    ("other", ("crafting station",)),
)

_BUILDERS_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")


class UpgradeEngineError(RuntimeError):
    """Errore bloccante dell'engine (stato inatteso, OCR assente, finestra non valida)."""


@dataclass(frozen=True)
class HudRead:
    """Risorse e builder letti dalla home."""

    gold: int | None = None
    elixir: int | None = None
    dark: int | None = None
    gems: int | None = None
    builders_available: int | None = None
    builders_total: int | None = None
    notes: tuple[str, ...] = ()

    def amount(self, currency: str) -> int | None:
        return {"gold": self.gold, "elixir": self.elixir, "dark": self.dark, "gems": self.gems}.get(currency)

    @property
    def builders_known(self) -> bool:
        return self.builders_available is not None and self.builders_total is not None

    @property
    def has_free_builder(self) -> bool:
        return (self.builders_available or 0) > 0

    def __str__(self) -> str:
        def fmt(value: int | None) -> str:
            return "?" if value is None else f"{value:,}".replace(",", " ")

        return (
            f"oro={fmt(self.gold)} elisir={fmt(self.elixir)} dark={fmt(self.dark)} gemme={fmt(self.gems)} "
            f"| builder={self.builders_available}/{self.builders_total}"
        )


@dataclass(frozen=True)
class UpgradeCandidate:
    """Riga candidata per un upgrade."""

    row: build_menu.BuildRow
    category: str
    priority_index: int

    def __str__(self) -> str:
        return f"[{self.category}] {self.row}"


@dataclass(frozen=True)
class SkippedRow:
    row: build_menu.BuildRow
    reason: str


@dataclass
class UpgradePlan:
    """Piano di upgrade calcolato dalla lista (nessuna azione eseguita qui)."""

    hud: HudRead
    scanned_rows: int
    candidates: list[UpgradeCandidate] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    chosen: list[UpgradeCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hud": asdict(self.hud),
            "scanned_rows": self.scanned_rows,
            "chosen": [
                {
                    "name": item.row.name,
                    "category": item.category,
                    "level": item.row.level,
                    "cost": item.row.cost,
                    "currency": item.row.currency,
                    "time_s": item.row.time_s,
                    "scroll_index": item.row.scroll_index,
                }
                for item in self.chosen
            ],
            "candidates": [str(item) for item in self.candidates],
            "skipped": [{"row": str(item.row), "reason": item.reason} for item in self.skipped],
            "notes": self.notes,
        }


@dataclass
class ScanReport:
    """Risultato della scansione del menu Build."""

    hud: HudRead
    rows: list[build_menu.BuildRow]
    positions: int
    elapsed_s: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hud": asdict(self.hud),
            "positions": self.positions,
            "elapsed_s": round(self.elapsed_s, 2),
            "rows": [
                {
                    "name": row.name,
                    "raw_name": row.raw_name,
                    "level": row.level,
                    "count": row.count,
                    "cost": row.cost,
                    "currency": row.currency,
                    "time_s": row.time_s,
                    "is_new": row.is_new,
                    "description": row.description,
                    "scroll_index": row.scroll_index,
                }
                for row in self.rows
            ],
            "notes": self.notes,
        }


@dataclass
class ExecutionResult:
    """Esito dell'esecuzione di un upgrade."""

    row: build_menu.BuildRow
    ok: bool
    reason: str = ""
    dialog_cost: int | None = None
    hud_after: HudRead | None = None


def categorize(name: str) -> str | None:
    """Categoria dell'edificio/eroe dal nome normalizzato; ``None`` se non riconosciuto.

    ``None`` e' intenzionale: un nome OCR sbagliato non deve diventare un candidato. I soli
    errori OCR "di poco" sui nomi noti vengono recuperati dal match fuzzy di
    :func:`canonical_name` (conservativo: solo nomi lunghi, similarita' alta).
    """
    return _canonical_building(name)[1]


# parole chiave troppo corte producono falsi positivi nel match fuzzy: si escludono
_FUZZY_MIN_KEYWORD_LEN = 6
_FUZZY_MIN_RATIO = 0.86


def _canonical_building(name: str) -> tuple[str, str | None]:
    """(nome canonico, categoria) per una riga del catalogo; categoria ``None`` se ignota.

    Prima si cerca la parola chiave esatta (comportamento storico, nessun rischio). Solo se non
    c'e' match si prova un match fuzzy molto prudente sui nomi noti lunghi: recupera errori tipo
    ``"Craftina Station"`` -> ``"Crafting Station"`` senza inventare categorie per nomi sporchi.
    """
    normalized = textparse.normalize(name)
    if not normalized:
        return "", None
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return normalized, category
    best: tuple[float, str, str] | None = None
    for category, keywords in CATEGORY_KEYWORDS:
        for keyword in keywords:
            if len(keyword) < _FUZZY_MIN_KEYWORD_LEN:
                continue
            ratio = difflib.SequenceMatcher(None, normalized, keyword).ratio()
            if ratio >= _FUZZY_MIN_RATIO and (best is None or ratio > best[0]):
                best = (ratio, keyword, category)
    if best is not None:
        return best[1], best[2]
    return normalized, None


def canonical_name(name: str) -> str:
    """Nome canonico per merge e confronti tra letture OCR (fallback: nome normalizzato)."""
    return _canonical_building(name)[0]


def _row_matches(page_row: build_menu.BuildRow, target: build_menu.BuildRow) -> bool:
    """Stessa riga del piano: nome canonico (tollera OCR sporco), costo e valuta uguali."""
    return (
        canonical_name(page_row.name) == canonical_name(target.name)
        and page_row.cost == target.cost
        and page_row.currency == target.currency
    )


def priority_list(config: Config) -> tuple[str, ...]:
    """Ordine di priorita' delle categorie (config, con fallback sicuro)."""
    configured = tuple(str(item).lower() for item in (config.upgrade.priority or ()))
    if not configured:
        return DEFAULT_PRIORITY
    known = {category for category, _ in CATEGORY_KEYWORDS} | {"other"}
    ordered = tuple(item for item in configured if item in known)
    remaining = tuple(item for item in DEFAULT_PRIORITY if item not in ordered)
    return ordered + remaining


def _normalize_name(name: str) -> str:
    return textparse.normalize(name).replace("&", "and")


def _row_quality(row: build_menu.BuildRow) -> int:
    """Quanti campi utili sono stati letti (per preferire la lettura migliore)."""
    score = 0
    score += 1 if row.level is not None else 0
    score += 1 if row.time_s is not None else 0
    score += 1 if row.cost is not None else 0
    score += 1 if row.currency not in ("unknown", "") else 0
    score += 1 if row.description else 0
    return score


def _same_row(first: build_menu.BuildRow, second: build_menu.BuildRow) -> bool:
    """True se due letture descrivono la stessa riga della lista (anche se parziali)."""
    if canonical_name(first.name) != canonical_name(second.name):
        return False
    if first.is_new != second.is_new:
        return False
    if first.cost is not None and second.cost is not None and first.cost != second.cost:
        return False
    first_currency_known = first.currency not in ("unknown", "")
    second_currency_known = second.currency not in ("unknown", "")
    if first_currency_known and second_currency_known and first.currency != second.currency:
        return False
    if first.level is not None and second.level is not None and first.level != second.level:
        return False
    if first.time_s is not None and second.time_s is not None and first.time_s != second.time_s:
        return False
    first_desc = textparse.normalize(first.description)
    second_desc = textparse.normalize(second.description)
    return not (first_desc and second_desc and first_desc != second_desc)


def _merge_pair(first: build_menu.BuildRow, second: build_menu.BuildRow) -> build_menu.BuildRow:
    """Unisce due letture della stessa riga: vince la lettura di qualita' migliore, campo per campo."""
    best = first if _row_quality(first) >= _row_quality(second) else second
    other = second if best is first else first
    return replace(
        best,
        name=canonical_name(best.name),
        level=best.level if best.level is not None else other.level,
        time_s=best.time_s if best.time_s is not None else other.time_s,
        cost=best.cost if best.cost is not None else other.cost,
        currency=best.currency if best.currency not in ("unknown", "") else other.currency,
        description=best.description or other.description,
        scroll_index=best.scroll_index if best.scroll_index is not None else other.scroll_index,
    )


def merge_rows(rows: list[build_menu.BuildRow]) -> list[build_menu.BuildRow]:
    """Fonde le letture multiple della stessa riga (una riga e' visibile a scroll adiacenti)."""
    merged: list[build_menu.BuildRow] = []
    for row in rows:
        for index, candidate in enumerate(merged):
            if _same_row(candidate, row):
                merged[index] = _merge_pair(candidate, row)
                break
        else:
            merged.append(row)
    return merged


def walls_status(report: ScanReport) -> str:
    """Stato delle mura dedotto dalla scansione: ``"max"``, ``"available"`` o ``"unknown"``.

    Nel catalogo le mura al massimo compaiono senza costo (badge "MAX"): nessuna riga con
    costo -> sono max. Se non e' stata letta alcuna riga mura restituisce ``"unknown"`` e il
    planner resta prudente (preset A: builder riservato).
    """
    wall_rows = [row for row in report.rows if categorize(row.name) == "walls"]
    if not wall_rows:
        return "unknown"
    return "available" if any(row.cost is not None for row in wall_rows) else "max"


def build_plan(config: Config, report: ScanReport) -> UpgradePlan:
    """Calcola il piano di upgrade da una scansione (funzione pura, testabile offline)."""
    plan = UpgradePlan(hud=report.hud, scanned_rows=len(report.rows))
    if not config.upgrade.enabled:
        plan.notes.append("upgrade.enabled=false: nessun upgrade pianificato")
        return plan
    priority = priority_list(config)
    reserves = config.upgrade.reserves or {}
    ignore = {str(item).lower() for item in config.upgrade.ignore_categories}

    for row in report.rows:
        category = categorize(row.name)
        if category is None:
            plan.skipped.append(SkippedRow(row, "nome non riconosciuto (OCR/allowlist)"))
            continue
        if category in ignore:
            plan.skipped.append(SkippedRow(row, "categoria in ignore_categories"))
            continue
        if row.is_new:
            plan.skipped.append(SkippedRow(row, "edificio nuovo: flusso piazzamento non supportato"))
            continue
        if category == "walls":
            if not config.upgrade.include_walls:
                plan.skipped.append(SkippedRow(row, "mura escluse (upgrade.include_walls=false)"))
                continue
            if config.walls.mode is WallMode.OFF:
                plan.skipped.append(SkippedRow(row, "mura disabilitate (walls.mode=off)"))
                continue
        if category == "heroes" and not config.upgrade.use_heroes:
            plan.skipped.append(SkippedRow(row, "eroi esclusi (upgrade.use_heroes=false)"))
            continue
        if row.cost is None:
            plan.skipped.append(SkippedRow(row, "costo illeggibile"))
            continue
        if row.currency not in ("gold", "elixir", "dark"):
            plan.skipped.append(SkippedRow(row, f"valuta non gestita: {row.currency}"))
            continue
        available = report.hud.amount(row.currency)
        if available is None:
            plan.skipped.append(SkippedRow(row, f"risorsa non nota: {row.currency}"))
            continue
        reserve = int(reserves.get(row.currency, 0))
        if row.cost + reserve > available:
            plan.skipped.append(
                SkippedRow(
                    row,
                    f"risorse insufficienti: serve {row.cost} + riserva {reserve}, "
                    f"disponibile {available} {row.currency}",
                )
            )
            continue
        plan.candidates.append(UpgradeCandidate(row=row, category=category, priority_index=priority.index(category)))

    if not report.hud.builders_known:
        plan.notes.append("builder non letti: il piano non e' eseguibile finche' non si leggono")
    elif not report.hud.has_free_builder:
        plan.notes.append("nessun builder libero: nessun upgrade eseguibile")

    plan.candidates.sort(key=lambda item: (item.priority_index, item.row.scroll_index or 0))
    limit = max(1, int(config.upgrade.max_upgrades_per_cycle))
    wall_limit = max(0, int(config.walls.max_wall_batches_per_cycle))
    if not report.hud.has_free_builder:
        return plan
    # --- preset A/B mura -------------------------------------------------------
    # Preset A: un builder resta libero e riservato alle mura (il loro upgrade e' istantaneo,
    # quindi non consuma il builder ma ne serve uno libero al momento del tap).
    # Preset B (automatico): quando tutte le mura sono max tutti i builder lavorano.
    walls_enabled = config.upgrade.include_walls and config.walls.mode is not WallMode.OFF
    walls_state = walls_status(report)
    walls_max = walls_state == "max"
    keep_builder_for_walls = bool(
        walls_enabled
        and config.walls.reserve_builder_for_walls
        and not (walls_max and config.walls.switch_to_all_builders_when_walls_max)
    )
    free_builders = report.hud.builders_available or 0
    builder_slots = max(0, free_builders - (1 if keep_builder_for_walls else 0))
    if keep_builder_for_walls:
        plan.notes.append(
            "preset A mura: 1 builder riservato alle mura "
            f"({builder_slots} disponibili per edifici/eroi)"
        )
    elif walls_max and config.walls.reserve_builder_for_walls:
        plan.notes.append("mura max: preset B, tutti i builder disponibili per gli upgrade")
    # budget cumulativo: ogni upgrade scelto consuma risorse (le mura costano una per volta)
    remaining: dict[str, int | None] = {
        currency: report.hud.amount(currency) for currency in ("gold", "elixir", "dark")
    }
    chosen: list[UpgradeCandidate] = []
    wall_count = 0
    non_wall_count = 0
    builder_note_added = False
    for candidate in plan.candidates:
        if len(chosen) >= limit:
            break
        row = candidate.row
        if row.cost is None:
            continue
        if candidate.category == "walls" and wall_count >= wall_limit:
            plan.notes.append(f"limite walls.max_wall_batches_per_cycle={wall_limit}: mura oltre il limite")
            continue
        if candidate.category != "walls" and non_wall_count >= builder_slots:
            if not builder_note_added:
                reserved = free_builders - builder_slots
                plan.notes.append(
                    f"builder esauriti per edifici/eroi: {builder_slots} utilizzabili"
                    + (f", {reserved} riservati alle mura (preset A)" if reserved else "")
                )
                builder_note_added = True
            continue
        available = remaining.get(row.currency)
        reserve = int(reserves.get(row.currency, 0))
        if available is None or row.cost + reserve > available:
            plan.notes.append(
                f"budget {row.currency} esaurito: salto {row.name} (serve {row.cost} + riserva {reserve})"
            )
            continue
        chosen.append(candidate)
        remaining[row.currency] = available - row.cost
        if candidate.category == "walls":
            wall_count += 1
        else:
            non_wall_count += 1
    plan.chosen = chosen
    if not chosen and walls_max and config.walls.auto_stop_when_walls_max:
        plan.notes.append("auto-stop: mura tutte al massimo e nessun altro upgrade disponibile")
    if plan.candidates and not chosen:
        plan.notes.append("nessun candidato scelto: budget/limiti non consentono upgrade")
    return plan


class UpgradeEngine:
    """Naviga il menu Build, pianifica ed esegue upgrade (dry-run di default).

    Non avvia il gioco: si aspetta che sia aperto. Gestisce pero' i casi in cui la
    finestra e' minimizzata (ripristino con ``ShowWindow``) e la disconnessione per
    inattivita' (preme ``RELOAD GAME`` e attende il caricamento), perche' durante una
    sessione lunga il gioco puo' disconnettersi da solo.
    Input via ``WinMsgSink``: non ruba focus ne' muove il cursore.
    """

    def __init__(
        self,
        window: GameWindow,
        config: Config,
        *,
        source: WgcScreenSource | None = None,
        sink: WinMsgSink | None = None,
        log: Callable[[str], None] | None = None,
        action_wait_s: float = 1.1,
        scroll_wait_s: float = 0.45,
    ) -> None:
        self.window = window
        self.config = config
        self.log = log or (lambda message: None)
        self.action_wait_s = action_wait_s
        self.scroll_wait_s = scroll_wait_s
        self.source = source or WgcScreenSource(window, target_fps=config.capture.target_fps)
        self.sink = sink or WinMsgSink(window, jitter_ms=(0, 0))
        self._own_source = source is None
        self._own_sink = sink is None

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        if self._own_source:
            self.source.close()
        if self._own_sink:
            self.sink.close()

    def __enter__(self) -> UpgradeEngine:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ input/capture
    def _rebind_window(self, info: win32.WindowInfo) -> None:
        """Riaggancia finestra/sorgente dopo una ricreazione (es. reload del gioco)."""
        self.log(f"finestra riagganciata: hwnd=0x{info.hwnd:X} client={info.client_size}")
        if self._own_source:
            self.source.close()
            self.window = GameWindow(info)
            self.source = WgcScreenSource(self.window, target_fps=self.config.capture.target_fps)
        else:
            self.window = GameWindow(info)
        if self._own_sink:
            self.sink.window = self.window  # type: ignore[attr-defined]

    def _ensure_window_ready(self, *, timeout_s: float = 120.0, poll_s: float = 1.0) -> bool:
        """Attende che la finestra del gioco esista e non sia minimizzata (la ripristina)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            info = find_game_window()
            if info is not None:
                if info.hwnd != self.window.hwnd or info.client_size != self.window.info.client_size:
                    self._rebind_window(info)
                if win32.is_minimized(info.hwnd):
                    self.log("finestra minimizzata: ripristino (ShowWindow SW_RESTORE)")
                    win32.user32.ShowWindow(win32.HWND(info.hwnd), win32.SW_RESTORE)
                    time.sleep(0.8)
                return True
            time.sleep(poll_s)
        return False

    def grab(self) -> np.ndarray:
        """Frame corrente (client-cropped). Errore se la finestra e' minimizzata/nera.

        Il primo frame di una sessione WGC puo' essere nero (artefatto transitorio): si
        riprova brevemente prima di dichiarare la finestra inutilizzabile.
        """
        info = find_game_window()
        if info is None:
            raise UpgradeEngineError("finestra di gioco non trovata")
        if info.hwnd != self.window.hwnd or info.client_size != self.window.info.client_size:
            self._rebind_window(info)
        if win32.is_minimized(info.hwnd):
            raise UpgradeEngineError("finestra del gioco minimizzata")
        for _attempt in range(3):
            frame = self.source.grab()
            image = frame.image
            if image is not None and image.size > 0 and not frame.metadata.get("black"):
                return image
            time.sleep(0.3)
        raise UpgradeEngineError("frame nero: la finestra del gioco e' minimizzata o coperta in modo anomalo")

    # ------------------------------------------------------------------ reload/attesa
    def wait_for_load(self, *, timeout_s: float = 200.0, poll_s: float = 2.0) -> bool:
        """Attende che il gioco finisca di caricare e arrivi in home (dopo un reload)."""
        deadline = time.monotonic() + timeout_s
        last_state: ScreenState | None = None
        while time.monotonic() < deadline:
            try:
                frame = self.grab()
            except UpgradeEngineError:
                if not self._ensure_window_ready(timeout_s=8.0):
                    time.sleep(poll_s)
                continue
            state = states.classify(frame)
            if state is not last_state:
                self.log(f"attesa caricamento: stato {state.value}")
                last_state = state
            if state is ScreenState.HOME:
                return True
            if state is ScreenState.MAINTENANCE:
                self.log("attesa caricamento: manutenzione del gioco in corso (MAINTENANCE BREAK)")
                return False
            if state is ScreenState.NETWORK_ERROR:
                point = ui.find_inactivity_modal(frame)
                if point is not None:
                    self._tap(point, wait_s=2.5)
            time.sleep(poll_s)
        self.log("attesa caricamento: timeout")
        return False

    def reload_game(self, *, timeout_s: float = 200.0) -> bool:
        """Gestisce la disconnessione: preme il pulsante di retry e attende il caricamento.

        I modal osservati su questa versione sono due varianti, entrambe riconosciute da
        ``ui.find_inactivity_modal`` (testo del pulsante in azzurro):
        - "Connection lost" con "TRY AGAIN";
        - "Anyone there?" con "RELOAD GAME".
        Il reload puo' minimizzare la finestra; ``wait_for_load`` la ripristina. Se il gioco
        entra in manutenzione ("MAINTENANCE BREAK") il reload fallisce in fretta, senza input.
        """
        self.log("rete/disconnessione: premo il pulsante di retry (RELOAD GAME / TRY AGAIN)")
        if not self._ensure_window_ready(timeout_s=10.0):
            self.log("reload: finestra di gioco non trovata")
            return False
        try:
            frame = self.grab()
        except UpgradeEngineError:
            if not self._ensure_window_ready(timeout_s=10.0):
                return False
            try:
                frame = self.grab()
            except UpgradeEngineError:
                return False
        point = ui.find_inactivity_modal(frame)
        if point is None:
            self.log("reload: modal di inattivita' non rilevato")
            return False
        self._tap(point, wait_s=2.5)
        return self.wait_for_load(timeout_s=timeout_s)

    def state(self, image: np.ndarray | None = None) -> ScreenState:
        return states.classify(image if image is not None else self.grab())

    def _tap(self, point: tuple[int, int], *, wait_s: float | None = None) -> None:
        self.sink.tap_pixels(int(point[0]), int(point[1]))
        time.sleep(self.action_wait_s if wait_s is None else wait_s)

    def _wheel(self, panel: ui.Rect, delta: int) -> None:
        """Invia WM_MOUSEWHEEL alla finestra (non invasivo: niente focus/cursore)."""
        hwnd = self.window.hwnd
        ox, oy = win32.client_origin(hwnd)
        x = panel.x + panel.w // 2
        y = panel.y + panel.h // 2
        lparam = (((oy + y) & 0xFFFF) << 16) | ((ox + x) & 0xFFFF)
        wparam = ((delta & 0xFFFF) << 16) & 0xFFFFFFFF
        win32.user32.PostMessageW(win32.HWND(hwnd), WM_MOUSEWHEEL, wparam, lparam)

    @staticmethod
    def _panel_delta(first: np.ndarray, second: np.ndarray) -> float:
        """Differenza media del pannello destro fra due frame (per rilevare lo scroll)."""
        if first.shape != second.shape:
            return 255.0
        width = first.shape[1]
        x0 = int(width * 0.735)
        diff = cv2.absdiff(first[:, x0:], second[:, x0:]).max(axis=2)
        return float(diff.mean())

    def _settle_menu(
        self,
        *,
        expect_change: bool = False,
        timeout_s: float = 4.0,
        poll_s: float = 0.15,
        threshold: float = 0.4,
    ) -> np.ndarray:
        """Attende che la lista del menu Build smetta di animarsi e restituisce il frame.

        Il gioco anima lo scroll per ~1.8 s: leggere o tappare prima porta a coordinate
        sbagliate. Stabile = due frame consecutivi quasi identici nella zona pannello.
        Con ``expect_change=True`` attende che almeno un frame sia cambiato (o fallisce
        per timeout): serve a non fidarsi di frame WGC fermi/obsoleti.
        """
        previous = self.grab()
        deadline = time.monotonic() + timeout_s
        observed_change = not expect_change
        stable_count = 0
        while time.monotonic() < deadline:
            time.sleep(poll_s)
            current = self.grab()
            changed = self._panel_delta(previous, current) >= threshold
            if changed:
                observed_change = True
                stable_count = 0
            else:
                stable_count += 1
            previous = current
            if observed_change and stable_count >= 2:
                return current
        return self.grab()

    def _wait_state(
        self, expected: ScreenState, *, timeout_s: float = 3.0, poll_s: float = 0.2
    ) -> np.ndarray | None:
        """Attende uno stato specifico (polling dei frame) e restituisce il frame, o None."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(poll_s)
            try:
                frame = self.grab()
            except UpgradeEngineError:
                continue
            if states.classify(frame) is expected:
                return frame
        return None

    # ------------------------------------------------------------------ HUD
    def read_hud(self, image: np.ndarray) -> HudRead:
        """Legge risorse e builder dalla home via OCR (4 numeri + coppie "X/Y")."""
        notes: list[str] = []
        resources = ui.resources_region(image)
        resource_items = ocr_module.read_texts(
            image[resources.y : resources.bottom, resources.x : resources.right],
            offset=(resources.x, resources.y),
        )
        amounts: list[tuple[int, int]] = []
        for item in resource_items:
            amount = textparse.parse_amount(item.text)
            if amount is not None:
                amounts.append((item.cy, amount))
        amounts.sort()
        values = [amount for _y, amount in amounts]
        gold, elixir, dark, gems = (values + [None, None, None, None])[:4]
        if len(values) < 3:
            notes.append(f"risorse: letti solo {len(values)} valori")

        builders = ui.builders_region(image)
        builder_items = ocr_module.read_texts(
            image[builders.y : builders.bottom, builders.x : builders.right],
            offset=(builders.x, builders.y),
        )
        pairs: list[tuple[int, int]] = []
        for item in builder_items:
            for match in _BUILDERS_PATTERN.finditer(item.text.replace(" ", "")):
                pairs.append((int(match.group(1)), int(match.group(2))))
        available, total = pairs[0] if pairs else (None, None)
        if available is None:
            notes.append("builder non letti (attesi come 'X/Y' in basso a destra)")
        elif total is not None and not (1 <= total <= 8 and 0 <= available <= total):
            notes.append(f"builder implausibili: {available}/{total}")
            available, total = None, None
        return HudRead(
            gold=gold,
            elixir=elixir,
            dark=dark,
            gems=gems,
            builders_available=available,
            builders_total=total,
            notes=tuple(notes),
        )

    # ------------------------------------------------------------------ stato/navigazione
    def recover_home(self, *, max_attempts: int = 6) -> bool:
        """Riporta il gioco in home usando solo chiusure sicure (mai tap sulla mappa).

        Gestisce anche: finestra minimizzata (ripristino) e disconnessione per inattivita'
        (RELOAD GAME + attesa caricamento).
        """
        for _attempt in range(max_attempts):
            try:
                image = self.grab()
            except UpgradeEngineError as exc:
                if not self._ensure_window_ready(timeout_s=10.0):
                    self.log(f"recover: {exc}")
                    return False
                continue
            state = states.classify(image)
            if state is ScreenState.HOME:
                return True
            if state is ScreenState.UPGRADE_CONFIRM:
                point = ui.find_dialog_close(image)
            elif state is ScreenState.PLACEMENT:
                point = ui.find_placement_exit(image)
            elif state is ScreenState.BATTLE_MENU:
                point = ui.find_battle_menu_close(image)
            elif state is ScreenState.BUILD_MENU:
                point = ui.find_menu_close(image)
            elif state is ScreenState.MAINTENANCE:
                self.log("recover: manutenzione del gioco in corso, nessuna azione possibile")
                return False
            elif state is ScreenState.NETWORK_ERROR:
                return self.reload_game()
            else:
                point = None
            if point is not None:
                self.log(f"recover: chiusura {state.value} @ {point}")
                self._tap(point)
                continue
            # fallback: apri e chiudi il menu Build (pulisce i pannelli info)
            button = ui.find_build_button(image)
            if button is None:
                self.log(f"recover: stato {state.value} senza via di chiusura sicura")
                return False
            self._tap(ui.center(button))
            menu_image = self.grab()
            menu_close = ui.find_menu_close(menu_image)
            if menu_close is not None:
                self._tap(menu_close)
        try:
            return states.classify(self.grab()) is ScreenState.HOME
        except UpgradeEngineError:
            return False

    def open_build_menu(self) -> bool:
        """Apre il menu Build dalla home e verifica lo stato."""
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.BUILD_MENU:
            return True
        if state is not ScreenState.HOME and not self.recover_home():
            return False
        image = self.grab()
        button = ui.find_build_button(image)
        if button is None:
            self.log("open_build_menu: pulsante Build non trovato")
            return False
        self._tap(ui.center(button))
        frame = self._wait_state(ScreenState.BUILD_MENU, timeout_s=4.0)
        if frame is None:
            self.log("open_build_menu: menu non rilevato dopo il tap")
            return False
        self._settle_menu()
        return True

    def close_build_menu(self) -> bool:
        """Chiude il menu Build (o un dialogo) e verifica il ritorno in home."""
        state = states.classify(self.grab())
        if state is ScreenState.HOME:
            return True
        if state is not ScreenState.BUILD_MENU:
            return self.recover_home()
        image = self.grab()
        point = ui.find_menu_close(image)
        if point is None:
            return self.recover_home()
        self._tap(point)
        return self.recover_home(max_attempts=3)

    def _current_panel(self, *, attempts: int = 4) -> ui.Rect:
        """Pannello del menu Build; retry per assorbire l'animazione di apertura.

        Se il rilevamento fallisce (frame transitorio) ma lo stato e' comunque menu Build,
        si usa il fallback geometrico: il bordo sinistro del pannello e' a ~0.734 della
        larghezza, frazione verificata stabile tra windowed e fullscreen.
        """
        image = self.grab()
        for _attempt in range(attempts):
            panel = ui.find_build_panel(image)
            if panel is not None:
                return panel
            time.sleep(0.25)
            image = self.grab()
        if states.classify(image) is ScreenState.BUILD_MENU:
            width = image.shape[1]
            left = int(round(width * 0.734))
            self.log(f"_current_panel: fallback geometrico (left={left})")
            return ui.Rect(left, 0, width - left, image.shape[0])
        raise UpgradeEngineError("pannello del menu Build non rilevato")

    def scroll_to_top(self, *, max_steps: int = 45) -> int:
        """Scorre la lista fino in cima (frame stabili identici = cima). Ritorna i passi fatti."""
        panel = self._current_panel()
        previous = self.grab()
        for step in range(max_steps):
            self._wheel(panel, +120)
            current = self._settle_menu()
            still = self._panel_delta(previous, current) < 0.5
            retries = 0
            while still and retries < 2:  # frame puo' essere obsoleto: riprova
                self._wheel(panel, +120)
                current = self._settle_menu()
                still = self._panel_delta(previous, current) < 0.5
                retries += 1
            previous = current
            if still:
                return step
        self.log(f"scroll_to_top: limite di {max_steps} passi raggiunto")
        return max_steps

    # ------------------------------------------------------------------ scansione
    def scan(self, *, max_scrolls: int | None = None) -> ScanReport:
        """Scansiona l'intero catalogo del menu Build (sola lettura, nessuna spesa)."""
        started = time.monotonic()
        limit = max_scrolls if max_scrolls is not None else self.config.upgrade.max_scan_scrolls
        notes: list[str] = []
        if not self.recover_home():
            current = states.classify(self.grab())
            hint = (
                " (gioco disconnesso per inattivita': serve 'RELOAD GAME')"
                if current is ScreenState.NETWORK_ERROR
                else ""
            )
            raise UpgradeEngineError(f"impossibile portare il gioco in home per la scansione{hint}")
        hud = self.read_hud(self.grab())
        notes.extend(hud.notes)
        if not self.open_build_menu():
            raise UpgradeEngineError("impossibile aprire il menu Build")
        self.scroll_to_top()
        panel = self._current_panel()
        raw_rows: list[build_menu.BuildRow] = []
        scroll_index = 0
        previous = self.grab()
        for _step in range(limit):
            page = build_menu.read_rows(previous)
            for row in page:
                raw_rows.append(replace(row, scroll_index=scroll_index))
            self._wheel(panel, -120)
            current = self._settle_menu(expect_change=True)
            still = self._panel_delta(previous, current) < 0.5
            retries = 0
            while still and retries < 2:  # frame obsoleto: riprova lo scroll
                self._wheel(panel, -120)
                current = self._settle_menu(expect_change=True)
                still = self._panel_delta(previous, current) < 0.5
                retries += 1
            previous = current
            scroll_index += 1
            if still:
                # ultima pagina: prova a leggerla (potrebbe non essere ancora stata letta)
                for row in build_menu.read_rows(current):
                    raw_rows.append(replace(row, scroll_index=scroll_index))
                break
        rows = merge_rows(raw_rows)
        # normalizza i nomi riconosciuti: "Craftina Station" -> "crafting station" (le righe
        # davvero illeggibili restano col nome normalizzato e verranno scartate dal planner)
        rows = [replace(row, name=canonical_name(row.name)) for row in rows]
        if not self.close_build_menu():
            notes.append("menu Build non chiuso correttamente dopo la scansione")
        elapsed = time.monotonic() - started
        notes.append(
            f"scansione: {len(rows)} righe uniche (da {len(raw_rows)} letture) in {scroll_index} posizioni di scroll"
        )
        return ScanReport(hud=hud, rows=rows, positions=scroll_index, elapsed_s=elapsed, notes=notes)

    # ------------------------------------------------------------------ pianificazione
    def plan(self, report: ScanReport) -> UpgradePlan:
        """Sceglie gli upgrade da fare secondo priorita'/riserve/config (solo calcolo)."""
        return build_plan(self.config, report)

    # ------------------------------------------------------------------ esecuzione
    def execute(self, plan: UpgradePlan, *, dry_run: bool = True) -> list[ExecutionResult]:
        """Esegue il piano. ``dry_run=True`` (default) non invia alcuna azione."""
        if dry_run:
            return [
                ExecutionResult(row=candidate.row, ok=True, reason="dry-run: nessuna azione")
                for candidate in plan.chosen
            ]
        results: list[ExecutionResult] = []
        for candidate in plan.chosen:
            try:
                results.append(self._execute_upgrade(candidate))
            except (UpgradeEngineError, ocr_module.OcrUnavailable) as exc:  # pragma: no cover - dipende dal gioco
                results.append(ExecutionResult(row=candidate.row, ok=False, reason=str(exc)))
                break
        return results

    def _find_row_live(self, target: build_menu.BuildRow, *, max_pages: int = 40) -> build_menu.BuildRow | None:
        """Cerca la riga target scorrendo il menu Build dall'inizio (una pagina per volta)."""
        self.scroll_to_top()
        panel = self._current_panel()
        previous = self._settle_menu()
        for _page in range(max_pages):
            for page_row in build_menu.read_rows(previous):
                if _row_matches(page_row, target):
                    return page_row
            self._wheel(panel, -120)
            current = self._settle_menu(expect_change=True)
            still = self._panel_delta(previous, current) < 0.5
            retries = 0
            while still and retries < 2:  # frame WGC obsoleto: riprova
                self._wheel(panel, -120)
                current = self._settle_menu(expect_change=True)
                still = self._panel_delta(previous, current) < 0.5
                retries += 1
            previous = current
            if still:
                break
        return None

    def _wait_wall_panel(self, *, timeout_s: float = 5.0, poll_s: float = 0.25) -> build_menu.WallPanelInfo | None:
        """Attende che, dopo il tap sulla riga Wall, compaia il pannello azioni del muro."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                frame = self.grab()
            except UpgradeEngineError:
                time.sleep(poll_s)
                continue
            info = build_menu.read_wall_panel(frame)
            if info.ok:
                return info
            time.sleep(poll_s)
        return None

    def _execute_wall_upgrade(self, candidate: UpgradeCandidate) -> ExecutionResult:  # pragma: no cover - live
        """Upgrade di un muro dal pannello azioni ("Wall Upgrader"), con verifica delle risorse.

        Flusso osservato: tap sulla riga "Wall x N" del menu Build -> il gioco seleziona un
        muro e mostra Info / Select ROW / Upgrade MORE / Upgrade (oro) / Upgrade (elisir).
        NON c'e' dialogo di conferma: si preme direttamente il pulsante "Upgrade" della
        valuta scelta dal planner, poi si verificano livello selezionato e risorse.
        Mai premere "Select ROW"/"Upgrade MORE" (modalita' bulk, costi multipli).
        """
        row = candidate.row
        if row.cost is None or row.currency not in ("gold", "elixir"):
            raise UpgradeEngineError(f"muro non eseguibile: costo/valuta non noti ({row})")
        cost = row.cost
        if not self.recover_home():
            raise UpgradeEngineError("stato non home: esecuzione annullata")
        before = self.read_hud(self.grab())
        if not before.builders_known or not before.has_free_builder:
            raise UpgradeEngineError("nessun builder libero verificato: esecuzione annullata")
        if not self.open_build_menu():
            raise UpgradeEngineError("menu Build non aperto")
        match = self._find_row_live(row)
        if match is None:
            raise UpgradeEngineError(f"riga non ritrovata nella lista: {row.name} ({cost} {row.currency})")
        self._tap((match.tap_x, match.tap_y), wait_s=1.2)
        panel = self._wait_wall_panel()
        if panel is None:
            self.recover_home()
            raise UpgradeEngineError("pannello azioni del muro non comparso: esecuzione annullata")
        matching = [button for button in panel.buttons if button.cost == cost]
        exact = [button for button in matching if button.currency == row.currency]
        button = exact[0] if exact else (matching[0] if len(matching) == 1 else None)
        if button is None:
            self.recover_home()
            raise UpgradeEngineError(
                f"pulsante Upgrade muro ({cost} {row.currency}) non identificato: {panel.buttons}"
            )
        if button.currency not in ("gold", "elixir"):
            self.recover_home()
            raise UpgradeEngineError(f"valuta del pulsante muro non gestita: {button.currency}")
        if button.currency != row.currency:
            self.log(f"muro: uso la valuta del pulsante ({button.currency}) invece della riga ({row.currency})")
        level_before = panel.selected_level
        self.log(
            f"muro livello {level_before}: premo Upgrade {button.currency} {cost} @ {button.point}"
        )
        self._tap(button.point, wait_s=1.2)
        # dopo "Upgrade" compare un dialogo di conferma ("Upgrade Wall to Level N?"): va
        # verificato e confermato SOLO se nome/livello/costo corrispondono al piano.
        dialog_image = self._wait_state(ScreenState.UPGRADE_CONFIRM, timeout_s=4.0)
        if dialog_image is None:
            self.recover_home()
            raise UpgradeEngineError("dialogo di conferma muro non comparso: esecuzione annullata")
        dialog = build_menu.read_dialog(dialog_image)
        expected_level = None if level_before is None else level_before + 1
        problems: list[str] = []
        if dialog.name is None or "wall" not in _normalize_name(dialog.name):
            problems.append(f"nome dialogo {dialog.name!r} non contiene 'wall'")
        if expected_level is not None and dialog.target_level is not None and dialog.target_level != expected_level:
            problems.append(f"livello dialogo {dialog.target_level} diverso da {expected_level}")
        if dialog.cost is None or dialog.cost != cost:
            problems.append(f"costo dialogo {dialog.cost} diverso da {cost}")
        if problems:
            if dialog.close_point is not None:
                self._tap(dialog.close_point)
            self.recover_home()
            raise UpgradeEngineError("dialogo muro non corrispondente: " + "; ".join(problems))
        confirm_rect = dialog.confirm_rect or ui.find_confirm_button(dialog_image)
        if confirm_rect is None:
            self.recover_home()
            raise UpgradeEngineError("pulsante CONFIRM del muro non trovato")
        self.log(f"muro: confermo Upgrade (dialogo {dialog.title!r}, costo {dialog.cost})")
        self._tap(ui.center(confirm_rect), wait_s=1.8)
        for _attempt in range(6):
            if states.classify(self.grab()) is not ScreenState.UPGRADE_CONFIRM:
                break
            time.sleep(0.3)
        if not self.close_build_menu():
            raise UpgradeEngineError("menu Build non chiuso dopo l'upgrade del muro")
        after = self.read_hud(self.grab())
        currency = button.currency
        available_before = before.amount(currency)
        available_after = after.amount(currency)
        delta = None if available_before is None or available_after is None else available_before - available_after
        if self.config.upgrade.verify_after_upgrade and (delta is None or delta != cost):
            raise UpgradeEngineError(
                f"verifica muro fallita: {currency} {available_before}->{available_after}, atteso -{cost}"
            )
        return ExecutionResult(
            row=row,
            ok=True,
            reason=(
                f"muro potenziato: livello selezionato {level_before}->{expected_level}, "
                f"risorse -{cost} {currency} (verificate)"
            ),
            dialog_cost=dialog.cost,
            hud_after=after,
        )

    def _execute_upgrade(self, candidate: UpgradeCandidate) -> ExecutionResult:  # pragma: no cover - live
        """Naviga alla riga, verifica il dialogo e conferma l'upgrade."""
        if candidate.category == "walls":
            return self._execute_wall_upgrade(candidate)
        row = candidate.row
        if row.cost is None or row.currency not in ("gold", "elixir", "dark"):
            raise UpgradeEngineError(f"candidato non eseguibile: costo/valuta non noti ({row})")
        cost = row.cost
        if not self.recover_home():
            raise UpgradeEngineError("stato non home: esecuzione annullata")
        before = self.read_hud(self.grab())
        if not before.builders_known or not before.has_free_builder:
            raise UpgradeEngineError("nessun builder libero verificato: esecuzione annullata")
        if not self.open_build_menu():
            raise UpgradeEngineError("menu Build non aperto")
        match = self._find_row_live(row)
        if match is None:
            raise UpgradeEngineError(f"riga non ritrovata nella lista: {row.name} ({cost} {row.currency})")
        self._tap((match.tap_x, match.tap_y))
        dialog_image = self._wait_state(ScreenState.UPGRADE_CONFIRM, timeout_s=3.0)
        if dialog_image is None:
            self.recover_home()
            raise UpgradeEngineError("dialogo di conferma non aperto: esecuzione annullata")
        dialog = build_menu.read_dialog(dialog_image)
        # la riga del catalogo mostra il livello di DESTINAZIONE: il dialogo conferma
        # "Upgrade <X> to Level <row.level>?" (verificato su frame reali: clan castle 8/8,
        # gold mine 15/15, air bomb 3/3). Per le mura vale l'opposto: il pannello mostra il
        # livello ATTUALE e il target e' selected_level+1 (vedi _execute_wall_upgrade).
        expected_level = row.level
        problems: list[str] = []
        if dialog.name is None or _normalize_name(dialog.name) not in _normalize_name(
            canonical_name(row.name)
        ):
            problems.append(f"nome dialogo {dialog.name!r} diverso da {row.name!r}")
        if expected_level is not None and dialog.target_level is not None and dialog.target_level != expected_level:
            problems.append(f"livello dialogo {dialog.target_level} diverso da {expected_level}")
        if dialog.cost is None or dialog.cost != cost:
            problems.append(f"costo dialogo {dialog.cost} diverso da {cost}")
        if problems:
            point = dialog.close_point
            if point is not None:
                self._tap(point)
            self.recover_home()
            raise UpgradeEngineError("dialogo non corrispondente: " + "; ".join(problems))
        confirm_rect = dialog.confirm_rect or ui.find_confirm_button(dialog_image)
        if confirm_rect is None:
            raise UpgradeEngineError("pulsante CONFIRM non trovato")
        self._tap(ui.center(confirm_rect), wait_s=max(1.6, self.action_wait_s))
        after_image = self.grab()
        if states.classify(after_image) is ScreenState.UPGRADE_CONFIRM:
            raise UpgradeEngineError("dialogo ancora aperto dopo CONFIRM")
        if not self.close_build_menu():
            raise UpgradeEngineError("menu Build non chiuso dopo l'upgrade")
        after = self.read_hud(self.grab())
        if self.config.upgrade.verify_after_upgrade:
            builders_consumed = after.builders_known and before.builders_known and (
                (after.builders_available or 0) < (before.builders_available or 0)
            )
            if after.builders_known and before.builders_known and not builders_consumed:
                raise UpgradeEngineError("verifica fallita: builder non consumato")
            available_before = before.amount(row.currency)
            available_after = after.amount(row.currency)
            if (
                available_before is not None
                and available_after is not None
                and available_after > available_before - cost
            ):
                raise UpgradeEngineError(
                    f"verifica fallita: {row.currency} {available_before}->{available_after}, atteso -{cost}"
                )
        return ExecutionResult(
            row=row,
            ok=True,
            reason="upgrade confermato e verificato",
            dialog_cost=dialog.cost,
            hud_after=after,
        )


def save_json(path: str | Path, payload: dict) -> Path:
    """Salva un payload JSON con indentazione (per report/diagnostica)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


__all__ = [
    "CATEGORY_KEYWORDS",
    "DEFAULT_PRIORITY",
    "ExecutionResult",
    "HudRead",
    "ScanReport",
    "SkippedRow",
    "UpgradeCandidate",
    "UpgradeEngine",
    "UpgradeEngineError",
    "UpgradePlan",
    "build_plan",
    "canonical_name",
    "categorize",
    "merge_rows",
    "priority_list",
    "save_json",
    "walls_status",
]
