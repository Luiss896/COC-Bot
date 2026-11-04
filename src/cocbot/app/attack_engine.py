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

import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from cocbot.app.upgrade_engine import UpgradeEngine, UpgradeEngineError
from cocbot.capture import win32
from cocbot.core.types import Rect, ScreenState
from cocbot.vision import battle_result, states, textparse, ui
from cocbot.vision import ocr as ocr_module

VK_ESCAPE = 0x1B

DEFAULT_WEIGHTS: dict[str, float] = {"gold": 1.0, "elixir": 1.0, "dark": 100.0}

# costo indicativo di una ricerca base o di uno skip ("Next"), usato per i tetti di spesa
SEARCH_COST_GOLD = 1_100

# azioni di un ciclo di attacco dopo le quali il farm si ferma (invece di continuare)
FARM_STOP_ACTIONS: dict[str, str] = {
    "storage_full": "storage piene e dark insufficiente per il fallback",
    "skip_limit": "limite di skip/ricerche raggiunto",
    "search_cap": "tetto ricerche raggiunto",
    "unreadable_loot": "bottino non leggibile",
    "battle_end_timeout": "timeout in attesa della fine battaglia",
    "battle_aborted_home": "battaglia interrotta (ritorno in home)",
    "next_failed": "'Next' non riuscito",
    "battle_not_started": "battaglia non iniziata",
}


def farm_stop_reason(cycle_report: dict) -> str | None:
    """Motivo per fermare il farm dopo un ciclo di attacco; ``None`` se si può continuare."""
    action = cycle_report.get("action")
    if action == "attacked":
        return None
    return FARM_STOP_ACTIONS.get(action or "", f"azione non prevista: {action}")


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


def usable_capacity(
    hud,
    *,
    cap_gold: int,
    cap_elixir: int,
) -> tuple[int | None, int | None]:
    """Capacita' residua delle storage (oro, elisir) letta dall'HUD; ``None`` = non nota.

    Con storage piene il bottino in eccesso va perso: il loop attacco usa questi valori per
    decidere se valga la pena spendere una ricerca (funzione pura).
    """
    gold = None if hud.gold is None else max(0, cap_gold - hud.gold)
    elixir = None if hud.elixir is None else max(0, cap_elixir - hud.elixir)
    return gold, elixir


def usable_dark_capacity(hud, *, cap_dark: int) -> int | None:
    """Capacita' residua del dark elixir (``None`` se non nota)."""
    return None if hud.dark is None else max(0, cap_dark - hud.dark)


def apply_capacity(
    loot: LootPreview,
    *,
    usable_gold: int | None,
    usable_elixir: int | None,
) -> LootPreview:
    """Riduce il bottino atteso alla capacita' residua (evita raid che non incassano)."""
    gold = loot.gold
    if gold is not None and usable_gold is not None:
        gold = min(gold, usable_gold)
    elixir = loot.elixir
    if elixir is not None and usable_elixir is not None:
        elixir = min(elixir, usable_elixir)
    return LootPreview(gold=gold, elixir=elixir, dark=loot.dark, notes=loot.notes)


def save_attack_report(report: dict, out_dir: str | Path = "out/attack", prefix: str = "attack") -> Path:
    """Salva il report di un raid/farm in JSON (telemetria) e ritorna il percorso."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def dark_fallback_decision(
    loot: LootPreview,
    *,
    usable_gold: int | None,
    usable_elixir: int | None,
    usable_dark: int | None = None,
    thresholds: dict[str, int] | None = None,
    weights: dict[str, float] | None = None,
) -> LootDecision | None:
    """Attacco "solo dark" quando oro/elisir non sono incassabili (storage piene).

    Se la capacita' residua rende oro/elisir sotto le soglie ma il **dark elixir** della base
    raggiunge ``dark_min``, autorizza comunque il raid (il dark non e' limitato dalle storage
    piene). ``usable_dark == 0`` (dark al cap) disattiva il fallback. Funzione pura; ``None``
    se il fallback non si applica.
    """
    thresholds = thresholds or {}
    weights = weights or DEFAULT_WEIGHTS
    if usable_dark == 0:
        return None
    effective = apply_capacity(loot, usable_gold=usable_gold, usable_elixir=usable_elixir)
    if effective.gold is None or effective.elixir is None:
        return None
    gold_min = int(thresholds.get("gold_min", 0))
    elixir_min = int(thresholds.get("elixir_min", 0))
    dark_min = int(thresholds.get("dark_min", 0))
    # si applica solo se oro/elisir sono stati limitati dalla capacita'
    if effective.gold >= gold_min and effective.elixir >= elixir_min:
        return None
    dark = loot.dark
    if dark is None or dark < dark_min:
        return None
    score = dark * float(weights.get("dark", 100.0))
    reason = (
        f"solo dark: {dark} >= {dark_min} (oro/elisir limitati dalla capacita': "
        f"{effective.gold}/{effective.elixir})"
    )
    return LootDecision(
        gold=effective.gold,
        elixir=effective.elixir,
        dark=dark,
        score=score,
        should_attack=True,
        reason=reason,
    )


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

    def read_battle_result(self) -> battle_result.BattleResult:
        """Legge esito/danno/bottino/truppe dalla schermata risultati (stato BATTLE_END)."""
        image = self.grab()
        if states.classify(image) is not ScreenState.BATTLE_END:
            self.log("read_battle_result: non sono nella schermata risultati")
        return battle_result.read_result(image)

    def read_overall_damage(self) -> int | None:
        """Legge la percentuale "Overall Damage" mostrata in basso a destra in battaglia."""
        return battle_result.read_overall_damage(self.grab())

    def end_battle_early(self, *, confirm_timeout_s: float = 4.0) -> bool:
        """Durante la battaglia: preme "End Battle" (chiude con il danno attuale → risultati).

        Se compare un dialogo di conferma preme il bottone verde CONFIRM. Ritorna True se si
        raggiunge la schermata risultati (o la home), False se non e' riuscito.
        """
        image = self.grab()
        button = ui.find_end_battle_button(image)
        if button is None:
            self.log("end_battle_early: pulsante End Battle non trovato")
            return False
        self.log("end_battle_early: premo 'End Battle' durante la battaglia")
        self._tap(ui.center(button), wait_s=1.2)
        deadline = time.monotonic() + confirm_timeout_s
        while time.monotonic() < deadline:
            frame = self.grab()
            state = states.classify(frame)
            if state in (ScreenState.BATTLE_END, ScreenState.HOME):
                return True
            confirm = ui.find_confirm_button(frame)
            if confirm is not None:
                self.log("end_battle_early: confermo la fine battaglia")
                self._tap(ui.center(confirm), wait_s=1.2)
            time.sleep(0.5)
        return self._wait_state(ScreenState.BATTLE_END, timeout_s=15.0) is not None

    def _hud_text(self) -> str | None:
        try:
            return str(self.read_hud(self.grab()))
        except AttackEngineError:
            return None

    def _finish_report(self, report: dict) -> dict:
        report["hud_after"] = self._hud_text()
        try:
            report["report_path"] = str(save_attack_report(report))
        except OSError as exc:
            report["report_path"] = None
            self.log(f"telemetria: salvataggio report fallito: {exc}")
        return report

    def run_attack(
        self,
        *,
        allow_spend: bool = False,
        max_searches: int = 2,
        dragons: int = 13,
        heroes: bool = True,
        spells: int = 0,
        respect_storage_caps: bool = True,
        early_exit_damage: int = 0,
        battle_end_timeout_s: float = 240.0,
    ) -> dict:
        """Ciclo di attacco completo: ricerca (eventuali skip), deploy, esito, ritorno in home.

        ``allow_spend=False`` = **dry-run**: apre e richiude il pannello esercito senza spendere.
        Con ``allow_spend=True`` ogni ricerca/"Next" costa ~1100 oro e ``max_searches`` limita il
        numero totale di ricerche (= tetto di spesa ``max_searches * 1100`` oro circa); in piu'
        ``SkipSession`` applica i limiti di config ``loot.max_skip_per_attack`` / ``skip_timeout_s``.
        ``spells``: quante spell lanciare dopo draghi/eroi (0 = nessuna).
        ``respect_storage_caps``: legge l'HUD prima di spendere e salta il raid se oro+elisir sono
        al cap (``attack.storage_cap_gold``/``storage_cap_elixir``); il bottino atteso viene ridotto
        alla capacita' residua per la decisione.
        ``early_exit_damage``: se >0, durante la battaglia legge "Overall Damage" e quando il danno
        raggiunge la soglia preme "End Battle" per chiudere subito (risparmia tempo); 0 = disattivo.
        Ritorna un report con ricerche/skip, bottini letti, decisione, esito e HUD prima/dopo.
        """
        report: dict = {
            "dry_run": not allow_spend,
            "searches": 0,
            "skips": 0,
            "skip_limit_reason": None,
            "loots": [],
            "decision": None,
            "usable_capacity": None,
            "attacked": False,
            "early_exit": False,
            "dark_fallback": False,
            "result": None,
            "action": None,
            "hud_before": None,
            "hud_after": None,
            "report_path": None,
        }
        if not self.open_battle_menu():
            raise AttackEngineError("menu Battle non apribile")
        if not allow_spend:
            if not self.open_army_panel():
                raise AttackEngineError("pannello My Army non apribile")
            if not self.close_army_panel():
                raise AttackEngineError("pannello My Army non chiudibile")
            if not self.close_battle_menu():
                raise AttackEngineError("menu Battle non chiudibile")
            report["action"] = "dry_run"
            return report
        hud = self.read_hud(self.grab())
        report["hud_before"] = str(hud)
        usable_gold: int | None = None
        usable_elixir: int | None = None
        usable_dark: int | None = None
        attack_config = self.config.attack
        if respect_storage_caps and attack_config.respect_storage_caps:
            usable_gold, usable_elixir = usable_capacity(
                hud,
                cap_gold=attack_config.storage_cap_gold,
                cap_elixir=attack_config.storage_cap_elixir,
            )
            usable_dark = usable_dark_capacity(hud, cap_dark=attack_config.storage_cap_dark)
            report["usable_capacity"] = {
                "gold": usable_gold,
                "elixir": usable_elixir,
                "dark": usable_dark,
            }
            gold_elixir_full = usable_gold == 0 and usable_elixir == 0
            dark_full = usable_dark == 0
            if gold_elixir_full and dark_full:
                self.log(
                    "run_attack: storage piene (oro+elisir+dark al cap): nessuna ricerca avviata"
                )
                report["action"] = "storage_full"
                self.close_battle_menu()
                return self._finish_report(report)
            if gold_elixir_full:
                self.log(
                    "run_attack: oro+elisir al cap ma dark disponibile: si procede "
                    "(il fallback 'solo dark' decidera' sulla base)"
                )
        skip_session = SkipSession(
            max_skip=max(0, min(self.config.loot.max_skip_per_attack, max_searches - 1)),
            timeout_s=float(self.config.loot.skip_timeout_s),
        )
        try:
            if not self.open_search():
                raise AttackEngineError("ricerca base non avviata / anteprima non rilevata")
            report["searches"] = 1
            skip_session.start(time.monotonic())
            while True:
                loot = self.read_loot()
                effective = apply_capacity(
                    loot, usable_gold=usable_gold, usable_elixir=usable_elixir
                )
                report["loots"].append(
                    {
                        "gold": loot.gold,
                        "elixir": loot.elixir,
                        "dark": loot.dark,
                        "incassabile_gold": effective.gold,
                        "incassabile_elixir": effective.elixir,
                    }
                )
                decision = evaluate_loot_from_config(self.config.loot, effective)
                if not decision.should_attack and attack_config.attack_for_dark_when_full:
                    fallback = dark_fallback_decision(
                        loot,
                        usable_gold=usable_gold,
                        usable_elixir=usable_elixir,
                        usable_dark=usable_dark,
                        thresholds={
                            "gold_min": self.config.loot.thresholds.gold_min,
                            "elixir_min": self.config.loot.thresholds.elixir_min,
                            "dark_min": self.config.loot.thresholds.dark_min,
                        },
                        weights=self.config.loot.weights,
                    )
                    if fallback is not None:
                        decision = fallback
                        report["dark_fallback"] = True
                report["decision"] = decision.reason
                if decision.should_attack:
                    break
                if (
                    self.config.loot.skip_if_unreadable
                    and loot.gold is None
                    and loot.elixir is None
                    and loot.dark is None
                ):
                    report["action"] = "unreadable_loot"
                    self.end_battle()
                    return self._finish_report(report)
                if report["searches"] >= max_searches:
                    report["action"] = "search_cap"
                    self.end_battle()
                    return self._finish_report(report)
                can_skip, reason = skip_session.can_continue(time.monotonic())
                if not can_skip:
                    report["action"] = "skip_limit"
                    report["skip_limit_reason"] = reason
                    self.end_battle()
                    return self._finish_report(report)
                if not self.next_base():
                    self.log("run_attack: 'Next' non riuscito, esco con End Battle")
                    report["action"] = "next_failed"
                    self.end_battle()
                    return self._finish_report(report)
                report["searches"] += 1
                report["skips"] += 1
                skip_session.record_skip(time.monotonic())
            if not self.wait_battle_start():
                report["action"] = "battle_not_started"
                self.end_battle()
                return self._finish_report(report)
            time.sleep(3.0)
            battle = self.grab()
            self.pan_camera(0.28, image=battle)
            time.sleep(0.8)
            report["deploy_taps"] = self.deploy_dragon_spam(
                self.grab(), dragons=dragons, heroes=heroes
            )
            if spells > 0:
                report["spell_taps"] = self.deploy_spells(self.grab(), count=spells)
            end_frame = None
            started = time.monotonic()
            early_exit_fired = False
            while time.monotonic() - started < battle_end_timeout_s:
                try:
                    image = self.grab()
                except AttackEngineError as exc:
                    self.log(f"battaglia: grab fallito: {exc}")
                    time.sleep(1.0)
                    continue
                state = states.classify(image)
                if state is ScreenState.BATTLE_END:
                    end_frame = image
                    break
                if state is ScreenState.HOME:
                    report["action"] = "battle_aborted_home"
                    return self._finish_report(report)
                if early_exit_damage > 0 and state is ScreenState.BATTLE and not early_exit_fired:
                    percent = battle_result.read_overall_damage(image)
                    if percent is not None and percent >= early_exit_damage:
                        self.log(
                            f"early-exit: danno {percent}% >= obiettivo {early_exit_damage}%"
                        )
                        report["early_exit_damage_pct"] = percent
                        early_exit_fired = True
                        self.end_battle_early()
                        continue
                time.sleep(4.0)
            report["early_exit"] = early_exit_fired
            if end_frame is None:
                report["action"] = "battle_end_timeout"
                return self._finish_report(report)
            result = self.read_battle_result()
            report["result"] = {
                "outcome": result.outcome,
                "damage_pct": result.damage_pct,
                "loot_gold": result.loot_gold,
                "loot_elixir": result.loot_elixir,
                "loot_dark": result.loot_dark,
                "troops_expended": result.troops_expended,
                "notes": list(result.notes),
            }
            report["attacked"] = True
            report["action"] = "attacked"
            self.return_home()
            return self._finish_report(report)
        finally:
            state = states.classify(self.grab())
            if state is ScreenState.PREVIEW:
                self.end_battle()
            elif state is ScreenState.BATTLE_END:
                self.return_home()

    def run_farm(
        self,
        *,
        cycles: int = 2,
        allow_spend: bool = False,
        max_searches: int = 1,
        dragons: int = 13,
        heroes: bool = True,
        spells: int = 5,
        early_exit_damage: int = 40,
        max_gold_spend: int = 2_200,
        sleep_between_s: float = 8.0,
    ) -> dict:
        """Ripete il ciclo attacco con **tetto di spesa** e si ferma se un ciclo non attacca.

        Spesa stimata = ``ricerche * 1100`` oro (ricerca + eventuali "Next"); il farm non supera
        ``max_gold_spend``. Dry-run: un solo ``run_attack`` senza spese. Il report complessivo
        (cicli, spesa, esiti, motivo di stop) viene salvato in ``out/attack/farm-*.json``.
        """
        report: dict = {
            "dry_run": not allow_spend,
            "cycles_requested": max(1, cycles),
            "cycles_done": 0,
            "spent_gold": 0,
            "max_gold_spend": max_gold_spend,
            "stopped": None,
            "reports": [],
            "report_path": None,
        }
        if not allow_spend:
            cycle_report = self.run_attack(
                allow_spend=False,
                max_searches=1,
                dragons=dragons,
                heroes=heroes,
                spells=0,
                early_exit_damage=0,
            )
            report["reports"].append(cycle_report)
            report["stopped"] = "dry_run"
            return report
        for index in range(report["cycles_requested"]):
            if report["spent_gold"] + SEARCH_COST_GOLD > max_gold_spend:
                report["stopped"] = (
                    f"tetto spesa oro ({report['spent_gold']} + {SEARCH_COST_GOLD} > {max_gold_spend})"
                )
                break
            self.log(
                f"farm: ciclo {index + 1}/{report['cycles_requested']} "
                f"(speso finora {report['spent_gold']} oro)"
            )
            cycle_report = self.run_attack(
                allow_spend=True,
                max_searches=max_searches,
                dragons=dragons,
                heroes=heroes,
                spells=spells,
                early_exit_damage=early_exit_damage,
            )
            report["reports"].append(cycle_report)
            report["cycles_done"] += 1
            report["spent_gold"] += int(cycle_report.get("searches") or 0) * SEARCH_COST_GOLD
            reason = farm_stop_reason(cycle_report)
            if reason is not None:
                report["stopped"] = reason
                break
            if index + 1 < report["cycles_requested"]:
                time.sleep(max(0.0, sleep_between_s))
        if report["stopped"] is None:
            report["stopped"] = "completato"
        try:
            report["report_path"] = str(save_attack_report(report, prefix="farm"))
        except OSError as exc:
            self.log(f"farm: salvataggio report fallito: {exc}")
        return report

    @staticmethod
    def _region_diff(first, second, region: Rect) -> float:
        a = first[region.y : region.bottom, region.x : region.right]
        b = second[region.y : region.bottom, region.x : region.right]
        if a.shape != b.shape or a.size == 0:
            return -1.0
        return float(cv2.absdiff(a, b).mean())

    def pan_camera(self, dx_fraction: float = 0.25, dy_fraction: float = 0.0, *, image=None) -> None:
        """Panna la camera del campo con un drag via messaggi Win32 (nessuna truppa selezionata).

        Verificato live: il drag sposta la vista e rivela la zona deployabile (erba con tessere
        tratteggiate) attorno al villaggio nemico; deve avvenire **prima** di selezionare la
        truppa (con una truppa selezionata il drag sul campo non panna).
        """
        frame = image if image is not None else self.grab()
        h, w = frame.shape[:2]
        x0, y0 = int(w * 0.55), int(h * 0.45)
        x1 = int(x0 - w * dx_fraction)
        y1 = int(y0 - h * dy_fraction)
        win32.post_mouse_drag(self.window.hwnd, x0, y0, x1, y1, steps=12, hold_ms=60)
        time.sleep(0.6)
        self.log(f"pan_camera: drag ({x0},{y0})->({x1},{y1})")

    def deploy_spells(self, image: np.ndarray, *, count: int = 5) -> int:
        """Seleziona la card spell e lancia le spell sulle tessere di erba/centro villaggio.

        Meccanica assunta (da validare live): tap card spell = seleziona, tap sul campo = lancia.
        Ritorna i tap inviati (2 per spell).
        """
        h, w = image.shape[:2]
        card = ui.battle_card_point(image, ui.BATTLE_SPELL_CARD)
        targets = ui.find_deploy_candidates(image, limit=8)
        if not targets:
            targets = [(int(w * 0.50), int(h * 0.45))]
        taps = 0
        self.log(f"deploy_spells: seleziono la spell @ {card} e ne lancio {count}")
        for index in range(count):
            self._tap(card, wait_s=0.35)
            self._tap(targets[index % len(targets)], wait_s=0.5)
            taps += 2
        return taps

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
        """Dalla schermata risultati battaglia: preme "Return Home" e attende la home.

        Se lo stato e' ancora ``BATTLE``/``PREVIEW`` **non** preme nulla: nella barra truppe
        ci sono elementi verdi (es. "Boost Heroes") che possono somigliare a "Return Home";
        in battaglia la chiusura va fatta con ``end_battle``/``end_battle_early``.
        """
        image = self.grab()
        state = states.classify(image)
        if state is ScreenState.HOME:
            return True
        if state in (ScreenState.BATTLE, ScreenState.PREVIEW):
            self.log(
                f"return_home: stato {state.value}: non premo 'Return Home' "
                "(serve end_battle/end_battle_early)"
            )
            return False
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
