"""Test del tema GUI: risoluzione nome, contrasto WCAG e stili ttk applicati."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from cocbot.gui.theme import (
    DARK,
    LIGHT,
    Palette,
    apply_theme,
    contrast_ratio,
    relative_luminance,
    resolve_theme_name,
)


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except tk.TclError:
        return False
    return True


@pytest.mark.parametrize(
    "value,expected",
    (
        ("dark", "dark"),
        ("DARK", "dark"),
        (None, "dark"),
        ("boh", "dark"),
        ("light", "light"),
        ("Light", "light"),
    ),
)
def test_resolve_theme_name(value: str | None, expected: str) -> None:
    assert resolve_theme_name(value) == expected


@pytest.mark.parametrize("palette", (DARK, LIGHT), ids=("dark", "light"))
def test_text_contrast_wcag(palette: Palette) -> None:
    assert contrast_ratio(palette.text, palette.bg) >= 7.0
    assert contrast_ratio(palette.text, palette.card) >= 7.0
    assert contrast_ratio(palette.text_soft, palette.card) >= 4.5
    assert contrast_ratio(palette.muted, palette.card) >= 4.5
    assert contrast_ratio(palette.muted, palette.surface) >= 4.5
    assert contrast_ratio(palette.on_accent, palette.accent) >= 4.5
    assert contrast_ratio(palette.accent, palette.card) >= 4.5


@pytest.mark.parametrize("palette", (DARK, LIGHT), ids=("dark", "light"))
def test_badge_contrast_wcag(palette: Palette) -> None:
    pairs = (
        (palette.warn, palette.warn_soft),
        (palette.danger, palette.danger_soft),
        (palette.ok, palette.ok_soft),
        (palette.info, palette.info_soft),
    )
    for foreground, background in pairs:
        assert contrast_ratio(foreground, background) >= 4.5, (foreground, background)


def test_relative_luminance_extremes() -> None:
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert relative_luminance("#ffffff") == pytest.approx(1.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)


@pytest.mark.skipif(not _tk_available(), reason="tkinter/display non disponibile")
def test_apply_theme_registers_styles() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        theme = apply_theme(root, "dark")
        assert theme.name == "dark"
        assert theme.palette is DARK
        assert root.cget("bg") == DARK.bg
        style = ttk.Style(root)
        assert style.lookup("TFrame", "background") == DARK.bg
        assert style.lookup("Card.TFrame", "background") == DARK.card
        assert style.lookup("Accent.TButton", "background") == DARK.accent
        assert style.lookup("Kill.TButton", "background") == DARK.danger
    finally:
        root.destroy()
