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
    previous_foreground: int | None = None

    if args.backend == "wgc":
        from cocbot.capture.screen_wgc import WgcScreenSource, save_frame_png

        if game_window.is_foreground:
            print("Finestra in primo piano (non serve: WGC cattura anche se coperta).")
        else:
            print("Finestra non in primo piano: cattura WGC 'coperta' (serve solo non minimizzata).")
        source = WgcScreenSource(game_window, target_fps=args.fps)
    else:
        from cocbot.capture.screen_mss import MssScreenSource, save_frame_png

        if not game_window.is_foreground and not args.include_launcher:
            print(
                "ATTENZIONE: la finestra del gioco non è in primo piano. "
                "La cattura 'mss' richiede che sia visibile/non coperta: portala in foreground."
            )
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
    print(f"Cattura {args.backend.upper()} da {game_window} per {args.seconds:.1f}s -> {out_dir}")
    try:
        while time.monotonic() - started < args.seconds:
            try:
                frame = source.grab()
            except RuntimeError as exc:
                print(f"ERRORE cattura: {exc}")
                break
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
        f"frame neri: {health.black_frames}  |  frame stale: {health.stale_frames}"
    )
    print(f"PNG salvati: {saved} in {out_dir.resolve()}")
    if health.black_frames > 0:
        print("ATTENZIONE: frame neri rilevati (finestra minimizzata/coperta o problema di cattura).")
    if health.last_error:
        print(f"Ultimo errore cattura: {health.last_error}")
    return 0


def cmd_input_test(args: argparse.Namespace) -> int:
    from cocbot.capture import win32, window
    from cocbot.capture.input_winmsg import WinMsgSink
    from cocbot.core.types import GamePoint

    win32.set_dpi_awareness()
    info = window.find_game_window()
    if info is None:
        print("ERRORE: gioco non in esecuzione. Avvialo manualmente da GPGPC.")
        return 2
    game_window = window.GameWindow(info)
    sink = WinMsgSink(game_window, jitter_ms=(0, 0))
    point = GamePoint(args.x, args.y)
    client = window.canonical_to_client((point.x, point.y), game_window.client_width, game_window.client_height)
    fg_before = win32.foreground_window()
    cursor_before = win32.cursor_pos()
    print(f"finestra: {game_window}")
    print(f"tap canonico {point} -> client {client} (backend winmsg, nessun focus)")
    print(f"foreground prima: 0x{fg_before:X}  |  cursore prima: {cursor_before}")
    if not args.execute:
        print("dry-run: nessun click inviato (usa --execute per inviarlo).")
        return 0
    sink.tap_canonical(point)
    time.sleep(0.8)
    fg_after = win32.foreground_window()
    cursor_after = win32.cursor_pos()
    print(f"foreground dopo: 0x{fg_after:X}  |  cursore dopo: {cursor_after}")
    print(f"interferenza: focus cambiato={fg_before != fg_after}  cursore mosso={cursor_before != cursor_after}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from cocbot.gui.app import load_default_config, run_gui

    config = load_default_config()
    print(f"GUI: config caricata (profilo {config.profile_name})")
    return run_gui(config, selftest_s=args.selftest, auto_start=args.autostart)


def cmd_bench(args: argparse.Namespace) -> int:
    """Misura l'impatto del bot: FPS cattura, CPU%, RAM, frame stale/neri (sola lettura)."""
    from cocbot.capture import win32, window
    from cocbot.capture.screen_wgc import WgcScreenSource

    win32.set_dpi_awareness()
    info = window.find_game_window()
    if info is None:
        print("ERRORE: gioco non in esecuzione. Avvialo manualmente da GPGPC.")
        return 2
    game_window = window.GameWindow(info)
    if win32.is_minimized(game_window.hwnd):
        print("ERRORE: finestra del gioco minimizzata (WGC non cattura finestre minimizzate).")
        return 2
    source = WgcScreenSource(game_window, target_fps=args.fps)
    frames = stale = black = 0
    mem_start = win32.process_memory_mb()
    cpu_start = time.process_time()
    wall_start = time.monotonic()
    print(f"bench: {args.seconds:.0f}s a ~{args.fps} FPS su {game_window}")
    try:
        while time.monotonic() - wall_start < args.seconds:
            frame = source.grab()
            frames += 1
            stale += int(frame.stale)
            black += int(bool(frame.metadata.get("black")))
            time.sleep(max(0.0, 1.0 / args.fps - 0.001))
    except KeyboardInterrupt:
        print("interrotto")
    finally:
        health = source.health()
        source.close()
    wall = max(1e-6, time.monotonic() - wall_start)
    cpu = time.process_time() - cpu_start
    mem_end = win32.process_memory_mb()
    print("\n== RISULTATO BENCH (impatto del bot) ==")
    print(f"durata: {wall:.1f}s | frame nel loop: {frames} | FPS loop: {frames / wall:.2f}")
    print(f"FPS cattura: {health.fps} | frame stale: {stale} | frame neri: {black}")
    print(f"CPU processo: {cpu:.2f}s su {wall:.1f}s = {100.0 * cpu / wall:.1f}% di un core")
    print(f"RAM working set: {mem_start:.1f} MB -> {mem_end:.1f} MB (delta {mem_end - mem_start:+.1f} MB)")
    print("Nota: la cattura WGC gira in un thread nativo; il carico del gioco non è incluso.")
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
    print(f"  input: {config.input.backend}  |  gui hotkey start/stop: {config.gui.hotkey_start_stop}")
    print(f"  ui: {config.ui.profile}  |  locale: {config.ui.locale}  |  canonical: {config.ui.canonical_size}")
    print(f"  safety: mode={config.safety.mode.value}  never_spend_gems={config.safety.never_spend_gems}")
    print(
        f"  limiti: sessione={config.safety.max_session_hours}h  "
        f"attacchi/h={config.safety.max_attacks_per_hour}  "
        f"upgrade/h={config.safety.max_upgrades_per_hour}  (None = illimitato)"
    )
    print(
        f"  auto-stop: nothing_to_do={config.safety.auto_stop_when_nothing_to_do}  "
        f"walls_max={config.walls.auto_stop_when_walls_max}"
    )
    print(
        f"  walls: mode={config.walls.mode.value}  reserve_builder={config.walls.reserve_builder_for_walls}  "
        f"switch_all_when_walls_max={config.walls.switch_to_all_builders_when_walls_max}"
    )
    print(f"  attack: strategy={config.attack.strategy}  preset={config.upgrade.preset}")
    print(
        f"  upgrade: enabled={config.upgrade.enabled}  dry_run={config.upgrade.dry_run}  "
        f"priority={config.upgrade.priority}  max/cycle={config.upgrade.max_upgrades_per_cycle}  "
        f"include_walls={config.upgrade.include_walls}"
    )
    print(
        f"  humanize: enabled={config.humanize.enabled}  delay_ms={config.humanize.action_delay_ms}  "
        f"idle_tap_prob={config.humanize.idle_tap_probability}  "
        f"max_actions/min={config.humanize.max_actions_per_minute}"
    )
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


def _load_upgrade_engine(config_path: str):
    """Crea un ``UpgradeEngine`` sul gioco aperto (errore chiaro se manca/minimizzato)."""
    from cocbot.app.upgrade_engine import UpgradeEngine
    from cocbot.capture import win32, window
    from cocbot.config import load_config

    win32.set_dpi_awareness()
    config = load_config(Path(config_path))
    info = window.find_game_window()
    if info is None:
        raise SystemExit("ERRORE: gioco non in esecuzione. Avvialo manualmente da GPGPC.")
    if win32.is_minimized(info.hwnd):
        raise SystemExit("ERRORE: finestra del gioco minimizzata (WGC non cattura finestre minimizzate).")
    game_window = window.GameWindow(info)
    print(f"finestra: {game_window}")
    return config, UpgradeEngine(game_window, config, log=print)


def _upgrade_report_path(out_arg: str | None, prefix: str) -> Path:
    if out_arg:
        return Path(out_arg)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path("out") / "upgrade" / f"{prefix}-{stamp}.json"


def _print_scan_summary(report, plan) -> None:
    from cocbot.app.upgrade_engine import categorize

    print(f"\n== HUD (letto in home) ==\n  {report.hud}")
    for note in report.notes:
        print(f"  nota: {note}")
    print(f"\n== CATALOGO (righe lette: {len(report.rows)}) ==")
    for row in report.rows:
        category = categorize(row.name) or "?"
        new_txt = " [NEW]" if row.is_new else ""
        print(f"  [{category:9s}] {row}{new_txt}")
    print(f"\n== PIANO (candidati: {len(plan.candidates)}, scelti: {len(plan.chosen)}) ==")
    for note in plan.notes:
        print(f"  nota: {note}")
    for item in plan.chosen:
        print(f"  -> [{item.category}] {item.row}")
    if not plan.chosen:
        print("  (nessun upgrade pianificato)")
    if plan.skipped:
        print(f"\n  scartati: {len(plan.skipped)}")
        for skipped in plan.skipped[:12]:
            print(f"    - {skipped.row} · {skipped.reason}")
        if len(plan.skipped) > 12:
            print(f"    ... e altri {len(plan.skipped) - 12}")


def cmd_upgrade_scan(args: argparse.Namespace) -> int:
    """Legge il catalogo del menu Build e stampa il piano. NON invia input di upgrade."""
    from cocbot.app.upgrade_engine import UpgradeEngineError, save_json
    from cocbot.vision.ocr import OcrUnavailable

    config, engine = _load_upgrade_engine(args.config)
    try:
        report = engine.scan(max_scrolls=args.max_scrolls)
        plan = engine.plan(report)
        _print_scan_summary(report, plan)
        path = save_json(
            _upgrade_report_path(args.out, "scan"),
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "config": args.config,
                "dry_run": True,
                "scan": report.to_dict(),
                "plan": plan.to_dict(),
            },
        )
        print(f"\nreport salvato: {path}")
        print("Nessuna spesa: scansione di sola lettura (il menu viene aperto e chiuso).")
        return 0
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    finally:
        engine.close()


def cmd_upgrade_run(args: argparse.Namespace) -> int:
    """Pianifica ed esegue gli upgrade. Senza ``--execute`` e' un dry-run."""
    from cocbot.app.upgrade_engine import UpgradeEngineError, save_json
    from cocbot.vision.ocr import OcrUnavailable

    config, engine = _load_upgrade_engine(args.config)
    dry_run = not getattr(args, "execute", False)
    try:
        report = engine.scan(max_scrolls=args.max_scrolls)
        plan = engine.plan(report)
        _print_scan_summary(report, plan)
        results = engine.execute(plan, dry_run=dry_run)
        print(f"\n== ESECUZIONE ({'dry-run' if dry_run else 'REALE'}) ==")
        for result in results:
            status = "OK" if result.ok else "FALLITO"
            print(f"  [{status}] {result.row} · {result.reason}")
        if not dry_run and results:
            print("ATTENZIONE: esecuzione reale richiesta. Verifica HUD/builder nel report.")
        path = save_json(
            _upgrade_report_path(args.out, "run"),
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "config": args.config,
                "dry_run": dry_run,
                "scan": report.to_dict(),
                "plan": plan.to_dict(),
                "execution": [
                    {"row": str(result.row), "ok": result.ok, "reason": result.reason} for result in results
                ],
            },
        )
        print(f"\nreport salvato: {path}")
        return 0 if all(result.ok for result in results) else 1
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    finally:
        engine.close()


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
        "--backend",
        choices=["wgc", "mss"],
        default="wgc",
        help="wgc = cattura la finestra anche se coperta (default); mss = solo schermo visibile",
    )
    capture.add_argument(
        "--focus",
        action="store_true",
        help="(solo mss) porta la finestra in primo piano durante la cattura e ripristina dopo",
    )
    capture.set_defaults(func=cmd_capture)

    input_test = sub.add_parser("input-test", help="testa un tap non invasivo (messaggi Win32, nessun focus)")
    input_test.add_argument("--x", type=int, default=960, help="coordinata canonica X (0-1920)")
    input_test.add_argument("--y", type=int, default=540, help="coordinata canonica Y (0-1080)")
    input_test.add_argument("--execute", action="store_true", help="invia davvero il click (default: dry-run)")
    input_test.set_defaults(func=cmd_input_test)

    gui = sub.add_parser("gui", help="GUI minimale: Start/Stop, hotkey globale Ctrl+Alt+L, stato e avvisi")
    gui.add_argument("--selftest", type=float, default=None, help="apre la GUI e la chiude dopo N secondi")
    gui.add_argument("--autostart", action="store_true", help="avvia il bot all'apertura della GUI")
    gui.set_defaults(func=cmd_gui)

    bench = sub.add_parser("bench", help="misura impatto del bot (FPS cattura, CPU, RAM) in sola lettura")
    bench.add_argument("--seconds", type=float, default=20.0)
    bench.add_argument("--fps", type=int, default=5)
    bench.set_defaults(func=cmd_bench)

    config_check = sub.add_parser("config-check", help="valida la configurazione YAML")
    config_check.add_argument("--path", default="config/config.example.yaml")
    config_check.set_defaults(func=cmd_config_check)

    adb_check = sub.add_parser("adb-check", help="verifica disponibilità backend ADB")
    adb_check.add_argument("--adb", default=None)
    adb_check.add_argument("--serial", default="localhost:6520")
    adb_check.set_defaults(func=cmd_adb_check)

    upgrade_scan = sub.add_parser(
        "upgrade-scan",
        help="scansiona il menu Build e stampa il piano di upgrade (sola lettura, nessuna spesa)",
    )
    upgrade_scan.add_argument("--config", default="config/config.example.yaml")
    upgrade_scan.add_argument("--max-scrolls", type=int, default=None, help="limite posizioni di scroll")
    upgrade_scan.add_argument("--out", default=None, help="file JSON del report (default out/upgrade/scan-<ts>.json)")
    upgrade_scan.set_defaults(func=cmd_upgrade_scan)

    upgrade_run = sub.add_parser(
        "upgrade-run",
        help="scansiona, pianifica ed esegue gli upgrade (dry-run di default; --execute spende risorse)",
    )
    upgrade_run.add_argument("--config", default="config/config.example.yaml")
    upgrade_run.add_argument("--max-scrolls", type=int, default=None)
    upgrade_run.add_argument("--out", default=None)
    upgrade_run.add_argument(
        "--execute",
        action="store_true",
        help="esegue davvero gli upgrade (preme CONFIRM: spende risorse). Default: dry-run.",
    )
    upgrade_run.set_defaults(func=cmd_upgrade_run)

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
