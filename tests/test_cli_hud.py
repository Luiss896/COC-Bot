"""Test del comando CLI read-only `hud` (stato schermo + risorse) con engine finto."""
from __future__ import annotations

import json
from typing import Any

import pytest

import cocbot.__main__ as main_module
from cocbot.app.upgrade_engine import HudRead, UpgradeEngineError
from cocbot.config.models import Config
from cocbot.core.types import ScreenState
from cocbot.vision.ocr import OcrUnavailable


class FakeEngine:
    def __init__(
        self,
        *,
        screen_state: ScreenState = ScreenState.HOME,
        hud: HudRead | Exception | None = None,
        grab_error: Exception | None = None,
    ) -> None:
        self.screen_state = screen_state
        self.hud = hud if hud is not None else HudRead(
            gold=9_670_273,
            elixir=8_616_738,
            dark=200_000,
            gems=1_925,
            builders_available=1,
            builders_total=6,
            notes=("builder non letti",),
        )
        self.grab_error = grab_error
        self.closed = False

    def grab(self) -> Any:
        if self.grab_error is not None:
            raise self.grab_error
        return object()

    def state(self, image: Any) -> ScreenState:
        return self.screen_state

    def read_hud(self, image: Any) -> HudRead:
        if isinstance(self.hud, Exception):
            raise self.hud
        return self.hud

    def close(self) -> None:
        self.closed = True


def run_hud(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: FakeEngine,
    argv: list[str],
) -> tuple[int, str]:
    monkeypatch.setattr(main_module, "_load_engine", lambda config: (Config(), engine))
    code = main_module.main(argv)
    output = capsys.readouterr().out
    return code, output


def test_hud_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    engine = FakeEngine()
    code, output = run_hud(monkeypatch, capsys, engine, ["hud", "--json"])
    assert code == 0
    assert engine.closed is True
    payload = json.loads([line for line in output.splitlines() if line.strip().startswith("{")][-1])
    assert payload["state"] == "home"
    assert payload["home"] is True
    assert payload["hud"] == {
        "gold": 9_670_273,
        "elixir": 8_616_738,
        "dark": 200_000,
        "gems": 1_925,
        "builders_available": 1,
        "builders_total": 6,
    }
    assert payload["notes"] == ["builder non letti"]


def test_hud_human_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    engine = FakeEngine()
    code, output = run_hud(monkeypatch, capsys, engine, ["hud"])
    assert code == 0
    assert "== HUD (sola lettura) ==" in output
    assert "stato schermo: home" in output
    assert "oro: 9 670 273" in output
    assert "builder: 1/6" in output
    assert "sola lettura" in output.lower()
    assert engine.closed is True


def test_hud_reports_missing_ocr(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    engine = FakeEngine(hud=OcrUnavailable("rapidocr non installato"))
    code, output = run_hud(monkeypatch, capsys, engine, ["hud"])
    assert code == 1
    assert "ERRORE OCR" in output
    assert "pip install" in output
    assert engine.closed is True


def test_hud_reports_engine_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    engine = FakeEngine(grab_error=UpgradeEngineError("finestra del gioco minimizzata"))
    code, output = run_hud(monkeypatch, capsys, engine, ["hud", "--json"])
    assert code == 1
    assert "ERRORE engine" in output
    assert "minimizzata" in output
    assert engine.closed is True


def test_hud_parser_is_registered() -> None:
    parser = main_module.build_parser()
    args = parser.parse_args(["hud", "--json"])
    assert args.command == "hud"
    assert args.json is True
    assert args.config == "config/config.example.yaml"
