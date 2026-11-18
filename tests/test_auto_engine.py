"""Test del loop AUTO (decisione pura + orchestrazione con engine finti)."""
from __future__ import annotations

from pathlib import Path

import pytest

import cocbot.__main__ as main_module
from cocbot.app import auto_engine
from cocbot.app.auto_engine import (
    AutoAction,
    AutoEngine,
    decide_auto_step,
    storage_status,
)
from cocbot.app.upgrade_engine import (
    ExecutionResult,
    HudRead,
    UpgradeCandidate,
    UpgradePlan,
)
from cocbot.config.models import Config
from cocbot.vision import build_menu

CAP_GOLD, CAP_ELIXIR, CAP_DARK = 10_000_000, 10_000_000, 200_000


def _hud(**kwargs: object) -> HudRead:
    defaults: dict[str, object] = {
        "gold": 1_000_000,
        "elixir": 1_000_000,
        "dark": 10_000,
        "gems": 1_925,
        "builders_available": 3,
        "builders_total": 5,
    }
    defaults.update(kwargs)
    return HudRead(**defaults)  # type: ignore[arg-type]


def _full_hud(**kwargs: object) -> HudRead:
    return _hud(gold=CAP_GOLD, elixir=CAP_ELIXIR, dark=CAP_DARK, **kwargs)


def _row(name: str = "Cannon", *, cost: int = 1_000_000) -> build_menu.BuildRow:
    return build_menu.BuildRow(
        raw_name=name,
        name=name.lower(),
        count=1,
        level=10,
        time_s=3600,
        cost=cost,
        currency="gold",
        is_new=False,
        description="",
        tap_x=10,
        tap_y=10,
        scroll_index=0,
    )


def _candidate(name: str = "Cannon") -> UpgradeCandidate:
    return UpgradeCandidate(row=_row(name), category="defense", priority_index=1)


def _plan(*, chosen: int = 0, candidates: int | None = None) -> UpgradePlan:
    candidate_list = [_candidate(f"Cannon {index}") for index in range(candidates or chosen)]
    return UpgradePlan(
        hud=_full_hud(),
        scanned_rows=len(candidate_list),
        candidates=candidate_list,
        chosen=candidate_list[:chosen],
    )


# ------------------------------------------------------------------ logica pura
def test_storage_status_full_and_partial() -> None:
    config = Config()
    assert storage_status(_full_hud(), config).all_full is True
    partial = _hud(gold=CAP_GOLD, elixir=CAP_ELIXIR, dark=10_000)
    status = storage_status(partial, config)
    assert status.gold_full and status.elixir_full and not status.dark_full
    assert status.all_full is False


def test_storage_status_respects_ratio() -> None:
    config = Config()
    config.auto.storage_full_ratio = 0.5
    hud = _hud(gold=5_500_000, elixir=5_500_000, dark=120_000)
    assert storage_status(hud, config).all_full is True


def test_decide_farm_when_storages_not_full() -> None:
    decision = decide_auto_step(_hud(), None, Config())
    assert decision.action is AutoAction.FARM
    assert "depositi non pieni" in decision.reason


def test_decide_upgrade_when_full_and_builder_free() -> None:
    decision = decide_auto_step(_full_hud(builders_available=2), _plan(chosen=1), Config())
    assert decision.action is AutoAction.UPGRADE
    assert "2 builder liberi" in decision.reason


def test_decide_stop_when_builders_full_and_storages_full() -> None:
    decision = decide_auto_step(_full_hud(builders_available=0), _plan(), Config())
    assert decision.action is AutoAction.STOP
    assert "AUTO-STOP" in decision.reason
    assert "builder" in decision.reason and "depositi" in decision.reason


def test_decide_stop_when_nothing_to_upgrade() -> None:
    decision = decide_auto_step(_full_hud(builders_available=3), _plan(), Config())
    assert decision.action is AutoAction.STOP
    assert "nessun upgrade" in decision.reason


def test_decide_stop_when_candidates_not_executable() -> None:
    plan = _plan(chosen=0, candidates=2)
    decision = decide_auto_step(_full_hud(builders_available=2), plan, Config())
    assert decision.action is AutoAction.STOP
    assert "budget/limiti" in decision.reason


def test_decide_upgrade_when_builders_unreadable() -> None:
    hud = _full_hud(builders_available=None, builders_total=None)
    decision = decide_auto_step(hud, _plan(chosen=1), Config())
    assert decision.action is AutoAction.UPGRADE


def test_decide_wait_when_lab_pets_required_but_unknown() -> None:
    config = Config()
    config.auto.require_lab_and_pets = True
    decision = decide_auto_step(
        _full_hud(builders_available=0), _plan(), config, lab_busy=None, pets_busy=None
    )
    assert decision.action is AutoAction.WAIT
    assert "non rilevabili" in decision.reason


def test_decide_stop_when_lab_and_pets_working() -> None:
    config = Config()
    config.auto.require_lab_and_pets = True
    decision = decide_auto_step(
        _full_hud(builders_available=0),
        _plan(),
        config,
        lab_busy=True,
        pets_busy=True,
    )
    assert decision.action is AutoAction.STOP
    assert "laboratorio" in decision.reason


def test_decide_wait_when_lab_idle() -> None:
    config = Config()
    config.auto.require_lab_and_pets = True
    decision = decide_auto_step(
        _full_hud(builders_available=0),
        _plan(),
        config,
        lab_busy=False,
        pets_busy=True,
    )
    assert decision.action is AutoAction.WAIT


def test_decide_stop_when_auto_disabled() -> None:
    config = Config()
    config.auto.enabled = False
    decision = decide_auto_step(_hud(), None, config)
    assert decision.action is AutoAction.STOP


# ------------------------------------------------------------------ orchestrazione
class FakeUpgradeEngine:
    def __init__(self, huds: list[HudRead], plans: list[UpgradePlan] | None = None) -> None:
        self.huds = list(huds)
        self.plans = list(plans or [])
        self.scan_calls = 0
        self.executed: list[list[UpgradeCandidate]] = []
        self.logs: list[str] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def recover_home(self, *, max_attempts: int = 6) -> bool:
        return True

    def grab(self) -> object:
        return object()

    def read_hud(self, image: object) -> HudRead:
        if len(self.huds) > 1:
            return self.huds.pop(0)
        return self.huds[0]

    def scan(self, *, max_scrolls: int | None = None) -> object:
        self.scan_calls += 1
        return object()

    def plan(self, scan: object) -> UpgradePlan:
        return self.plans.pop(0) if self.plans else _plan()

    def execute(self, plan: UpgradePlan, *, dry_run: bool = True) -> list[ExecutionResult]:
        self.executed.append(list(plan.chosen))
        return [ExecutionResult(row=candidate.row, ok=True, reason="ok") for candidate in plan.chosen]

    def close(self) -> None:
        return None


class FakeAttackEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_attack(self, **kwargs: object) -> dict:
        self.calls.append(dict(kwargs))
        return {
            "action": "attacked",
            "searches": kwargs.get("max_searches", 1),
            "skips": 0,
            "strategy": kwargs.get("strategy") or "dragon_clone",
            "result": {
                "outcome": "victory",
                "damage_pct": 50,
                "loot_gold": 100,
                "loot_elixir": 200,
                "loot_dark": 300,
            },
        }


@pytest.fixture
def fake_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auto_engine,
        "save_json",
        lambda path, payload: Path("out/auto/fake.json"),
    )


def test_auto_dry_run_does_not_spend(fake_save: None) -> None:
    upgrade = FakeUpgradeEngine([_hud()], [_plan(chosen=1)])
    attack = FakeAttackEngine()
    auto = AutoEngine(upgrade, attack, Config(), sleep=lambda _s: None)
    report = auto.run(allow_spend=False, cycles=3)
    assert report["dry_run"] is True
    assert report["stop_reason"] == "dry_run"
    assert attack.calls and attack.calls[0]["allow_spend"] is False
    assert report["actions"][0]["action"] == "dry_run"
    assert report["report_path"] == str(Path("out/auto/fake.json"))


def test_auto_stops_immediately_when_conditions_met(fake_save: None) -> None:
    upgrade = FakeUpgradeEngine([_full_hud(builders_available=0)], [_plan()])
    attack = FakeAttackEngine()
    auto = AutoEngine(upgrade, attack, Config(), sleep=lambda _s: None)
    report = auto.run(allow_spend=True, cycles=5)
    assert attack.calls == []
    assert "AUTO-STOP" in report["stop_reason"]
    assert report["cycles_done"] == 0


def test_auto_loop_farm_then_upgrade_then_stop(fake_save: None) -> None:
    huds = [_hud(), _full_hud(builders_available=2), _full_hud(builders_available=0)]
    plans = [_plan(chosen=1), _plan()]
    upgrade = FakeUpgradeEngine(huds, plans)
    attack = FakeAttackEngine()
    auto = AutoEngine(upgrade, attack, Config(), sleep=lambda _s: None)
    report = auto.run(allow_spend=True, cycles=3, farm_max_searches=2)

    actions = [action["action"] for action in report["actions"]]
    assert actions == ["farm", "upgrade"]
    assert attack.calls[0]["allow_spend"] is True
    assert attack.calls[0]["max_searches"] == 2
    assert upgrade.executed and len(upgrade.executed[0]) == 1
    assert "AUTO-STOP" in report["stop_reason"]
    assert report["cycles_done"] == 2
    assert report["farm"]["attacks"] == 1
    assert report["upgrade"]["executed"] == 1


def test_auto_waits_for_lab_pets_instead_of_stopping(fake_save: None) -> None:
    upgrade = FakeUpgradeEngine([_full_hud(builders_available=0)], [_plan()])
    attack = FakeAttackEngine()
    sleeps: list[float] = []
    auto = AutoEngine(
        upgrade,
        attack,
        Config(),
        sleep=sleeps.append,
        lab_pets_detector=lambda engine: (None, None),
    )
    report = auto.run(allow_spend=True, cycles=2, require_lab_and_pets=True, wait_between_s=10)
    assert attack.calls == []
    assert [action["action"] for action in report["actions"]] == ["wait", "wait"]
    assert "massimo" in report["stop_reason"]
    assert sleeps == [10, 10]


def test_auto_report_path_present(fake_save: None) -> None:
    upgrade = FakeUpgradeEngine([_full_hud(builders_available=0)], [_plan()])
    auto = AutoEngine(upgrade, FakeAttackEngine(), Config(), sleep=lambda _s: None)
    report = auto.run(allow_spend=True, cycles=1)
    assert report["report_path"] == str(Path("out/auto/fake.json"))
    assert report["final_hud"] is not None


# ------------------------------------------------------------------ CLI
def test_cli_auto_run_parser() -> None:
    parser = main_module.build_parser()
    args = parser.parse_args(
        ["auto-run", "--allow-spend", "--cycles", "5", "--clones", "3", "--max-upgrades", "2"]
    )
    assert args.command == "auto-run"
    assert args.allow_spend is True
    assert args.cycles == 5
    assert args.clones == 3
    assert args.max_upgrades == 2
    assert args.require_lab_pets is False
    defaults = parser.parse_args(["auto-run"])
    assert defaults.allow_spend is False
    assert defaults.cycles is None
