"""Engine del loop attacco (auto-battaglia): **v1 = menu Battle in sola lettura**.

Prima di lanciare raid reali servono frame reali di anteprima/battaglia per loot OCR, skip e
deploy; questa v1:
1. apre il menu Battle dalla home (pulsante Battle) e verifica lo stato;
2. localizza il pulsante "Find a Match" (geometria/cromia, senza OCR);
3. valuta il bottino con una funzione **pura** testabile off-line (:func:`evaluate_loot`);
4. chiude il menu e torna in home con chiusure sicure (ESC via messaggio, fallback navigazione).

Non preme **mai** "Find a Match": nessun raid, nessuna spesa, nessuna battaglia. Skip ed
esecuzione del raid verranno aggiunti dopo la validazione dei frame reali di anteprima.

Eredita da ``UpgradeEngine`` la navigazione prudente (X di menu/dialogo, mai tap sulla mappa).
"""
from __future__ import annotations

from dataclasses import dataclass

from cocbot.app.upgrade_engine import UpgradeEngine, UpgradeEngineError
from cocbot.core.types import Rect, ScreenState
from cocbot.vision import states, ui

VK_ESCAPE = 0x1B

DEFAULT_WEIGHTS: dict[str, float] = {"gold": 1.0, "elixir": 1.0, "dark": 100.0}


class AttackEngineError(UpgradeEngineError):
    """Errore bloccante del loop attacco (menu non aperto, chiusura fallita, ecc.)."""


@dataclass(frozen=True, slots=True)
class LootDecision:
    """Esito della valutazione del bottino di una base (solo calcolo, nessun input)."""

    gold: int | None
    elixir: int | None
    dark: int | None
    score: float
    should_attack: bool
    reason: str


def evaluate_loot(
    gold: int | None,
    elixir: int | None,
    dark: int | None,
    *,
    thresholds: dict[str, int] | None = None,
    weights: dict[str, float] | None = None,
) -> LootDecision:
    """Decide se attaccare una base in base a soglie e punteggio del bottino.

    Regola (documentata anche in ADR-004): si attacca se **oro, elisir e dark** raggiungono le
    rispettive soglie *e* il punteggio pesato raggiunge ``score_min``; con bottino illeggibile
    (oro/elisir sconosciuti) non si attacca mai. ``dark=None`` non blocca: la soglia dark
    semplicemente non viene controllata (il bottino dark puo' non esserci).
    """
    thresholds = thresholds or {}
    weights = weights or DEFAULT_WEIGHTS
    if gold is None or elixir is None:
        return LootDecision(gold, elixir, dark, 0.0, False, "bottino non leggibile (oro/elisir)")

    score = gold * float(weights.get("gold", 1.0)) + elixir * float(weights.get("elixir", 1.0))
    if dark is not None:
        score += dark * float(weights.get("dark", 100.0))

    problems: list[str] = []
    gold_min = int(thresholds.get("gold_min", 0))
    elixir_min = int(thresholds.get("elixir_min", 0))
    dark_min = int(thresholds.get("dark_min", 0))
    score_min = float(thresholds.get("score_min", 0))
    if gold_min and gold < gold_min:
        problems.append(f"oro {gold} < {gold_min}")
    if elixir_min and elixir < elixir_min:
        problems.append(f"elisir {elixir} < {elixir_min}")
    if dark is not None and dark_min and dark < dark_min:
        problems.append(f"dark {dark} < {dark_min}")
    if score_min and score < score_min:
        problems.append(f"score {score:.0f} < {score_min:.0f}")

    if problems:
        return LootDecision(gold, elixir, dark, score, False, "base da saltare: " + ", ".join(problems))
    return LootDecision(gold, elixir, dark, score, True, f"bottino buono (score {score:.0f})")


@dataclass(frozen=True, slots=True)
class BattleMenuRead:
    """Contenuto letto dal menu Battle (sola lettura, nessun raid avviato)."""

    state: str
    find_match_rect: Rect | None
    find_match_center: tuple[int, int] | None
    notes: tuple[str, ...] = ()


@dataclass
class SkipSession:
    """Contatore e timer degli skip durante la ricerca della base (config ``loot.*``).

    Regole documentate nel piano di progetto: ``loot.max_skip_per_attack`` e
    ``loot.skip_timeout_s`` limitano quanti villaggi saltare e per quanto tempo cercare.
    Classe pura (nessun I/O): il chiamante passa ``now`` (``time.monotonic()``).
    """

    max_skip: int
    timeout_s: float
    skips: int = 0
    started_at: float | None = None

    def start(self, now: float) -> None:
        self.started_at = now
        self.skips = 0

    def elapsed_s(self, now: float) -> float:
        return 0.0 if self.started_at is None else max(0.0, now - self.started_at)

    def can_continue(self, now: float) -> tuple[bool, str]:
        """(True, "") se si puo' ancora cercare/saltare; altrimenti (False, motivo)."""
        if self.max_skip > 0 and self.skips >= self.max_skip:
            return False, f"limite di skip raggiunto ({self.skips}/{self.max_skip})"
        if self.timeout_s > 0 and self.started_at is not None and self.elapsed_s(now) >= self.timeout_s:
            return False, f"timeout ricerca base ({self.timeout_s:.0f}s)"
        return True, ""

    def record_skip(self, now: float) -> tuple[bool, str]:
        """Registra uno skip e dice se si puo' continuare."""
        self.skips += 1
        return self.can_continue(now)


class AttackEngine(UpgradeEngine):
    """Engine del loop attacco: v1 apre/legge/chiude il menu Battle, senza combattere."""

    # ------------------------------------------------------------------ menu Battle
    def open_battle_menu(self) -> bool:
        """Apre il menu Battle dalla home e verifica lo stato (nessun raid)."""
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.BATTLE_MENU:
            return True
        if state is not ScreenState.HOME and not self.recover_home():
            self.log(f"open_battle_menu: stato {state.value} non recuperabile")
            return False
        image = self.grab()
        button = ui.find_battle_button(image)
        if button is None:
            self.log("open_battle_menu: pulsante Battle non trovato in home")
            return False
        self._tap(ui.center(button))
        frame = self._wait_state(ScreenState.BATTLE_MENU, timeout_s=4.0)
        if frame is None:
            self.log("open_battle_menu: menu Battle non rilevato dopo il tap")
            return False
        return True

    def close_battle_menu(self) -> bool:
        """Chiude il menu Battle e torna in home (ESC via messaggio; fallback sicuro)."""
        if states.classify(self.grab()) is ScreenState.HOME:
            return True
        self.log("close_battle_menu: provo ESC (messaggio Win32, nessun focus)")
        self.sink.key(VK_ESCAPE)
        if self._wait_state(ScreenState.HOME, timeout_s=3.0) is not None:
            return True
        self.log("close_battle_menu: ESC non sufficiente, fallback a recover_home")
        return self.recover_home()

    def scan_battle_menu(self) -> BattleMenuRead:
        """Apre il menu Battle, legge gli elementi principali e torna in home (sola lettura)."""
        notes: list[str] = []
        if not self.open_battle_menu():
            raise AttackEngineError("menu Battle non aperto")
        try:
            image = self.grab()
            state = states.classify(image)
            button = ui.find_find_match_button(image)
            if button is None:
                notes.append("pulsante 'Find a Match' non trovato")
            return BattleMenuRead(
                state=state.value,
                find_match_rect=button,
                find_match_center=None if button is None else ui.center(button),
                notes=tuple(notes),
            )
        finally:
            if not self.close_battle_menu():
                self.log("scan_battle_menu: chiusura del menu Battle non riuscita")


__all__ = [
    "AttackEngine",
    "AttackEngineError",
    "BattleMenuRead",
    "DEFAULT_WEIGHTS",
    "LootDecision",
    "SkipSession",
    "evaluate_loot",
]
