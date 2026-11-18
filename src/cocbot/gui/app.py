"""GUI desktop (tkinter) di cocbot: pannello unico, chiaro e con spese confermate.

Struttura della finestra:

- **barra laterale** con navigazione, pulsante rosso "FERMA TUTTO" sempre visibile e hotkey;
- **Panoramica**: stato di gioco/bot/cattura, risorse HUD, attività in corso e avvio rapido;
- **Battaglia**: cosa fa un raid, parametri con costo stimato, simulazione (gratis),
  scout loot, raid reale e farm (tutti con conferma della spesa);
- **Upgrade**: analisi in sola lettura, tetti di spesa, esecuzione target/piano (con conferma);
- **Registro**: log filtrabile, colorato, esportabile;
- **Sicurezza**: regole non negoziabili, kill switch, configurazione attiva.

Le azioni di gioco sono lanciate come CLI ``python -m cocbot ...`` in un sottoprocesso
(:class:`cocbot.gui.tasks.CliTaskRunner`): un task alla volta, annullabile dal kill switch o
alla chiusura della finestra (mai processi orfani mentre il bot spende risorse).
"""
from __future__ import annotations

import contextlib
import queue
import re
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Protocol

from cocbot import __version__
from cocbot.app.controller import BotController, BotSnapshot, BotState
from cocbot.config import load_config
from cocbot.config.models import Config
from cocbot.gui import formatting
from cocbot.gui.hotkey import GlobalHotkey, parse_hotkey
from cocbot.gui.tasks import CliTaskRunner, TaskEvent
from cocbot.gui.theme import Theme, apply_theme, resolve_theme_name
from cocbot.gui.widgets import (
    Badge,
    Card,
    LogView,
    NavButton,
    Pill,
    ScrollableFrame,
    StatBlock,
    Tooltip,
    autowrap,
    divider,
    key_value_row,
)

# radice del repo (src/cocbot/gui/app.py -> parents[3]) per lanciare `python -m cocbot`
REPO_ROOT = Path(__file__).resolve().parents[3]

_HOTKEY_START_STOP = 1
_HOTKEY_KILL = 2

PAGES: tuple[str, ...] = ("dashboard", "attack", "upgrade", "auto", "logs", "safety")
_PAGE_TITLES = {
    "dashboard": "Panoramica",
    "attack": "Battaglia",
    "upgrade": "Upgrade",
    "auto": "Auto",
    "logs": "Registro",
    "safety": "Sicurezza",
}
_PAGE_SUBTITLES = {
    "dashboard": "Stato di gioco, bot e risorse in un colpo d'occhio.",
    "attack": "Raid automatici: ogni ricerca costa ~1.100 oro. Le simulazioni non spendono nulla.",
    "upgrade": "Pianifica ed esegui upgrade dal menu Build. Di default è tutto in sola lettura.",
    "auto": "Loop unico: farm fino a depositi pieni, poi upgrade per priorità; stop con builder e depositi pieni.",
    "logs": "Tutto quello che succede: comandi, output del bot, avvisi ed errori.",
    "safety": "Regole non negoziabili, kill switch e configurazione attiva.",
}

_STATE_PILLS: dict[BotState, tuple[str, str]] = {
    BotState.IDLE: ("PRONTO", "idle"),
    BotState.WAITING_GAME: ("IN ATTESA DEL GIOCO", "warn"),
    BotState.RUNNING: ("IN ESECUZIONE", "running"),
    BotState.PAUSED: ("IN PAUSA", "warn"),
    BotState.STOPPED: ("FERMATO", "idle"),
    BotState.ERROR: ("ERRORE", "error"),
}

_ACTION_BUTTONS = (
    "probe_game",
    "read_hud",
    "read_hud_card",
    "attack_dry",
    "attack_scout",
    "attack_raid",
    "attack_farm",
    "upgrade_analyze",
    "upgrade_target",
    "upgrade_plan",
    "auto_dry",
    "auto_run",
)
_LEVEL_FILTERS = {"Tutti": 0, "Avvisi ed errori": 2, "Solo errori": 3}
_TARGET_SUGGESTIONS = (
    "Gold Mine",
    "Elixir Collector",
    "Gold Storage",
    "Elixir Storage",
    "Dark Elixir Storage",
    "Dark Elixir Drill",
    "Wall",
    "Crafting Station",
    "Clan Castle",
    "Army Camp",
    "Laboratory",
    "Barbarian King",
    "Archer Queen",
    "Grand Warden",
    "Royal Champion",
)
_LOG_REPORT_RE = re.compile(r"report salvato:\s*(?P<path>.+\.json)\s*$", re.MULTILINE)


def _looks_like_json_line(line: str) -> bool:
    """True per le righe di JSON (indentato o singola riga) da non riversare nel registro."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped[0] in "{}[]\"":
        return True
    return stripped.endswith((",", "[", "{", ":"))


class ControllerLike(Protocol):
    """Interfaccia minima del controller usata dalla GUI (iniettabile nei test)."""

    def snapshot(self) -> BotSnapshot: ...

    def toggle(self) -> bool: ...

    def stop(self, join_timeout_s: float = ...) -> None: ...


def find_config_path() -> Path | None:
    """Trova ``config/config.yaml`` (o l'esempio) indipendentemente dalla cwd.

    La GUI precedente caricava la config relativa alla cwd: avviata da un'altra directory
    mostrava impostazioni diverse da quelle usate dai task CLI.
    """
    candidates = (
        REPO_ROOT / "config" / "config.yaml",
        REPO_ROOT / "config" / "config.example.yaml",
        Path("config/config.yaml"),
        Path("config/config.example.yaml"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_default_config() -> Config:
    """Carica la config del repo (fallback: ``Config()`` in memoria)."""
    path = find_config_path()
    if path is None:
        return Config()
    return load_config(path)


class CocbotApp:
    """Finestra principale. Costruibile nei test senza hotkey né polling automatico."""

    def __init__(
        self,
        root: tk.Tk,
        config: Config,
        *,
        controller: ControllerLike | None = None,
        runner: CliTaskRunner | None = None,
        config_path: Path | None = None,
        confirm: Callable[[str, str], bool] | None = None,
        enable_hotkeys: bool = True,
        hotkey_factory: Callable[[dict[int, tuple[int, int]]], GlobalHotkey] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.config = config
        self.theme: Theme = apply_theme(root, resolve_theme_name(config.gui.theme))
        self.config_path = config_path.resolve() if config_path is not None else find_config_path()
        self.enable_hotkeys = enable_hotkeys
        self._hotkey_factory = hotkey_factory or GlobalHotkey
        self._clock = clock
        self.confirm = confirm or self._ask_confirm
        self._main_thread = threading.main_thread()
        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.logs: list[tuple[str, str]] = []
        self.game_payload: dict[str, Any] | None = None
        self.hud_payload: dict[str, Any] | None = None
        self.buttons: dict[str, ttk.Button] = {}
        self.nav_buttons: dict[str, NavButton] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.page_scrolls: dict[str, ScrollableFrame] = {}
        self.game_values: dict[str, tk.StringVar] = {}
        self.hud_stats: dict[str, StatBlock] = {}
        self.attack_vars: dict[str, tk.StringVar] = {}
        self.upgrade_vars: dict[str, tk.StringVar] = {}
        self.config_vars: dict[str, tk.StringVar] = {}
        self.current_page: str | None = None

        self.hotkeys: GlobalHotkey | None = None
        self.hotkey_errors: list[str] = []
        self.task_status_var = tk.StringVar(value="Nessuna attività in corso.")
        self.task_detail_var = tk.StringVar(value="Le azioni di gioco girano come processo separato.")
        self.task_pill: Pill | None = None
        self.task_progress: ttk.Progressbar | None = None
        self._current_action: str | None = None
        self._task_output: list[str] = []
        self._task_started_at: float | None = None
        self._after_id: str | None = None
        self._polling = False
        self._closed = False

        self.controller: ControllerLike = controller or BotController(config, log=self.log)
        self.runner: CliTaskRunner = runner or CliTaskRunner(REPO_ROOT)

        self._build_shell()
        self._build_dashboard_page()
        self._build_attack_page()
        self._build_upgrade_page()
        self._build_auto_page()
        self._build_logs_page()
        self._build_safety_page()
        self._bind_shortcuts()
        self.show_page("dashboard")
        self._refresh_status()
        self._sync_buttons()

    # ================================================================== costruzione UI
    def _build_shell(self) -> None:
        palette = self.theme.palette
        self.root.configure(bg=palette.bg)
        self.root.title(f"cocbot {__version__} — pannello di controllo Clash of Clans")
        self.root.geometry("1180x840")
        self.root.minsize(1040, 720)

        self._build_footer()
        shell = tk.Frame(self.root, bg=palette.bg)
        shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(shell, bg=palette.surface, width=238)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = tk.Frame(shell, bg=palette.bg)
        self.content.pack(side="left", fill="both", expand=True)

        self._build_sidebar()

        header = tk.Frame(self.content, bg=palette.bg)
        header.pack(fill="x", padx=24, pady=(14, 8))
        titles = tk.Frame(header, bg=palette.bg)
        titles.pack(side="left", fill="x", expand=True)
        self.page_title_var = tk.StringVar(value=_PAGE_TITLES["dashboard"])
        self.page_sub_var = tk.StringVar(value=_PAGE_SUBTITLES["dashboard"])
        ttk.Label(titles, textvariable=self.page_title_var, style="PageTitle.TLabel").pack(anchor="w")
        subtitle = ttk.Label(titles, textvariable=self.page_sub_var, style="PageSub.TLabel")
        subtitle.pack(anchor="w", pady=(2, 0))
        autowrap(subtitle, titles)
        self.header_pill = Pill(header, self.theme, "PRONTO", "idle")
        self.header_pill.pack(side="right", padx=(12, 0))

        self.page_host = tk.Frame(self.content, bg=palette.bg)
        self.page_host.pack(fill="both", expand=True, pady=(4, 0))

    def _build_footer(self) -> None:
        palette = self.theme.palette
        footer = tk.Frame(self.root, bg=palette.surface, height=36)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        self.footer_game_var = tk.StringVar(value="Gioco: non rilevato")
        self.footer_task_var = tk.StringVar(value="Attività: nessuna")
        ttk.Label(footer, textvariable=self.footer_game_var, style="SidebarSub.TLabel").pack(
            side="left", padx=(24, 18)
        )
        ttk.Label(footer, textvariable=self.footer_task_var, style="SidebarSub.TLabel").pack(side="left")
        ttk.Label(
            footer,
            text=(
                f"F5 avvia/ferma · {self.config.gui.hotkey_kill.upper()} ferma tutto · "
                "chiudere la finestra annulla il task"
            ),
            style="SidebarSub.TLabel",
        ).pack(side="right", padx=24)

    def _build_sidebar(self) -> None:
        palette = self.theme.palette
        brand = tk.Frame(self.sidebar, bg=palette.surface, padx=18, pady=6)
        brand.pack(fill="x", pady=(14, 0))
        tk.Label(
            brand,
            text="cocbot",
            font=self.theme.font("display"),
            fg=palette.accent,
            bg=palette.surface,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            brand,
            text="Clash of Clans · GPGPC",
            font=self.theme.font("small"),
            fg=palette.muted,
            bg=palette.surface,
            anchor="w",
        ).pack(fill="x")
        divider(self.sidebar, self.theme, pady=(12, 10))

        tk.Label(
            self.sidebar,
            text="PANNELLO",
            font=self.theme.font("small_bold"),
            fg=palette.subtle,
            bg=palette.surface,
            anchor="w",
            padx=18,
        ).pack(fill="x", pady=(0, 6))
        nav_frame = tk.Frame(self.sidebar, bg=palette.surface)
        nav_frame.pack(fill="x")
        for key in PAGES:
            button = NavButton(
                nav_frame,
                self.theme,
                _PAGE_TITLES[key],
                lambda page=key: self.show_page(page),
            )
            button.pack(fill="x")
            self.nav_buttons[key] = button

        bottom = tk.Frame(self.sidebar, bg=palette.surface, padx=14, pady=14)
        bottom.pack(side="bottom", fill="x")
        kill = ttk.Button(
            bottom, text="■   FERMA TUTTO", style="Kill.TButton", command=self.kill_everything
        )
        kill.pack(fill="x")
        self.buttons["kill_all"] = kill
        hint = ttk.Label(
            bottom,
            text=(
                f"{self.config.gui.hotkey_kill.upper()} ferma tutto.\n"
                "Nessuna gemma viene mai spesa."
            ),
            style="SidebarSub.TLabel",
            justify="left",
        )
        hint.pack(anchor="w", pady=(8, 0))
        autowrap(hint, bottom)
        tk.Label(
            bottom,
            text=f"v{__version__} · uso didattico (ToS Supercell)",
            font=self.theme.font("small"),
            fg=palette.subtle,
            bg=palette.surface,
            anchor="w",
        ).pack(fill="x", pady=(10, 0))

    def _new_page(self, key: str) -> tuple[tk.Frame, tk.Frame | None]:
        palette = self.theme.palette
        frame = tk.Frame(self.page_host, bg=palette.bg)
        self.pages[key] = frame
        if key == "logs":
            return frame, None
        scroll = ScrollableFrame(frame, self.theme)
        scroll.pack(fill="both", expand=True)
        body = tk.Frame(scroll.body, bg=palette.bg, padx=24, pady=16)
        body.pack(fill="both", expand=True)
        self.page_scrolls[key] = scroll
        return frame, body

    @staticmethod
    def command_preview(arguments: Sequence[str]) -> str:
        return "python -m cocbot " + " ".join(str(part) for part in arguments)

    def _tip(self, widget: tk.Misc, text: str) -> None:
        Tooltip(widget, self.theme, text)

    def _caption(self, parent: tk.Misc, text: str, *, style: str = "CardMuted.TLabel") -> ttk.Label:
        label = ttk.Label(parent, text=text, style=style, justify="left")
        label.pack(anchor="w", pady=(2, 0))
        autowrap(label, parent)
        return label

    def _bullet_rows(self, parent: tk.Misc, texts: Sequence[str]) -> None:
        palette = self.theme.palette
        for text in texts:
            row = tk.Frame(parent, bg=palette.card)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text="•", fg=palette.accent, bg=palette.card, font=self.theme.font("body_bold")
            ).pack(side="left", padx=(0, 6))
            label = ttk.Label(row, text=text, style="CardMuted.TLabel", justify="left")
            label.pack(side="left")
            autowrap(label, parent)

    def _card_grid(self, parent: tk.Misc, columns: int = 2) -> tk.Frame:
        grid = tk.Frame(parent, bg=self.theme.color("bg"))
        grid.pack(fill="x")
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="cards")
        return grid

    def _register_action_button(
        self,
        key: str,
        button: ttk.Button,
        *,
        side: str = "left",
        padx: tuple[int, int] = (0, 0),
        pady: tuple[int, int] = (0, 0),
    ) -> ttk.Button:
        button.pack(side=side, padx=padx, pady=pady)
        self.buttons[key] = button
        return button

    # ================================================================== pagina Panoramica
    def _build_dashboard_page(self) -> None:
        _frame, body = self._new_page("dashboard")
        assert body is not None
        palette = self.theme.palette

        hero = Card(body, self.theme, bg_key="surface", padx=22, pady=18)
        hero.pack(fill="x", pady=(0, 14))
        ttk.Label(hero.body, text="Pannello di controllo", style="Hero.TLabel").pack(anchor="w")
        intro = ttk.Label(
            hero.body,
            text=(
                "Automatizza Clash of Clans su Google Play Games on PC: controlla lo stato del gioco, "
                "simula le azioni e spendi risorse solo quando decidi tu."
            ),
            style="HeroSub.TLabel",
            justify="left",
        )
        intro.pack(anchor="w", pady=(3, 10))
        autowrap(intro, hero.body)

        steps = tk.Frame(hero.body, bg=palette.surface)
        steps.pack(fill="x", pady=(0, 12))
        for number, text in (
            ("1", "Apri Clash of Clans da Google Play Games"),
            ("2", "Premi «Rileva gioco» e controlla i dati"),
            ("3", "Scegli Battaglia o Upgrade: le simulazioni non spendono nulla"),
        ):
            row = tk.Frame(steps, bg=palette.surface)
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=number,
                font=self.theme.font("small_bold"),
                fg=palette.accent,
                bg=palette.surface,
                width=2,
                anchor="w",
            ).pack(side="left")
            ttk.Label(row, text=text, style="HeroSub.TLabel").pack(side="left")

        quick = tk.Frame(hero.body, bg=palette.surface)
        quick.pack(fill="x")
        probe = ttk.Button(quick, text="Rileva gioco", style="Accent.TButton", command=self.probe_game)
        self._register_action_button("probe_game", probe)
        hud = ttk.Button(
            quick, text="Leggi HUD (sola lettura)", style="Ghost.TButton", command=self.read_hud
        )
        self._register_action_button("read_hud", hud, padx=(8, 0))
        bot = ttk.Button(quick, text="Avvia bot", style="Ghost.TButton", command=self.toggle_bot)
        bot.pack(side="left", padx=(8, 0))
        self.buttons["bot_toggle"] = bot
        self._tip(probe, "Verifica che la finestra del gioco sia rilevata (sola lettura, nessun input).")
        self._tip(hud, "Legge oro, elisir, dark, gemme e builder dallo schermo. Nessun input inviato.")
        self._tip(bot, "Avvia/ferma il monitoraggio del gioco (F5).")
        self._bot_note = ttk.Label(
            quick, text="Bot fermo: nessun input inviato al gioco.", style="HeroSub.TLabel"
        )
        self._bot_note.pack(side="left", padx=(14, 0))

        cards = self._card_grid(body)
        self._build_game_card(cards).grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 7))
        self._build_bot_card(cards).grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 7))
        self._build_hud_card(cards).grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(7, 0))
        self._build_activity_card(cards).grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(7, 0))

        tips = Card(body, self.theme)
        tips.pack(fill="x", pady=(14, 0))
        tips.header("Suggerimenti rapidi")
        self._bullet_rows(
            tips.body,
            (
                "Le azioni marcate «SPENDE» chiedono sempre conferma con il costo stimato.",
                f"{self.config.gui.hotkey_start_stop.upper()} avvia/ferma il bot · "
                f"{self.config.gui.hotkey_kill.upper()} ferma bot e attività in corso.",
                "Chiudere questa finestra annulla l'attività in corso prima di uscire.",
                "Niente gemme, shop/IAP o guerre: le regole sono nella sezione Sicurezza.",
            ),
        )

        preview_card = Card(body, self.theme, padx=0, pady=0)
        preview_card.pack(fill="x", pady=(14, 0))
        header = tk.Frame(preview_card.body, bg=palette.card, padx=16, pady=10)
        header.pack(fill="x")
        ttk.Label(header, text="Ultime attività", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(
            header, text="Log completo nella sezione Registro", style="CardSub.TLabel"
        ).pack(side="right")
        self.preview_log = LogView(preview_card.body, self.theme, height=5, with_scrollbar=False, max_lines=200)
        self.preview_log.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.page_scrolls["dashboard"].enable_mousewheel()

    def _build_game_card(self, parent: tk.Misc) -> Card:
        palette = self.theme.palette
        card = Card(parent, self.theme)
        head = tk.Frame(card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="Gioco", style="CardTitle.TLabel").pack(side="left")
        self.game_pill = Pill(head, self.theme, "NON RILEVATO", "idle")
        self.game_pill.pack(side="right")
        self._caption(card.body, "Finestra di Clash of Clans / Google Play Games.")
        for label, key in (
            ("Finestra", "window"),
            ("Stato schermo", "home"),
            ("Processo", "process"),
            ("Client GPGPC", "launcher"),
        ):
            self.game_values[key] = key_value_row(card.body, self.theme, label)
        self.game_hint_var = tk.StringVar(value="Premi «Rileva gioco» per aggiornare.")
        hint = ttk.Label(card.body, textvariable=self.game_hint_var, style="CardMuted.TLabel", justify="left")
        hint.pack(anchor="w", pady=(8, 0))
        autowrap(hint, card.body)
        return card

    def _build_bot_card(self, parent: tk.Misc) -> Card:
        palette = self.theme.palette
        card = Card(parent, self.theme)
        head = tk.Frame(card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="Bot", style="CardTitle.TLabel").pack(side="left")
        self.bot_pill = Pill(head, self.theme, "PRONTO", "idle")
        self.bot_pill.pack(side="right")
        self.bot_message_var = tk.StringVar(value="Bot fermo.")
        message = ttk.Label(card.body, textvariable=self.bot_message_var, style="CardMuted.TLabel", justify="left")
        message.pack(anchor="w", pady=(2, 8))
        autowrap(message, card.body)

        stats = tk.Frame(card.body, bg=palette.card)
        stats.pack(fill="x")
        for column in range(3):
            stats.columnconfigure(column, weight=1)
        self.stats: dict[str, StatBlock] = {}
        entries = (
            ("fps", "Cattura FPS"),
            ("frames", "Frame"),
            ("session", "Sessione"),
            ("actions", "Azioni"),
            ("breaks", "Pause"),
            ("warnings", "Avvisi"),
        )
        for index, (key, caption) in enumerate(entries):
            block = StatBlock(stats, self.theme, caption)
            block.grid(row=index // 3, column=index % 3, sticky="nsew", pady=(2, 6))
            self.stats[key] = block
        self.bot_warnings_var = tk.StringVar(value="Avvisi anti-ban: nessuno.")
        warning = ttk.Label(
            card.body, textvariable=self.bot_warnings_var, style="CardMuted.TLabel", justify="left"
        )
        warning.pack(anchor="w", pady=(4, 0))
        autowrap(warning, card.body)
        return card

    def _build_hud_card(self, parent: tk.Misc) -> Card:
        palette = self.theme.palette
        card = Card(parent, self.theme)
        head = tk.Frame(card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="Risorse (HUD)", style="CardTitle.TLabel").pack(side="left")
        Badge(head, self.theme, "SOLA LETTURA", "info").pack(side="right")
        self._caption(card.body, "Oro, elisir, dark, gemme e builder letti dallo schermo.")
        stats = tk.Frame(card.body, bg=palette.card)
        stats.pack(fill="x", pady=(6, 0))
        for column in range(3):
            stats.columnconfigure(column, weight=1)
        for index, (key, caption) in enumerate(
            (
                ("gold", "Oro"),
                ("elixir", "Elisir"),
                ("dark", "Dark elisir"),
                ("gems", "Gemme"),
                ("builders", "Builder"),
                ("hud_state", "Stato schermo"),
            )
        ):
            block = StatBlock(stats, self.theme, caption, "—", font_key="h3")
            block.grid(row=index // 3, column=index % 3, sticky="nsew", pady=(2, 4))
            self.hud_stats[key] = block
        row = tk.Frame(card.body, bg=palette.card)
        row.pack(fill="x", pady=(8, 0))
        button = ttk.Button(row, text="Leggi HUD ora", style="Ghost.TButton", command=self.read_hud)
        self._register_action_button("read_hud_card", button)
        self.hud_hint_var = tk.StringVar(value="Nessun input inviato al gioco.")
        hint = ttk.Label(row, textvariable=self.hud_hint_var, style="CardMuted.TLabel")
        hint.pack(side="left", padx=(10, 0))
        return card

    def _build_activity_card(self, parent: tk.Misc) -> Card:
        palette = self.theme.palette
        card = Card(parent, self.theme)
        head = tk.Frame(card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="Attività", style="CardTitle.TLabel").pack(side="left")
        self.task_pill = Pill(head, self.theme, "NESSUNA", "idle")
        self.task_pill.pack(side="right")
        status = ttk.Label(card.body, textvariable=self.task_status_var, style="Card.TLabel", justify="left")
        status.pack(anchor="w", pady=(2, 4))
        autowrap(status, card.body)
        detail = ttk.Label(card.body, textvariable=self.task_detail_var, style="CardMuted.TLabel", justify="left")
        detail.pack(anchor="w")
        autowrap(detail, card.body)
        self.task_progress = ttk.Progressbar(card.body, mode="determinate", maximum=100, value=0)
        self.task_progress.pack(fill="x", pady=(8, 6))
        cancel = ttk.Button(
            card.body, text="Annulla attività", style="Ghost.TButton", command=self.cancel_task
        )
        self._register_action_button("cancel_task", cancel)
        return card

    # ================================================================== pagina Battaglia
    def _build_attack_page(self) -> None:
        _frame, body = self._new_page("attack")
        assert body is not None
        palette = self.theme.palette

        intro = Card(body, self.theme)
        intro.pack(fill="x", pady=(0, 14))
        intro.header(
            "Come funziona un raid",
            "Il bot non tocca gemme, shop o guerre: usa solo l'esercito che hai già.",
        )
        steps = tk.Frame(intro.body, bg=palette.card)
        steps.pack(fill="x", pady=(4, 0))
        for index, (title, text) in enumerate(
            (
                ("1 · Ricerca", "Cerca una base (~1.100 oro) e salta quelle con poco bottino."),
                (
                    "2 · Deploy",
                    "Dragon Clone: tutti i draghi nello stesso punto, cloni sui draghi, eroi subito dopo.",
                ),
                ("3 · Esito", "Legge Victory/Defeat e il bottino, poi torna in home."),
            )
        ):
            block = tk.Frame(steps, bg=palette.card)
            block.pack(side="left", fill="x", expand=True, padx=(0, 12 if index < 2 else 0))
            ttk.Label(block, text=title, style="CardTitle.TLabel").pack(anchor="w")
            caption = ttk.Label(block, text=text, style="CardSub.TLabel", justify="left")
            caption.pack(anchor="w", pady=(2, 0))
            autowrap(caption, block)

        options = Card(body, self.theme)
        options.pack(fill="x", pady=(0, 14))
        options.header(
            "Parametri",
            "Valgono per raid reale e farm. La simulazione usa gli stessi valori ma non spende.",
        )
        grid = tk.Frame(options.body, bg=palette.card)
        grid.pack(fill="x")
        for column in range(4):
            grid.columnconfigure(column, weight=1)
        self.attack_vars = {
            "searches": tk.StringVar(value="2"),
            "spells": tk.StringVar(value="0"),
            "dragons": tk.StringVar(value="13"),
            "clones": tk.StringVar(value=str(self.config.attack.clone_spells)),
            "early": tk.StringVar(value="0"),
            "cycles": tk.StringVar(value="2"),
            "strategy": tk.StringVar(value=self.config.attack.strategy),
            "heroes": tk.StringVar(value="1"),
            "caps": tk.StringVar(value="1"),
        }
        fields = (
            ("searches", "Ricerche max", 1, 20, "Tetto di spesa: ~1.100 oro per ricerca."),
            ("spells", "Spell", 0, 8, "Spell già in esercito da lanciare dopo il deploy."),
            ("dragons", "Draghi", 1, 20, "Numero di draghi da schierare (tutti nello stesso punto)."),
            ("clones", "Cloni", 0, 8, "Clone Spell da lanciare subito sui draghi."),
            ("early", "Early-exit danno %", 0, 100, "0 = disattivato; esce al raggiungimento della soglia."),
            ("cycles", "Cicli farm", 1, 5, "Solo per il farm: quanti raid ripetere."),
        )
        for index, (key, label, low, high, tooltip) in enumerate(fields):
            row = (index // 4) * 2
            column = index % 4
            ttk.Label(grid, text=label, style="Field.TLabel").grid(
                row=row, column=column, sticky="w", padx=(0, 8), pady=(4, 0)
            )
            spin = ttk.Spinbox(
                grid, from_=low, to=high, increment=1, textvariable=self.attack_vars[key], width=7
            )
            spin.grid(row=row + 1, column=column, sticky="w", padx=(0, 8), pady=(2, 0))
            self._tip(spin, tooltip)
            self.attack_vars[key].trace_add("write", lambda *_args: self._update_attack_costs())
        ttk.Label(grid, text="Strategia", style="Field.TLabel").grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=(4, 0)
        )
        strategy = ttk.Combobox(
            grid,
            textvariable=self.attack_vars["strategy"],
            values=("dragon_clone", "dragon_spam"),
            state="readonly",
            width=14,
        )
        strategy.grid(row=3, column=2, sticky="w", padx=(0, 8), pady=(2, 0))
        self._tip(
            strategy,
            "dragon_clone: tutti i draghi nello stesso punto, poi cloni, poi eroi (più veloce). "
            "dragon_spam: vecchia strategia a due passate.",
        )
        checks = tk.Frame(options.body, bg=palette.card)
        checks.pack(fill="x", pady=(10, 0))
        heroes = ttk.Checkbutton(
            checks,
            text="Usa eroi",
            variable=self.attack_vars["heroes"],
            onvalue="1",
            offvalue="0",
            style="Card.TCheckbutton",
        )
        heroes.pack(side="left")
        caps = ttk.Checkbutton(
            checks,
            text="Rispetta cap storage",
            variable=self.attack_vars["caps"],
            onvalue="1",
            offvalue="0",
            style="Card.TCheckbutton",
        )
        caps.pack(side="left", padx=(14, 0))
        self._tip(heroes, "Se un eroe è in upgrade non viene schierato.")
        self._tip(
            caps,
            "Con storage piene il raid viene saltato (o si attacca solo per il dark) per non sprecare risorse.",
        )
        self.attack_cost_var = tk.StringVar(value="")
        cost = tk.Label(
            options.body,
            textvariable=self.attack_cost_var,
            font=self.theme.font("body_bold"),
            fg=palette.warn,
            bg=palette.card,
            anchor="w",
        )
        cost.pack(fill="x", pady=(10, 0))
        self.attack_command_var = tk.StringVar(value="")
        command = ttk.Label(options.body, textvariable=self.attack_command_var, style="Mono.TLabel", justify="left")
        command.pack(anchor="w", pady=(4, 0))
        autowrap(command, options.body)

        actions = self._card_grid(body, columns=2)
        self._build_attack_action_cards(actions)

        notes = Card(body, self.theme)
        notes.pack(fill="x", pady=(14, 0))
        notes.header("Cose da sapere")
        self._bullet_rows(
            notes.body,
            (
                "Ogni ricerca/Next costa ~1.100 oro: «Ricerche max» è il tetto di spesa.",
                "Dragon Clone: draghi tutti nello stesso punto, poi cloni, poi eroi (deploy veloce).",
                "Con storage piene il bot evita raid inutili (o attacca solo per il dark, se configurato).",
                "Non chiudere il gioco durante una battaglia: usa «Annulla attività» o il kill switch.",
                "Esiti e bottino finiscono nel Registro e nei report in out/attack/.",
            ),
        )

        self._update_attack_costs()
        self.page_scrolls["attack"].enable_mousewheel()

    def _build_attack_action_cards(self, parent: tk.Frame) -> None:
        palette = self.theme.palette
        self.attack_cost_vars = {
            "dry": tk.StringVar(value="Nessuna spesa"),
            "scout": tk.StringVar(value=formatting.format_gold_estimate(1)),
            "raid": tk.StringVar(value=""),
            "farm": tk.StringVar(value=""),
        }
        definitions: tuple[dict[str, Any], ...] = (
            {
                "row": 0,
                "column": 0,
                "key": "attack_dry",
                "title": "Simulazione completa",
                "badge": ("GRATIS", "free"),
                "description": "Apre e chiude i menu del raid senza spendere: verifica che tutto risponda.",
                "button": "Avvia simulazione",
                "style": "Accent.TButton",
                "cost_var": "dry",
                "command": self.attack_dry_run,
            },
            {
                "row": 0,
                "column": 1,
                "key": "attack_scout",
                "title": "Scout loot",
                "badge": ("SPENDE", "spend"),
                "description": "Una ricerca (~1.100 oro): legge il bottino della base e torna in home senza deploy.",
                "button": "Scout loot (1 ricerca)",
                "style": "Spend.TButton",
                "cost_var": "scout",
                "command": self.attack_scout,
            },
            {
                "row": 1,
                "column": 0,
                "key": "attack_raid",
                "title": "Raid reale",
                "badge": ("SPENDE", "spend"),
                "description": "Ricerca, skip se il loot è basso, deploy di draghi/eroi/spell, esito e home.",
                "button": "Avvia raid reale",
                "style": "Spend.TButton",
                "cost_var": "raid",
                "command": self.attack_raid,
            },
            {
                "row": 1,
                "column": 1,
                "key": "attack_farm",
                "title": "Farm automatico",
                "badge": ("SPENDE", "spend"),
                "description": "Ripete i raid per N cicli, con tetto di spesa e stop automatico.",
                "button": "Avvia farm",
                "style": "Spend.TButton",
                "cost_var": "farm",
                "command": self.attack_farm,
            },
        )
        for definition in definitions:
            card = Card(parent, self.theme)
            card.grid(
                row=int(definition["row"]),
                column=int(definition["column"]),
                sticky="nsew",
                padx=(0, 7) if definition["column"] == 0 else (7, 0),
                pady=(0, 7) if definition["row"] == 0 else (7, 0),
            )
            head = tk.Frame(card.body, bg=palette.card)
            head.pack(fill="x")
            ttk.Label(head, text=str(definition["title"]), style="CardTitle.TLabel").pack(side="left")
            badge_text, badge_kind = definition["badge"]
            Badge(head, self.theme, str(badge_text), str(badge_kind)).pack(side="right")
            caption = ttk.Label(
                card.body, text=str(definition["description"]), style="CardSub.TLabel", justify="left"
            )
            caption.pack(anchor="w", pady=(2, 2))
            autowrap(caption, card.body)
            cost = tk.Label(
                card.body,
                textvariable=self.attack_cost_vars[str(definition["cost_var"])],
                font=self.theme.font("small_bold"),
                fg=palette.warn,
                bg=palette.card,
                anchor="w",
            )
            cost.pack(fill="x", pady=(6, 6))
            button = ttk.Button(
                card.body,
                text=str(definition["button"]),
                style=str(definition["style"]),
                command=definition["command"],
            )
            self._register_action_button(str(definition["key"]), button, pady=(2, 0))

    # ================================================================== pagina Upgrade
    def _build_upgrade_page(self) -> None:
        _frame, body = self._new_page("upgrade")
        assert body is not None
        palette = self.theme.palette

        intro = Card(body, self.theme)
        intro.pack(fill="x", pady=(0, 14))
        intro.header(
            "Come funziona il planner",
            "Scansiona il menu Build, propone un piano per priorità e lo esegue solo se autorizzi.",
        )
        steps = tk.Frame(intro.body, bg=palette.card)
        steps.pack(fill="x", pady=(4, 0))
        for index, (title, text) in enumerate(
            (
                ("1 · Scansione", "Legge il catalogo «Buildings & Heroes» e l'HUD (sola lettura)."),
                ("2 · Piano", "Mura → difese → esercito → eroi → risorse. Il livello riga è il target."),
                ("3 · Esecuzione", "Premi tu «Esegui»: il bot conferma ogni dialogo e verifica l'HUD."),
            )
        ):
            block = tk.Frame(steps, bg=palette.card)
            block.pack(side="left", fill="x", expand=True, padx=(0, 12 if index < 2 else 0))
            ttk.Label(block, text=title, style="CardTitle.TLabel").pack(anchor="w")
            caption = ttk.Label(block, text=text, style="CardSub.TLabel", justify="left")
            caption.pack(anchor="w", pady=(2, 0))
            autowrap(caption, block)

        analysis = Card(body, self.theme)
        analysis.pack(fill="x", pady=(0, 14))
        analysis.header(
            "1 · Analisi e piano (sola lettura)",
            "Apre e chiude il menu Build. Nessun upgrade, nessuna spesa.",
        )
        analyze = ttk.Button(
            analysis.body, text="Analizza e pianifica", style="Accent.TButton", command=self.upgrade_analyze
        )
        self._register_action_button("upgrade_analyze", analyze, pady=(4, 0))

        budgets = Card(body, self.theme)
        budgets.pack(fill="x", pady=(0, 14))
        budgets.header(
            "2 · Tetti di spesa (opzionali)",
            "Cumulativi per ciclo. Lascia vuoto per nessun tetto: valgono per target e piano.",
        )
        grid = tk.Frame(budgets.body, bg=palette.card)
        grid.pack(fill="x")
        for column in range(4):
            grid.columnconfigure(column, weight=1)
        self.upgrade_vars = {
            "max_gold": tk.StringVar(value=""),
            "max_elixir": tk.StringVar(value=""),
            "max_dark": tk.StringVar(value=""),
            "max_upgrades": tk.StringVar(value=""),
            "target": tk.StringVar(value=""),
        }
        for column, (key, label, tooltip) in enumerate(
            (
                ("max_gold", "Max oro", "Tetto cumulativo di oro speso nel ciclo."),
                ("max_elixir", "Max elisir", "Tetto cumulativo di elisir speso nel ciclo."),
                ("max_dark", "Max dark", "Tetto cumulativo di dark elisir speso nel ciclo."),
                ("max_upgrades", "Max upgrade", "Numero massimo di upgrade nel ciclo."),
            )
        ):
            ttk.Label(grid, text=label, style="Field.TLabel").grid(row=0, column=column, sticky="w", padx=(0, 8))
            entry = ttk.Entry(grid, textvariable=self.upgrade_vars[key], width=14)
            entry.grid(row=1, column=column, sticky="w", padx=(0, 8), pady=(2, 0))
            self._tip(entry, tooltip)

        target_card = Card(body, self.theme)
        target_card.pack(fill="x", pady=(0, 14))
        target_card.header(
            "3 · Esegui un target mirato",
            "Nome della riga catalogo (match fuzzy). Esempi: Gold Mine, Wall, Dark Elixir Storage.",
        )
        target_row = tk.Frame(target_card.body, bg=palette.card)
        target_row.pack(fill="x", pady=(2, 0))
        ttk.Label(target_row, text="Target:", style="Field.TLabel").pack(side="left")
        combobox = ttk.Combobox(
            target_row,
            textvariable=self.upgrade_vars["target"],
            values=list(_TARGET_SUGGESTIONS),
            width=30,
        )
        combobox.pack(side="left", padx=(6, 10))
        exec_target = ttk.Button(
            target_row, text="Esegui target (spende)", style="Spend.TButton", command=self.upgrade_execute_target
        )
        self._register_action_button("upgrade_target", exec_target)
        self._tip(
            combobox,
            "Puoi anche digitare un nome libero: il match è fuzzy e i nomi illeggibili vengono scartati.",
        )

        plan_card = Card(body, self.theme)
        plan_card.pack(fill="x", pady=(0, 14))
        plan_card.header(
            "4 · Esegui il piano completo",
            "Esegue gli upgrade scelti dal planner secondo la priorità della configurazione.",
        )
        plan_row = tk.Frame(plan_card.body, bg=palette.card)
        plan_row.pack(fill="x", pady=(2, 0))
        exec_plan = ttk.Button(
            plan_row, text="Esegui piano (spende)", style="Spend.TButton", command=self.upgrade_execute_plan
        )
        self._register_action_button("upgrade_plan", exec_plan)
        ttk.Label(plan_row, text="Applica i tetti impostati sopra.", style="CardMuted.TLabel").pack(
            side="left", padx=(12, 0)
        )

        status = Card(body, self.theme)
        status.pack(fill="x", pady=(0, 4))
        status.header("Stato e ultimo report")
        status_label = ttk.Label(
            status.body, textvariable=self.task_status_var, style="Card.TLabel", justify="left"
        )
        status_label.pack(anchor="w")
        autowrap(status_label, status.body)
        self.last_report_var = tk.StringVar(value="Nessun report: lancia un'analisi per iniziare.")
        report_label = ttk.Label(
            status.body, textvariable=self.last_report_var, style="Mono.TLabel", justify="left"
        )
        report_label.pack(anchor="w", pady=(4, 0))
        autowrap(report_label, status.body)

        self.page_scrolls["upgrade"].enable_mousewheel()

    # ================================================================== pagina Auto
    def _build_auto_page(self) -> None:
        _frame, body = self._new_page("auto")
        assert body is not None
        palette = self.theme.palette

        intro = Card(body, self.theme)
        intro.pack(fill="x", pady=(0, 14))
        intro.header(
            "Come funziona AUTO",
            "Un unico loop (mai farm e upgrade in parallelo): farm finché i depositi sono "
            "pieni, poi upgrade per priorità; si ferma quando builder e depositi sono pieni.",
        )
        steps = tk.Frame(intro.body, bg=palette.card)
        steps.pack(fill="x", pady=(4, 0))
        for index, (title, text) in enumerate(
            (
                ("1 · Farm", "Raid Dragon Clone ripetuti finché oro, elisir e dark non sono al cap."),
                ("2 · Upgrade", "Piano per priorità (mura→difese→esercito→eroi→risorse) con i tetti di spesa."),
                ("3 · Stop", "Builder tutti occupati + depositi pieni (+ lab/famigli al lavoro, se richiesto)."),
            )
        ):
            block = tk.Frame(steps, bg=palette.card)
            block.pack(side="left", fill="x", expand=True, padx=(0, 12 if index < 2 else 0))
            ttk.Label(block, text=title, style="CardTitle.TLabel").pack(anchor="w")
            caption = ttk.Label(block, text=text, style="CardSub.TLabel", justify="left")
            caption.pack(anchor="w", pady=(2, 0))
            autowrap(caption, block)

        controls = Card(body, self.theme)
        controls.pack(fill="x", pady=(0, 14))
        controls.header(
            "Parametri del loop",
            "Draghi/spell/cloni/strategia si impostano in Battaglia; i tetti di spesa in Upgrade.",
        )
        grid = tk.Frame(controls.body, bg=palette.card)
        grid.pack(fill="x")
        for column in range(3):
            grid.columnconfigure(column, weight=1)
        self.auto_vars = {
            "cycles": tk.StringVar(value=str(self.config.auto.max_cycles)),
            "require_lab_pets": tk.StringVar(
                value="1" if self.config.auto.require_lab_and_pets else "0"
            ),
        }
        ttk.Label(grid, text="Cicli max", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        cycles = ttk.Spinbox(
            grid, from_=1, to=100, increment=1, textvariable=self.auto_vars["cycles"], width=7
        )
        cycles.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._tip(cycles, "Numero massimo di azioni (un raid o un ciclo di upgrade) prima dello stop.")
        ttk.Label(grid, text="Ricerche per raid", style="Field.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        searches = ttk.Spinbox(
            grid, from_=1, to=5, increment=1, textvariable=self.attack_vars["searches"], width=7
        )
        searches.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(2, 0))
        self._tip(searches, "Tetto ricerche per ogni raid di farm (~1.100 oro ciascuna).")
        require = ttk.Checkbutton(
            grid,
            text="Richiedi lab + famigli al lavoro per lo stop (sperimentale)",
            variable=self.auto_vars["require_lab_pets"],
            onvalue="1",
            offvalue="0",
            style="Card.TCheckbutton",
        )
        require.grid(row=0, column=2, rowspan=2, sticky="w", padx=(10, 0))
        self._tip(
            require,
            "Se attivo il bot non si ferma finché non verifica laboratorio e famigli al lavoro; "
            "il rilevamento live non è ancora implementato (in tal caso attende).",
        )
        self._caption(
            controls.body,
            "Deploy del farm: parametri della pagina Battaglia · "
            f"tetti upgrade attuali: {self._budget_summary()}",
        )

        actions = self._card_grid(body, columns=2)
        dry_card = Card(actions, self.theme)
        dry_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 7))
        head = tk.Frame(dry_card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="Simulazione AUTO", style="CardTitle.TLabel").pack(side="left")
        Badge(head, self.theme, "GRATIS", "free").pack(side="right")
        self._caption(dry_card.body, "Legge HUD, decide farm/upgrade e simula un raid: nessuna spesa.")
        self._register_action_button(
            "auto_dry",
            ttk.Button(
                dry_card.body,
                text="Simula il loop",
                style="Accent.TButton",
                command=self.auto_dry_run,
            ),
            pady=(6, 0),
        )
        real_card = Card(actions, self.theme)
        real_card.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 7))
        head = tk.Frame(real_card.body, bg=palette.card)
        head.pack(fill="x")
        ttk.Label(head, text="AUTO reale", style="CardTitle.TLabel").pack(side="left")
        Badge(head, self.theme, "SPENDE", "spend").pack(side="right")
        caption = ttk.Label(
            real_card.body,
            text=(
                "Farm + upgrade automatici: spende oro per le ricerche e risorse per gli upgrade. "
                "Si ferma con builder e depositi pieni (e lab/famigli se richiesto)."
            ),
            style="CardSub.TLabel",
            justify="left",
        )
        caption.pack(anchor="w", pady=(2, 2))
        autowrap(caption, real_card.body)
        self._register_action_button(
            "auto_run",
            ttk.Button(
                real_card.body,
                text="Avvia AUTO (spende)",
                style="Spend.TButton",
                command=self.auto_run,
            ),
            pady=(6, 0),
        )

        status = Card(body, self.theme)
        status.pack(fill="x", pady=(14, 0))
        status.header("Stato AUTO")
        label = ttk.Label(status.body, textvariable=self.task_status_var, style="Card.TLabel", justify="left")
        label.pack(anchor="w")
        autowrap(label, status.body)
        self.auto_detail_var = tk.StringVar(value="Nessuna esecuzione AUTO.")
        detail = ttk.Label(
            status.body, textvariable=self.auto_detail_var, style="CardMuted.TLabel", justify="left"
        )
        detail.pack(anchor="w", pady=(4, 0))
        autowrap(detail, status.body)
        self.page_scrolls["auto"].enable_mousewheel()

    # ================================================================== pagina Registro
    def _build_logs_page(self) -> None:
        frame, _body = self._new_page("logs")
        palette = self.theme.palette
        wrapper = tk.Frame(frame, bg=palette.bg, padx=24, pady=16)
        wrapper.pack(fill="both", expand=True)

        toolbar = tk.Frame(wrapper, bg=palette.bg)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="Filtra:", style="Muted.TLabel").pack(side="left")
        self.log_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(toolbar, textvariable=self.log_filter_var, width=26)
        filter_entry.pack(side="left", padx=(6, 10))
        self.log_filter_var.trace_add("write", lambda *_args: self._apply_log_filter())
        ttk.Label(toolbar, text="Livello:", style="Muted.TLabel").pack(side="left")
        self.log_level_var = tk.StringVar(value="Tutti")
        level_combo = ttk.Combobox(
            toolbar,
            textvariable=self.log_level_var,
            values=list(_LEVEL_FILTERS),
            state="readonly",
            width=17,
        )
        level_combo.pack(side="left", padx=(6, 10))
        level_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_log_filter())
        self.log_follow_var = tk.BooleanVar(value=True)
        follow = ttk.Checkbutton(
            toolbar,
            text="Segui automaticamente",
            variable=self.log_follow_var,
            command=self._toggle_log_follow,
        )
        follow.pack(side="left")
        export = ttk.Button(toolbar, text="Esporta…", style="Ghost.TButton", command=self.export_log)
        export.pack(side="right")
        clear = ttk.Button(toolbar, text="Svuota", style="Ghost.TButton", command=self.clear_log)
        clear.pack(side="right", padx=(0, 6))
        self.buttons["log_clear"] = clear
        self.buttons["log_export"] = export

        self.log_view = LogView(wrapper, self.theme, height=22)
        self.log_view.pack(fill="both", expand=True)

    # ================================================================== pagina Sicurezza
    def _build_safety_page(self) -> None:
        _frame, body = self._new_page("safety")
        assert body is not None
        palette = self.theme.palette

        kill_card = Card(body, self.theme)
        kill_card.pack(fill="x", pady=(0, 14))
        kill_card.header("Ferma tutto, subito", "Ferma il bot e annulla l'attività CLI in corso.")
        kill_row = tk.Frame(kill_card.body, bg=palette.card)
        kill_row.pack(fill="x", pady=(2, 6))
        kill = ttk.Button(
            kill_row, text="■   FERMA TUTTO ORA", style="Kill.TButton", command=self.kill_everything
        )
        kill.pack(side="left")
        self.buttons["kill_all_page"] = kill
        caption = ttk.Label(
            kill_row,
            text=f"Oppure hotkey globale {self.config.gui.hotkey_kill.upper()}.",
            style="CardMuted.TLabel",
        )
        caption.pack(side="left", padx=(14, 0))

        rules = Card(body, self.theme)
        rules.pack(fill="x", pady=(0, 14))
        rules.header("Regole non negoziabili", "Sono cablate nel bot: non si possono disattivare da qui.")
        for text, badge, kind in (
            ("Mai spendere gemme (GemGuard).", "GEMS", "danger"),
            ("Mai acquistare nello shop / IAP (Gold Pass, Hoggy Bank).", "IAP", "danger"),
            ("Mai guerre, CWL o attacchi a clan.", "GUERRE", "danger"),
            ("Dry-run di default: si spende solo con conferma esplicita.", "DRY-RUN", "info"),
            ("Input via messaggi Win32: niente furto di focus/mouse/tastiera.", "ZERO FOCUS", "info"),
            ("Task CLI annullato da kill switch e alla chiusura della finestra.", "KILL SWITCH", "ok"),
        ):
            row = tk.Frame(rules.body, bg=palette.card)
            row.pack(fill="x", pady=2)
            Badge(row, self.theme, badge, str(kind)).pack(side="left")
            label = ttk.Label(row, text=text, style="CardMuted.TLabel", justify="left")
            label.pack(side="left", padx=(10, 0))
            autowrap(label, rules.body)

        config_card = Card(body, self.theme)
        config_card.pack(fill="x", pady=(0, 14))
        config_card.header("Configurazione attiva", "File YAML, backend e limiti di sicurezza in uso.")
        self.config_vars = {}
        config_path = self._display_path(self.config_path) if self.config_path else "predefinita (in memoria)"
        rows = (
            ("config_path", "File config", config_path),
            ("profile", "Profilo", self.config.profile_name),
            ("device", "Device backend", self.config.device.backend),
            ("capture", "Capture backend", self.config.capture.backend),
            ("input", "Input backend", self.config.input.backend),
            ("mode", "Modalità sicurezza", self.config.safety.mode.value),
            ("dry_run", "Upgrade dry-run", "sì" if self.config.upgrade.dry_run else "NO"),
            ("hotkeys", "Hotkey", f"{self.config.gui.hotkey_start_stop.upper()} · "
                                      f"{self.config.gui.hotkey_kill.upper()}"),
            ("limits", "Limiti", self._limits_summary()),
            (
                "walls",
                "Mura",
                f"modalità {self.config.walls.mode.value} · builder riservato: "
                f"{'sì' if self.config.walls.reserve_builder_for_walls else 'no'}",
            ),
        )
        for key, label, value in rows:
            self.config_vars[key] = key_value_row(config_card.body, self.theme, label, value=value)

        danger = Card(body, self.theme)
        danger.pack(fill="x", pady=(0, 4))
        danger.header("Avvertenza")
        text = ttk.Label(
            danger.body,
            text=(
                "L'automazione di Clash of Clans viola i Termini di Servizio di Supercell: esiste il rischio "
                "di ban dell'account. Usa questa GUI solo su un account di cui accetti il rischio e in modo "
                "supervisionato. I dati di gioco (screenshot, dataset, report) restano locali e non vengono "
                "pubblicati."
            ),
            style="CardMuted.TLabel",
            justify="left",
        )
        text.pack(anchor="w")
        autowrap(text, danger.body)
        self.page_scrolls["safety"].enable_mousewheel()

    def _limits_summary(self) -> str:
        safety = self.config.safety
        if safety.max_attacks_per_hour or safety.max_upgrades_per_hour:
            hourly = (
                f"orari: {safety.max_attacks_per_hour or '∞'}/h attacchi, "
                f"{safety.max_upgrades_per_hour or '∞'}/h upgrade"
            )
        else:
            hourly = "orari: illimitati"
        session = (
            f"sessione: {safety.max_session_hours}h" if safety.max_session_hours else "sessione: illimitata"
        )
        return f"{hourly} · {session}"

    # ================================================================== navigazione / log
    def show_page(self, key: str) -> None:
        if key not in self.pages or self.current_page == key:
            return
        if self.current_page is not None:
            self.pages[self.current_page].pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self.current_page = key
        for page_key, nav in self.nav_buttons.items():
            nav.set_active(page_key == key)
        self.page_title_var.set(_PAGE_TITLES[key])
        self.page_sub_var.set(_PAGE_SUBTITLES[key])
        scroll = self.page_scrolls.get(key)
        if scroll is not None:
            scroll.reset_scroll()
        self.root.update_idletasks()
        self._refresh_status()

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F5>", lambda _event: self.toggle_bot())
        self.root.bind("<F1>", lambda _event: self.show_page("safety"))
        self.root.bind("<Control-q>", lambda _event: self.request_close())

    def log(self, message: str, level: str = "info") -> None:
        """Registra un messaggio; chiamabile anche da thread non-tkinter (accodato)."""
        if threading.current_thread() is not self._main_thread:
            self._log_queue.put((level, message))
            return
        self._append_log(level, message)

    def _append_log(self, level: str, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append((level, line))
        log_view = getattr(self, "log_view", None)
        if log_view is not None:
            log_view.append(line, level)
        preview = getattr(self, "preview_log", None)
        if preview is not None:
            preview.append(line, level)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                level, message = self._log_queue.get_nowait()
            except queue.Empty:
                return
            self._append_log(level, message)

    @staticmethod
    def classify_line(line: str) -> str:
        upper = line.upper()
        if "ERRORE" in upper or "TRACEBACK" in upper or "ERROR" in upper or "FALLITO" in upper:
            return "error"
        if "ATTENZIONE" in upper or "WARNING" in upper or "WARN" in upper:
            return "warn"
        if line.startswith("task:") or line.startswith("▶") or line.startswith("✔"):
            return "task"
        if "VICTORY" in upper or "VITTORIA" in upper or "[OK]" in upper:
            return "ok"
        return "info"

    def _apply_log_filter(self) -> None:
        min_level = _LEVEL_FILTERS.get(self.log_level_var.get(), 0)
        self.log_view.set_filter(self.log_filter_var.get(), min_level=min_level)

    def _toggle_log_follow(self) -> None:
        self.log_view.autoscroll = bool(self.log_follow_var.get())

    def export_log(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="Esporta registro",
            defaultextension=".log",
            filetypes=[("File di log", "*.log"), ("Tutti i file", "*.*")],
            initialfile=time.strftime("cocbot-log-%Y%m%d-%H%M%S.log"),
        )
        if not target:
            return
        try:
            path = self.log_view.export(target)
        except OSError as exc:
            messagebox.showerror("Esporta registro", f"Salvataggio non riuscito: {exc}", parent=self.root)
            return
        self.log(f"registro esportato in {path}", "ok")

    def clear_log(self) -> None:
        self.log_view.clear()
        self.logs.clear()
        if getattr(self, "preview_log", None) is not None:
            self.preview_log.clear()
        self.log("registro svuotato", "muted")

    # ================================================================== hotkey / lifecycle
    def start_hotkeys(self) -> None:
        """Registra le hotkey globali; una config non valida non deve far crashare la GUI."""
        self.hotkeys = None
        self.hotkey_errors = []
        if not self.enable_hotkeys:
            self.log("hotkey disabilitate (modalità test/selftest)", "muted")
            return
        try:
            bindings = {
                _HOTKEY_START_STOP: parse_hotkey(self.config.gui.hotkey_start_stop),
                _HOTKEY_KILL: parse_hotkey(self.config.gui.hotkey_kill),
            }
        except ValueError as exc:
            self.hotkey_errors.append(str(exc))
            self.log(f"ATTENZIONE: hotkey non valida in config: {exc}", "warn")
            self.log("la GUI funziona lo stesso: usa i pulsanti e il kill switch della sidebar.", "muted")
            return
        hotkeys = self._hotkey_factory(bindings)
        started = hotkeys.start()
        self.hotkeys = hotkeys
        for error in hotkeys.errors:
            self.hotkey_errors.append(error)
            self.log(f"ATTENZIONE hotkey: {error}", "warn")
        if not started:
            self.hotkey_errors.append("thread hotkey non avviato")
            self.log("ATTENZIONE: thread hotkey non avviato", "warn")
        else:
            self.log(
                f"Hotkey attive: {self.config.gui.hotkey_start_stop.upper()} (start/stop) · "
                f"{self.config.gui.hotkey_kill.upper()} (kill switch)",
                "ok",
            )

    def start(self, *, auto_start: bool = False) -> None:
        self.start_hotkeys()
        self.log("GUI pronta. Le azioni di gioco girano come processi separati.", "ok")
        self.log("Il gioco va aperto manualmente da Google Play Games (finestra non minimizzata).", "muted")
        self._polling = True
        self._after_id = self.root.after(150, self.tick)
        if auto_start:
            self.toggle_bot()

    def tick(self) -> None:
        """Ciclo di aggiornamento UI: consuma eventi e ridisegna lo stato."""
        if self._closed:
            return
        try:
            self._drain_log_queue()
            self._drain_task_events()
            self._drain_hotkeys()
            self._refresh_status()
            self._refresh_task_elapsed()
        finally:
            if self._polling and not self._closed:
                self._after_id = self.root.after(150, self.tick)
            else:
                self._after_id = None

    def _drain_hotkeys(self) -> None:
        if self.hotkeys is None:
            return
        while True:
            try:
                hotkey_id = self.hotkeys.events.get_nowait()
            except queue.Empty:
                return
            if hotkey_id == _HOTKEY_START_STOP:
                self.toggle_bot()
            elif hotkey_id == _HOTKEY_KILL:
                self.log("KILL SWITCH da hotkey: fermo bot e attività", "error")
                self.kill_everything()

    def request_close(self) -> bool:
        """Chiude la GUI annullando prima l'eventuale task (evita processi orfani)."""
        if self._closed:
            return True
        if self.runner.running:
            if not self.confirm(
                "Attività in corso",
                "C'è un'attività del bot in corso (potrebbe essere un raid reale).\n\n"
                "Annullarla e chiudere la finestra?",
            ):
                self.log("chiusura annullata: attività lasciata in corso", "warn")
                return False
            self.runner.cancel()
            self.log("attività annullata prima della chiusura", "warn")
        self._polling = False
        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._after_id)
            self._after_id = None
        try:
            self.controller.stop(join_timeout_s=1.0)
        except TypeError:  # controller di test senza parametro timeout
            self.controller.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        self._closed = True
        with contextlib.suppress(tk.TclError):
            self.root.destroy()
        return True

    def _ask_confirm(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self.root))

    # ================================================================== stato / refresh
    def _refresh_status(self) -> None:
        snapshot = self.controller.snapshot()
        label, kind = _STATE_PILLS.get(snapshot.state, ("PRONTO", "idle"))
        if hasattr(self, "header_pill"):
            self.header_pill.set_state(label, kind)
        if hasattr(self, "bot_pill"):
            self.bot_pill.set_state(label, kind)
            self.bot_message_var.set(snapshot.message or "—")
            self.stats["fps"].set(f"{snapshot.fps:.1f}")
            self.stats["frames"].set(formatting.format_number(snapshot.frames))
            self.stats["session"].set(formatting.format_duration(snapshot.session_s))
            self.stats["actions"].set(formatting.format_number(snapshot.actions))
            self.stats["breaks"].set(formatting.format_number(snapshot.breaks))
            self.stats["warnings"].set(formatting.format_number(len(snapshot.warnings)))
            warnings = "; ".join(snapshot.warnings) if snapshot.warnings else "nessuno"
            self.bot_warnings_var.set(f"Avvisi anti-ban: {warnings}")
            bot_running = snapshot.state in (
                BotState.RUNNING,
                BotState.WAITING_GAME,
                BotState.PAUSED,
            )
            self.buttons["bot_toggle"].configure(text="Ferma bot" if bot_running else "Avvia bot")
            if hasattr(self, "_bot_note"):
                self._bot_note.configure(
                    text="Bot attivo: sta monitorando il gioco."
                    if bot_running
                    else "Bot fermo: nessun input inviato al gioco."
                )
            if snapshot.home_detected and "home" in self.game_values:
                self.game_values["home"].set("Home rilevata")
        if self.game_payload is not None:
            self._refresh_game_footer()
        self._refresh_task_text()
        self._sync_buttons()

    def _refresh_task_text(self) -> None:
        if self.runner.running:
            self.footer_task_var.set(f"Attività: {self.runner.label} in corso")
        else:
            self.footer_task_var.set("Attività: nessuna")
        if self.task_pill is not None and not self.runner.running:
            self.task_pill.set_state("NESSUNA", "idle")

    def _refresh_task_elapsed(self) -> None:
        if self.runner.running and self._task_started_at is not None:
            elapsed = formatting.format_duration(self._clock() - self._task_started_at)
            self.task_detail_var.set(f"Avviata da {elapsed} · {self.runner.label}")

    def _refresh_game_footer(self) -> None:
        payload = self.game_payload
        if payload is None:
            return
        game = payload.get("game")
        if game:
            size = game.get("client_size") or []
            size_text = "×".join(str(part) for part in size) if size else "—"
            aspect = "16:9" if game.get("is_16_9") else "NON 16:9"
            self.footer_game_var.set(f"Gioco: rilevato · {size_text} · {aspect}")
        else:
            self.footer_game_var.set("Gioco: non rilevato")

    def _sync_buttons(self) -> None:
        busy = self._busy()
        for key in _ACTION_BUTTONS:
            button = self.buttons.get(key)
            if button is not None:
                button.configure(state="disabled" if busy else "normal")
        if "bot_toggle" in self.buttons:
            self.buttons["bot_toggle"].configure(state="disabled" if self.runner.running else "normal")
        if "cancel_task" in self.buttons:
            self.buttons["cancel_task"].configure(state="normal" if self.runner.running else "disabled")

    def _busy(self) -> bool:
        if self.runner.running:
            return True
        try:
            # il bot può essere in attesa del gioco o in pausa con il thread ancora attivo:
            # avviare un task CLI in quel momento creerebbe due motori input sullo stesso gioco.
            return self.controller.snapshot().state in (
                BotState.RUNNING,
                BotState.WAITING_GAME,
                BotState.PAUSED,
            )
        except Exception:  # noqa: BLE001 - controller di test
            return False

    # ================================================================== task runner
    def _begin_task(self, action: str, arguments: Sequence[str], label: str) -> bool:
        if self.runner.running:
            self.log("C'è già un'attività in corso: attendi o annullala.", "warn")
            return False
        self._current_action = action
        self._task_output = []
        self._task_started_at = self._clock()
        self.task_status_var.set(f"In corso: {label}…")
        self.task_detail_var.set(self.command_preview(arguments))
        started = self.runner.start(arguments, label)
        if not started:  # pragma: no cover - difensivo
            self._current_action = None
            self.log(f"avvio non riuscito: {label}", "error")
            return False
        return True

    def _drain_task_events(self) -> None:
        while True:
            try:
                event = self.runner.queue.get_nowait()
            except queue.Empty:
                return
            self._on_task_event(event)

    def _on_task_event(self, event: TaskEvent) -> None:
        if event.kind == "started":
            display = event.arguments or event.command[4:]
            self.log(f"▶ {event.label}: {self.command_preview(display)}", "task")
            if self.task_progress is not None:
                self.task_progress.configure(mode="indeterminate")
                self.task_progress.start(14)
            self.task_status_var.set(f"In corso: {event.label}…")
            if self.task_pill is not None:
                self.task_pill.set_state("IN CORSO", "running")
            self._sync_buttons()
            return
        if event.kind == "line":
            self._task_output.append(event.line)
            # probe/hud in --json producono JSON: non inondare il registro (il payload viene
            # riepilogato da _apply_probe_payload/_apply_hud_payload).
            if self._current_action not in ("probe", "hud") or not _looks_like_json_line(event.line):
                self.log(event.line, self.classify_line(event.line))
            return

        if self.task_progress is not None:
            self.task_progress.stop()
            self.task_progress.configure(mode="determinate", value=0)
        if event.kind == "error":
            self.log(f"✖ {event.label}: {event.line}", "error")
            self.task_status_var.set(f"Avvio non riuscito: {event.label}")
        elif event.kind == "cancelled":
            self.log(f"■ {event.label}: annullato", "warn")
            self.task_status_var.set(f"Annullato: {event.label}")
        else:
            ok = event.exit_code == 0
            outcome = "completato" if ok else f"terminato con errori (exit {event.exit_code})"
            self.log(
                f"{'✔' if ok else '✖'} {event.label}: {outcome} in "
                f"{formatting.format_duration(event.duration_s)}",
                "ok" if ok else "error",
            )
            self.task_status_var.set(f"{event.label}: {outcome}")
            self._handle_task_result(event)
            if not ok:
                output = "\n".join(self._task_output).upper()
                # attenzione: i log di RapidOCR contengono "OCR" ma non sono errori.
                if "ERRORE OCR" in output or "OCR NON DISPONIBILE" in output:
                    self.log(
                        "suggerimento: OCR non disponibile → python -m pip install -e .[ocr]",
                        "muted",
                    )
                else:
                    self.log("suggerimento: controlla che il gioco sia aperto e non minimizzato.", "muted")
        self._task_started_at = None
        self._current_action = None
        self._refresh_status()

    def _handle_task_result(self, event: TaskEvent) -> None:
        action = self._current_action
        output = "\n".join(self._task_output)
        if action in ("probe", "hud"):
            payload = formatting.parse_last_json_object(output)
            if payload is None:
                self.log("output non interpretabile (JSON assente): vedi il Registro.", "warn")
                return
            if action == "probe":
                self._apply_probe_payload(payload)
            else:
                self._apply_hud_payload(payload)
        elif action in ("upgrade_analyze", "upgrade_target", "upgrade_plan", "auto_run", "auto_dry"):
            match = _LOG_REPORT_RE.search(output)
            if match:
                path_text = match.group("path").strip()
                self.last_report_var.set(f"Report: {path_text}")
                if action in ("auto_run", "auto_dry") and hasattr(self, "auto_detail_var"):
                    self.auto_detail_var.set(f"Ultimo report AUTO: {path_text}")
            if action in ("auto_run", "auto_dry") and hasattr(self, "auto_detail_var"):
                for line in reversed(output.splitlines()):
                    if line.strip().startswith("stop:"):
                        self.auto_detail_var.set(line.strip())
                        break
        if event.exit_code not in (0, None):
            self.log("l'uscita non è pulita: controlla le righe sopra nel Registro.", "muted")

    def cancel_task(self) -> None:
        if not self.runner.running:
            self.log("nessuna attività da annullare", "muted")
            return
        label = self.runner.label
        if self.runner.cancel():
            self.log(f"annullamento richiesto per: {label}", "warn")
        else:
            self.log(f"impossibile annullare: {label}", "error")

    # ================================================================== dati probe/hud
    def _apply_probe_payload(self, payload: dict[str, Any]) -> None:
        self.game_payload = payload
        game = payload.get("game")
        launcher = payload.get("launcher")
        if game:
            size = game.get("client_size") or []
            size_text = "×".join(str(part) for part in size) if size else "—"
            self.game_pill.set_state("GIOCO RILEVATO", "ok")
            self.game_values["window"].set(size_text)
            self.game_values["process"].set(str(game.get("process", "—")))
            self.game_values["launcher"].set("presente" if launcher else "assente")
            self.game_values["home"].set("premi «Leggi HUD» per lo stato schermo")
            self.game_hint_var.set(
                "Finestra pronta. Il bot può lavorare in background senza rubare il focus."
                if game.get("is_16_9")
                else "ATTENZIONE: la finestra non è 16:9. Metti il gioco in finestra 16:9."
            )
            self.log(
                f"gioco rilevato: {game.get('process', '?')} · finestra {size_text} · "
                f"16:9={game.get('is_16_9')}",
                "ok",
            )
        else:
            self.game_pill.set_state("NON RILEVATO", "warn")
            for key in ("window", "process", "home"):
                self.game_values[key].set("—")
            self.game_values["launcher"].set("presente" if launcher else "assente")
            self.game_hint_var.set(
                "Avvia Clash of Clans da Google Play Games, poi premi «Rileva gioco». "
                "Il client GPGPC può restare aperto senza avviare il gioco."
            )
            self.log("gioco non rilevato: avvialo da Google Play Games.", "warn")
        self._refresh_game_footer()
        self._sync_buttons()

    def _apply_hud_payload(self, payload: dict[str, Any]) -> None:
        self.hud_payload = payload
        hud = payload.get("hud") or {}
        notes = payload.get("notes") or []
        self.hud_stats["gold"].set(formatting.format_number(hud.get("gold")))
        self.hud_stats["elixir"].set(formatting.format_number(hud.get("elixir")))
        self.hud_stats["dark"].set(formatting.format_number(hud.get("dark")))
        self.hud_stats["gems"].set(formatting.format_number(hud.get("gems")), tone="ok")
        self.hud_stats["builders"].set(
            formatting.format_builder(hud.get("builders_available"), hud.get("builders_total"))
        )
        state_label = formatting.game_state_label(payload.get("state"))
        self.hud_stats["hud_state"].set(state_label)
        if "home" in self.game_values:
            self.game_values["home"].set(state_label)
        if hud.get("gems") == 0:
            self.hud_hint_var.set("Gemme a 0: nessuna spesa in gemme.")
        elif notes:
            self.hud_hint_var.set("Nota: " + formatting.truncate("; ".join(str(note) for note in notes), 90))
        else:
            self.hud_hint_var.set("Nessun input inviato al gioco. Gemme mai spese dal bot.")
        self.log(
            f"HUD letto · stato={state_label} · oro={formatting.format_number(hud.get('gold'))} · "
            f"elisir={formatting.format_number(hud.get('elixir'))} · "
            f"dark={formatting.format_number(hud.get('dark'))} · "
            f"gemme={formatting.format_number(hud.get('gems'))}",
            "ok",
        )
        for note in notes:
            self.log(f"nota HUD: {note}", "warn")
        self._sync_buttons()

    # ================================================================== azioni: analisi
    def probe_game(self) -> None:
        self._begin_task("probe", ["probe", "--json"], "Rilevamento gioco")

    def read_hud(self) -> None:
        self._begin_task("hud", self._with_config(["hud", "--json"]), "Lettura HUD")

    @staticmethod
    def _display_path(path: Path | None) -> str:
        """Percorso leggibile: relativo al repo se possibile (config in cwd repo)."""
        if path is None:
            return "—"
        try:
            return path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)

    def _with_config(self, arguments: Sequence[str]) -> list[str]:
        result = list(arguments)
        if self.config_path is not None:
            result.extend(["--config", self._display_path(self.config_path)])
        return result

    # ================================================================== azioni: AUTO
    def _auto_arguments(self, *, allow_spend: bool) -> list[str] | None:
        options = self._attack_options()
        budgets = self._budget_args()
        if budgets is None:
            return None
        cycles = formatting.clamp_int(
            self.auto_vars["cycles"].get(),
            default=int(self.config.auto.max_cycles),
            minimum=1,
            maximum=100,
        )
        arguments = [
            "auto-run",
            "--cycles",
            str(cycles),
            "--max-searches",
            str(int(options["searches"])),
            "--dragons",
            str(int(options["dragons"])),
            "--spells",
            str(int(options["spells"])),
            "--clones",
            str(int(options["clones"])),
            "--strategy",
            str(options["strategy"]),
            "--early-exit-damage",
            str(int(options["early"])),
        ]
        if allow_spend:
            arguments.append("--allow-spend")
        if not options["heroes"]:
            arguments.append("--no-heroes")
        arguments.extend(budgets)
        if self.auto_vars["require_lab_pets"].get() == "1":
            arguments.append("--require-lab-pets")
        return self._with_config(arguments)

    def auto_dry_run(self) -> None:
        arguments = self._auto_arguments(allow_spend=False)
        if arguments is None:
            return
        self._begin_task("auto_dry", arguments, "Simulazione AUTO")

    def auto_run(self) -> None:
        options = self._attack_options()
        lab_note = (
            "Stop: builder tutti occupati + depositi pieni + lab/famigli al lavoro."
            if self.auto_vars["require_lab_pets"].get() == "1"
            else "Stop: builder tutti occupati + depositi pieni."
        )
        message = (
            "Loop AUTO (farm + upgrade).\n\n"
            f"{lab_note}\n"
            f"Cicli max: {self.auto_vars['cycles'].get()} · ricerche per raid: {options['searches']}.\n"
            f"Deploy: {options['dragons']} draghi + {options['clones']} cloni "
            f"(strategia {options['strategy']}).\n"
            f"Tetti upgrade: {self._budget_summary()}.\n\n"
            "Questa azione SPENDE risorse reali. Continuare?"
        )
        if not self._confirm_spend("AUTO farm + upgrade", message):
            return
        arguments = self._auto_arguments(allow_spend=True)
        if arguments is None:
            return
        self._begin_task("auto_run", arguments, "AUTO farm + upgrade")

    # ================================================================== azioni: battaglia
    def _attack_options(self) -> dict[str, int | bool | str]:
        clamp = formatting.clamp_int
        strategy = self.attack_vars["strategy"].get() or "dragon_clone"
        if strategy not in ("dragon_clone", "dragon_spam"):
            strategy = "dragon_clone"
        return {
            "searches": clamp(self.attack_vars["searches"].get(), default=2, minimum=1, maximum=20),
            "spells": clamp(self.attack_vars["spells"].get(), default=0, minimum=0, maximum=8),
            "dragons": clamp(self.attack_vars["dragons"].get(), default=13, minimum=1, maximum=20),
            "clones": clamp(
                self.attack_vars["clones"].get(),
                default=int(self.config.attack.clone_spells),
                minimum=0,
                maximum=8,
            ),
            "early": clamp(self.attack_vars["early"].get(), default=0, minimum=0, maximum=100),
            "cycles": clamp(self.attack_vars["cycles"].get(), default=2, minimum=1, maximum=5),
            "heroes": self.attack_vars["heroes"].get() == "1",
            "caps": self.attack_vars["caps"].get() == "1",
            "strategy": strategy,
        }

    def _update_attack_costs(self) -> None:
        if not getattr(self, "attack_cost_vars", None):
            return
        options = self._attack_options()
        searches = int(options["searches"])
        cycles = int(options["cycles"])
        self.attack_cost_vars["raid"].set(
            f"Spesa massima stimata: {formatting.format_gold_estimate(searches)} "
            f"({searches} ricerche × ~1.100 oro)"
        )
        self.attack_cost_vars["farm"].set(
            f"Spesa massima stimata: {formatting.format_gold_estimate(cycles * searches)} "
            f"({cycles} cicli × {searches} ricerche)"
        )
        if hasattr(self, "attack_cost_var"):
            self.attack_cost_var.set(
                f"Spesa massima stimata: raid {formatting.format_gold_estimate(searches)} · "
                f"farm {formatting.format_gold_estimate(cycles * searches)}"
            )
        if hasattr(self, "attack_command_var"):
            self.attack_command_var.set(self.command_preview(self._raid_arguments()))

    def _raid_arguments(self) -> list[str]:
        options = self._attack_options()
        arguments = [
            "attack-run",
            "--allow-spend",
            "--max-searches",
            str(options["searches"]),
            "--dragons",
            str(options["dragons"]),
            "--spells",
            str(options["spells"]),
            "--clones",
            str(options["clones"]),
            "--strategy",
            str(options["strategy"]),
            "--early-exit-damage",
            str(options["early"]),
        ]
        if not options["heroes"]:
            arguments.append("--no-heroes")
        if not options["caps"]:
            arguments.append("--ignore-caps")
        return self._with_config(arguments)

    def _farm_arguments(self) -> list[str]:
        options = self._attack_options()
        max_gold = formatting.estimate_attack_gold(int(options["cycles"]) * int(options["searches"]))
        arguments = [
            "attack-farm",
            "--allow-spend",
            "--cycles",
            str(options["cycles"]),
            "--max-searches",
            str(options["searches"]),
            "--dragons",
            str(options["dragons"]),
            "--spells",
            str(options["spells"]),
            "--clones",
            str(options["clones"]),
            "--strategy",
            str(options["strategy"]),
            "--early-exit-damage",
            str(options["early"]),
            "--max-gold-spend",
            str(max_gold),
        ]
        if not options["heroes"]:
            arguments.append("--no-heroes")
        if not options["caps"]:
            arguments.append("--ignore-caps")
        return self._with_config(arguments)

    def _confirm_spend(self, title: str, message: str) -> bool:
        if self.confirm(title, message):
            return True
        self.log(f"azione annullata: {title} (nessuna spesa)", "warn")
        return False

    def attack_dry_run(self) -> None:
        if self._begin_task(
            "attack_dry", self._with_config(["attack-run"]), "Simulazione raid"
        ):
            self.log("simulazione: nessuna spesa, i menu vengono aperti e chiusi.", "muted")

    def attack_scout(self) -> None:
        if not self._confirm_spend(
            "Scout loot",
            "Questa azione spende ~1.100 oro per una ricerca base.\n\n"
            "Il bot leggerà il bottino della base e tornerà in home senza schierare truppe.\n\n"
            "Continuare?",
        ):
            return
        self._begin_task("attack_scout", self._with_config(["attack-scout", "--allow-spend"]), "Scout loot")

    def attack_raid(self) -> None:
        options = self._attack_options()
        searches = int(options["searches"])
        deploy = f"{options['dragons']} draghi"
        deploy += " + eroi" if options["heroes"] else ""
        if int(options["clones"]):
            deploy += f" + {options['clones']} cloni"
        if int(options["spells"]):
            deploy += f" + {options['spells']} spell"
        deploy += f" (strategia {options['strategy']})"
        early = int(options["early"])
        extra = f"Early-exit al {early}% di danno.\n" if early else ""
        if not self._confirm_spend(
            "Raid reale",
            "Questa azione spende risorse reali.\n\n"
            f"Ricerche max: {searches} (spesa massima stimata {formatting.format_gold_estimate(searches)}).\n"
            f"Deploy: {deploy}.\n{extra}\n"
            "Continuare?",
        ):
            return
        self._begin_task("attack_raid", self._raid_arguments(), "Raid reale")

    def attack_farm(self) -> None:
        options = self._attack_options()
        cycles = int(options["cycles"])
        searches = int(options["searches"])
        total = formatting.format_gold_estimate(cycles * searches)
        if not self._confirm_spend(
            "Farm automatico",
            "Questa azione spende risorse reali.\n\n"
            f"Cicli: {cycles} · ricerche per ciclo: {searches}.\n"
            f"Deploy: {options['dragons']} draghi + {options['clones']} cloni"
            + (" + eroi" if options["heroes"] else "")
            + f" (strategia {options['strategy']}).\n"
            f"Tetto di spesa: {total} ({cycles} × {searches} × ~1.100 oro).\n\n"
            "Il farm si ferma da solo se un ciclo non porta a un attacco (es. storage piene).\n\n"
            "Continuare?",
        ):
            return
        self._begin_task("attack_farm", self._farm_arguments(), "Farm automatico")

    # ================================================================== azioni: upgrade
    def _budget_args(self) -> list[str] | None:
        """Costruisce i tetti di spesa; ``None`` se un campo contiene un valore non valido."""
        specifications = (
            ("max_gold", "--max-gold", 0),
            ("max_elixir", "--max-elixir", 0),
            ("max_dark", "--max-dark", 0),
            ("max_upgrades", "--max-upgrades", 1),
        )
        arguments: list[str] = []
        for key, flag, minimum in specifications:
            raw = self.upgrade_vars[key].get().strip()
            if not raw:
                continue
            value = formatting.clamp_int(raw, default=-1, minimum=minimum, maximum=100_000_000)
            if value < 0:
                self.log(f"tetto non valido per {flag}: «{raw}» — usa un numero intero", "warn")
                return None
            arguments.extend([flag, str(value)])
        return arguments

    def _budget_summary(self) -> str:
        parts: list[str] = []
        labels = (
            ("max_gold", "oro"),
            ("max_elixir", "elisir"),
            ("max_dark", "dark"),
            ("max_upgrades", "upgrade"),
        )
        for key, name in labels:
            raw = self.upgrade_vars[key].get().strip()
            if raw:
                parts.append(f"{name} max {raw}")
        return " · ".join(parts) if parts else "nessun tetto (illimitato)"

    def upgrade_analyze(self) -> None:
        self._begin_task("upgrade_analyze", self._with_config(["upgrade-run"]), "Analisi piano upgrade")

    def upgrade_execute_target(self) -> None:
        target = self.upgrade_vars["target"].get().strip()
        if not target:
            self.log("indica un target (es. Gold Mine) prima di eseguire.", "warn")
            return
        budgets = self._budget_args()
        if budgets is None:
            return
        if not self._confirm_spend(
            "Esegui upgrade mirato",
            "Questa azione preme CONFIRM e SPENDE risorse reali.\n\n"
            f"Target: {target}\nTetti: {self._budget_summary()}\n\nContinuare?",
        ):
            return
        arguments = self._with_config(["upgrade-run", "--execute", "--only", target, *budgets])
        self._begin_task("upgrade_target", arguments, f"Upgrade «{target}»")

    def upgrade_execute_plan(self) -> None:
        budgets = self._budget_args()
        if budgets is None:
            return
        if not self._confirm_spend(
            "Esegui piano upgrade",
            "Questa azione preme CONFIRM e SPENDE risorse reali per gli upgrade pianificati.\n\n"
            f"Tetti: {self._budget_summary()}\n\nContinuare?",
        ):
            return
        arguments = self._with_config(["upgrade-run", "--execute", *budgets])
        self._begin_task("upgrade_plan", arguments, "Esecuzione piano upgrade")

    # ================================================================== azioni: bot / kill
    def toggle_bot(self) -> None:
        if self.runner.running:
            self.log("attività CLI in corso: annullala prima di avviare il bot.", "warn")
            return
        running = self.controller.toggle()
        self.log("bot avviato" if running else "bot fermato", "task")
        self._refresh_status()

    def kill_everything(self) -> None:
        had_task = self.runner.running
        if had_task:
            self.runner.cancel()
        try:
            self.controller.stop(join_timeout_s=1.0)
        except TypeError:
            self.controller.stop()
        parts = ["bot fermato"]
        if had_task:
            parts.append("attività CLI annullata")
        self.log("KILL SWITCH: " + " e ".join(parts), "error")
        self._refresh_status()

    # ================================================================== audit visivo
    def capture_screenshot(self, path: str | Path) -> Path | None:
        """Salva uno screenshot della finestra (audit visivo in modalità selftest)."""
        target = Path(path)
        try:
            import cv2
            import mss
            import numpy as np
        except ImportError as exc:  # pragma: no cover - dipendenze già richieste
            self.log(f"audit: screenshot non disponibile ({exc})", "warn")
            return None
        try:
            self.root.update_idletasks()
            self.root.update()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            width, height = self.root.winfo_width(), self.root.winfo_height()
            if width < 10 or height < 10:
                return None
            with mss.mss() as sct:
                shot = sct.grab({"left": x, "top": y, "width": width, "height": height})
            image = np.asarray(shot)[:, :, :3]
            target.parent.mkdir(parents=True, exist_ok=True)
            ok, buffer = cv2.imencode(".png", image)
            if not ok:  # pragma: no cover
                return None
            target.write_bytes(buffer.tobytes())
            return target
        except Exception as exc:  # noqa: BLE001 - l'audit non deve rompere la sessione
            self.log(f"audit: screenshot fallito ({exc!r})", "warn")
            return None


def run_gui(
    config: Config | None = None,
    *,
    selftest_s: float | None = None,
    auto_start: bool = False,
    screenshots_dir: str | Path | None = None,
    hidden: bool = False,
    config_path: Path | None = None,
) -> int:
    """Avvia la finestra. Con ``selftest_s`` si chiude da sola dopo N secondi."""
    config = config or load_default_config()
    if screenshots_dir is not None and selftest_s is None:
        selftest_s = 5.0
    root = tk.Tk()
    app = CocbotApp(root, config, config_path=config_path, enable_hotkeys=not hidden)
    if hidden:
        root.withdraw()
    app.start(auto_start=auto_start)

    hotkey_ok = app.hotkeys is not None and not app.hotkey_errors
    if selftest_s is not None:
        print(
            f"selftest GUI: hotkey registrate={hotkey_ok} errori={app.hotkey_errors} · "
            f"pagine={len(app.pages)} · config={app.config_path}"
        )

    if screenshots_dir is not None and not hidden:
        directory = Path(screenshots_dir)
        keys = list(app.pages)

        def capture_next(index: int = 0) -> None:
            if app._closed:  # noqa: SLF001 - audit interno
                return
            if index >= len(keys):
                app.request_close()
                return
            key = keys[index]
            app.show_page(key)
            root.update_idletasks()
            root.update()
            target = app.capture_screenshot(directory / f"{index + 1:02d}-{key}.png")
            if target is not None:
                print(f"screenshot: {target}")
            root.after(450, lambda: capture_next(index + 1))

        root.after(800, capture_next)

    if selftest_s is not None:
        delay = int(max(0.2, float(selftest_s)) * 1000)
        root.after(delay, app.request_close)
    try:
        root.mainloop()
    except KeyboardInterrupt:  # pragma: no cover
        app.request_close()
    return 0


__all__ = ["CocbotApp", "find_config_path", "load_default_config", "run_gui"]
