"""Widget riutilizzabili per la GUI (tkinter/ttk) sul tema di :mod:`cocbot.gui.theme`.

Contiene card, pill di stato, badge, tooltip, log colorato e contenitore scrollabile.
La logica applicativa sta in :mod:`cocbot.gui.app`.
"""
from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from cocbot.gui.theme import Theme

TEXT_LEVELS = ("info", "muted", "warn", "error", "ok", "task", "cmd")

_LEVEL_ORDER = {"info": 0, "muted": 0, "task": 0, "cmd": 0, "ok": 1, "warn": 2, "error": 3}


class Card(tk.Frame):
    """Riquadro con bordo sottile e padding interno (sfondo tema)."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        padx: int = 16,
        pady: int = 14,
        bg_key: str = "card",
        border_key: str = "border",
    ) -> None:
        super().__init__(parent, bg=theme.color(border_key), bd=0, highlightthickness=0)
        self.theme = theme
        self.bg_key = bg_key
        self.body = tk.Frame(self, bg=theme.color(bg_key))
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self._inner = tk.Frame(self.body, bg=theme.color(bg_key), padx=padx, pady=pady)
        self._inner.pack(fill="both", expand=True)
        self.body = self._inner

    def header(self, title: str, subtitle: str | None = None) -> tk.Frame:
        """Aggiunge un'intestazione alla card; ritorna il frame del corpo sottostante."""
        header = tk.Frame(self.body, bg=self.theme.color(self.bg_key))
        header.pack(fill="x", anchor="w")
        ttk.Label(header, text=title, style="CardTitle.TLabel").pack(anchor="w")
        if subtitle:
            caption = ttk.Label(header, text=subtitle, style="CardSub.TLabel")
            caption.pack(anchor="w", pady=(2, 0))
            autowrap(caption, header)
        spacer = tk.Frame(self.body, bg=self.theme.color(self.bg_key), height=10)
        spacer.pack(fill="x")
        return self.body

    def divider(self, pady: int = 10) -> None:
        line = tk.Frame(self.body, bg=self.theme.color("border"), height=1)
        line.pack(fill="x", pady=pady)


class Pill(tk.Label):
    """Etichetta di stato colorata ("● PRONTO", "● IN ESECUZIONE", ...)."""

    _KINDS = {
        "idle": ("muted", "card_alt"),
        "ok": ("ok", "ok_soft"),
        "running": ("accent", "card_alt"),
        "warn": ("warn", "warn_soft"),
        "error": ("danger", "danger_soft"),
        "info": ("info", "info_soft"),
    }

    def __init__(self, parent: tk.Misc, theme: Theme, text: str = "", kind: str = "idle", **kwargs: object) -> None:
        super().__init__(
            parent,
            text="",
            font=theme.font("small_bold"),
            bd=0,
            padx=10,
            pady=3,
            **kwargs,  # type: ignore[arg-type]
        )
        self.theme = theme
        self.set_state(text, kind)

    def set_state(self, text: str, kind: str = "idle") -> None:
        foreground, background = self._KINDS.get(kind, self._KINDS["idle"])
        self.configure(
            text=f"●  {text}" if text else "",
            foreground=self.theme.color(foreground),
            background=self.theme.color(background),
        )


class Badge(tk.Label):
    """Piccola etichetta informativa ("GRATIS", "SPENDE", "SOLA LETTURA")."""

    _KINDS = {
        "free": ("ok", "ok_soft"),
        "spend": ("warn", "warn_soft"),
        "danger": ("danger", "danger_soft"),
        "info": ("info", "info_soft"),
        "muted": ("muted", "card_alt"),
    }

    def __init__(self, parent: tk.Misc, theme: Theme, text: str, kind: str = "info") -> None:
        foreground, background = self._KINDS.get(kind, self._KINDS["info"])
        super().__init__(
            parent,
            text=text,
            font=theme.font("small_bold"),
            fg=theme.color(foreground),
            bg=theme.color(background),
            bd=0,
            padx=7,
            pady=2,
        )


class StatBlock(tk.Frame):
    """Valore numerico con didascalia (per le card di stato)."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        caption: str,
        value: str = "—",
        *,
        bg_key: str = "card",
        font_key: str = "h2",
    ) -> None:
        super().__init__(parent, bg=theme.color(bg_key))
        self.theme = theme
        self.value_var = tk.StringVar(value=value)
        label_style = "Value.TLabel" if font_key == "h2" else "ValueSmall.TLabel"
        self.value_label = ttk.Label(
            self,
            textvariable=self.value_var,
            style=label_style,
            font=theme.font(font_key),
            foreground=theme.color("text"),
        )
        self.value_label.pack(anchor="w")
        ttk.Label(self, text=caption, style="CardSmall.TLabel").pack(anchor="w", pady=(1, 0))

    def set(self, value: str, *, tone: str | None = None) -> None:
        self.value_var.set(value)
        color = self.theme.color(tone) if tone else self.theme.color("text")
        self.value_label.configure(foreground=color)


class NavButton(tk.Frame):
    """Voce della barra laterale: barra indicatrice + pulsante a tutta larghezza."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        text: str,
        command: Callable[[], None],
        *,
        icon: str = "",
    ) -> None:
        super().__init__(parent, bg=theme.color("surface"))
        self.theme = theme
        self._active = False
        self._hover = False
        self.indicator = tk.Frame(self, width=3, bg=theme.color("surface"))
        self.indicator.pack(side="left", fill="y")
        self.button = tk.Button(
            self,
            text=f"{icon}  {text}" if icon else f"   {text}",
            command=command,
            anchor="w",
            font=theme.font("nav"),
            bg=theme.color("surface"),
            fg=theme.color("muted"),
            activebackground=theme.color("card_alt"),
            activeforeground=theme.color("text"),
            relief="flat",
            bd=0,
            padx=14,
            pady=10,
            cursor="hand2",
            highlightthickness=0,
        )
        self.button.pack(side="left", fill="x", expand=True)
        self.button.bind("<Enter>", lambda _event: self._set_hover(True), add="+")
        self.button.bind("<Leave>", lambda _event: self._set_hover(False), add="+")

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._paint()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    def _paint(self) -> None:
        surface = self.theme.color("surface")
        if self._active:
            background = self.theme.color("card_alt")
            foreground = self.theme.color("text")
            indicator = self.theme.color("accent")
        elif self._hover:
            background = self.theme.color("card")
            foreground = self.theme.color("text_soft")
            indicator = self.theme.color("border")
        else:
            background = surface
            foreground = self.theme.color("muted")
            indicator = surface
        self.configure(bg=indicator)
        self.indicator.configure(bg=indicator)
        self.button.configure(bg=background, fg=foreground, activebackground=self.theme.color("card_alt"))


class LogView(tk.Frame):
    """Area di log con tag colorati, filtro e esportazione."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        *,
        height: int = 12,
        with_scrollbar: bool = True,
        max_lines: int | None = None,
    ) -> None:
        super().__init__(parent, bg=theme.color("log_bg"))
        self.theme = theme
        self._lines: list[tuple[str, str]] = []
        self._filter_text = ""
        self._min_level = 0
        self._max_lines = max_lines
        self.autoscroll = True
        self.text = tk.Text(
            self,
            height=height,
            wrap="word",
            state="disabled",
            bg=theme.color("log_bg"),
            fg=theme.color("text_soft"),
            insertbackground=theme.color("text"),
            selectbackground=theme.color("selection"),
            selectforeground=theme.color("text"),
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=theme.font("mono"),
            highlightthickness=0,
        )
        if with_scrollbar:
            scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
            scrollbar.pack(side="right", fill="y")
            self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        self._configure_tags()
        self.text.configure(state="disabled")

    def _configure_tags(self) -> None:
        palette = self.theme.palette
        self.text.tag_configure("info", foreground=palette.text_soft)
        self.text.tag_configure("muted", foreground=palette.muted)
        self.text.tag_configure("warn", foreground=palette.warn)
        self.text.tag_configure("error", foreground=palette.danger)
        self.text.tag_configure("ok", foreground=palette.ok)
        self.text.tag_configure("task", foreground=palette.accent)
        self.text.tag_configure("cmd", foreground=palette.info)

    # ------------------------------------------------------------------ contenuto
    @property
    def lines(self) -> list[tuple[str, str]]:
        return list(self._lines)

    def append(self, message: str, level: str = "info") -> None:
        """Aggiunge una riga (memorizzata anche se il filtro la nasconde)."""
        level = level if level in TEXT_LEVELS else "info"
        self._lines.append((level, message))
        if self._passes_filter(level, message):
            self._insert(level, message)
        self._trim()

    def _trim(self) -> None:
        if self._max_lines is None or len(self._lines) <= self._max_lines:
            return
        excess = len(self._lines) - self._max_lines
        del self._lines[:excess]
        self._rerender()

    def _passes_filter(self, level: str, message: str) -> bool:
        if _LEVEL_ORDER.get(level, 0) < self._min_level:
            return False
        needle = self._filter_text.strip().lower()
        return not needle or needle in message.lower()

    def _insert(self, level: str, message: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", message + "\n", level)
        self.text.configure(state="disabled")
        if self.autoscroll:
            self.text.see("end")

    def set_filter(self, needle: str = "", *, min_level: int = 0) -> None:
        """Filtra le righe già presenti (testo libero e livello minimo)."""
        self._filter_text = needle
        self._min_level = max(0, min(3, int(min_level)))
        self._rerender()

    def _rerender(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        for level, message in self._lines:
            if self._passes_filter(level, message):
                self._insert(level, message)
        if self.autoscroll:
            self.text.see("end")

    def clear(self) -> None:
        self._lines.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def full_text(self) -> str:
        return "\n".join(message for _level, message in self._lines)

    def export(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.full_text() + "\n", encoding="utf-8")
        return target


class ScrollableFrame(tk.Frame):
    """Contenitore verticalmente scrollabile (le pagine possono superare l'altezza finestra)."""

    def __init__(self, parent: tk.Misc, theme: Theme, *, bg_key: str = "bg") -> None:
        super().__init__(parent, bg=theme.color(bg_key))
        self.theme = theme
        self._canvas = tk.Canvas(
            self,
            bg=theme.color(bg_key),
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self.scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body = tk.Frame(self._canvas, bg=theme.color(bg_key))
        self._window = self._canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_body_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)

    def scroll(self, event: tk.Event) -> str:
        delta = int(getattr(event, "delta", 0))
        if delta:
            self._canvas.yview_scroll(int(-delta / 120), "units")
        return "break"

    def enable_mousewheel(self) -> None:
        """Collega la rotella a tutti i figli tranne le aree di testo (che scrollano da sole)."""

        def walk(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if isinstance(child, (tk.Text, tk.Canvas, tk.Listbox, ttk.Combobox)):
                    continue
                child.bind("<MouseWheel>", self.scroll, add="+")
                walk(child)

        walk(self.body)

    def reset_scroll(self) -> None:
        self._canvas.yview_moveto(0)


class Tooltip:
    """Suggerimento al passaggio del mouse (utile per spiegare le opzioni)."""

    def __init__(self, widget: tk.Misc, theme: Theme, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.theme = theme
        self.text = text
        self.delay_ms = max(0, int(delay_ms))
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._hide()
        self._after_id = self.widget.after(self.delay_ms, self._show)  # type: ignore[assignment]

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:  # pragma: no cover - widget distrutto
            return
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.configure(bg=self.theme.color("border"))
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            bg=self.theme.color("card_alt"),
            fg=self.theme.color("text"),
            font=self.theme.font("small"),
            padx=10,
            pady=6,
            wraplength=360,
        )
        label.pack(padx=1, pady=1)
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._window is not None:
            with contextlib.suppress(tk.TclError):
                self._window.destroy()
            self._window = None


# ---------------------------------------------------------------------- helper
def autowrap(label: ttk.Label, container: tk.Misc, *, padding: int = 8, minimum: int = 200) -> None:
    """Fa andare a capo il testo della label con la larghezza del contenitore."""
    state = {"width": 0}

    def resize(event: tk.Event) -> None:
        width = max(minimum, int(getattr(event, "width", 0)) - padding)
        if width != state["width"]:
            state["width"] = width
            label.configure(wraplength=width)

    container.bind("<Configure>", resize, add="+")


def divider(parent: tk.Misc, theme: Theme, *, pady: int = 0) -> tk.Frame:
    line = tk.Frame(parent, bg=theme.color("border"), height=1)
    line.pack(fill="x", pady=pady)
    return line


def spacer(parent: tk.Misc, theme: Theme, height: int = 10, *, bg_key: str = "bg") -> tk.Frame:
    frame = tk.Frame(parent, bg=theme.color(bg_key), height=height)
    frame.pack(fill="x")
    return frame


def key_value_row(
    parent: tk.Misc,
    theme: Theme,
    key: str,
    *,
    value: str = "—",
    bg_key: str = "card",
) -> tk.StringVar:
    """Riga "chiave: valore" con valore aggiornabile; ritorna la StringVar del valore."""
    row = tk.Frame(parent, bg=theme.color(bg_key))
    row.pack(fill="x", pady=1)
    ttk.Label(row, text=key, style="CardSmall.TLabel", foreground=theme.color("muted")).pack(side="left")
    variable = tk.StringVar(value=value)
    ttk.Label(
        row,
        textvariable=variable,
        style="ValueSmall.TLabel",
        foreground=theme.color("text"),
    ).pack(side="right")
    return variable


def kv_grid(
    parent: tk.Misc,
    theme: Theme,
    rows: int,
    columns: int = 2,
    *,
    bg_key: str = "card",
) -> tk.Frame:
    frame = tk.Frame(parent, bg=theme.color(bg_key))
    frame.pack(fill="x")
    for index in range(columns):
        frame.columnconfigure(index, weight=1, uniform="kv")
    return frame


__all__ = [
    "Badge",
    "Card",
    "LogView",
    "NavButton",
    "Pill",
    "ScrollableFrame",
    "StatBlock",
    "Tooltip",
    "autowrap",
    "divider",
    "key_value_row",
    "kv_grid",
    "spacer",
]
