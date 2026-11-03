"""GUI minimale (tkinter, stdlib): stato, Start/Stop e hotkey globali.

- non ruba il focus: nessuna chiamata a focus_force/lift;
- hotkey globale start/stop configurabile (`gui.hotkey_start_stop`, default Ctrl+Alt+L);
- kill switch globale `F12`;
- mostra stato, FPS, sessione, azioni, pause e avvisi anti-ban.
"""
from __future__ import annotations

import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk

from cocbot.app.controller import BotController, BotState
from cocbot.config import load_config
from cocbot.config.models import Config
from cocbot.gui.hotkey import GlobalHotkey, parse_hotkey

_HOTKEY_START_STOP = 1
_HOTKEY_KILL = 2

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
    root.geometry("640x470")
    root.minsize(560, 400)

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

    log_box = scrolledtext.ScrolledText(main, height=14, state="disabled", wrap="word")
    log_box.pack(fill="both", expand=True)

    def append_log(message: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", message + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def toggle_bot() -> None:
        running = controller.toggle()
        start_button.configure(text="Ferma bot" if running else "Avvia bot")

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
