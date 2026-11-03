from pathlib import Path

import pytest
from pydantic import ValidationError

from cocbot.config import load_config
from cocbot.config.models import Config, RunMode, WallMode

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"


def test_defaults_are_safe() -> None:
    config = Config()
    assert config.safety.never_spend_gems is True
    assert config.safety.ban_iap_shop is True
    assert config.safety.mode is RunMode.DRY_RUN
    assert config.ui.locale == "en"
    assert config.walls.mode is WallMode.CHECK_ONLY
    # decisioni utente del 3 nov: nessun limite di default (illimitato se non impostato),
    # input non invasivo, preset builder riservato alle mura + switch automatico
    assert config.safety.max_session_hours is None
    assert config.safety.max_attacks_per_hour is None
    assert config.safety.max_upgrades_per_hour is None
    assert config.safety.auto_stop_when_nothing_to_do is True
    assert config.input.backend == "winmsg"
    assert config.walls.reserve_builder_for_walls is True
    assert config.walls.switch_to_all_builders_when_walls_max is True
    assert config.walls.auto_stop_when_walls_max is True
    assert config.gui.hotkey_start_stop == "ctrl+alt+l"
    # humanization/anti-ban attiva di default (richiesta utente)
    assert config.humanize.enabled is True
    assert config.humanize.max_actions_per_minute == 30
    assert config.humanize.idle_tap_probability > 0
    assert config.humanize.break_probability > 0


def test_never_spend_gems_cannot_be_disabled() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"safety": {"never_spend_gems": False}})
    with pytest.raises(ValidationError):
        Config.model_validate({"safety": {"ban_iap_shop": False}})


def test_canonical_size_must_be_16_9() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"ui": {"canonical_size": [1024, 768]}})


def test_example_config_is_valid() -> None:
    assert EXAMPLE.is_file(), f"config di esempio mancante: {EXAMPLE}"
    config = load_config(EXAMPLE)
    assert config.safety.never_spend_gems is True
    assert config.device.backend in {"window", "adb"}
    assert config.attack.strategy == "dragon_spam"
    assert config.capture.backend == "wgc"
    assert config.input.backend == "winmsg"
    assert config.safety.max_session_hours is None  # illimitato di default
    assert config.gui.hotkey_start_stop == "ctrl+alt+l"


def test_safety_rejects_negative_limits() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"safety": {"max_session_hours": -1}})
