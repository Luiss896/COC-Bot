"""CLI di sviluppo: probe | capture | config-check | adb-check."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _print_windows(window_module, win32, windows) -> None:
    header = f"{'PROCESS':<14}{'CLASS':<28}{'TITLE':<44}{'CLIENT':<12}{'DPI':<6}{'ASPECT':<8}"
    print(header)
    print("-" * len(header))
    for info in windows:
        title = window_module.masked_title(info.title)[:42]
        print(
            f"{info.process:<14}{info.class_name[:26]:<28}{title:<44}"
            f"{info.client_width}x{info.client_height:<7}{info.dpi:<6}"
            f"{info.client_width / max(1, info.client_height):<8.3f}"
        )


def cmd_probe(args: argparse.Namespace) -> int:
    from cocbot.capture import win32, window

    win32.set_dpi_awareness()
    windows = [w for w in window.find_windows() if w.process.lower() in {"crosvm.exe", "client.exe"}]
    game_info = window.find_game_window()
    launcher_info = window.find_launcher_window()

    if args.json:
        payload = {
            "game": None if game_info is None else {
                "process": game_info.process,
                "title_masked": window.masked_title(game_info.title),
                "client_size": list(game_info.client_size),
                "dpi": game_info.dpi,
                "is_16_9": abs(game_info.aspect - 16 / 9) <= 0.02,
            },
            "launcher": None if launcher_info is None else {
                "process": launcher_info.process,
                "title": window.masked_title(launcher_info.title),
                "client_size": list(launcher_info.client_size),
                "dpi": launcher_info.dpi,
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        print("== cocbot probe (sola lettura) ==")
        if windows:
            _print_windows(window, win32, windows)
        else:
            print("Nessuna finestra GPGPC trovata: apri Google Play Games e avvia il gioco.")
        if game_info is not None:
            game = window.GameWindow(game_info)
            print()
            print(f"Gioco rilevato: {game}")
            print(f"  16:9: {game.is_16_9}  |  in foreground: {game.is_foreground}  |  DPI: {game.dpi}")
            print(
                "  client origin (screen): "
                f"{game.client_origin()}  |  esempio punto canonico (1920,1080) -> screen "
                f"{game.canonical_to_screen((1920, 1080))}"
            )
        else:
            print()
            print("Gioco NON in esecuzione: avvia 'Gioca' dal client Google Play Games.")
            if launcher_info is not None:
                print("Client/launcher GPGPC trovato (finestra store).")
            else:
                print("Client GPGPC non trovato: avvia Google Play Games.")

    info = game_info or launcher_info
    if info is not None and not args.json:
        aspect = info.client_width / max(1, info.client_height)
        if abs(aspect - 16 / 9) > 0.02:
            print(
                f"\nATTENZIONE: aspect {aspect:.3f} non 16:9. Il gioco dovrebbe essere in finestra 16:9 "
                "(o usare il letterbox: le coordinate canoniche vengono adattate automaticamente)."
            )
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from cocbot.capture import win32, window
    from cocbot.capture.screen_mss import MssScreenSource, save_frame_png

    win32.set_dpi_awareness()
    info = window.find_game_window()
    if info is None and args.include_launcher:
        info = window.find_launcher_window()
        if info is not None:
            print("Gioco non in esecuzione: catturo il client/launcher (store).")
    if info is None:
        print("ERRORE: nessuna finestra da catturare. Avvia il gioco (o usa --include-launcher).")
        return 2

    game_window = window.GameWindow(info)
    if not game_window.is_foreground and not args.include_launcher:
        print(
            "ATTENZIONE: la finestra del gioco non è in primo piano. "
            "La cattura 'mss' richiede che sia visibile/non coperta: portala in foreground."
        )

    previous_foreground: int | None = None
    if args.focus:
        previous_foreground = win32.foreground_window()
        if game_window.focus():
            print("Finestra portata in primo piano per la cattura.")
        else:
            print("ATTENZIONE: focus non riuscito (la cattura potrebbe essere coperta).")
        time.sleep(0.4)

    source = MssScreenSource(game_window, target_fps=args.fps)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    saved = 0
    frame_index = 0
    print(f"Cattura da {game_window} per {args.seconds:.1f}s a ~{args.fps} FPS -> {out_dir}")
    try:
        while time.monotonic() - started < args.seconds:
            frame = source.grab()
            if frame_index % args.save_every == 0 and saved < args.max_frames:
                path = out_dir / f"frame-{saved:04d}.png"
                save_frame_png(frame, path)
                saved += 1
            frame_index += 1
            time.sleep(max(0.0, 1.0 / args.fps - 0.001))
    except KeyboardInterrupt:
        print("Interrotto dall'utente.")
    finally:
        health = source.health()
        source.close()
        if previous_foreground:
            win32.focus_window(previous_foreground)

    print(
        f"\nFrame acquisiti: {health.frames}  |  FPS: {health.fps}  |  "
        f"frame neri: {health.black_frames}  |  frame identici: {health.stale_frames}"
    )
    print(f"PNG salvati: {saved} in {out_dir.resolve()}")
    if health.black_frames > 0:
        print("ATTENZIONE: frame neri rilevati (finestra minimizzata/coperta o problema di cattura).")
    return 0


def cmd_config_check(args: argparse.Namespace) -> int:
    from cocbot.config import load_config

    path = Path(args.path)
    if not path.is_file():
        print(f"ERRORE: config non trovata: {path}")
        return 2
    try:
        config = load_config(path)
    except Exception as exc:  # noqa: BLE001 - CLI: mostrare l'errore di validazione
        print(f"ERRORE di validazione config: {exc}")
        return 1
    print(f"Config valida: {path}")
    print(f"  profile: {config.profile_name}  |  device: {config.device.backend}  |  capture: {config.capture.backend}")
    print(f"  ui: {config.ui.profile}  |  locale: {config.ui.locale}  |  canonical: {config.ui.canonical_size}")
    print(f"  safety: mode={config.safety.mode.value}  never_spend_gems={config.safety.never_spend_gems}")
    print(f"  walls: mode={config.walls.mode.value}  check_before_upgrades={config.walls.check_before_upgrades}")
    print(f"  attack: strategy={config.attack.strategy}  preset={config.upgrade.preset}")
    return 0


def cmd_adb_check(args: argparse.Namespace) -> int:
    from cocbot.capture.adb import AdbDevice, AdbError, find_adb

    adb = find_adb(args.adb)
    if adb is None:
        print("adb non trovato.")
        print("Sul consumer GPGPC ADB non è disponibile.")
        print(
            "Per il backend ADB installa il Google Play Games Developer Emulator:\n"
            "  https://developer.android.com/games/playgames/emulator\n"
            "Poi adb.exe sarà in: <install>\\current\\emulator\\adb.exe (device serial localhost:6520)."
        )
        return 2
    print(f"adb: {adb}")
    device = AdbDevice(adb_path=adb, serial=args.serial)
    print(f"serial: {device.serial}  |  package: {device.package}")
    try:
        print(f"device online: {device.is_online()}")
        print(f"devices: {device.devices()}")
        if device.is_online():
            print(f"screen size: {device.screen_size()}")
    except AdbError as exc:
        print(f"ERRORE ADB: {exc}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocbot",
        description="cocbot - automazione visiva Clash of Clans (uso didattico; viola i ToS Supercell).",
    )
    parser.add_argument("--version", action="version", version="cocbot 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="elenca finestre GPGPC e stato del gioco (sola lettura)")
    probe.add_argument("--json", action="store_true", help="output JSON")
    probe.set_defaults(func=cmd_probe)

    capture = sub.add_parser("capture", help="cattura frame dal gioco/launcher (test cattura)")
    capture.add_argument("--seconds", type=float, default=4.0)
    capture.add_argument("--fps", type=int, default=10)
    capture.add_argument("--out", default="out/captures")
    capture.add_argument("--max-frames", type=int, default=20)
    capture.add_argument("--save-every", type=int, default=1)
    capture.add_argument("--include-launcher", action="store_true", help="se il gioco è chiuso usa il client")
    capture.add_argument(
        "--focus",
        action="store_true",
        help="porta la finestra in primo piano durante la cattura e ripristina dopo",
    )
    capture.set_defaults(func=cmd_capture)

    config_check = sub.add_parser("config-check", help="valida la configurazione YAML")
    config_check.add_argument("--path", default="config/config.example.yaml")
    config_check.set_defaults(func=cmd_config_check)

    adb_check = sub.add_parser("adb-check", help="verifica disponibilità backend ADB")
    adb_check.add_argument("--adb", default=None)
    adb_check.add_argument("--serial", default="localhost:6520")
    adb_check.set_defaults(func=cmd_adb_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:  # output UTF-8 (accenti italiani) su console Windows
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
