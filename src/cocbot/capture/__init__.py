"""Backend di cattura/input.

- consumer GPGPC: ``window`` + ``SendInputSink`` + ``MssScreenSource`` (fallback) / WGC (in arrivo);
- Developer Emulator: ``AdbDevice``.
"""
from cocbot.capture import win32  # importato per primo: evita import circolare con window
from cocbot.capture.adb import AdbDevice, AdbError, find_adb, validate_serial
from cocbot.capture.input_sendinput import SendInputSink
from cocbot.capture.screen_mss import MssScreenSource, save_frame_png
from cocbot.capture.window import (
    GameWindow,
    canonical_to_client,
    find_game_window,
    find_game_windows,
    find_launcher_window,
    find_windows,
    fit_viewport,
    masked_title,
    wait_for_game_window,
)

__all__ = [
    "AdbDevice",
    "AdbError",
    "GameWindow",
    "MssScreenSource",
    "SendInputSink",
    "canonical_to_client",
    "find_adb",
    "find_game_window",
    "find_game_windows",
    "find_launcher_window",
    "find_windows",
    "fit_viewport",
    "masked_title",
    "save_frame_png",
    "validate_serial",
    "wait_for_game_window",
    "win32",
]
