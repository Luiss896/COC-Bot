"""Tema visivo della GUI (tkinter/ttk): palette, font e stili condivisi.

La GUI usa un tema scuro ad alto contrasto (default, coerente con ``gui.theme: dark`` in
config) e un tema chiaro alternativo. Qui vivono solo colori/font/stili: la logica e i
widget sono in :mod:`cocbot.gui.widgets` e :mod:`cocbot.gui.app`.
"""
from __future__ import annotations

import contextlib
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Literal

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True)
class Palette:
    """Palette di un tema (hex RGB)."""

    name: str
    bg: str
    surface: str
    surface_alt: str
    card: str
    card_alt: str
    card_hover: str
    border: str
    border_strong: str
    text: str
    text_soft: str
    muted: str
    subtle: str
    accent: str
    accent_hover: str
    accent_pressed: str
    on_accent: str
    ok: str
    ok_soft: str
    warn: str
    warn_soft: str
    danger: str
    danger_soft: str
    info: str
    info_soft: str
    input_bg: str
    input_border: str
    log_bg: str
    selection: str
    disabled_bg: str
    disabled_fg: str


DARK = Palette(
    name="dark",
    bg="#0b111c",
    surface="#111a29",
    surface_alt="#0d1523",
    card="#16202f",
    card_alt="#1c2839",
    card_hover="#223147",
    border="#26344a",
    border_strong="#35486a",
    text="#e9effb",
    text_soft="#c4cfe2",
    muted="#93a1ba",
    subtle="#64748e",
    accent="#4d8dff",
    accent_hover="#6ea3ff",
    accent_pressed="#3a72d9",
    on_accent="#0b111c",
    ok="#3ecf8e",
    ok_soft="#10301f",
    warn="#f2b13c",
    warn_soft="#332610",
    danger="#f2637a",
    danger_soft="#38141d",
    info="#57c7e8",
    info_soft="#0e2c36",
    input_bg="#0c1422",
    input_border="#2b3b55",
    log_bg="#080d16",
    selection="#24477e",
    disabled_bg="#1d283a",
    disabled_fg="#5f6d86",
)

LIGHT = Palette(
    name="light",
    bg="#eef2f8",
    surface="#ffffff",
    surface_alt="#f6f9fd",
    card="#ffffff",
    card_alt="#f2f6fc",
    card_hover="#e9f0fa",
    border="#d5dfec",
    border_strong="#b6c5da",
    text="#16202f",
    text_soft="#2b3a4e",
    muted="#596a82",
    subtle="#7b8ca3",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_pressed="#1e40af",
    on_accent="#ffffff",
    ok="#0c6f46",
    ok_soft="#e4f7ee",
    warn="#8f590e",
    warn_soft="#fdf2dd",
    danger="#b82840",
    danger_soft="#fde9ed",
    info="#0b688c",
    info_soft="#e6f6fb",
    input_bg="#ffffff",
    input_border="#c6d3e4",
    log_bg="#f8fafc",
    selection="#cfe0ff",
    disabled_bg="#e5eaf2",
    disabled_fg="#93a0b3",
)

# Font: tuple compatibili con tkinter (family, size) o (family, size, style).
FONTS: dict[str, tuple] = {
    "display": ("Segoe UI", 23, "bold"),
    "title": ("Segoe UI", 17, "bold"),
    "h2": ("Segoe UI", 12, "bold"),
    "h3": ("Segoe UI", 10, "bold"),
    "body": ("Segoe UI", 10),
    "body_bold": ("Segoe UI", 10, "bold"),
    "small": ("Segoe UI", 9),
    "small_bold": ("Segoe UI", 9, "bold"),
    "mono": ("Consolas", 9),
    "mono_bold": ("Consolas", 9, "bold"),
    "nav": ("Segoe UI", 10, "bold"),
}

_SPACING = {"xs": 4, "sm": 8, "md": 14, "lg": 20, "xl": 28}


@dataclass(frozen=True)
class Theme:
    """Tema applicato: palette + font (gli stili ttk sono registrati da :func:`apply_theme`)."""

    palette: Palette
    fonts: dict[str, tuple]
    spacing: dict[str, int]

    @property
    def name(self) -> str:
        return self.palette.name

    def font(self, key: str) -> tuple:
        return self.fonts[key]

    def color(self, key: str) -> str:
        return getattr(self.palette, key)


def resolve_theme_name(value: str | None) -> ThemeName:
    """Normalizza il valore di config ``gui.theme`` (default scuro)."""
    return "light" if str(value or "").strip().lower() == "light" else "dark"


def _mix(hex_a: str, hex_b: str, ratio: float) -> str:
    """Mischia due colori hex (ratio 0 = a, 1 = b) preservando il formato #rrggbb."""
    a = hex_a.lstrip("#")
    b = hex_b.lstrip("#")
    channels = []
    for index in (0, 2, 4):
        av = int(a[index : index + 2], 16)
        bv = int(b[index : index + 2], 16)
        channels.append(round(av + (bv - av) * max(0.0, min(1.0, ratio))))
    return "#" + "".join(f"{value:02x}" for value in channels)


def apply_theme(root: tk.Misc, name: str = "dark") -> Theme:
    """Registra gli stili ttk del tema e ritorna :class:`Theme`.

    Va chiamata una sola volta, subito dopo la creazione della root, prima di creare i widget.
    """
    palette = LIGHT if resolve_theme_name(name) == "light" else DARK
    fonts = FONTS
    style = ttk.Style(root)
    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")
    if isinstance(root, (tk.Tk, tk.Toplevel)):
        root.configure(bg=palette.bg)

    background = palette.bg
    card_hover = _mix(palette.card, palette.text, 0.07)
    input_hover = _mix(palette.input_bg, palette.text, 0.05)

    style.configure(
        ".",
        background=background,
        foreground=palette.text,
        fieldbackground=palette.input_bg,
        fieldforeground=palette.text,
        bordercolor=palette.border,
        focuscolor=palette.accent,
        troughcolor=palette.surface_alt,
        font=fonts["body"],
        selectbackground=palette.selection,
        selectforeground=palette.text,
        insertcolor=palette.text,
    )
    style.configure("TFrame", background=background)
    style.configure("Surface.TFrame", background=palette.surface)
    style.configure("Card.TFrame", background=palette.card)
    style.configure("CardAlt.TFrame", background=palette.card_alt)
    style.configure("Log.TFrame", background=palette.log_bg)

    # ---- label
    style.configure("TLabel", background=background, foreground=palette.text)
    style.configure("PageTitle.TLabel", font=fonts["title"], foreground=palette.text, background=background)
    style.configure("PageSub.TLabel", font=fonts["small"], foreground=palette.muted, background=background)
    style.configure("Card.TLabel", background=palette.card)
    style.configure("CardTitle.TLabel", font=fonts["h2"], background=palette.card, foreground=palette.text)
    style.configure("CardSub.TLabel", font=fonts["small"], background=palette.card, foreground=palette.muted)
    style.configure("Section.TLabel", font=fonts["h3"], background=background, foreground=palette.text_soft)
    style.configure("Muted.TLabel", foreground=palette.muted, background=background)
    style.configure("CardMuted.TLabel", foreground=palette.muted, background=palette.card)
    style.configure("Small.TLabel", font=fonts["small"], foreground=palette.muted, background=background)
    style.configure("CardSmall.TLabel", font=fonts["small"], foreground=palette.muted, background=palette.card)
    style.configure("Field.TLabel", font=fonts["small"], foreground=palette.muted, background=palette.card)
    style.configure("Value.TLabel", font=fonts["h2"], foreground=palette.text, background=palette.card)
    style.configure("ValueSmall.TLabel", font=fonts["body"], foreground=palette.text_soft, background=palette.card)
    style.configure("Mono.TLabel", font=fonts["mono"], foreground=palette.muted, background=palette.card)
    style.configure("MonoBg.TLabel", font=fonts["mono"], foreground=palette.muted, background=background)
    style.configure("Accent.TLabel", foreground=palette.accent, background=background)
    style.configure("CardAccent.TLabel", foreground=palette.accent, background=palette.card)
    style.configure("Warn.TLabel", foreground=palette.warn, background=palette.card)
    style.configure("Hero.TLabel", font=fonts["h2"], foreground=palette.text, background=palette.surface)
    style.configure("HeroSub.TLabel", font=fonts["small"], foreground=palette.muted, background=palette.surface)
    style.configure("SidebarTitle.TLabel", font=fonts["title"], foreground=palette.text, background=palette.surface)
    style.configure("SidebarSub.TLabel", font=fonts["small"], foreground=palette.muted, background=palette.surface)
    style.configure("Status.TLabel", font=fonts["small_bold"], background=palette.card_alt, foreground=palette.text)

    # ---- bottoni
    style.configure(
        "TButton",
        font=fonts["body_bold"],
        padding=(12, 7),
        background=palette.card_alt,
        foreground=palette.text,
        bordercolor=palette.border,
        lightcolor=palette.card_alt,
        darkcolor=palette.card_alt,
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("pressed", palette.card_hover), ("active", card_hover), ("disabled", palette.disabled_bg)],
        foreground=[("disabled", palette.disabled_fg)],
        bordercolor=[("disabled", palette.border)],
    )
    style.configure(
        "Accent.TButton",
        background=palette.accent,
        foreground=palette.on_accent,
        bordercolor=palette.accent,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", palette.accent_pressed),
            ("active", palette.accent_hover),
            ("disabled", palette.disabled_bg),
        ],
        foreground=[("disabled", palette.disabled_fg)],
        bordercolor=[("disabled", palette.border)],
    )
    spend_hover = _mix(palette.warn_soft, palette.warn, 0.18)
    spend_pressed = _mix(palette.warn_soft, palette.warn, 0.28)
    danger_hover = _mix(palette.danger_soft, palette.danger, 0.2)
    danger_pressed = _mix(palette.danger_soft, palette.danger, 0.3)
    kill_hover = _mix(palette.danger, "#ffffff", 0.18)
    kill_pressed = _mix(palette.danger, "#000000", 0.25)
    ghost_hover = _mix(palette.card_alt, palette.text, 0.10)

    style.configure(
        "Spend.TButton",
        background=palette.warn_soft,
        foreground=palette.warn,
        bordercolor=palette.warn,
        lightcolor=palette.warn_soft,
        darkcolor=palette.warn_soft,
    )
    style.map(
        "Spend.TButton",
        background=[
            ("pressed", spend_pressed),
            ("active", spend_hover),
            ("disabled", palette.disabled_bg),
        ],
        foreground=[("disabled", palette.disabled_fg)],
        bordercolor=[("disabled", palette.border)],
    )
    style.configure(
        "Danger.TButton",
        background=palette.danger_soft,
        foreground=palette.danger,
        bordercolor=palette.danger,
        lightcolor=palette.danger_soft,
        darkcolor=palette.danger_soft,
    )
    style.map(
        "Danger.TButton",
        background=[
            ("pressed", danger_pressed),
            ("active", danger_hover),
            ("disabled", palette.disabled_bg),
        ],
        foreground=[("disabled", palette.disabled_fg)],
        bordercolor=[("disabled", palette.border)],
    )
    style.configure(
        "Kill.TButton",
        background=palette.danger,
        foreground="#ffffff",
        bordercolor=palette.danger,
        lightcolor=palette.danger,
        darkcolor=palette.danger,
        font=fonts["body_bold"],
        padding=(14, 9),
    )
    style.map(
        "Kill.TButton",
        background=[
            ("pressed", kill_pressed),
            ("active", kill_hover),
            ("disabled", palette.disabled_bg),
        ],
        foreground=[("disabled", palette.disabled_fg)],
    )
    style.configure(
        "Ghost.TButton",
        background=palette.card_alt,
        foreground=palette.text_soft,
        bordercolor=palette.border_strong,
        lightcolor=palette.card_alt,
        darkcolor=palette.card_alt,
    )
    style.map(
        "Ghost.TButton",
        background=[
            ("pressed", palette.card_hover),
            ("active", ghost_hover),
            ("disabled", palette.disabled_bg),
        ],
        foreground=[("disabled", palette.disabled_fg)],
        bordercolor=[("active", palette.accent), ("disabled", palette.border)],
    )
    style.configure(
        "Link.TButton",
        background=palette.card,
        foreground=palette.accent,
        bordercolor=palette.card,
        lightcolor=palette.card,
        darkcolor=palette.card,
        padding=(4, 2),
        font=fonts["small_bold"],
    )
    style.map(
        "Link.TButton",
        background=[("pressed", palette.card), ("active", card_hover)],
        foreground=[("active", palette.accent_hover), ("disabled", palette.disabled_fg)],
    )

    # ---- input
    for widget_style in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget_style,
            fieldbackground=palette.input_bg,
            foreground=palette.text,
            background=palette.card_alt,
            bordercolor=palette.input_border,
            lightcolor=palette.input_bg,
            darkcolor=palette.input_bg,
            insertcolor=palette.text,
            arrowcolor=palette.muted,
            padding=(6, 4),
        )
    style.map(
        "TEntry",
        bordercolor=[("focus", palette.accent)],
        fieldbackground=[("disabled", palette.disabled_bg)],
        foreground=[("disabled", palette.disabled_fg)],
    )
    style.map(
        "TSpinbox",
        bordercolor=[("focus", palette.accent)],
        fieldbackground=[("disabled", palette.disabled_bg)],
        foreground=[("disabled", palette.disabled_fg)],
        arrowcolor=[("disabled", palette.disabled_fg)],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.input_bg), ("disabled", palette.disabled_bg)],
        foreground=[("readonly", palette.text), ("disabled", palette.disabled_fg)],
        selectbackground=[("readonly", palette.input_bg)],
        selectforeground=[("readonly", palette.text)],
        bordercolor=[("focus", palette.accent)],
        arrowcolor=[("disabled", palette.disabled_fg)],
    )
    root.option_add("*TCombobox*Listbox.background", palette.input_bg)
    root.option_add("*TCombobox*Listbox.foreground", palette.text)
    root.option_add("*TCombobox*Listbox.selectBackground", palette.selection)
    root.option_add("*TCombobox*Listbox.selectForeground", palette.text)

    style.configure(
        "TCheckbutton",
        background=palette.card,
        foreground=palette.text_soft,
        indicatorbackground=palette.input_bg,
        indicatorforeground=palette.accent,
        bordercolor=palette.input_border,
        focuscolor=palette.card,
        padding=(2, 3),
    )
    style.map(
        "TCheckbutton",
        background=[("active", palette.card)],
        foreground=[("disabled", palette.disabled_fg)],
        indicatorbackground=[("selected", palette.accent), ("active", input_hover), ("disabled", palette.disabled_bg)],
        indicatorforeground=[("selected", palette.on_accent)],
    )
    style.configure(
        "Card.TCheckbutton",
        background=palette.card,
        foreground=palette.text_soft,
        focuscolor=palette.card,
    )
    style.map("Card.TCheckbutton", background=[("active", palette.card)])

    # ---- progressbar / scrollbar / separator
    style.configure(
        "TProgressbar",
        background=palette.accent,
        troughcolor=palette.surface_alt,
        bordercolor=palette.surface_alt,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        thickness=6,
    )
    style.configure(
        "TScrollbar",
        background=palette.border,
        troughcolor=palette.surface_alt,
        bordercolor=palette.surface_alt,
        arrowcolor=palette.muted,
        lightcolor=palette.border,
        darkcolor=palette.border,
    )
    style.map(
        "TScrollbar",
        background=[("active", palette.border_strong)],
        arrowcolor=[("active", palette.text_soft)],
    )
    style.configure("TSeparator", background=palette.border)

    return Theme(palette=palette, fonts=dict(fonts), spacing=dict(_SPACING))


def relative_luminance(color: str) -> float:
    """Luminanza relativa WCAG di un colore ``#rrggbb`` (0 = nero, 1 = bianco)."""

    def channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    raw = color.lstrip("#")
    r, g, b = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """Rapporto di contrasto WCAG tra due colori (>= 4.5 = testo normale leggibile)."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


__all__ = [
    "DARK",
    "FONTS",
    "LIGHT",
    "Palette",
    "Theme",
    "ThemeName",
    "apply_theme",
    "contrast_ratio",
    "relative_luminance",
    "resolve_theme_name",
]
