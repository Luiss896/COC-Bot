"""Test del caricamento config della GUI (indipendente dalla working directory)."""
from __future__ import annotations

from pathlib import Path

import pytest

from cocbot.config.models import Config
from cocbot.gui import app as app_module
from cocbot.gui.app import CocbotApp, find_config_path, load_default_config


def test_find_config_path_independent_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    found = find_config_path()
    expected = (app_module.REPO_ROOT / "config" / "config.example.yaml").resolve()
    assert found == expected


def test_load_default_config_independent_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_default_config()
    assert config.profile_name == "default"
    assert config.gui.hotkey_start_stop == "ctrl+alt+l"
    assert config.capture.backend == "wgc"


def test_prefers_config_yaml_over_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("profile_name: custom\n", encoding="utf-8")
    (config_dir / "config.example.yaml").write_text("profile_name: example\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert find_config_path() == (config_dir / "config.yaml").resolve()
    assert load_default_config().profile_name == "custom"


def test_falls_back_to_memory_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "REPO_ROOT", tmp_path / "repo-inesistente")
    monkeypatch.chdir(tmp_path)
    assert find_config_path() is None
    config = load_default_config()
    assert isinstance(config, Config)
    assert config.profile_name == "default"


def test_display_path_relative_to_repo() -> None:
    inside = app_module.REPO_ROOT / "config" / "config.example.yaml"
    assert CocbotApp._display_path(inside) == "config/config.example.yaml"
    assert CocbotApp._display_path(None) == "—"
    outside = Path("C:/Windows/System32/drivers/etc/hosts")
    assert CocbotApp._display_path(outside) == str(outside)
