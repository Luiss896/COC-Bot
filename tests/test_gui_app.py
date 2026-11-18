"""Test della GUI tkinter in modalità headless (finestra nascosta, controller e CLI finti).

Copre: navigazione, conferme di spesa, gating dei pulsanti, annullamento task, kill
switch, chiusura con task in corso, parsing probe/HUD, filtri del registro e hotkey.
"""
from __future__ import annotations

import contextlib
import queue
import subprocess
import sys
import tkinter as tk
from typing import Any

import pytest

from cocbot.app.controller import BotSnapshot, BotState
from cocbot.config.models import Config
from cocbot.gui import app as app_module
from cocbot.gui.app import PAGES, REPO_ROOT, CocbotApp
from cocbot.gui.tasks import TaskEvent

TEST_CONFIG_PATH = REPO_ROOT / "config" / "config.test.yaml"
CONFIG_ARG = ["--config", "config/config.test.yaml"]


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _tk_available(), reason="tkinter/display non disponibile")


class FakeController:
    """Controller minimale: nessuna cattura, stati controllabili dai test."""

    def __init__(self) -> None:
        self.state = BotState.IDLE
        self.message = "pronto"
        self.toggle_calls = 0
        self.stop_calls: list[float] = []

    def snapshot(self) -> BotSnapshot:
        return BotSnapshot(self.state, self.message)

    def toggle(self) -> bool:
        self.toggle_calls += 1
        if self.state is BotState.RUNNING:
            self.state = BotState.STOPPED
            return False
        self.state = BotState.RUNNING
        return True

    def stop(self, join_timeout_s: float = 3.0) -> None:
        self.stop_calls.append(join_timeout_s)
        self.state = BotState.STOPPED


class FakeRunner:
    """Runner CLI finto: registra i comandi e permette di simulare gli eventi."""

    def __init__(self) -> None:
        self.queue: queue.Queue[TaskEvent] = queue.Queue()
        self._running = False
        self.label = ""
        self.starts: list[tuple[list[str], str]] = []
        self.cancel_calls = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self, arguments: Any, label: str) -> bool:
        if self._running:
            return False
        self._running = True
        self.label = label
        arguments = [str(argument) for argument in arguments]
        self.starts.append((arguments, label))
        self.queue.put(
            TaskEvent(
                "started",
                label=label,
                command=("python", "-u", "-m", "cocbot", *arguments),
                arguments=tuple(arguments),
            )
        )
        return True

    def cancel(self) -> bool:
        if not self._running:
            return False
        self._running = False
        self.cancel_calls += 1
        self.queue.put(TaskEvent("cancelled", label=self.label))
        return True

    def emit_line(self, line: str) -> None:
        self.queue.put(TaskEvent("line", line=line, label=self.label))

    def finish(self, exit_code: int = 0, duration_s: float = 1.5) -> None:
        self._running = False
        self.queue.put(
            TaskEvent(
                "finished",
                label=self.label,
                exit_code=exit_code,
                duration_s=duration_s,
                command=("python", "-m", "cocbot"),
            )
        )


class FakeConfirm:
    def __init__(self) -> None:
        self.answer = True
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, message: str) -> bool:
        self.calls.append((title, message))
        return self.answer


class FakeHotkey:
    def __init__(self) -> None:
        self.events: queue.Queue[int] = queue.Queue()
        self.errors: list[str] = []
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True


class GuiHarness:
    def __init__(
        self,
        *,
        config: Config | None = None,
        enable_hotkeys: bool = False,
        hotkey_factory: Any = None,
    ) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.controller = FakeController()
        self.runner = FakeRunner()
        self.confirm = FakeConfirm()
        self.app = CocbotApp(
            self.root,
            config or Config(),
            controller=self.controller,
            runner=self.runner,
            config_path=TEST_CONFIG_PATH,
            confirm=self.confirm,
            enable_hotkeys=enable_hotkeys,
            hotkey_factory=hotkey_factory,
        )

    def log_text(self) -> str:
        return "\n".join(line for _level, line in self.app.logs)

    def close(self) -> None:
        self.confirm.answer = True
        with contextlib.suppress(tk.TclError):
            self.app.request_close()


@pytest.fixture
def gui():
    harness = GuiHarness()
    try:
        yield harness
    finally:
        harness.close()


def test_pages_and_navigation(gui: GuiHarness) -> None:
    assert tuple(gui.app.pages) == PAGES
    assert gui.app.current_page == "dashboard"
    gui.app.show_page("attack")
    assert gui.app.current_page == "attack"
    assert gui.app.page_title_var.get() == "Battaglia"
    assert gui.app.nav_buttons["attack"]._active is True
    gui.app.show_page("pagina-inesistente")
    assert gui.app.current_page == "attack"


def test_attack_options_are_clamped(gui: GuiHarness) -> None:
    gui.app.attack_vars["searches"].set("99")
    assert gui.app._attack_options()["searches"] == 20
    gui.app.attack_vars["searches"].set("abc")
    assert gui.app._attack_options()["searches"] == 2
    gui.app.attack_vars["spells"].set("-3")
    assert gui.app._attack_options()["spells"] == 0


def test_attack_cost_preview_updates(gui: GuiHarness) -> None:
    gui.app.attack_vars["searches"].set("3")
    assert "3.300" in gui.app.attack_cost_vars["raid"].get()
    assert "3.300" in gui.app.attack_cost_var.get()
    assert "--max-searches 3" in gui.app.attack_command_var.get()


def test_dry_run_does_not_require_confirmation(gui: GuiHarness) -> None:
    gui.confirm.answer = False
    gui.app.buttons["attack_dry"].invoke()
    assert len(gui.runner.starts) == 1
    arguments, label = gui.runner.starts[0]
    assert label == "Simulazione raid"
    assert arguments[0] == "attack-run"
    assert "--allow-spend" not in arguments
    assert gui.confirm.calls == []
    assert arguments[-2:] == CONFIG_ARG


def test_raid_requires_confirmation_and_uses_teto(gui: GuiHarness) -> None:
    gui.confirm.answer = False
    gui.app.buttons["attack_raid"].invoke()
    assert gui.runner.starts == []
    assert gui.confirm.calls
    assert "annullata" in gui.log_text()

    gui.confirm.answer = True
    gui.app.buttons["attack_raid"].invoke()
    assert len(gui.runner.starts) == 1
    arguments, label = gui.runner.starts[0]
    assert label == "Raid reale"
    assert arguments[:2] == ["attack-run", "--allow-spend"]
    assert arguments[2:4] == ["--max-searches", "2"]
    assert "--dragons" in arguments and "--spells" in arguments
    assert arguments[arguments.index("--clones") + 1] == "2"
    assert arguments[arguments.index("--strategy") + 1] == "dragon_clone"
    assert arguments[-2:] == CONFIG_ARG
    assert gui.confirm.calls[-1][0] == "Raid reale"


def test_scout_and_farm_require_confirmation(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["attack_scout"].invoke()
    arguments, _label = gui.runner.starts[0]
    assert arguments[:2] == ["attack-scout", "--allow-spend"]
    gui.runner.finish()
    gui.app.tick()

    gui.app.buttons["attack_farm"].invoke()
    arguments, label = gui.runner.starts[-1]
    assert label == "Farm automatico"
    assert arguments[0] == "attack-farm"
    assert "--max-gold-spend" in arguments
    index = arguments.index("--max-gold-spend")
    assert arguments[index + 1] == "4400"


def test_auto_page_and_dry_run(gui: GuiHarness) -> None:
    assert "auto" in gui.app.pages
    assert "auto_dry" in gui.app.buttons
    assert "auto_run" in gui.app.buttons
    gui.app.buttons["auto_dry"].invoke()
    arguments, label = gui.runner.starts[0]
    assert arguments[0] == "auto-run"
    assert "--allow-spend" not in arguments
    assert "--cycles" in arguments
    assert label == "Simulazione AUTO"


def test_auto_run_requires_confirmation(gui: GuiHarness) -> None:
    gui.confirm.answer = False
    gui.app.buttons["auto_run"].invoke()
    assert gui.runner.starts == []
    assert gui.confirm.calls[-1][0] == "AUTO farm + upgrade"

    gui.confirm.answer = True
    gui.app.buttons["auto_run"].invoke()
    arguments, label = gui.runner.starts[0]
    assert arguments[0] == "auto-run"
    assert "--allow-spend" in arguments
    assert arguments[arguments.index("--cycles") + 1] == "20"
    assert arguments[arguments.index("--strategy") + 1] == "dragon_clone"
    assert arguments[-2:] == CONFIG_ARG
    assert label == "AUTO farm + upgrade"


def test_auto_require_lab_pets_flag(gui: GuiHarness) -> None:
    gui.app.auto_vars["require_lab_pets"].set("1")
    gui.app.buttons["auto_dry"].invoke()
    arguments, _label = gui.runner.starts[0]
    assert "--require-lab-pets" in arguments


def test_gui_clones_and_strategy_reach_cli(gui: GuiHarness) -> None:
    gui.app.attack_vars["clones"].set("4")
    gui.app.attack_vars["strategy"].set("dragon_spam")
    gui.confirm.answer = True
    gui.app.buttons["attack_raid"].invoke()
    arguments, _label = gui.runner.starts[0]
    assert arguments[arguments.index("--clones") + 1] == "4"
    assert arguments[arguments.index("--strategy") + 1] == "dragon_spam"
    assert "--strategy" in arguments


def test_gui_clones_default_from_config(gui: GuiHarness) -> None:
    assert gui.app.attack_vars["clones"].get() == "2"
    assert gui.app.attack_vars["strategy"].get() == "dragon_clone"


def test_upgrade_target_execution_and_budgets(gui: GuiHarness) -> None:
    gui.app.upgrade_vars["target"].set("Gold Mine")
    gui.app.upgrade_vars["max_gold"].set("1.500.000")
    gui.confirm.answer = True
    gui.app.buttons["upgrade_target"].invoke()
    arguments, label = gui.runner.starts[0]
    assert label == "Upgrade «Gold Mine»"
    assert arguments[:4] == ["upgrade-run", "--execute", "--only", "Gold Mine"]
    index = arguments.index("--max-gold")
    assert arguments[index + 1] == "1500000"
    assert arguments[-2:] == CONFIG_ARG


def test_upgrade_plan_execution(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["upgrade_plan"].invoke()
    arguments, _label = gui.runner.starts[0]
    assert arguments[:2] == ["upgrade-run", "--execute"]
    assert arguments[-2:] == CONFIG_ARG


def test_invalid_budget_blocks_execution(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.upgrade_vars["target"].set("Wall")
    gui.app.upgrade_vars["max_gold"].set("abc")
    gui.app.buttons["upgrade_target"].invoke()
    assert gui.runner.starts == []
    assert "tetto non valido" in gui.log_text()


def test_missing_target_blocks_execution(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["upgrade_target"].invoke()
    assert gui.runner.starts == []
    assert "indica un target" in gui.log_text()


def test_busy_buttons_and_cancel(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["attack_raid"].invoke()
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "disabled"
    assert str(gui.app.buttons["probe_game"]["state"]) == "disabled"
    assert str(gui.app.buttons["kill_all"]["state"]) == "normal"
    assert str(gui.app.buttons["cancel_task"]["state"]) == "normal"
    assert "in corso" in gui.app.task_status_var.get().lower()

    gui.app.buttons["cancel_task"].invoke()
    assert gui.runner.cancel_calls == 1
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "normal"
    assert "annullato" in gui.app.task_status_var.get().lower()


def test_kill_switch_stops_bot_and_task(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["attack_raid"].invoke()
    gui.app.tick()
    gui.controller.state = BotState.RUNNING
    gui.app.buttons["kill_all"].invoke()
    assert gui.runner.cancel_calls == 1
    assert gui.controller.stop_calls
    assert gui.runner.running is False
    assert "KILL SWITCH" in gui.log_text()
    assert str(gui.app.buttons["kill_all"]["state"]) == "normal"


def test_bot_toggle_gates_tasks(gui: GuiHarness) -> None:
    gui.app.buttons["bot_toggle"].invoke()
    assert gui.controller.toggle_calls == 1
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "disabled"
    gui.app.buttons["bot_toggle"].invoke()
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "normal"


def test_bot_waiting_for_game_gates_tasks(gui: GuiHarness) -> None:
    gui.controller.state = BotState.WAITING_GAME
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "disabled"
    assert gui.app.buttons["bot_toggle"].cget("text") == "Ferma bot"
    gui.controller.state = BotState.STOPPED
    gui.app.tick()
    assert str(gui.app.buttons["attack_raid"]["state"]) == "normal"
    assert gui.app.buttons["bot_toggle"].cget("text") == "Avvia bot"


def test_probe_payload_updates_dashboard(gui: GuiHarness) -> None:
    gui.app.buttons["probe_game"].invoke()
    assert gui.runner.starts[0][0] == ["probe", "--json"]
    gui.runner.emit_line(
        '{"game": {"process": "crosvm.exe", "client_size": [1733, 975], "is_16_9": true}, '
        '"launcher": null}'
    )
    gui.runner.finish()
    gui.app.tick()
    assert "GIOCO RILEVATO" in gui.app.game_pill.cget("text")
    assert gui.app.game_values["window"].get() == "1733×975"
    assert "rilevato" in gui.app.footer_game_var.get()
    assert "gioco rilevato" in gui.log_text().lower()
    assert str(gui.app.buttons["probe_game"]["state"]) == "normal"


def test_probe_multiline_json_updates_dashboard(gui: GuiHarness) -> None:
    """Simula l'output reale di probe --json (indentato): prima falliva la lettura."""
    gui.app.buttons["probe_game"].invoke()
    for line in (
        "{",
        '  "game": {',
        '    "process": "crosvm.exe",',
        '    "client_size": [',
        "      1733,",
        "      975",
        "    ],",
        '    "is_16_9": true',
        "  },",
        '  "launcher": null',
        "}",
    ):
        gui.runner.emit_line(line)
    gui.runner.finish()
    gui.app.tick()
    assert "GIOCO RILEVATO" in gui.app.game_pill.cget("text")
    assert gui.app.game_values["window"].get() == "1733×975"
    assert "output non interpretabile" not in gui.log_text()


def test_hud_payload_updates_resources(gui: GuiHarness) -> None:
    gui.app.buttons["read_hud"].invoke()
    arguments, label = gui.runner.starts[0]
    assert arguments[:2] == ["hud", "--json"]
    assert label == "Lettura HUD"
    gui.runner.emit_line(
        '{"state": "home", "home": true, "hud": {"gold": 9670273, "elixir": 8616738, '
        '"dark": 200000, "gems": 1925, "builders_available": 1, "builders_total": 6}, "notes": []}'
    )
    gui.runner.finish()
    gui.app.tick()
    assert gui.app.hud_stats["gold"].value_var.get() == "9.670.273"
    assert gui.app.hud_stats["elixir"].value_var.get() == "8.616.738"
    assert gui.app.hud_stats["builders"].value_var.get() == "1/6"
    assert gui.app.hud_stats["hud_state"].value_var.get() == "Home"
    assert gui.app.game_values["home"].get() == "Home"
    assert "Gemme" in gui.app.hud_hint_var.get()


def test_failed_hud_shows_suggestion(gui: GuiHarness) -> None:
    gui.app.buttons["read_hud"].invoke()
    gui.runner.emit_line("ERRORE OCR: rapidocr non installato")
    gui.runner.finish(exit_code=1)
    gui.app.tick()
    assert "OCR" in gui.log_text()
    assert "pip install" in gui.log_text()


def test_close_with_running_task_asks_confirmation(gui: GuiHarness) -> None:
    gui.confirm.answer = True
    gui.app.buttons["attack_raid"].invoke()
    gui.app.tick()

    gui.confirm.answer = False
    assert gui.app.request_close() is False
    assert gui.runner.cancel_calls == 0
    assert gui.confirm.calls[-1][0] == "Attività in corso"

    gui.confirm.answer = True
    assert gui.app.request_close() is True
    assert gui.runner.cancel_calls == 1
    assert gui.controller.stop_calls


def test_invalid_hotkey_does_not_crash() -> None:
    config = Config()
    config.gui.hotkey_start_stop = "ctrl+alt+"
    harness = GuiHarness(
        config=config,
        enable_hotkeys=True,
        hotkey_factory=lambda bindings: pytest.fail("non deve registrare hotkey non valide"),
    )
    try:
        harness.app.start_hotkeys()
        assert harness.app.hotkeys is None
        assert harness.app.hotkey_errors
        assert "non valida" in harness.log_text()
    finally:
        harness.close()


def test_hotkey_events_control_bot_and_kill_switch() -> None:
    fake = FakeHotkey()
    harness = GuiHarness(enable_hotkeys=True, hotkey_factory=lambda bindings: fake)
    try:
        harness.app.start_hotkeys()
        assert harness.app.hotkeys is fake
        assert fake.started is True
        fake.events.put(app_module._HOTKEY_START_STOP)
        harness.app.tick()
        assert harness.controller.toggle_calls == 1
        fake.events.put(app_module._HOTKEY_KILL)
        harness.app.tick()
        assert harness.controller.stop_calls
        assert fake.errors == []
    finally:
        harness.close()
        assert fake.stopped is True


def test_log_filter_and_clear(gui: GuiHarness) -> None:
    gui.app.log("errore grave", "error")
    gui.app.log("messaggio informativo", "info")
    gui.app.log_level_var.set("Solo errori")
    gui.app._apply_log_filter()
    rendered = gui.app.log_view.text.get("1.0", "end")
    assert "errore grave" in rendered
    assert "messaggio informativo" not in rendered

    gui.app.log_level_var.set("Tutti")
    gui.app.log_filter_var.set("informativo")
    gui.app._apply_log_filter()
    rendered = gui.app.log_view.text.get("1.0", "end")
    assert "messaggio informativo" in rendered
    assert "errore grave" not in rendered

    gui.app.log_level_var.set("Tutti")
    gui.app.log_filter_var.set("")
    gui.app.clear_log()
    rendered = gui.app.log_view.text.get("1.0", "end")
    assert "errore grave" not in rendered
    assert "registro svuotato" in rendered
    assert gui.app.logs


def test_classify_line() -> None:
    assert CocbotApp.classify_line("ERRORE engine: x") == "error"
    assert CocbotApp.classify_line("ATTENZIONE hotkey") == "warn"
    assert CocbotApp.classify_line("▶ task avviato") == "task"
    assert CocbotApp.classify_line("VICTORY 79%") == "ok"
    assert CocbotApp.classify_line("riga normale") == "info"


def test_selftest_cli_runs_hidden() -> None:
    """Il percorso CLI `python -m cocbot gui --selftest --hidden` deve funzionare."""
    result = subprocess.run(
        [sys.executable, "-m", "cocbot", "gui", "--selftest", "1", "--hidden"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "selftest GUI" in result.stdout
    assert "pagine=6" in result.stdout
