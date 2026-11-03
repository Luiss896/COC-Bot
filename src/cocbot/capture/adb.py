"""Backend ADB (opzionale): Google Play Games Developer Emulator o emulatori Android.

Non funziona sul consumer GPGPC (che non espone ADB): serve il Developer Emulator ufficiale
(device serial tipico ``localhost:6520``) oppure un emulatore Android con ADB abilitato.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from cocbot.core.types import CaptureHealth, Frame, Rect, Viewport

DEFAULT_PACKAGE = "com.supercell.clashofclans"
DEFAULT_SERIAL = "localhost:6520"
DEFAULT_DEV_EMULATOR_ADB = (
    r"C:\Program Files\Google\Play Games Developer Emulator\current\emulator\adb.exe"
)

_SERIAL_PATTERNS = (
    re.compile(r"^[A-Za-z0-9._-]+:\d{1,5}$"),  # host:port
    re.compile(r"^emulator-\d+$"),
    re.compile(r"^[A-Za-z0-9]{6,}$"),
)


class AdbError(RuntimeError):
    pass


def validate_serial(serial: str) -> str:
    """Valida il seriale del device per evitare command injection."""
    serial = (serial or "").strip()
    if not serial or any(p.match(serial) for p in _SERIAL_PATTERNS):
        return serial
    raise ValueError(f"serial ADB non valido: {serial!r}")


def find_adb(explicit: str | Path | None = None) -> str | None:
    """Trova adb.exe: path esplicito -> PATH -> Developer Emulator -> platform-tools locale."""
    candidates: list[str] = []
    if explicit:
        candidates.append(str(explicit))
    if os.environ.get("ADB_PATH"):
        candidates.append(os.environ["ADB_PATH"])
    which = shutil.which("adb")
    if which:
        candidates.append(which)
    candidates.append(DEFAULT_DEV_EMULATOR_ADB)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(str(Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


@dataclass
class AdbDevice:
    """Implementazione ScreenSource + InputSink via ADB."""

    adb_path: str
    serial: str = DEFAULT_SERIAL
    package: str = DEFAULT_PACKAGE
    timeout_s: float = 30.0
    connect_timeout_s: float = 60.0
    _connected: bool = field(default=False, init=False)
    _frames: int = field(default=0, init=False)
    _black_frames: int = field(default=0, init=False)
    _last_frame_time: float | None = field(default=None, init=False)
    _fps: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.serial = validate_serial(self.serial)

    # ------------------------------------------------------------------ adb
    def _run(self, *args: str, binary: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
        command = [self.adb_path]
        if self.serial:
            command += ["-s", self.serial]
        command += list(args)
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=not binary,
                timeout=timeout or self.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise AdbError(f"adb non trovato: {self.adb_path}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"timeout adb: {' '.join(command[1:])}") from exc

    def server(self, *args: str) -> subprocess.CompletedProcess:
        command = [self.adb_path, *args]
        return subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_s, check=False)

    def devices(self) -> list[tuple[str, str]]:
        result = self.server("devices")
        devices: list[tuple[str, str]] = []
        for line in (result.stdout or "").strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
        return devices

    def connect(self) -> bool:
        if ":" in self.serial:
            self.server("connect", self.serial)
        self._connected = self.is_online()
        return self._connected

    def is_online(self) -> bool:
        return any(serial == self.serial and status == "device" for serial, status in self.devices())

    def ensure_online(self) -> None:
        if self.is_online():
            self._connected = True
            return
        deadline = time.monotonic() + self.connect_timeout_s
        while time.monotonic() < deadline:
            if self.connect():
                return
            time.sleep(3)
        raise AdbError(f"device ADB non online: {self.serial}")

    def screen_size(self) -> tuple[int, int]:
        result = self._run("shell", "wm", "size")
        match = re.search(r"(\d+)x(\d+)", result.stdout or "")
        if not match:
            raise AdbError(f"impossibile leggere wm size: {result.stdout!r} {result.stderr!r}")
        return int(match.group(1)), int(match.group(2))

    def launch_app(self) -> None:
        self._run(
            "shell",
            "monkey",
            "-p",
            self.package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )

    # ------------------------------------------------------------------ ScreenSource
    def grab(self) -> Frame:
        import cv2
        import numpy as np

        result = self._run("exec-out", "screencap", "-p", binary=True)
        if result.returncode != 0 or not result.stdout:
            raise AdbError(f"screencap fallito: {result.stderr!r}")
        image = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AdbError("screencap: immagine non decodificabile")
        timestamp = time.monotonic()
        if self._last_frame_time is not None:
            delta = max(1e-6, timestamp - self._last_frame_time)
            self._fps = 0.85 * self._fps + 0.15 * (1.0 / delta) if self._fps else 1.0 / delta
        self._last_frame_time = timestamp
        if float(image.mean()) < 8.0:
            self._black_frames += 1
        self._frames += 1
        height, width = image.shape[:2]
        return Frame(
            image=image,
            timestamp=timestamp,
            viewport=Viewport(Rect(0, 0, width, height)),
            source="adb",
            stale=False,
            metadata={"device": self.serial},
        )

    def viewport(self) -> Viewport:
        width, height = self.screen_size()
        return Viewport(Rect(0, 0, width, height))

    def health(self) -> CaptureHealth:
        return CaptureHealth(
            fps=round(self._fps, 2),
            frames=self._frames,
            black_frames=self._black_frames,
            stale_frames=0,
        )

    def close(self) -> None:
        self._connected = False

    # ------------------------------------------------------------------ InputSink
    def tap_canonical(self, point, *, jitter: bool = True) -> None:  # type: ignore[no-untyped-def]
        from cocbot.capture.window import fit_viewport

        width, height = self.screen_size()
        scale, off_x, off_y = fit_viewport(width, height)
        x = off_x + round(point.x * scale)
        y = off_y + round(point.y * scale)
        self._run("shell", "input", "tap", str(x), str(y))

    def tap_pixels(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def key(self, vk: int) -> None:
        self._run("shell", "input", "keyevent", str(vk))

    def focus_game(self) -> bool:
        # ADB non richiede focus: input iniettato nel device.
        return True
