"""Engine del loop attacco (auto-battaglia): menu Battle, anteprima esercito e anteprima base.

Stato attuale (validato live 4 nov 2026):
1. apre il menu Battle dalla home e localizza "Find a Match" (geometria, senza OCR);
2. "Find a Match" -> pannello **My Army** (`ARMY_REVIEW`): X rossa per chiudere, pulsante verde
   "Attack!" che avvia la **ricerca base a pagamento** (~1100 oro);
3. "Attack!" -> **anteprima base** (`PREVIEW`): bottino disponibile (oro/elisir/dark), pulsante
   "Next" (salta base, ~1100 oro) e "End Battle" (torna in home senza deployare);
4. `evaluate_loot` (pura) decide se la base merita l'attacco; `SkipSession` limita skip/timeout.

**Non deploya e non attacca**: il deploy (dragon spam) e la gestione esiti verranno aggiunti dopo
la validazione dei frame di battaglia. Le azioni che spendono oro (Attack!, Next) sono esplicite
e non automatiche.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from cocbot.app.upgrade_engine import UpgradeEngine, UpgradeEngineError
from cocbot.core.types import Rect, ScreenState
from cocbot.vision import ocr as ocr_module
from cocbot.vision import states, textparse, ui

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


@dataclass(frozen=True, slots=True)
class LootPreview:
    """Bottino disponibile letto dall'anteprima base (pannello ``Available Loot``)."""

    gold: int | None
    elixir: int | None
    dark: int | None
    notes: tuple[str, ...] = ()


def parse_loot_items(items) -> LootPreview:
    """Estrae oro/elisir/dark dai testi OCR del pannello "Available Loot".

    I tre importi compaiono in quest'ordine dall'alto (oro, elisir, elisir nero); gli altri
    testi (nome giocatore, etichetta) non sono numeri e vengono ignorati. Funzione pura.
    """
    amounts: list[tuple[int, int]] = []
    for item in items:
        amount = textparse.parse_amount(item.text)
        if amount is not None:
            amounts.append((item.cy, amount))
    amounts.sort()
    values = [amount for _cy, amount in amounts]
    notes: list[str] = []
    if len(values) < 3:
        notes.append(f"loot: letti {len(values)} valori su 3")
    gold, elixir, dark = (values + [None, None, None])[:3]
    return LootPreview(gold=gold, elixir=elixir, dark=dark, notes=tuple(notes))


def evaluate_loot_from_config(loot, preview: LootPreview) -> LootDecision:
    """Applica la policy loot della config (``loot.thresholds`` + ``loot.weights``)."""
    thresholds = {
        "gold_min": loot.thresholds.gold_min,
        "elixir_min": loot.thresholds.elixir_min,
        "dark_min": loot.thresholds.dark_min,
        "score_min": loot.thresholds.score_min,
    }
    return evaluate_loot(
        preview.gold,
        preview.elixir,
        preview.dark,
        thresholds=thresholds,
        weights=loot.weights,
    )


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
    """Engine del loop attacco: menu Battle, anteprima esercito, anteprima base e skip."""

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
        """Chiude il menu Battle e torna in home (tap target in alto a destra; ESC fallback).

        Il menu Battle di questa versione non ha una X visibile: la chiusura e' un'area
        cliccabile invisibile nell'angolo in alto a destra (validata a runtime il 4 nov).
        """
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.HOME:
            return True
        if state is not ScreenState.BATTLE_MENU:
            self.log(f"close_battle_menu: stato {state.value}, uso recover_home")
            return self.recover_home()
        point = ui.find_battle_menu_close(image)
        if point is not None:
            self.log(f"close_battle_menu: tap di chiusura in alto a destra @ {point}")
            self.sink.tap_pixels(*point)
            if self._wait_state(ScreenState.HOME, timeout_s=4.0) is not None:
                return True
        self.log("close_battle_menu: tap di chiusura non sufficiente, provo ESC (messaggio)")
        self.sink.key(VK_ESCAPE)
        if self._wait_state(ScreenState.HOME, timeout_s=2.0) is not None:
            return True
        return self.recover_home()

    def open_army_panel(self) -> bool:
        """Apre il pannello "My Army" (anteprima pre-battaglia) dal menu Battle.

        Non spende risorse: la ricerca base (a pagamento) parte solo dal pulsante "Attack!".
        """
        if not self.open_battle_menu():
            return False
        image = self.grab()
        button = ui.find_find_match_button(image)
        if button is None:
            self.log("open_army_panel: pulsante 'Find a Match' non trovato")
            return False
        self._tap(ui.center(button), wait_s=1.2)
        frame = self._wait_state(ScreenState.ARMY_REVIEW, timeout_s=5.0)
        if frame is None:
            self.log("open_army_panel: pannello 'My Army' non rilevato")
            return False
        return True

    def close_army_panel(self) -> bool:
        """Chiude il pannello "My Army" con la X rossa e torna in home."""
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.HOME:
            return True
        point = ui.find_army_panel_close(image)
        if point is None:
            self.log(f"close_army_panel: X non trovata (stato {state.value}), uso recover_home")
            return self.recover_home()
        self._tap(point, wait_s=1.2)
        if self._wait_state(ScreenState.HOME, timeout_s=4.0) is not None:
            return True
        return self.recover_home()

    # ------------------------------------------------------------------ anteprima base
    def read_loot(self) -> LootPreview:
        """Legge oro/elisir/dark del pannello "Available Loot" (OCR ~0,9 s)."""
        image = self.grab()
        region = ui.loot_region(image)
        items = ocr_module.read_texts(
            image[region.y : region.bottom, region.x : region.right],
            offset=(region.x, region.y),
        )
        preview = parse_loot_items(items)
        if preview.notes:
            self.log(f"read_loot: {', '.join(preview.notes)}")
        return preview

    def open_search(self, *, timeout_s: float = 25.0) -> bool:
        """Da home: menu Battle -> Find a Match -> My Army -> "Attack!" -> anteprima base.

        Se il pannello "My Army" e' gia' aperto riusa quello (evita un giro inutile).
        **Spende ~1100 oro** (costo della ricerca base): usare solo con autorizzazione esplicita.
        """
        state = states.classify(self.grab())
        if state is not ScreenState.ARMY_REVIEW and not self.open_army_panel():
            return False
        image = self.grab()
        attack = ui.find_attack_button(image)
        if attack is None:
            self.log("open_search: pulsante 'Attack!' non trovato")
            return False
        self.log("open_search: premo 'Attack!' (avvia la ricerca base, ~1100 oro)")
        self._tap(ui.center(attack), wait_s=0.5)
        frame = self._wait_state(ScreenState.PREVIEW, timeout_s=timeout_s)
        if frame is None:
            self.log("open_search: anteprima base non rilevata")
            return False
        return True

    def next_base(self, *, timeout_s: float = 25.0) -> bool:
        """Salta alla base successiva con "Next" (**spende ~1100 oro**)."""
        image = self.grab()
        button = ui.find_next_button(image)
        if button is None:
            self.log("next_base: pulsante Next non trovato")
            return False
        self.log("next_base: premo 'Next' (~1100 oro)")
        self._tap(ui.center(button), wait_s=0.5)
        return self._wait_state(ScreenState.PREVIEW, timeout_s=timeout_s) is not None

    def end_battle(self) -> bool:
        """Torna in home dall'anteprima base con "End Battle" (nessun deploy)."""
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.HOME:
            return True
        button = ui.find_end_battle_button(image)
        if button is None:
            self.log(f"end_battle: pulsante End Battle non trovato (stato {state.value})")
            return self.recover_home()
        self.log("end_battle: premo 'End Battle' (nessun deploy)")
        self._tap(ui.center(button), wait_s=1.2)
        if self._wait_state(ScreenState.HOME, timeout_s=8.0) is not None:
            return True
        self.log("end_battle: home non raggiunta, uso recover_home")
        return self.recover_home()

    def wait_battle_start(self, *, timeout_s: float = 40.0) -> bool:
        """Attende che il countdown 'Battle starts in' finisca (nessun input inviato)."""
        if states.classify(self.grab()) is ScreenState.BATTLE:
            return True
        frame = self._wait_state(ScreenState.BATTLE, timeout_s=timeout_s)
        if frame is None:
            self.log("wait_battle_start: battaglia non iniziata entro il timeout")
            return False
        return True

    @staticmethod
    def _region_diff(first, second, region: Rect) -> float:
        a = first[region.y : region.bottom, region.x : region.right]
        b = second[region.y : region.bottom, region.x : region.right]
        if a.shape != b.shape or a.size == 0:
            return -1.0
        return float(cv2.absdiff(a, b).mean())

    def deploy_dragon_spam(
        self,
        image: np.ndarray,
        *,
        dragons: int = 13,
        heroes: bool = True,
        max_taps: int = 90,
    ) -> int:
        """Deploya i draghi provando tessere di erba libera + griglia, in **due passate**.

        Misura live: tap sulla card = selezione (la card si ingrandisce e **resta selezionata**
        dopo i deploy: non va ritoccata, altrimenti si rischia di deselezionarla); tap su una
        tessera di erba libera = una truppa deployata; tap su edifici/muri = sola ispezione.
        Le tessere visibili e deployabili sono poche (le altre sono fuori schermo): la seconda
        passata, dopo una pausa, riprova le stesse tessere quando le truppe le hanno liberate.
        Il contatore "xN" della card viene confrontato per differenza immagine.
        Ritorna i tap di deploy inviati.
        """
        h, w = image.shape[:2]
        candidates = ui.find_deploy_candidates(image, limit=max(dragons, 6))
        grid = ui.battle_field_grid(image)
        points: list[tuple[int, int]] = []
        for point in candidates + grid:
            if point not in points:
                points.append(point)
        if not points:
            self.log("deploy: nessun punto di deploy trovato")
            return 0
        count_region = Rect(int(w * 0.168), int(h * 0.848), int(w * 0.042), int(h * 0.034))
        card = ui.battle_card_point(image, ui.BATTLE_DRAGON_CARD)
        self.log(f"deploy: seleziono i draghi @ {card} ({len(candidates)} erba + {len(grid)} griglia)")
        self._tap(card, wait_s=0.5)
        previous = self.grab()
        deployed = 0
        attempts = 0
        for pass_index in range(2):
            if pass_index == 1:
                if deployed >= dragons:
                    break
                self.log(f"deploy: seconda passata (deployati finora {deployed})")
                time.sleep(3.0)
            for point in points[:max_taps]:
                self._tap(point, wait_s=0.3)
                attempts += 1
                current = self.grab()
                if self._region_diff(previous, current, count_region) > 6.0:
                    deployed += 1
                    if deployed >= dragons:
                        break
                previous = current
        if heroes:
            for label, fraction in (
                ("arciere", ui.BATTLE_QUEEN_CARD),
                ("grand warden", ui.BATTLE_WARDEN_CARD),
            ):
                hero_card = ui.battle_card_point(image, fraction)
                self.log(f"deploy: provo l'eroe {label} @ {hero_card}")
                self._tap(hero_card, wait_s=0.4)
                self._tap(points[attempts % len(points)], wait_s=0.3)
                attempts += 1
        self.log(f"deploy: truppe deployate rilevate={deployed}, tap={attempts}")
        return attempts

    def return_home(self) -> bool:
        """Dalla schermata risultati battaglia: preme "Return Home" e attende la home."""
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.HOME:
            return True
        button = ui.find_return_home_button(image)
        if button is None:
            self.log(f"return_home: pulsante Return Home non trovato (stato {state.value})")
            return self.recover_home()
        self.log("return_home: premo 'Return Home' (fine battaglia)")
        self._tap(ui.center(button), wait_s=1.5)
        if self._wait_state(ScreenState.HOME, timeout_s=8.0) is not None:
            return True
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
    "LootPreview",
    "SkipSession",
    "evaluate_loot",
    "evaluate_loot_from_config",
    "parse_loot_items",
]
