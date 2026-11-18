"""Regressioni robustezza upgrade (log utente 18 nov 2026): costi/dialoghi OCR ed errori."""
from __future__ import annotations

from cocbot.app.upgrade_engine import (
    HudRead,
    ScanReport,
    UpgradeCandidate,
    UpgradeEngine,
    UpgradePlan,
    build_plan,
    dialog_cost_decision,
)
from cocbot.config.models import Config
from cocbot.vision import build_menu


def _row(
    name: str,
    *,
    level: int | None = 10,
    cost: int | None = 100_000,
    currency: str = "gold",
    time_s: int | None = 3600,
    is_new: bool = False,
    scroll_index: int = 0,
) -> build_menu.BuildRow:
    return build_menu.BuildRow(
        raw_name=name,
        name=name.lower(),
        count=1,
        level=level,
        time_s=time_s,
        cost=cost,
        currency=currency,
        is_new=is_new,
        description="",
        tap_x=10,
        tap_y=10,
        scroll_index=scroll_index,
    )


def _hud(**kwargs: object) -> HudRead:
    defaults: dict[str, object] = {
        "gold": 8_000_000,
        "elixir": 8_000_000,
        "dark": 200_000,
        "gems": 1_925,
        "builders_available": 5,
        "builders_total": 5,
    }
    defaults.update(kwargs)
    return HudRead(**defaults)  # type: ignore[arg-type]


def _report(rows: list[build_menu.BuildRow], hud: HudRead | None = None) -> ScanReport:
    return ScanReport(hud=hud or _hud(), rows=rows, positions=1, elapsed_s=0.1)


# ------------------------------------------------------------------ planner
def test_plan_skips_implausible_ocr_cost() -> None:
    """Visto nel log: 'Tornado Trap 2 gold'. Un costo così basso è OCR errato."""
    plan = build_plan(Config(), _report([_row("Tornado Trap", cost=2, currency="gold")]))
    assert plan.chosen == []
    assert any("implausibile" in skipped.reason for skipped in plan.skipped)


def test_plan_accepts_plausible_cheap_trap() -> None:
    plan = build_plan(Config(), _report([_row("Bomb", cost=100_000, currency="gold")]))
    assert len(plan.chosen) == 1


# ------------------------------------------------------------------ dialoghi
def test_dialog_cost_decision_equal() -> None:
    decision = dialog_cost_decision(750_000, 750_000, available=5_000_000)
    assert decision.ok is True
    assert decision.trusted_cost == 750_000
    assert decision.warning is None


def test_dialog_cost_decision_mismatch_within_budget() -> None:
    """Log reale: muro riga 1.500.000, dialogo letto 1500."""
    decision = dialog_cost_decision(1_500_000, 1500, available=6_000_000, reserve=200_000)
    assert decision.ok is True
    assert decision.trusted_cost == 1_500_000
    assert decision.warning is not None
    assert "1500000" in decision.warning


def test_dialog_cost_decision_trap_mismatch_within_budget() -> None:
    """Log reale: riga 2 oro, dialogo 2500."""
    decision = dialog_cost_decision(2, 2500, available=6_000_000, reserve=200_000)
    assert decision.ok is True
    assert decision.trusted_cost == 2500


def test_dialog_cost_decision_mismatch_over_budget() -> None:
    decision = dialog_cost_decision(1_500_000, 1500, available=1_000_000, reserve=200_000)
    assert decision.ok is False
    assert "budget" in (decision.warning or "")


def test_dialog_cost_decision_missing_values() -> None:
    assert dialog_cost_decision(None, 1000, available=1).ok is False
    assert dialog_cost_decision(1000, None, available=1).ok is False


# ------------------------------------------------------------------ execute
class _FakeUpgradeEngine(UpgradeEngine):
    def __init__(self, outcomes: list[object]) -> None:  # pragma: no cover - costruzione manuale
        self.outcomes = list(outcomes)
        self.logs: list[str] = []

    def log(self, message: str) -> None:  # type: ignore[override]
        self.logs.append(message)

    def recover_home(self, *, max_attempts: int = 6) -> bool:  # type: ignore[override]
        return True

    def _execute_upgrade(self, candidate: UpgradeCandidate):  # type: ignore[override]
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _candidate(name: str) -> UpgradeCandidate:
    from cocbot.app.upgrade_engine import categorize, priority_list

    row = _row(name)
    category = categorize(row.name) or "other"
    index = priority_list(Config()).index(category)
    return UpgradeCandidate(row=row, category=category, priority_index=index)


def _plan(candidates: list[UpgradeCandidate]) -> UpgradePlan:
    return UpgradePlan(hud=_hud(), scanned_rows=1, chosen=candidates)


def test_execute_continues_after_one_failure() -> None:
    from cocbot.app.upgrade_engine import ExecutionResult, UpgradeEngineError

    first = _candidate("Cannon")
    second = _candidate("Archer Tower")
    ok_result = ExecutionResult(row=second.row, ok=True, reason="ok")
    engine = _FakeUpgradeEngine([UpgradeEngineError("dialogo non corrispondente"), ok_result])
    results = engine.execute(_plan([first, second]), dry_run=False)
    assert len(results) == 2
    assert results[0].ok is False
    assert results[1].ok is True
    assert any("fallito" in line for line in engine.logs)


def test_execute_stops_after_two_consecutive_errors() -> None:
    from cocbot.app.upgrade_engine import UpgradeEngineError

    candidates = [_candidate("Cannon"), _candidate("Archer Tower"), _candidate("Mortar")]
    engine = _FakeUpgradeEngine([UpgradeEngineError("e1"), UpgradeEngineError("e2"), UpgradeEngineError("e3")])
    results = engine.execute(_plan(candidates), dry_run=False)
    assert len(results) == 2
