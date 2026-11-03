"""Test dei parser di testo di gioco: importi, tempi, livelli, nomi con quantita'."""
from __future__ import annotations

import pytest

from cocbot.vision import textparse


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 500 000", 2_500_000),
        ("2500 000", 2_500_000),  # OCR perde uno spazio
        ("195-103", 195_103),  # OCR confonde lo spazio con un trattino
        ("44 000", 44_000),
        ("6 250", 6_250),
        ("1 925", 1_925),
        ("0", 0),
        (None, None),
        ("", None),
        ("2H 30M", None),  # durata, non importo
        ("1d", None),
        ("New", None),
        ("4 000 + 400", None),  # espressione, non importo
        ("1234567890", None),  # implausibile (>9 cifre)
    ],
)
def test_parse_amount(text: str | None, expected: int | None) -> None:
    assert textparse.parse_amount(text) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1d", 86_400),
        ("18H", 64_800),
        ("2H 30M", 9_000),
        ("30m 0s", 1_800),
        ("15M 0S", 900),
        ("1d 18h", 151_200),
        ("4h 48m", 17_280),
        ("0s", 0),
        ("2H 30M + 10%", None),
        ("Upgrade", None),
        ("1d 18h 3x", None),
        ("", None),
    ],
)
def test_parse_duration(text: str, expected: int | None) -> None:
    assert textparse.parse_duration(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("53", 53), ("8", 8), ("(15)", 15), ("0", 0), ("abc", None), ("", None), ("1234", None)],
)
def test_parse_level(text: str, expected: int | None) -> None:
    assert textparse.parse_level(text) == expected


@pytest.mark.parametrize(
    ("text", "expected_name", "expected_count"),
    [
        ("Wall x 284", "wall", 284),
        ("Elixir Collector x 7", "elixir collector", 7),
        ("Elixir Collector x7", "elixir collector", 7),
        ("Clan Castle", "clan castle", 1),
        ("  Dark Elixir Drill  x  3 ", "dark elixir drill", 3),
        ("30M Os", "30m os", 1),
    ],
)
def test_split_name_count(text: str, expected_name: str, expected_count: int) -> None:
    name, count = textparse.split_name_count(text)
    assert name == expected_name
    assert count == expected_count


def test_section_headers_and_helpers() -> None:
    assert textparse.is_section_header("Suggested upgrades")
    assert textparse.is_section_header("  other UPGRADES ")
    assert not textparse.is_section_header("Clan Castle")
    assert textparse.is_time_text("2h 30m")
    assert not textparse.is_time_text("2 500 000")
    assert textparse.is_amount_text("2 500 000")
    assert not textparse.is_amount_text("New")
