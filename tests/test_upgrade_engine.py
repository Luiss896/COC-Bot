"""Test del planner upgrade: categorie, priorita', filtri di sicurezza, dry-run."""
from __future__ import annotations

from cocbot.app.upgrade_engine import (
    HudRead,
    ScanReport,
    UpgradeEngine,
    build_plan,
    categorize,
    priority_list,
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
        "elixir": 1_000_000,
        "dark": 200_000,
        "gems": 1_925,
        "builders_available": 5,
        "builders_total": 5,
    }
    defaults.update(kwargs)
    return HudRead(**defaults)  # type: ignore[arg-type]


def _report(rows: list[build_menu.BuildRow], hud: HudRead | None = None) -> ScanReport:
    return ScanReport(hud=hud or _hud(), rows=rows, positions=1, elapsed_s=0.1)


def test_categorize_known_and_unknown() -> None:
    assert categorize("Barbarian King") == "heroes"
    assert categorize("Archer Queen") == "heroes"
    assert categorize("Wall") == "walls"
    assert categorize("Army Camp") == "army"
    assert categorize("Gold Mine") == "resources"
    assert categorize("Archer Tower") == "defense"
    assert categorize("Crafting Station") == "other"
    assert categorize("30M Os") is None  # OCR sbagliato: non deve diventare un candidato
    assert categorize("") is None


def test_priority_list_default_and_custom() -> None:
    config = Config()
    assert priority_list(config)[:2] == ("heroes", "army")
    config.upgrade.priority = ["defense", "heroes"]
    ordered = priority_list(config)
    assert ordered[:2] == ("defense", "heroes")
    assert "walls" in ordered  # le categorie mancanti vengono appese
    config.upgrade.priority = ["categoria_inventata"]
    assert priority_list(config) == ("heroes", "army", "defense", "resources", "walls", "other")


def test_build_plan_filters_and_ordering() -> None:
    rows = [
        _row("Barbarian King", cost=44_000, currency="dark", level=63),
        _row("Archer Tower", cost=800_000, currency="gold", scroll_index=1),
        _row("Cannon", cost=100_000, currency="gold", scroll_index=2),
        _row("Mortar", cost=200_000, currency="gold", scroll_index=3),
        _row("Army Camp", cost=2_250_000, currency="elixir"),  # elisir insufficiente
        _row("Wall", cost=750_000, currency="elixir"),  # mura escluse
        _row("Workshop", cost=1_200_000, currency="elixir", is_new=True),  # piazzamento
        _row("30M Os", cost=115_000, currency="gold"),  # nome non riconosciuto
        _row("Crafting Station", cost=4_000_000, currency="gold", scroll_index=4),
    ]
    plan = build_plan(Config(), _report(rows))
    chosen = [item.row.name for item in plan.chosen]
    # priorita': heroes prima, poi defense; "other" (Crafting Station) dopo e oltre il limite
    assert chosen == ["barbarian king", "archer tower", "cannon"]
    reasons = " | ".join(skipped.reason for skipped in plan.skipped)
    assert "risorse insufficienti" in reasons
    assert "mura escluse" in reasons
    assert "edificio nuovo" in reasons
    assert "nome non riconosciuto" in reasons
    assert plan.scanned_rows == len(rows)


def test_build_plan_custom_priority_respected() -> None:
    config = Config()
    config.upgrade.priority = ["resources", "heroes"]
    config.upgrade.max_upgrades_per_cycle = 2
    rows = [_row("Barbarian King", cost=44_000, currency="dark"), _row("Gold Mine", cost=600_000, currency="elixir")]
    plan = build_plan(config, _report(rows))
    assert [item.row.name for item in plan.chosen] == ["gold mine", "barbarian king"]


def test_build_plan_requires_free_builder() -> None:
    plan = build_plan(Config(), _report([_row("Archer Tower")], hud=_hud(builders_available=0)))
    assert plan.chosen == []
    assert any("builder" in note for note in plan.notes)


def test_build_plan_builder_unknown_blocks_execution() -> None:
    hud = _hud()
    hud = HudRead(gold=hud.gold, elixir=hud.elixir, dark=hud.dark, gems=hud.gems)
    plan = build_plan(Config(), _report([_row("Archer Tower")], hud=hud))
    assert plan.chosen == []
    assert any("builder non letti" in note for note in plan.notes)


def test_build_plan_reserves() -> None:
    config = Config()
    config.upgrade.reserves = {"gold": 7_900_000, "elixir": 0, "dark": 0}
    plan = build_plan(config, _report([_row("Archer Tower", cost=800_000, currency="gold")]))
    assert plan.chosen == []
    assert any("riserve" in skipped.reason or "risorse insufficienti" in skipped.reason for skipped in plan.skipped)


def test_build_plan_currency_and_cost_unknown_skipped() -> None:
    rows = [
        _row("Archer Tower", currency="unknown"),
        _row("Cannon", time_s=None),  # il tempo non e' richiesto per pianificare
        _row("Mortar", cost=None),
    ]
    plan = build_plan(Config(), _report(rows))
    reasons = " | ".join(skipped.reason for skipped in plan.skipped)
    assert "valuta non gestita" in reasons
    assert "costo illeggibile" in reasons
    # la riga senza tempo resta un candidato valido
    assert "cannon" in [item.row.name for item in plan.candidates]


def test_merge_rows_combines_partial_readings() -> None:
    from cocbot.app.upgrade_engine import merge_rows

    partial = _row("Gold Storage", level=None, cost=900_000, currency="gold", time_s=None, scroll_index=3)
    complete = _row("Gold Storage", level=13, cost=900_000, currency="gold", time_s=16_200, scroll_index=4)
    duplicate = _row("Gold Storage", level=None, cost=900_000, currency="unknown", time_s=16_200, scroll_index=5)
    other = _row("Air Bomb", level=6, cost=400_000, currency="gold", time_s=10_800, scroll_index=6)
    merged = merge_rows([partial, complete, duplicate, other])
    assert len(merged) == 2
    gold = next(row for row in merged if row.name == "gold storage")
    assert gold.level == 13
    assert gold.time_s == 16_200
    assert gold.currency == "gold"
    assert gold.scroll_index in (3, 4, 5)


def test_merge_rows_keeps_distinct_rows_with_same_name() -> None:
    from cocbot.app.upgrade_engine import merge_rows

    rows = [
        _row("Air Bomb", level=6, cost=400_000, time_s=10_800),
        _row("Air Bomb", level=5, cost=275_000, time_s=7_200),
    ]
    assert len(merge_rows(rows)) == 2


def test_merge_rows_prefers_described_crafting_station() -> None:
    from cocbot.app.upgrade_engine import merge_rows

    with_desc = _row("Crafting Station", level=2, cost=35_000, currency="dark", time_s=21_600)
    with_desc = build_menu.BuildRow(
        raw_name=with_desc.raw_name,
        name=with_desc.name,
        count=with_desc.count,
        level=with_desc.level,
        time_s=with_desc.time_s,
        cost=with_desc.cost,
        currency=with_desc.currency,
        is_new=False,
        description="Cake-A-Pult Damage",
        tap_x=10,
        tap_y=10,
        scroll_index=1,
    )
    without_desc = _row("Crafting Station", level=2, cost=35_000, currency="dark", time_s=21_600)
    merged = merge_rows([with_desc, without_desc])
    assert len(merged) == 1
    assert merged[0].description == "Cake-A-Pult Damage"


def test_build_plan_use_heroes_false() -> None:
    config = Config()
    config.upgrade.use_heroes = False
    plan = build_plan(config, _report([_row("Barbarian King", cost=44_000, currency="dark")]))
    assert plan.chosen == []
    assert any("eroi esclusi" in skipped.reason for skipped in plan.skipped)


def test_build_plan_include_walls() -> None:
    config = Config()
    config.upgrade.include_walls = True
    rows = [_row("Wall", cost=750_000, currency="elixir", time_s=0)]
    plan = build_plan(config, _report(rows))
    assert [item.row.name for item in plan.chosen] == ["wall"]


def test_dry_run_execute_sends_no_action() -> None:
    plan = build_plan(Config(), _report([_row("Archer Tower")]))
    engine = UpgradeEngine.__new__(UpgradeEngine)  # non serve I/O: il dry-run non tocca source/sink
    results = engine.execute(plan, dry_run=True)
    assert len(results) == 1
    assert results[0].ok
    assert "dry-run" in results[0].reason


def test_default_config_is_dry_run() -> None:
    config = Config()
    assert config.upgrade.dry_run is True
    assert config.safety.never_spend_gems is True
    assert config.upgrade.include_walls is False
