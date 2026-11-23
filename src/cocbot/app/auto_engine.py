"""Loop AUTO unico: farm finché i depositi sono pieni, poi upgrade per priorità, stop condizioni.

Un solo processo alterna le due fasi (mai due motori input in parallelo):

1. **farm**: raid Dragon Corner (angolo casuale, invisibilità) ripetuti finché
   oro/elisir/dark non raggiungono il cap;
2. **upgrade**: scansione del menu Build + piano per priorità (`upgrade.priority`) con i
   tetti di spesa configurati, eseguito dal planner esistente;
3. **stop**: si ferma solo quando *tutti i builder sono occupati* e *i depositi sono pieni*
   (e, se `auto.require_lab_and_pets`, anche laboratorio e casa dei famigli risultano al
   lavoro). Se lo stato di lab/famigli non è rilevabile, il loop aspetta invece di
   fermarsi: mai un auto-stop con condizioni non verificate.

La logica di decisione (:func:`decide_auto_step`, :func:`storage_status`) è pura e testabile
offline; :class:`AutoEngine` orchestra gli engine esistenti.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from cocbot.app.attack_engine import AttackEngine
from cocbot.app.upgrade_engine import (
    HudRead,
    UpgradeEngine,
    UpgradeEngineError,
    UpgradePlan,
    filter_plan_by_budget,
    save_json,
)
from cocbot.config.models import Config

AUTO_REPORT_PREFIX = "auto"


class AutoAction(StrEnum):
    FARM = "farm"
    UPGRADE = "upgrade"
    WAIT = "wait"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class StorageStatus:
    """Quali depositi sono al cap (letti dall'HUD della home)."""

    gold_full: bool
    elixir_full: bool
    dark_full: bool

    @property
    def all_full(self) -> bool:
        return self.gold_full and self.elixir_full and self.dark_full

    def describe(self) -> str:
        def label(name: str, full: bool) -> str:
            return f"{name}={'pieno' if full else 'non pieno'}"

        parts = (
            label("oro", self.gold_full),
            label("elisir", self.elixir_full),
            label("dark", self.dark_full),
        )
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class AutoDecision:
    action: AutoAction
    reason: str


def _is_full(value: int | None, cap: int, ratio: float) -> bool:
    if value is None or cap <= 0:
        return False
    return value >= cap * ratio


def storage_status(hud: HudRead, config: Config) -> StorageStatus:
    """Stato dei depositi rispetto ai cap di config (``auto.storage_full_ratio``)."""
    ratio = float(config.auto.storage_full_ratio)
    return StorageStatus(
        gold_full=_is_full(hud.gold, config.attack.storage_cap_gold, ratio),
        elixir_full=_is_full(hud.elixir, config.attack.storage_cap_elixir, ratio),
        dark_full=_is_full(hud.dark, config.attack.storage_cap_dark, ratio),
    )


def decide_auto_step(
    hud: HudRead,
    plan: UpgradePlan | None,
    config: Config,
    *,
    lab_busy: bool | None = None,
    pets_busy: bool | None = None,
    require_lab_and_pets: bool | None = None,
) -> AutoDecision:
    """Decide la prossima azione del loop AUTO (funzione pura).

    ``plan`` può essere ``None`` quando i depositi non sono pieni (non serve scansionare).
    ``lab_busy``/``pets_busy`` sono ``None`` quando non rilevabili: in tal caso, se la
    condizione è richiesta, il loop **aspetta** invece di fermarsi.
    """
    if not config.auto.enabled:
        return AutoDecision(AutoAction.STOP, "auto disabilitato in config (auto.enabled=false)")
    status = storage_status(hud, config)
    builders = hud.builders_available if hud.builders_known else None
    executable = len(plan.chosen) if plan is not None else 0
    candidates = len(plan.candidates) if plan is not None else 0

    if not status.all_full:
        return AutoDecision(AutoAction.FARM, f"farm: depositi non pieni ({status.describe()})")

    require_lab = config.auto.require_lab_and_pets if require_lab_and_pets is None else require_lab_and_pets
    if builders is None:
        if executable > 0:
            return AutoDecision(AutoAction.UPGRADE, "depositi pieni, builder non letti: provo il piano")
        return AutoDecision(AutoAction.STOP, "depositi pieni e builder non leggibili: stop prudente")

    if builders > 0:
        if executable > 0:
            return AutoDecision(
                AutoAction.UPGRADE,
                f"depositi pieni e {builders} builder liberi: eseguo {executable} upgrade",
            )
        if candidates > 0:
            return AutoDecision(
                AutoAction.STOP,
                "depositi pieni, builder liberi ma upgrade non eseguibili (budget/limiti)",
            )
        return AutoDecision(AutoAction.STOP, "depositi pieni e nessun upgrade disponibile")

    # tutti i builder occupati
    if executable > 0:
        return AutoDecision(AutoAction.STOP, "tutti i builder occupati: nessun upgrade eseguibile")
    if not require_lab:
        return AutoDecision(
            AutoAction.STOP,
            "AUTO-STOP: builder tutti occupati + depositi pieni",
        )
    if lab_busy is None or pets_busy is None:
        return AutoDecision(
            AutoAction.WAIT,
            "builder e depositi pieni, ma laboratorio/famigli non rilevabili: attendo (nessuno stop non verificato)",
        )
    if lab_busy and pets_busy:
        return AutoDecision(
            AutoAction.STOP,
            "AUTO-STOP: builder occupati + depositi pieni + laboratorio e famigli al lavoro",
        )
    return AutoDecision(
        AutoAction.WAIT,
        f"builder e depositi pieni, ma lab={lab_busy} famigli={pets_busy}: attendo che siano al lavoro",
    )


def detect_lab_and_pets(engine: UpgradeEngine) -> tuple[bool | None, bool | None]:
    """Rileva se laboratorio e casa dei famigli sono al lavoro.

    TODO(live): richiede frame/validazione del gioco reale (il laboratorio non espone lo
    stato nel menu Build). Finché non è implementato ritorna ``(None, None)``: con
    ``auto.require_lab_and_pets=true`` il loop AUTO attende invece di fermarsi, così non
    dichiara mai uno stop con condizioni non verificate.
    """
    engine.log("auto: stato laboratorio/famigli non rilevabile (serve validazione live)")
    return None, None


class AutoEngine:
    """Orchestratore AUTO: usa gli engine attack/upgrade esistenti in sequenza."""

    def __init__(
        self,
        upgrade: UpgradeEngine,
        attack: AttackEngine,
        config: Config,
        *,
        log: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lab_pets_detector: Callable[[UpgradeEngine], tuple[bool | None, bool | None]] | None = None,
        report_dir: str | Path = "out/auto",
    ) -> None:
        self.upgrade = upgrade
        self.attack = attack
        self.config = config
        self.log = log or (lambda _message: None)
        self._sleep = sleep
        self._lab_pets_detector = lab_pets_detector
        self.report_dir = Path(report_dir)

    # ------------------------------------------------------------------ helpers
    def _read_hud(self) -> HudRead:
        if not self.upgrade.recover_home():
            raise UpgradeEngineError("auto: non riesco a tornare in home")
        return self.upgrade.read_hud(self.upgrade.grab())

    def _scan_plan(self, budgets: dict[str, int] | None, max_upgrades: int | None) -> UpgradePlan:
        self.log("auto: scansione menu Build per il piano di upgrade")
        scan = self.upgrade.scan(max_scrolls=self.config.upgrade.max_scan_scrolls)
        plan = self.upgrade.plan(scan)
        if budgets or max_upgrades is not None:
            plan = filter_plan_by_budget(plan, budgets=budgets, max_upgrades=max_upgrades)
        return plan

    def _lab_pets(self, require: bool) -> tuple[bool | None, bool | None]:
        if not require:
            return None, None
        detector = self._lab_pets_detector or detect_lab_and_pets
        return detector(self.upgrade)

    @staticmethod
    def _farm_summary(cycle: dict[str, Any]) -> dict[str, Any]:
        result = cycle.get("result") or {}
        return {
            "action": cycle.get("action"),
            "searches": cycle.get("searches"),
            "skips": cycle.get("skips"),
            "strategy": cycle.get("strategy"),
            "corner": cycle.get("corner"),
            "deploy_phase": cycle.get("deploy_phase"),
            "battle_started_by_deploy": cycle.get("battle_started_by_deploy"),
            "outcome": result.get("outcome"),
            "damage_pct": result.get("damage_pct"),
            "loot_gold": result.get("loot_gold"),
            "loot_elixir": result.get("loot_elixir"),
            "loot_dark": result.get("loot_dark"),
        }

    def _finish(self, report: dict[str, Any]) -> dict[str, Any]:
        report["final_hud"] = report.pop("_final_hud", None)
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            report["report_path"] = str(
                save_json(self.report_dir / f"{AUTO_REPORT_PREFIX}-{stamp}.json", report)
            )
        except OSError as exc:
            report["report_path"] = None
            self.log(f"auto: salvataggio report fallito: {exc}")
        return report

    # ------------------------------------------------------------------ run
    def run(
        self,
        *,
        allow_spend: bool = False,
        cycles: int = 20,
        farm_max_searches: int = 1,
        dragons: int = 13,
        heroes: bool = True,
        spells: int = 0,
        clones: int | None = None,
        strategy: str | None = None,
        clone_card_slot: int | None = None,
        corner: str | None = None,
        invisibility: int | None = None,
        invisibility_card_slot: int | None = None,
        early_exit_damage: int = 0,
        upgrade_budgets: dict[str, int] | None = None,
        max_upgrades: int | None = None,
        require_lab_and_pets: bool | None = None,
        sleep_between_s: float = 2.0,
        wait_between_s: float = 120.0,
    ) -> dict[str, Any]:
        """Esegue il loop AUTO e ritorna il report (salvato in ``out/auto/``)."""
        report: dict[str, Any] = {
            "dry_run": not allow_spend,
            "cycles_requested": max(1, int(cycles)),
            "cycles_done": 0,
            "actions": [],
            "stop_reason": None,
            "farm": {"attacks": 0, "searches": 0, "outcomes": []},
            "upgrade": {"plans": 0, "executed": 0, "results": []},
            "final_hud": None,
            "report_path": None,
        }
        require = (
            self.config.auto.require_lab_and_pets
            if require_lab_and_pets is None
            else bool(require_lab_and_pets)
        )

        if not allow_spend:
            hud = self._read_hud()
            status = storage_status(hud, self.config)
            plan = self._scan_plan(upgrade_budgets, max_upgrades) if status.all_full else None
            lab_busy, pets_busy = self._lab_pets(require)
            decision = decide_auto_step(
                hud,
                plan,
                self.config,
                lab_busy=lab_busy,
                pets_busy=pets_busy,
                require_lab_and_pets=require,
            )
            attack_report = self.attack.run_attack(
                allow_spend=False,
                max_searches=1,
                dragons=dragons,
                heroes=heroes,
                spells=0,
                early_exit_damage=0,
                strategy=strategy,
                clones=clones,
                clone_card_slot=clone_card_slot,
                corner=corner,
                invisibility=invisibility,
                invisibility_card_slot=invisibility_card_slot,
            )
            report["actions"].append(
                {
                    "cycle": 1,
                    "action": "dry_run",
                    "decision": decision.action.value,
                    "reason": decision.reason,
                    "farm": self._farm_summary(attack_report),
                }
            )
            report["stop_reason"] = "dry_run"
            report["_final_hud"] = asdict(self._read_hud())
            return self._finish(report)

        for index in range(report["cycles_requested"]):
            hud = self._read_hud()
            status = storage_status(hud, self.config)
            plan = self._scan_plan(upgrade_budgets, max_upgrades) if status.all_full else None
            lab_busy, pets_busy = self._lab_pets(require)
            decision = decide_auto_step(
                hud,
                plan,
                self.config,
                lab_busy=lab_busy,
                pets_busy=pets_busy,
                require_lab_and_pets=require,
            )
            self.log(
                f"auto: ciclo {index + 1}/{report['cycles_requested']} → "
                f"{decision.action.value}: {decision.reason}"
            )
            if decision.action is AutoAction.STOP:
                report["stop_reason"] = decision.reason
                break
            if decision.action is AutoAction.WAIT:
                report["actions"].append(
                    {
                        "cycle": index + 1,
                        "action": "wait",
                        "reason": decision.reason,
                        "storage": status.describe(),
                    }
                )
                self._sleep(max(1.0, wait_between_s))
                report["cycles_done"] += 1
                continue
            if decision.action is AutoAction.FARM:
                cycle_report = self.attack.run_attack(
                    allow_spend=True,
                    max_searches=max(1, farm_max_searches),
                    dragons=dragons,
                    heroes=heroes,
                    spells=spells,
                    early_exit_damage=early_exit_damage,
                    strategy=strategy,
                    clones=clones,
                    clone_card_slot=clone_card_slot,
                    corner=corner,
                    invisibility=invisibility,
                    invisibility_card_slot=invisibility_card_slot,
                )
                summary = self._farm_summary(cycle_report)
                report["farm"]["attacks"] += 1
                report["farm"]["searches"] += int(cycle_report.get("searches") or 0)
                report["farm"]["outcomes"].append(summary)
                report["actions"].append(
                    {
                        "cycle": index + 1,
                        "action": "farm",
                        "reason": decision.reason,
                        "farm": summary,
                    }
                )
                self.upgrade.recover_home()
                report["cycles_done"] += 1
                self._sleep(max(0.0, sleep_between_s))
                continue
            # UPGRADE
            plan = plan if plan is not None else self._scan_plan(upgrade_budgets, max_upgrades)
            results = self.upgrade.execute(plan, dry_run=False)
            ok_count = sum(1 for result in results if result.ok)
            report["upgrade"]["plans"] += 1
            report["upgrade"]["executed"] += ok_count
            report["upgrade"]["results"].extend(
                {"row": str(result.row), "ok": result.ok, "reason": result.reason} for result in results
            )
            report["actions"].append(
                {
                    "cycle": index + 1,
                    "action": "upgrade",
                    "reason": decision.reason,
                    "planned": [str(candidate.row) for candidate in plan.chosen],
                    "executed": ok_count,
                }
            )
            self.upgrade.recover_home()
            report["cycles_done"] += 1
            self._sleep(max(0.0, sleep_between_s))
        else:
            report["stop_reason"] = "raggiunto il numero massimo di cicli"

        report["_final_hud"] = asdict(self._read_hud())
        return self._finish(report)


__all__ = [
    "AUTO_REPORT_PREFIX",
    "AutoAction",
    "AutoDecision",
    "AutoEngine",
    "StorageStatus",
    "decide_auto_step",
    "detect_lab_and_pets",
    "storage_status",
]
