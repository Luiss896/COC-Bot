"""Test della strategia DRAGON CORNER (aggiornati dopo il live del 23 nov 2026).

Coprono:
- scelta dell'angolo (casuale e forzata) e direzione del pan camera;
- erba deployabile per angolo e filtro delle zone vietate;
- deploy **adattivo** con verifica del contatore (draghi tutti sullo stesso punto, si cambia
  punto solo se il tap non schiera);
- Invisibility Spell e 3 eroi (King, Queen, Warden);
- fase di deploy al primo istante della battaglia (il countdown e' imposto dal gioco);
- dialogo "SURRENDER?" (UI nov 2026) e conferma Okay;
- card della barra truppe del layout attuale (King in barra: spell a 0,446);
- frame reali del 23 nov 2026 (dataset locale) e argomenti CLI/config.
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
from cocbot.core.types import ScreenState
from cocbot.vision import states, ui

IMAGE = np.zeros((975, 1733, 3), dtype=np.uint8)

LIVE_DATASET = Path(__file__).resolve().parents[1] / "dataset" / "build-win-20261123"
_HAS_LIVE = (LIVE_DATASET / "diagnostica-battle-start.png").is_file()
live_dataset = pytest.mark.skipif(not _HAS_LIVE, reason="frame live 23 nov assenti (gitignored)")


def _load_live(name: str) -> np.ndarray:
    image = cv2.imread(str(LIVE_DATASET / name))
    assert image is not None, f"frame assente: {name}"
    return image


def _fake_engine() -> tuple[attack_engine.AttackEngine, list[tuple[tuple[int, int], float | None]]]:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    taps: list[tuple[tuple[int, int], float | None]] = []
    engine._tap = lambda point, wait_s=None: taps.append((point, wait_s))
    engine.grab = lambda: IMAGE
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


def test_deploy_candidates_are_ordered_and_safe() -> None:
    image = _grass_image()
    candidates = ui.deploy_candidates_for_corner(image, "se")
    assert candidates
    for point in candidates:
        assert ui.battle_tap_is_safe(image, point)
    assert len(set(candidates)) == len(candidates)


def test_battle_tap_is_safe_rejects_buttons() -> None:
    assert ui.battle_tap_is_safe(IMAGE, (int(IMAGE.shape[1] * 0.50), int(IMAGE.shape[0] * 0.45)))
    # Surrender (basso sinistra), Next (basso destra), barra truppe, HUD
    assert not ui.battle_tap_is_safe(IMAGE, (int(1733 * 0.059), int(975 * 0.790)))
    assert not ui.battle_tap_is_safe(IMAGE, (int(1733 * 0.930), int(975 * 0.730)))
    assert not ui.battle_tap_is_safe(IMAGE, (int(1733 * 0.164), int(975 * 0.911)))
    assert not ui.battle_tap_is_safe(IMAGE, (int(1733 * 0.900), int(975 * 0.050)))


def test_card_bar_layout_nov_2026() -> None:
    """Layout UI nov 2026: King in barra, quindi AQ/GW/spell una posizione piu' a destra."""
    assert ui.BATTLE_DRAGON_CARD == (0.164, 0.911)
    assert ui.BATTLE_KING_CARD == (0.237, 0.911)
    assert ui.BATTLE_QUEEN_CARD == (0.310, 0.911)
    assert ui.BATTLE_WARDEN_CARD == (0.383, 0.911)
    assert ui.BATTLE_SPELL_CARD == (0.446, 0.911)
    step = ui.battle_spell_card(1)[0] - ui.battle_spell_card(0)[0]
    assert step == pytest.approx(ui.BATTLE_CARD_STEP, abs=1e-3)


# --------------------------------------------------------------------------- frame reali
@live_dataset
def test_live_frames_states_and_surrender_dialog() -> None:
    assert states.classify(_load_live("diagnostica-battle-start.png")) is ScreenState.BATTLE
    assert states.classify(_load_live("preview-1.png")) is ScreenState.PREVIEW
    surrender = _load_live("surrender-dialog.png")
    assert states.classify(surrender) is ScreenState.BATTLE_CONFIRM
    assert ui.find_surrender_ok(surrender) is not None
    # nessun falso positivo sulle altre schermate
    assert states.classify(_load_live("risultati-1.png")) is ScreenState.BATTLE_END
    assert ui.find_surrender_ok(_load_live("risultati-1.png")) is None
    assert ui.find_surrender_ok(_load_live("diagnostica-battle-start.png")) is None
    assert ui.find_surrender_ok(_load_live("preview-1.png")) is None
    assert ui.find_return_home_button(_load_live("risultati-1.png")) is not None


@live_dataset
def test_live_battle_frame_has_safe_corner_candidates() -> None:
    image = _load_live("diagnostica-battle-start.png")
    for corner in ui.CORNER_NAMES:
        candidates = ui.deploy_candidates_for_corner(image, corner)
        assert candidates, corner
        assert ui.battle_tap_is_safe(image, candidates[0])
    # il primo candidato del SE e' sul lato destro (anello esterno), non al centro
    first = ui.deploy_candidates_for_corner(image, "se")[0]
    assert first[0] > image.shape[1] * 0.55
    assert ui.battle_tap_is_safe(image, first)


# --------------------------------------------------------------------------- deploy
def test_deploy_dragon_corner_all_on_one_point(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui,
        "deploy_candidates_for_corner",
        lambda image, corner: [(300, 500), (600, 300)],
    )
    calls: list[tuple[int, int]] = []

    def always_ok(point, *, wait_s):
        calls.append(point)
        return True

    engine._tap_and_verify = always_ok
    result = engine.deploy_dragon_corner(
        IMAGE, corner="nw", dragons=13, heroes=True, invisibility=5
    )

    assert isinstance(result, CornerDeploy)
    assert result.deployed == 13
    assert result.taps == 1 + 13 + 5 * 2 + 3 * 2  # card + draghi + invis + 3 eroi
    assert result.point == (300, 500)
    assert calls == [(300, 500)] * 13  # tutti i draghi sullo stesso punto
    # card draghi selezionata una volta, poi (dopo i tap veri) l'invisibilita' e gli eroi
    assert taps[0][0] == ui.battle_card_point(IMAGE, ui.BATTLE_DRAGON_CARD)
    assert taps[1][0] == ui.battle_card_point(IMAGE, ui.battle_spell_card(0))
    hero_cards = {
        ui.battle_card_point(IMAGE, ui.BATTLE_KING_CARD),
        ui.battle_card_point(IMAGE, ui.BATTLE_QUEEN_CARD),
        ui.battle_card_point(IMAGE, ui.BATTLE_WARDEN_CARD),
    }
    assert hero_cards <= {point for point, _wait in taps}


def test_deploy_dragon_corner_moves_to_next_point_when_tap_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _taps = _fake_engine()
    candidates = [(100, 100), (200, 200), (300, 300)]
    monkeypatch.setattr(
        attack_engine.ui, "deploy_candidates_for_corner", lambda image, corner: candidates
    )
    attempts: list[tuple[int, int]] = []

    def fails_first_two(point, *, wait_s):
        attempts.append(point)
        return point == (300, 300)

    engine._tap_and_verify = fails_first_two
    result = engine.deploy_dragon_corner(
        IMAGE, corner="se", dragons=13, heroes=False, invisibility=0
    )
    assert result.deployed == 13
    assert result.point == (300, 300)
    assert attempts[:3] == [(100, 100), (200, 200), (300, 300)]
    # i punti falliti non vengono riprovati una volta trovato quello efficace
    assert (100, 100) not in attempts[3:]
    assert any("non ha schierato" in line for line in engine.logs)


def test_deploy_dragon_corner_all_fail_skips_invisibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "deploy_candidates_for_corner", lambda image, corner: [(10, 10)]
    )
    engine._tap_and_verify = lambda point, *, wait_s: False
    result = engine.deploy_dragon_corner(
        IMAGE, corner="ne", dragons=13, heroes=True, invisibility=5
    )
    assert result.deployed == 0
    assert result.point is None
    assert any("invisibilita' saltate" in line for line in engine.logs)
    # gli eroi vengono comunque schierati (sul primo candidato) per non perdere il raid
    assert ui.battle_card_point(IMAGE, ui.BATTLE_KING_CARD) in {point for point, _ in taps}


def test_deploy_dragon_corner_without_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, taps = _fake_engine()
    monkeypatch.setattr(
        attack_engine.ui, "deploy_candidates_for_corner", lambda image, corner: []
    )
    result = engine.deploy_dragon_corner(
        IMAGE, corner="se", dragons=3, heroes=False, invisibility=0
    )
    assert result.taps == 0
    assert result.point is None
    assert taps == []
    assert any("nessun punto" in line for line in engine.logs)


# --------------------------------------------------------------------------- fase deploy
def _phase_engine(monkeypatch: pytest.MonkeyPatch) -> tuple:
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    engine.grab = lambda: IMAGE
    calls = {"deploy": 0, "wait": 0, "pan": 0}
    outcome = CornerDeploy(taps=40, point=(120, 780), on_grass=True, corner="se", deployed=13)

    def fake_deploy(image, **kwargs):
        calls["deploy"] += 1
        return outcome

    def fake_wait(**kwargs):
        calls["wait"] += 1
        return True

    engine.deploy_dragon_corner = fake_deploy
    engine.wait_battle_start = fake_wait
    engine.pan_camera_towards_corner = lambda corner, image=None: calls.__setitem__(
        "pan", calls["pan"] + 1
    )
    return engine, calls


def test_corner_phase_deploys_right_at_battle_start(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, calls = _phase_engine(monkeypatch)
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
    assert calls["wait"] == 1  # aspetta l'inizio (countdown imposto dal gioco)
    assert calls["deploy"] == 1  # un solo deploy, niente tap sprecati in anteprima
    assert calls["pan"] == 1
    assert report["deploy_phase"] == "battle"
    assert report["preview_deploy_ignored"] is True
    assert report["deploy_taps"] == 40
    assert report["dragon_deployed"] == 13
    assert report["deploy_point"] == (120, 780)


def test_corner_phase_reports_when_battle_never_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, calls = _phase_engine(monkeypatch)
    engine.wait_battle_start = lambda **kwargs: False
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
    assert calls["deploy"] == 0


# --------------------------------------------------------------------------- SURRENDER
@live_dataset
def test_end_battle_early_confirms_surrender_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    image = _load_live("surrender-dialog.png")
    engine = attack_engine.AttackEngine.__new__(attack_engine.AttackEngine)
    engine.config = Config()
    engine.logs = []
    engine.log = engine.logs.append
    taps: list[tuple[int, int]] = []
    engine._tap = lambda point, wait_s=None: taps.append(point)
    frames = iter([image, image, _load_live("risultati-1.png")])
    engine.grab = lambda: next(frames, image)
    real_classify = states.classify
    monkeypatch.setattr(
        attack_engine.states, "classify", lambda frame: real_classify(frame)
    )
    monkeypatch.setattr(attack_engine.time, "sleep", lambda seconds: None)
    okay = ui.find_surrender_ok(image)
    assert okay is not None
    assert engine.end_battle_early(confirm_timeout_s=2.0) is True
    assert okay in taps


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
