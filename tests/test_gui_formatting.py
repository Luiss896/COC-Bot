"""Test delle funzioni pure di formattazione usate dalla GUI (nessun tkinter)."""
from __future__ import annotations

from cocbot.gui import formatting


def test_format_number_italian_thousands() -> None:
    assert formatting.format_number(9_670_273) == "9.670.273"
    assert formatting.format_number(0) == "0"
    assert formatting.format_number(None) == "—"
    assert formatting.format_number("non-un-numero") == "—"


def test_format_builder() -> None:
    assert formatting.format_builder(1, 6) == "1/6"
    assert formatting.format_builder(None, 6) == "—"
    assert formatting.format_builder(1, None) == "—"


def test_format_duration() -> None:
    assert formatting.format_duration(0) == "0s"
    assert formatting.format_duration(75) == "1m 15s"
    assert formatting.format_duration(3725) == "1h 02m"
    assert formatting.format_duration(None) == "—"


def test_gold_estimates() -> None:
    assert formatting.estimate_attack_gold(2) == 2200
    assert formatting.estimate_attack_gold("3") == 3300
    assert formatting.estimate_attack_gold(None) == 0
    assert formatting.format_gold_estimate(2) == "~2.200 oro"
    assert formatting.format_farm_estimate(2, 2) == "~4.400 oro"
    assert formatting.format_farm_estimate(3, 1) == "~3.300 oro"


def test_clamp_int() -> None:
    assert formatting.clamp_int("3", default=2, minimum=1, maximum=20) == 3
    assert formatting.clamp_int(" 12 ", default=2, minimum=1, maximum=5) == 5
    assert formatting.clamp_int("2.200", default=0, minimum=0, maximum=10**9) == 2200
    assert formatting.clamp_int("", default=7, minimum=1, maximum=9) == 7
    assert formatting.clamp_int("abc", default=4, minimum=1, maximum=9) == 4
    assert formatting.clamp_int("-5", default=4, minimum=1, maximum=9) == 1


def test_parse_last_json_object() -> None:
    output = (
        "finestra: crosvm.exe\n"
        "{\"game\": {\"process\": \"crosvm.exe\"}, \"launcher\": null}\n"
        "nota finale\n"
    )
    payload = formatting.parse_last_json_object(output)
    assert payload is not None
    assert payload["game"]["process"] == "crosvm.exe"
    assert formatting.parse_last_json_object("nessun json qui") is None
    assert formatting.parse_last_json_object("{\"rotto\": }") is None


def test_game_state_label() -> None:
    assert formatting.game_state_label("home") == "Home"
    assert formatting.game_state_label("battle") == "Battaglia in corso"

    class FakeState:
        value = "network_error"

    assert formatting.game_state_label(FakeState()) == "Errore di rete"
    assert formatting.game_state_label(None) == "Sconosciuto"


def test_truncate() -> None:
    assert formatting.truncate("ciao", 10) == "ciao"
    truncated = formatting.truncate("a" * 50, 20)
    assert len(truncated) == 20
    assert truncated.endswith("…")
