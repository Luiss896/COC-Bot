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


def test_safety_rejects_negative_limits() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"safety": {"max_session_hours": -1}})
