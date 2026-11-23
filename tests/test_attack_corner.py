"""Test della strategia DRAGON CORNER (23 nov 2026).

Coprono:
- scelta dell'angolo (casuale e forzata) e direzione del pan camera;
- rilevamento dell'erba deployabile per angolo con filtro delle zone vietate;
- deploy completo (draghi in un punto -> invisibilità -> eroi);
- fase di deploy **immediata** in anteprima con fallback all'inizio della battaglia;
- frame reali del dataset locale (angoli deployabili e pulsanti esclusi);
- argomenti CLI e config.
"""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from cocbot.app import attack_engine
from cocbot.app.attack_engine import (
    ATTACK_STRATEGIES,
    CORNER_PAN_DELTAS,
    CornerDeploy,
    pick_deploy_corner,
)
from cocbot.config.models import Config
from cocbot.vision import ui

IMAGE = np.zeros((975, 1733, 3), dtype=np.uint8)

BUILD_DATASET = Path(__file__).resolve().parents[1] / "dataset" / "build-win-20261103"
_HAS_BUILD = (BUILD_DATASET / "battle-phase-window.png").is_file()
build_dataset = pytest.mark.skipif(not _HAS_BUILD, reason="frame locali assenti (gitignored)")


def _load_build(name: str) -> np.ndarray:
    image = cv2.imread(str(BUILD_DATASET / name))
    assert image is not None, f"frame assente: {name}"
    return image


def _fake_engine() -> tuple[attack_engine.AttackEngine, list[tuple[tuple[int, int], float | None]]]:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    taps: list[tuple[tuple[int, int], float | None]] = []
    engine._tap = lambda point, wait_s=None: taps.append((point, wait_s))
    return engine, taps


def _grass_image() -> np.ndarray:
    """Frame sintetico 1000x600 con 4 chiazze di erba ai 4 angoli + una in zona vietata."""
    image = np.zeros((600, 1000, 3), dtype=np.uint8)
    grass_bgr = cv2.cvtColor(np.uint8([[[40, 150, 170]]]), cv2.COLOR_HSV2BGR)[0, 0]
    for cx, cy in ((250, 120), (750, 120), (250, 400), (750, 400), (100, 100)):
        image[cy - 20 : cy + 20, cx - 30 : cx + 30] = grass_bgr
    return image


# --------------------------------------------------------------------------- angolo
def test_pick_deploy_corner_random_and_forced() -> None:
    rng = random.Random(1234)
    picks = [pick_deploy_corner(rng) for _ in range(200)]
    assert set(picks) == set(ui.CORNER_NAMES)
    assert pick_deploy_corner(rng, corner="ne") == "ne"
    assert pick_deploy_corner(rng, corner="random") in ui.CORNER_NAMES
    assert pick_deploy_corner(rng, corner="sconosciuto") in ui.CORNER_NAMES


def test_corner_pan_deltas() -> None:
    assert set(CORNER_PAN_DELTAS) == set(ui.CORNER_NAMES)
    for corner in ("nw", "ne", "sw", "se"):
        dx, dy = CORNER_PAN_DELTAS[corner]
        assert abs(dx) > 0 and abs(dy) > 0
        assert (dx < 0) == (corner in ("nw", "sw"))  # ovest: trascina a destra
        assert (dy < 0) == (corner in ("nw", "ne"))  # nord: trascina in basso


def test_attack_strategies_and_config_defaults() -> None:
    config = Config()
    assert ATTACK_STRATEGIES == ("dragon_corner", "dragon_clone", "dragon_spam")
    assert config.attack.strategy == "dragon_corner"
    assert config.attack.corner == "random"
    assert config.attack.corner_pan is True
    assert config.attack.invisibility_spells == 5
    assert config.attack.invisibility_card_slot == 0
    # soglie loot richieste: oro >= 800k E elisir >= 800k
    assert config.loot.thresholds.gold_min == 800_000
    assert config.loot.thresholds.elixir_min == 800_000
    assert config.loot.thresholds.dark_min == 0
    assert config.loot.thresholds.score_min == 1_600_000


# --------------------------------------------------------------------------- visione
def test_grass_blobs_are_filtered_by_forbidden_zones() -> None:
    image = _grass_image()
    blobs = ui.grass_deploy_blobs(image)
    points = [(x, y) for x, y, _area in blobs]

    def has_point(x: int, y: int) -> bool:
        return any(abs(px - x) <= 2 and abs(py - y) <= 2 for px, py in points)

    assert has_point(250, 120)
    assert has_point(750, 120)
    assert has_point(250, 400)
    assert has_point(750, 400)
    # la chiazza in alto a sinistra e' dentro il pannello "Available Loot": esclusa
    assert not has_point(100, 100)
    for x, y, _area in blobs:
        assert ui.battle_tap_is_safe(image, (x, y))


def test_find_corner_deploy_point_picks_the_quadrant() -> None:
    image = _grass_image()
    expected = {
        "nw": (250, 120),
        "ne": (750, 120),
        "sw": (250, 400),
        "se": (750, 400),
    }
    for corner, (x, y) in expected.items():
        point = ui.find_corner_deploy_point(image, corner)
        assert point is not None
        assert abs(point[0] - x) <= 8 and abs(point[1] - y) <= 8, (corner, point)
    assert ui.find_corner_deploy_point(image, "boh") is None


def test_battle_tap_is_safe_rejects_buttons() -> None:
    image = np.zeros((975, 1733, 3), dtype=np.uint8)
    h, w = image.shape[:2]
    assert ui.battle_tap_is_safe(image, (int(w * 0.50), int(h * 0.45)))
    # End Battle (basso sinistra), Next (basso destra), barra truppe, HUD
    assert not ui.battle_tap_is_safe(image, (int(w * 0.059), int(h * 0.790)))
    assert not ui.battle_tap_is_safe(image, (int(w * 0.930), int(h * 0.730)))
    assert not ui.battle_tap_is_safe(image, (int(w * 0.164), int(h * 0.911)))
    assert not ui.battle_tap_is_safe(image, (int(w * 0.900), int(h * 0.050)))


@build_dataset
def test_real_frames_have_safe_corner_points() -> None:
    for name in ("battle-phase-window.png", "scout-screen-window.png"):
        image = _load_build(name)
        assert ui.grass_deploy_blobs(image), name
        for corner in ui.CORNER_NAMES:
            point = ui.find_corner_deploy_point(image, corner)
            assert point is not None, (name, corner)
            assert ui.battle_tap_is_safe(image, point), (name, corner, point)


@build_dataset
def test_real_buttons_are_forbidden_but_field_is_allowed() -> None:
    image = _load_build("scout-screen-window.png")
    end = ui.find_end_battle_button(image)
    next_button = ui.find_next_button(image)
    assert end is not None and next_button is not None
    assert not ui.battle_tap_is_safe(image, ui.center(end))
    assert not ui.battle_tap_is_safe(image, ui.center(next_button))
    # un punto di erba trovato dalla strategia e' sicuro
    point = ui.find_corner_deploy_point(image, "se")
    assert point is not None and ui.battle_tap_is_safe(image, point)


# --------------------------------------------------------------------------- deploy
def test_deploy_dragon_corner_order_and_taps(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "find_corner_deploy_point", lambda image, corner: (300, 500)
    )
    result = engine.deploy_dragon_corner(
        IMAGE, corner="nw", dragons=13, heroes=True, invisibility=5
    )

    assert isinstance(result, CornerDeploy)
    assert result.corner == "nw"
    assert result.point == (300, 500)
    assert result.on_grass is True
    assert result.taps == 1 + 13 + 5 * 2 + 4
    assert len(taps) == result.taps
    # card draghi una sola volta, poi tutti i draghi nello STESSO punto
    assert taps[0][0] == ui.battle_card_point(IMAGE, ui.BATTLE_DRAGON_CARD)
    assert {point for point, _wait in taps[1:14]} == {(300, 500)}
    # poi l'invisibilita' (card slot 0) sui draghi...
    assert taps[14][0] == ui.battle_card_point(IMAGE, ui.battle_spell_card(0))
    assert taps[15][0] == (300, 500)
    # ...e infine gli eroi (card + tap spostato verso il villaggio)
    assert taps[24][0] == ui.battle_card_point(IMAGE, ui.BATTLE_QUEEN_CARD)
    assert taps[25][0] != (300, 500)
    assert taps[26][0] == ui.battle_card_point(IMAGE, ui.BATTLE_WARDEN_CARD)


def test_deploy_dragon_corner_falls_back_to_global_grass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(attack_engine.ui, "find_corner_deploy_point", lambda image, corner: None)
    monkeypatch.setattr(
        attack_engine.ui, "find_deploy_candidates", lambda image, limit=10: [(400, 600)]
    )
    result = engine.deploy_dragon_corner(
        IMAGE, corner="sw", dragons=2, heroes=False, invisibility=0
    )
    assert result.on_grass is True
    assert result.point == (400, 600)
    assert result.taps == 1 + 2


def test_deploy_dragon_corner_uses_safe_grid_as_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _taps = _fake_engine()
    monkeypatch.setattr(attack_engine.ui, "find_corner_deploy_point", lambda image, corner: None)
    monkeypatch.setattr(attack_engine.ui, "find_deploy_candidates", lambda image, limit=10: [])
    monkeypatch.setattr(
        attack_engine.ui, "battle_field_grid", lambda image: [(866, 438)]
    )
    result = engine.deploy_dragon_corner(
        IMAGE, corner="sw", dragons=1, heroes=False, invisibility=0
    )
    assert result.on_grass is False
    assert result.point == (866, 438)
    assert result.taps == 1 + 1


def test_deploy_dragon_corner_without_any_point(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(attack_engine.ui, "find_corner_deploy_point", lambda image, corner: None)
    monkeypatch.setattr(attack_engine.ui, "find_deploy_candidates", lambda image, limit=10: [])
    monkeypatch.setattr(attack_engine.ui, "battle_field_grid", lambda image: [])
    result = engine.deploy_dragon_corner(IMAGE, corner="ne", dragons=5)
    assert result.taps == 0
    assert result.point is None
    assert taps == []
    assert any("nessun punto" in line for line in engine.logs)


# --------------------------------------------------------------------------- fase deploy
def _phase_engine(monkeypatch: pytest.MonkeyPatch, states_sequence) -> tuple:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    engine.grab = lambda: IMAGE
    calls = {"deploy": 0, "wait": 0, "pan": 0}
    deploys: list[dict] = []

    def fake_deploy(image, **kwargs):
        calls["deploy"] += 1
        deploys.append(kwargs)
        return CornerDeploy(taps=28, point=(120, 780), on_grass=True, corner=kwargs["corner"])

    def fake_wait(**_kwargs):
        calls["wait"] += 1
        return True

    engine.deploy_dragon_corner = fake_deploy
    engine.wait_battle_start = fake_wait
    engine.pan_camera_towards_corner = lambda corner, image=None: calls.__setitem__(
        "pan", calls["pan"] + 1
    )
    iterator = iter(states_sequence)
    monkeypatch.setattr(
        attack_engine.states,
        "classify",
        lambda image: next(iterator, attack_engine.ScreenState.BATTLE),
    )
    return engine, calls, deploys


def test_corner_phase_deploys_immediately_and_skips_countdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, calls, _deploys = _phase_engine(
        monkeypatch, [attack_engine.ScreenState.BATTLE]
    )
    report: dict = {"action": None}
    ok = engine.deploy_corner_phase(
        report=report,
        corner="se",
        dragons=13,
        heroes=True,
        invisibility=5,
        invisibility_card_slot=0,
    )
    assert ok is True
    assert calls["deploy"] == 1  # deployato subito in anteprima
    assert calls["wait"] == 0  # nessuna attesa del countdown
    assert calls["pan"] == 1
    assert report["deploy_phase"] == "preview"
    assert report["battle_started_by_deploy"] is True
    assert report["deploy_taps"] == 28


def test_corner_phase_falls_back_to_battle_start(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, calls, _deploys = _phase_engine(
        monkeypatch,
        [attack_engine.ScreenState.PREVIEW, attack_engine.ScreenState.BATTLE],
    )
    report: dict = {"action": None}
    ok = engine.deploy_corner_phase(
        report=report,
        corner="nw",
        dragons=13,
        heroes=True,
        invisibility=5,
        invisibility_card_slot=0,
    )
    assert ok is True
    assert calls["wait"] == 1  # ha atteso l'inizio della battaglia
    assert calls["deploy"] == 2  # e ripetuto il deploy
    assert calls["pan"] == 2
    assert report["preview_deploy_ignored"] is True
    assert report["deploy_phase"] == "battle"
    assert report["deploy_taps"] == 28 + 28


def test_corner_phase_reports_when_battle_never_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _calls, _deploys = _phase_engine(
        monkeypatch,
        [attack_engine.ScreenState.PREVIEW, attack_engine.ScreenState.PREVIEW],
    )
    engine.wait_battle_start = lambda **_kwargs: False
    report: dict = {"action": None}
    ok = engine.deploy_corner_phase(
        report=report,
        corner="ne",
        dragons=13,
        heroes=True,
        invisibility=5,
        invisibility_card_slot=0,
    )
    assert ok is False
    assert report["action"] == "battle_not_started"


# --------------------------------------------------------------------------- CLI/config
def test_cli_parser_dragon_corner_options() -> None:
    import cocbot.__main__ as main_module

    parser = main_module.build_parser()
    args = parser.parse_args(
        [
            "attack-run",
            "--strategy",
            "dragon_corner",
            "--corner",
            "se",
            "--invisibility",
            "3",
            "--invisibility-card-slot",
            "1",
        ]
    )
    assert args.strategy == "dragon_corner"
    assert args.corner == "se"
    assert args.invisibility == 3
    assert args.invisibility_card_slot == 1

    defaults = parser.parse_args(["attack-run"])
    assert defaults.corner is None
    assert defaults.invisibility is None

    farm = parser.parse_args(["attack-farm", "--corner", "nw", "--invisibility", "4"])
    assert farm.corner == "nw" and farm.invisibility == 4

    auto = parser.parse_args(["auto-run", "--strategy", "dragon_corner", "--corner", "sw"])
    assert auto.strategy == "dragon_corner" and auto.corner == "sw"


def test_example_config_has_dragon_corner_and_loot_800k() -> None:
    from cocbot.config import load_config

    example = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
    config = load_config(example)
    assert config.attack.strategy == "dragon_corner"
    assert config.attack.invisibility_spells == 5
    assert config.loot.thresholds.gold_min == 800_000
    assert config.loot.thresholds.elixir_min == 800_000
