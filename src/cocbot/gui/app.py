"""GUI minimale (tkinter, stdlib): stato, Start/Stop, hotkey globali e loop attacco.

- non ruba il focus: nessuna chiamata a focus_force/lift;
- hotkey globale start/stop configurabile (`gui.hotkey_start_stop`, default Ctrl+Alt+L);
- kill switch globale `F12`;
- mostra stato, FPS, sessione, azioni, pause e avvisi anti-ban;
- pannello **Attacco**: dry-run raid, scout loot e raid reale (questi ultimi spendono ~1100
  oro/ricerca) lanciati come CLI `python -m cocbot attack-*` in un thread, con output nel log.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from cocbot.app.controller import BotController, BotState
from cocbot.config import load_config
from cocbot.config.models import Config
from cocbot.gui.hotkey import GlobalHotkey, parse_hotkey

_HOTKEY_START_STOP = 1
_HOTKEY_KILL = 2

# radice del repo (src/cocbot/gui/app.py -> parents[3]) per lanciare `python -m cocbot`
REPO_ROOT = Path(__file__).resolve().parents[3]

_STATE_LABELS = {
    BotState.IDLE: "pronto",
    BotState.WAITING_GAME: "in attesa del gioco",
    BotState.RUNNING: "in esecuzione",
    BotState.PAUSED: "in pausa",
    BotState.STOPPED: "fermato",
    BotState.ERROR: "errore",
}


def load_default_config() -> Config:
    candidates = [
        Path("config/config.yaml"),
        Path("config/config.example.yaml"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return load_config(candidate)
    return Config()


def run_gui(
    config: Config | None = None,
    *,
    selftest_s: float | None = None,
    auto_start: bool = False,
) -> int:
    config = config or load_default_config()
    log_queue: queue.Queue[str] = queue.Queue()

    def log(message: str) -> None:
        log_queue.put(f"[{time.strftime('%H:%M:%S')}] {message}")

    controller = BotController(config, log=log)
    hotkeys = GlobalHotkey(
        {
            _HOTKEY_START_STOP: parse_hotkey(config.gui.hotkey_start_stop),
            _HOTKEY_KILL: parse_hotkey(config.gui.hotkey_kill),
        }
    )

    root = tk.Tk()
    root.title("cocbot — automazione Clash of Clans (uso didattico, viola i ToS)")
    root.geometry("660x660")
    root.minsize(600, 580)

    main = ttk.Frame(root, padding=10)
    main.pack(fill="both", expand=True)

    state_var = tk.StringVar(value="pronto")
    game_var = tk.StringVar(value="gioco: rilevamento…")
    metrics_var = tk.StringVar(value="")
    anti_var = tk.StringVar(value="")
    hotkey_var = tk.StringVar(
        value=f"Hotkey: {config.gui.hotkey_start_stop} (start/stop) · {config.gui.hotkey_kill} (kill switch)"
    )

    ttk.Label(main, textvariable=state_var, font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(main, textvariable=game_var).pack(anchor="w", pady=(2, 0))
    ttk.Label(main, textvariable=metrics_var).pack(anchor="w", pady=(2, 0))
    ttk.Label(main, textvariable=anti_var, foreground="#a33").pack(anchor="w", pady=(2, 0))
    ttk.Label(main, textvariable=hotkey_var, foreground="#555").pack(anchor="w", pady=(2, 6))

    buttons = ttk.Frame(main)
    buttons.pack(fill="x", pady=(0, 6))
    start_button = ttk.Button(buttons, text="Avvia bot")
    start_button.pack(side="left")

    # --- pannello attacco (CLI in thread, output nel log) -------------------------
    attack_frame = ttk.LabelFrame(main, text="Attacco (spende oro: ~1100 per ricerca)")
    attack_frame.pack(fill="x", pady=(0, 6))
    attack_options = ttk.Frame(attack_frame)
    attack_options.pack(fill="x", pady=(2, 2))
    searches_var = tk.IntVar(value=2)
    spells_var = tk.IntVar(value=0)
    heroes_var = tk.BooleanVar(value=config.attack.use_heroes)
    caps_var = tk.BooleanVar(value=config.attack.respect_storage_caps)
    ttk.Label(attack_options, text="ricerche max:").pack(side="left")
    ttk.Spinbox(attack_options, from_=1, to=5, width=3, textvariable=searches_var).pack(
        side="left", padx=(2, 8)
    )
    ttk.Label(attack_options, text="spell:").pack(side="left")
    ttk.Spinbox(attack_options, from_=0, to=8, width=3, textvariable=spells_var).pack(
        side="left", padx=(2, 8)
    )
    ttk.Checkbutton(attack_options, text="eroi", variable=heroes_var).pack(side="left", padx=(0, 8))
    ttk.Checkbutton(attack_options, text="rispetta cap storage", variable=caps_var).pack(side="left")
    attack_buttons_row = ttk.Frame(attack_frame)
    attack_buttons_row.pack(fill="x", pady=(2, 2))
    dry_button = ttk.Button(attack_buttons_row, text="Dry-run raid")
    scout_button = ttk.Button(attack_buttons_row, text="Scout loot (spende)")
    raid_button = ttk.Button(attack_buttons_row, text="Raid reale (spende)")
    for button in (dry_button, scout_button, raid_button):
        button.pack(side="left", padx=(0, 6))
    attack_var = tk.StringVar(value="attacco: idle")
    ttk.Label(attack_frame, textvariable=attack_var, foreground="#555").pack(anchor="w")

    # --- pannello planner upgrade (CLI in thread, output nel log) -----------------
    planner_frame = ttk.LabelFrame(main, text="Planner upgrade (dry-run di default)")
    planner_frame.pack(fill="x", pady=(0, 6))
    planner_options = ttk.Frame(planner_frame)
    planner_options.pack(fill="x", pady=(2, 2))
    target_var = tk.StringVar(value="")
    ttk.Label(planner_options, text="target (--only):").pack(side="left")
    ttk.Entry(planner_options, textvariable=target_var, width=24).pack(
        side="left", padx=(2, 8)
    )
    planner_buttons_row = ttk.Frame(planner_frame)
    planner_buttons_row.pack(fill="x", pady=(2, 2))
    plan_button = ttk.Button(planner_buttons_row, text="Scansiona + piano (dry-run)")
    exec_button = ttk.Button(planner_buttons_row, text="Esegui target (spende)")
    for button in (plan_button, exec_button):
        button.pack(side="left", padx=(0, 6))
    planner_var = tk.StringVar(value="planner: idle")
    ttk.Label(planner_frame, textvariable=planner_var, foreground="#555").pack(anchor="w")

    log_box = scrolledtext.ScrolledText(main, height=12, state="disabled", wrap="word")
    log_box.pack(fill="both", expand=True)

    def append_log(message: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", message + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    task_state: dict[str, bool] = {"running": False}
    task_buttons = (dry_button, scout_button, raid_button, plan_button, exec_button)

    def sync_task_buttons() -> None:
        bot_running = controller.snapshot().state == BotState.RUNNING
        enabled = not task_state["running"] and not bot_running
        for button in task_buttons:
            button.configure(state="normal" if enabled else "disabled")

    def start_task_cli(extra: list[str], label: str, status_var: tk.StringVar) -> None:
        if task_state["running"]:
            append_log(f"task: '{task_state_name['label']}' già in esecuzione")
            return
        task_state["running"] = True
        task_state_name["label"] = label
        sync_task_buttons()
        status_var.set(f"{label} in corso…")
        command = [sys.executable, "-m", "cocbot", *extra]
        append_log(f"task: avvio {label}: {' '.join(command[2:])}")

        def worker() -> None:
            exit_code = -1
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert process.stdout is not None
                for line in process.stdout:
                    log_queue.put(line.rstrip())
                exit_code = process.wait()
            except OSError as exc:
                log_queue.put(f"task: errore avvio: {exc}")
            finally:

                def finish() -> None:
                    task_state["running"] = False
                    status_var.set(f"{label} terminato (exit {exit_code})")
                    log_queue.put(f"task: {label} terminato (exit {exit_code})")
                    sync_task_buttons()

                root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    task_state_name: dict[str, str] = {"label": ""}

    def raid_args() -> list[str]:
        arguments = [
            "attack-run",
            "--allow-spend",
            "--max-searches",
            str(max(1, searches_var.get())),
            "--spells",
            str(max(0, spells_var.get())),
        ]
        if not heroes_var.get():
            arguments.append("--no-heroes")
        if not caps_var.get():
            arguments.append("--ignore-caps")
        return arguments

    def run_planner_execute() -> None:
        target = target_var.get().strip()
        if not target:
            append_log("planner: indica un target (--only) per l'esecuzione")
            return
        confirm = messagebox.askyesno(
            "Conferma spesa",
            f"Eseguire davvero l'upgrade di '{target}'?\n\nQuesta azione SPENDE risorse.",
        )
        if not confirm:
            append_log("planner: esecuzione annullata")
            return
        start_task_cli(
            ["upgrade-run", "--execute", "--only", target],
            f"upgrade '{target}'",
            planner_var,
        )

    dry_button.configure(
        command=lambda: start_task_cli(["attack-run"], "raid dry-run", attack_var)
    )
    scout_button.configure(
        command=lambda: start_task_cli(
            ["attack-scout", "--allow-spend"], "scout loot", attack_var
        )
    )
    raid_button.configure(
        command=lambda: start_task_cli(raid_args(), "raid reale", attack_var)
    )
    plan_button.configure(
        command=lambda: start_task_cli(["upgrade-run"], "planner dry-run", planner_var)
    )
    exec_button.configure(command=run_planner_execute)
    sync_task_buttons()

    def toggle_bot() -> None:
        running = controller.toggle()
        start_button.configure(text="Ferma bot" if running else "Avvia bot")
        sync_task_buttons()

    start_button.configure(command=toggle_bot)

    def poll() -> None:
        try:
            while True:
                append_log(log_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                hotkey_id = hotkeys.events.get_nowait()
                if hotkey_id == _HOTKEY_START_STOP:
                    toggle_bot()
                elif hotkey_id == _HOTKEY_KILL:
                    append_log(f"kill switch {config.gui.hotkey_kill}: stop del bot")
                    controller.stop()
                    start_button.configure(text="Avvia bot")
        except queue.Empty:
            pass
        snapshot = controller.snapshot()
        state_var.set(f"Stato: {_STATE_LABELS.get(snapshot.state, snapshot.state.value)} — {snapshot.message}")
        game_var.set(
            f"Gioco: {'home rilevata' if snapshot.home_detected else 'in attesa/non riconosciuto'} · "
            f"finestra: {'presente' if snapshot.state != BotState.WAITING_GAME else 'assente'}"
        )
        metrics_var.set(
            f"Cattura: {snapshot.fps:.1f} FPS · frame: {snapshot.frames} · "
            f"sessione: {snapshot.session_s / 60:.1f} min · azioni: {snapshot.actions} · pause: {snapshot.breaks}"
        )
        anti_var.set("Avvisi anti-ban: " + ("; ".join(snapshot.warnings) if snapshot.warnings else "nessuno"))
        root.after(150, poll)

    def on_close() -> None:
        controller.stop()
        hotkeys.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    started = hotkeys.start()
    if not started:
        log("ATTENZIONE: thread hotkey non avviato")
    for error in hotkeys.errors:
        log(f"ATTENZIONE: {error}")
    log(f"GUI pronta · hotkey {config.gui.hotkey_start_stop} · {config.gui.hotkey_kill} kill switch")
    if selftest_s is not None:
        print(f"selftest GUI: hotkey registrate={not hotkeys.errors} errori={hotkeys.errors}")
    if auto_start:
        toggle_bot()
    root.after(150, poll)
    if selftest_s is not None:
        root.after(int(selftest_s * 1000), on_close)
    root.mainloop()
    return 0
