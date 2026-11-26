"""CLI di sviluppo: probe | capture | config-check | adb-check | upgrade-* | attack-scan."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cocbot import __version__


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
    from cocbot.gui.app import find_config_path, load_default_config, run_gui

    config_path = find_config_path()
    config = load_default_config()
    label = str(config_path) if config_path is not None else "predefinita (in memoria)"
    print(f"GUI: config {label} · profilo {config.profile_name}")
    return run_gui(
        config,
        selftest_s=args.selftest,
        auto_start=args.autostart,
        screenshots_dir=args.screenshot_dir,
        hidden=args.hidden,
        config_path=config_path,
    )


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
    print(
        f"  auto: enabled={config.auto.enabled}  storage_full_ratio={config.auto.storage_full_ratio}  "
        f"require_lab_and_pets={config.auto.require_lab_and_pets}  max_cycles={config.auto.max_cycles}"
    )
    print(
        f"  attack: strategy={config.attack.strategy}  corner={config.attack.corner}  "
        f"corner_pan={config.attack.corner_pan}  invisibility={config.attack.invisibility_spells}  "
        f"invisibility_card_slot={config.attack.invisibility_card_slot}  "
        f"clones={config.attack.clone_spells}  deploy_interval_s={config.attack.deploy_interval_s}"
    )
    print(
        f"  loot: oro_min={config.loot.thresholds.gold_min}  "
        f"elisir_min={config.loot.thresholds.elixir_min}  "
        f"dark_min={config.loot.thresholds.dark_min}  "
        f"score_min={config.loot.thresholds.score_min:.0f}  preset={config.upgrade.preset}"
    )
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


def _load_engine(config_path: str, engine_class=None):
    """Crea un engine sul gioco aperto (errore chiaro se manca/minimizzato)."""
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
    engine_class = engine_class or UpgradeEngine
    return config, engine_class(game_window, config, log=print)


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

    config, engine = _load_engine(args.config)
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
    """Pianifica ed esegue gli upgrade. Senza ``--execute`` e' un dry-run.

    I tetti opzionali ``--max-gold/--max-elixir/--max-dark`` (cumulativi per il ciclo) e
    ``--max-upgrades`` limitano la spesa: utile per liberare capacità quando le risorse sono al cap.
    """
    from cocbot.app.upgrade_engine import UpgradeEngineError, filter_plan_by_budget, save_json
    from cocbot.vision.ocr import OcrUnavailable

    config, engine = _load_engine(args.config)
    dry_run = not getattr(args, "execute", False)
    try:
        report = engine.scan(max_scrolls=args.max_scrolls)
        plan = engine.plan(report, only=getattr(args, "only", None))
        budgets = {
            currency: value
            for currency, value in (
                ("gold", getattr(args, "max_gold", None)),
                ("elixir", getattr(args, "max_elixir", None)),
                ("dark", getattr(args, "max_dark", None)),
            )
            if value is not None
        }
        max_upgrades = getattr(args, "max_upgrades", None)
        if budgets or max_upgrades is not None:
            plan = filter_plan_by_budget(plan, budgets=budgets, max_upgrades=max_upgrades)
        _print_scan_summary(report, plan)
        results = engine.execute(plan, dry_run=dry_run)
        print(f"\n== ESECUZIONE ({'dry-run' if dry_run else 'REALE'}) ==")
        for result in results:
            status = "OK" if result.ok else "FALLITO"
            print(f"  [{status}] {result.row} · {result.reason}")
            if result.hud_after is not None:
                print(f"      HUD dopo: {result.hud_after}")
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
        ok_count = sum(1 for result in results if result.ok)
        failed = [result for result in results if not result.ok]
        if results:
            print(f"Riepilogo esecuzione: {ok_count}/{len(results)} upgrade riusciti")
        if failed and not ok_count:
            return 1
        if failed:
            print("RISULTATO PARZIALE: alcuni upgrade sono falliti, vedi le righe FALLITO sopra.")
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


def cmd_attack_scan(args: argparse.Namespace) -> int:
    """Apre il menu Battle e legge gli elementi principali. Sola lettura: nessun raid."""
    from cocbot.app.attack_engine import AttackEngine
    from cocbot.app.upgrade_engine import UpgradeEngineError

    _, engine = _load_engine(args.config, AttackEngine)
    try:
        read = engine.scan_battle_menu()
        print("\n== MENU BATTLE (sola lettura) ==")
        print(f"  stato: {read.state}")
        if read.find_match_rect is not None:
            print(f"  pulsante 'Find a Match': rect={read.find_match_rect} centro={read.find_match_center}")
        else:
            print("  pulsante 'Find a Match' NON trovato")
        for note in read.notes:
            print(f"  nota: {note}")
        print("\nNessuna battaglia avviata: comando di sola lettura (non preme 'Find a Match').")
        return 0
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    finally:
        engine.close()


def cmd_attack_scout(args: argparse.Namespace) -> int:
    """Anteprima base: apre la ricerca, legge il loot e torna in home SENZA deployare.

    Senza ``--allow-spend`` e' un dry-run: apre solo menu Battle e pannello My Army (nessuna
    spesa). Con ``--allow-spend`` preme "Attack!" (ricerca base, ~1100 oro) e legge il loot.
    """
    from cocbot.app.attack_engine import AttackEngine, evaluate_loot_from_config
    from cocbot.app.upgrade_engine import UpgradeEngineError
    from cocbot.vision.ocr import OcrUnavailable

    _, engine = _load_engine(args.config, AttackEngine)
    try:
        if not engine.open_army_panel():
            print("ERRORE: pannello My Army non aperto")
            return 1
        print("\n== ANTEPRIMA ESERCITO (My Army) ==")
        print("  pannello aperto; 'Attack!' avvia la ricerca base (~1100 oro)")
        if not getattr(args, "allow_spend", False):
            print("  DRY-RUN: nessuna ricerca avviata (usa --allow-spend per spendere ~1100 oro).")
            engine.close_army_panel()
            return 0
        if not engine.open_search():
            print("ERRORE: ricerca base non avviata / anteprima non rilevata")
            engine.close_army_panel()
            return 1
        try:
            loot = engine.read_loot()
            decision = evaluate_loot_from_config(engine.config.loot, loot)
            print("\n== ANTEPRIMA BASE (Available Loot) ==")
            print(f"  oro={loot.gold} elisir={loot.elixir} dark={loot.dark}")
            for note in loot.notes:
                print(f"  nota: {note}")
            print(f"  decisione: {'ATTACCA' if decision.should_attack else 'SALTA'} · {decision.reason}")
            print(f"  score={decision.score:.0f}")
            print("\nNessun deploy: torno in home con 'End Battle' (nessuna spesa oltre la ricerca).")
        finally:
            engine.end_battle()
        hud = engine.read_hud(engine.grab())
        print(f"HUD dopo: {hud}")
        return 0
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    finally:
        engine.close()


def cmd_attack_run(args: argparse.Namespace) -> int:
    """Ciclo attacco completo: ricerca (skip se il loot non basta), deploy, esito, home.

    Senza ``--allow-spend`` e' un dry-run (apre/chiude il pannello esercito, nessuna spesa).
    Con ``--allow-spend`` ogni ricerca/"Next" costa ~1100 oro e ``--max-searches`` limita il
    numero di ricerche (tetto di spesa). Deploy: ``--dragons`` draghi + eroi (``--no-heroes``).
    """
    from cocbot.app.attack_engine import AttackEngine
    from cocbot.app.upgrade_engine import UpgradeEngineError
    from cocbot.vision.ocr import OcrUnavailable

    _, engine = _load_engine(args.config, AttackEngine)
    try:
        report = engine.run_attack(
            allow_spend=args.allow_spend,
            max_searches=max(1, args.max_searches),
            dragons=max(1, args.dragons),
            heroes=not args.no_heroes,
            spells=max(0, args.spells),
            respect_storage_caps=not args.ignore_caps,
            early_exit_damage=max(0, args.early_exit_damage),
            strategy=args.strategy,
            clones=args.clones,
            clone_card_slot=args.clone_card_slot,
            corner=args.corner,
            invisibility=args.invisibility,
            invisibility_card_slot=args.invisibility_card_slot,
        )
        print("\n== ATTACK RUN ==")
        print(f"  dry_run={report['dry_run']} azione={report['action']}")
        print(f"  ricerche={report['searches']} skip={report['skips']}")
        if report.get("early_exit"):
            print(f"  early-exit a danno {report.get('early_exit_damage_pct')}%")
        capacity = report.get("usable_capacity")
        if capacity:
            print(
                f"  capacità residua: oro={capacity['gold']} elisir={capacity['elixir']} "
                f"dark={capacity.get('dark')}"
            )
        if report.get("skip_limit_reason"):
            print(f"  limite skip: {report['skip_limit_reason']}")
        if report.get("dark_fallback"):
            print("  fallback attivo: attacco 'solo dark' (oro/elisir limitati dalla capacità)")
        for index, loot in enumerate(report["loots"], start=1):
            print(
                f"  loot {index}: oro={loot['gold']} elisir={loot['elixir']} "
                f"dark={loot['dark']} (incassabile {loot.get('incassabile_gold')}/"
                f"{loot.get('incassabile_elixir')})"
            )
        if report.get("decision"):
            print(f"  decisione: {report['decision']}")
        if report.get("strategy"):
            corner = f" · angolo={report['corner']}" if report.get("corner") else ""
            phase = report.get("deploy_phase")
            phase_txt = {
                "preview": "subito (anteprima)",
                "battle": "al primo istante della battaglia (il countdown e' imposto dal gioco)",
            }.get(phase or "", phase or "—")
            print(f"  strategia: {report['strategy']}{corner} · deploy {phase_txt}")
            if report.get("preview_deploy_ignored"):
                print(
                    "  nota: durante il countdown il gioco ignora i tap → deploy al primo "
                    "istante utile della battaglia"
                )
            if report.get("dragon_deployed") is not None:
                print(f"  draghi deployati: {report.get('dragon_deployed')}")
            if report.get("deploy_point"):
                print(
                    f"  punto deploy: {report['deploy_point']} "
                    f"(erba={report.get('deploy_on_grass')})"
                )
            if report.get("deploy_started_after_s") is not None:
                print(f"  primo deploy dopo {report['deploy_started_after_s']} s dalla decisione")
        if report.get("deploy_taps") is not None:
            print(f"  tap deploy: {report['deploy_taps']}")
        if report.get("spell_taps") is not None:
            print(f"  tap spell: {report['spell_taps']}")
        result = report.get("result")
        if result:
            print(
                f"  esito: {result['outcome']} · danno={result['damage_pct']}% · "
                f"bottino={result['loot_gold']}/{result['loot_elixir']}/{result['loot_dark']} · "
                f"truppe={result['troops_expended']}"
            )
            for note in result["notes"]:
                print(f"  nota: {note}")
        if report.get("hud_before"):
            print(f"  HUD prima: {report['hud_before']}")
        if report.get("hud_after"):
            print(f"  HUD dopo:  {report['hud_after']}")
        if report.get("report_path"):
            print(f"  report telemetria: {report['report_path']}")
        return 0
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    finally:
        engine.close()


def cmd_attack_farm(args: argparse.Namespace) -> int:
    """Loop di raid ripetuti con tetto di spesa e stop automatico (dry-run di default).

    Il farm si ferma se un ciclo non porta a un attacco (es. storage piene senza dark),
    oppure prima di superare ``--max-gold-spend`` (≈1100 oro per ricerca/Next).
    """
    from cocbot.app.attack_engine import AttackEngine
    from cocbot.app.upgrade_engine import UpgradeEngineError
    from cocbot.vision.ocr import OcrUnavailable

    _, engine = _load_engine(args.config, AttackEngine)
    try:
        report = engine.run_farm(
            cycles=max(1, args.cycles),
            allow_spend=args.allow_spend,
            max_searches=max(1, args.max_searches),
            dragons=max(1, args.dragons),
            heroes=not args.no_heroes,
            spells=max(0, args.spells),
            early_exit_damage=max(0, args.early_exit_damage),
            max_gold_spend=max(0, args.max_gold_spend),
            strategy=args.strategy,
            clones=args.clones,
            clone_card_slot=args.clone_card_slot,
            corner=args.corner,
            invisibility=args.invisibility,
            invisibility_card_slot=args.invisibility_card_slot,
        )
        print("\n== ATTACK FARM ==")
        print(
            f"  dry_run={report['dry_run']} cicli={report['cycles_done']}/"
            f"{report['cycles_requested']} speso≈{report['spent_gold']} oro "
            f"tetto={report['max_gold_spend']}"
        )
        print(f"  stop: {report['stopped']}")
        for index, cycle in enumerate(report["reports"], start=1):
            result = cycle.get("result") or {}
            print(
                f"  ciclo {index}: azione={cycle['action']} ricerche={cycle['searches']} "
                f"skip={cycle['skips']} esito={result.get('outcome')} "
                f"danno={result.get('damage_pct')}% "
                f"bottino={result.get('loot_gold')}/{result.get('loot_elixir')}/{result.get('loot_dark')}"
            )
            if cycle.get("dark_fallback"):
                print("    (attacco 'solo dark': oro/elisir limitati dalla capacità)")
            if cycle.get("early_exit"):
                print(f"    (early-exit a {cycle.get('early_exit_damage_pct')}%)")
        if report.get("report_path"):
            print(f"  report telemetria: {report['report_path']}")
        return 0
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    finally:
        engine.close()


def cmd_hud(args: argparse.Namespace) -> int:
    """Legge stato schermo e HUD (risorse/builder) senza inviare alcun input.

    Sola lettura: nessun tap, nessuna spesa. Con ``--json`` stampa una riga JSON
    interpretabile dalla GUI.
    """
    from cocbot.app.upgrade_engine import UpgradeEngineError
    from cocbot.vision.ocr import OcrUnavailable
    from cocbot.vision.states import describe

    _, engine = _load_engine(args.config)
    try:
        image = engine.grab()
        state = engine.state(image)
        hud = engine.read_hud(image)
        payload = {
            "state": str(getattr(state, "value", state)),
            "home": str(getattr(state, "value", state)) == "home",
            "hud": {
                "gold": hud.gold,
                "elixir": hud.elixir,
                "dark": hud.dark,
                "gems": hud.gems,
                "builders_available": hud.builders_available,
                "builders_total": hud.builders_total,
            },
            "notes": list(hud.notes),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        def fmt(value: int | None) -> str:
            return "?" if value is None else f"{value:,}".replace(",", " ")

        print("== HUD (sola lettura) ==")
        print(f"  stato schermo: {getattr(state, 'value', state)} ({describe(state)})")
        print(f"  oro: {fmt(hud.gold)}  elisir: {fmt(hud.elixir)}  dark: {fmt(hud.dark)}  gemme: {fmt(hud.gems)}")
        print(f"  builder: {fmt(hud.builders_available)}/{fmt(hud.builders_total)}")
        for note in hud.notes:
            print(f"  nota: {note}")
        print("\nNessun input inviato: lettura di sola lettura.")
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


def cmd_auto_run(args: argparse.Namespace) -> int:
    """Loop AUTO unico: farm fino a depositi pieni, poi upgrade per priorità, poi stop.

    Condizioni di stop reali: **tutti i builder occupati + depositi pieni** (e, con
    ``--require-lab-pets``, anche laboratorio e famigli al lavoro). Senza ``--allow-spend``
    è un dry-run: legge HUD, decide e simula un raid senza spendere.
    """
    from cocbot.app.attack_engine import AttackEngine
    from cocbot.app.auto_engine import AutoEngine
    from cocbot.app.upgrade_engine import UpgradeEngineError
    from cocbot.vision.ocr import OcrUnavailable

    config, upgrade_engine = _load_engine(args.config)
    attack_engine = AttackEngine(upgrade_engine.window, config, log=print)
    budgets = {
        currency: value
        for currency, value in (
            ("gold", args.max_gold),
            ("elixir", args.max_elixir),
            ("dark", args.max_dark),
        )
        if value is not None
    }
    auto = AutoEngine(upgrade_engine, attack_engine, config, log=print)
    try:
        report = auto.run(
            allow_spend=args.allow_spend,
            cycles=args.cycles if args.cycles is not None else config.auto.max_cycles,
            farm_max_searches=max(1, args.max_searches),
            dragons=max(1, args.dragons),
            heroes=not args.no_heroes,
            spells=max(0, args.spells),
            clones=args.clones,
            strategy=args.strategy,
            clone_card_slot=args.clone_card_slot,
            corner=args.corner,
            invisibility=args.invisibility,
            invisibility_card_slot=args.invisibility_card_slot,
            early_exit_damage=max(0, args.early_exit_damage),
            upgrade_budgets=budgets or None,
            max_upgrades=args.max_upgrades,
            require_lab_and_pets=True if args.require_lab_pets else None,
            sleep_between_s=(
                args.sleep_between_s
                if args.sleep_between_s is not None
                else config.auto.sleep_between_s
            ),
            wait_between_s=(
                args.wait_between_s if args.wait_between_s is not None else config.auto.wait_between_s
            ),
        )
        print("\n== AUTO RUN ==")
        print(
            f"  dry_run={report['dry_run']} cicli={report['cycles_done']}/"
            f"{report['cycles_requested']}"
        )
        print(f"  stop: {report['stop_reason']}")
        print(f"  farm: raid={report['farm']['attacks']} ricerche={report['farm']['searches']}")
        print(
            f"  upgrade: piani={report['upgrade']['plans']} "
            f"eseguiti={report['upgrade']['executed']}"
        )
        for action in report["actions"]:
            kind = action["action"]
            if kind == "farm":
                farm = action["farm"]
                print(
                    f"  ciclo {action['cycle']}: farm → esito={farm['outcome']} "
                    f"danno={farm['damage_pct']}% bottino="
                    f"{farm['loot_gold']}/{farm['loot_elixir']}/{farm['loot_dark']}"
                )
            elif kind == "upgrade":
                print(
                    f"  ciclo {action['cycle']}: upgrade → {action['executed']} eseguiti "
                    f"({action['reason']})"
                )
            elif kind == "wait":
                print(f"  ciclo {action['cycle']}: attesa ({action['reason']})")
        if report.get("final_hud"):
            print(f"  HUD finale: {report['final_hud']}")
        if report.get("report_path"):
            print(f"  report: {report['report_path']}")
        return 0
    except UpgradeEngineError as exc:
        print(f"ERRORE engine: {exc}")
        return 1
    except OcrUnavailable as exc:
        print(f"ERRORE OCR: {exc}")
        print("Installa l'extra OCR: python -m pip install -e .[ocr]")
        return 1
    finally:
        attack_engine.close()
        upgrade_engine.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocbot",
        description="cocbot - automazione visiva Clash of Clans (uso didattico; viola i ToS Supercell).",
    )
    parser.add_argument("--version", action="version", version=f"cocbot {__version__}")
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

    gui = sub.add_parser(
        "gui",
        help="apre la GUI: pannello stato, Battaglia, Upgrade, Registro e Sicurezza (hotkey globali)",
    )
    gui.add_argument("--selftest", type=float, default=None, help="apre la GUI e la chiude dopo N secondi")
    gui.add_argument("--autostart", action="store_true", help="avvia il bot all'apertura della GUI")
    gui.add_argument(
        "--screenshot-dir",
        default=None,
        help="(selftest) salva uno screenshot per ogni pagina in questa cartella (audit visivo)",
    )
    gui.add_argument(
        "--hidden",
        action="store_true",
        help="apre la GUI senza mostrare la finestra e senza hotkey (test automatici)",
    )
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
        "--only",
        default=None,
        help="considera solo la riga con questo nome (match fuzzy); utile per target espliciti",
    )
    upgrade_run.add_argument(
        "--execute",
        action="store_true",
        help="esegue davvero gli upgrade (preme CONFIRM: spende risorse). Default: dry-run.",
    )
    upgrade_run.add_argument(
        "--max-gold", type=int, default=None, help="tetto cumulativo di oro speso nel ciclo"
    )
    upgrade_run.add_argument(
        "--max-elixir", type=int, default=None, help="tetto cumulativo di elisir speso nel ciclo"
    )
    upgrade_run.add_argument(
        "--max-dark", type=int, default=None, help="tetto cumulativo di dark speso nel ciclo"
    )
    upgrade_run.add_argument(
        "--max-upgrades", type=int, default=None, help="numero massimo di upgrade nel ciclo"
    )
    upgrade_run.set_defaults(func=cmd_upgrade_run)

    attack_scan = sub.add_parser(
        "attack-scan",
        help="apre il menu Battle e legge gli elementi (sola lettura: nessun raid, nessuna spesa)",
    )
    attack_scan.add_argument("--config", default="config/config.example.yaml")
    attack_scan.set_defaults(func=cmd_attack_scan)

    attack_scout = sub.add_parser(
        "attack-scout",
        help="anteprima base: rileva loot e torna in home senza deploy (dry-run; --allow-spend)",
    )
    attack_scout.add_argument("--config", default="config/config.example.yaml")
    attack_scout.add_argument(
        "--allow-spend",
        action="store_true",
        help="avvia davvero la ricerca base (~1100 oro); senza questo flag e' un dry-run",
    )
    attack_scout.set_defaults(func=cmd_attack_scout)

    attack_run = sub.add_parser(
        "attack-run",
        help="ciclo attacco completo: ricerca (e skip), deploy draghi+eroi, OCR esiti, home",
    )
    attack_run.add_argument("--config", default="config/config.example.yaml")
    attack_run.add_argument(
        "--allow-spend",
        action="store_true",
        help="esegue davvero il raid (~1100 oro per ricerca/Next); senza flag e' un dry-run",
    )
    attack_run.add_argument(
        "--max-searches",
        type=int,
        default=2,
        help="numero massimo di ricerche/skip (tetto di spesa ≈ max-searches*1100 oro)",
    )
    attack_run.add_argument("--dragons", type=int, default=13)
    attack_run.add_argument("--no-heroes", action="store_true")
    attack_run.add_argument("--spells", type=int, default=0, help="spell da lanciare dopo il deploy")
    attack_run.add_argument(
        "--strategy",
        choices=["dragon_corner", "dragon_clone", "dragon_spam"],
        default=None,
        help="strategia di deploy (default: attack.strategy in config)",
    )
    attack_run.add_argument(
        "--corner",
        choices=["random", "nw", "ne", "sw", "se"],
        default=None,
        help="angolo di deploy per dragon_corner (default: attack.corner in config)",
    )
    attack_run.add_argument(
        "--invisibility",
        type=int,
        default=None,
        help="Invisibility Spell sui draghi (default: attack.invisibility_spells)",
    )
    attack_run.add_argument(
        "--invisibility-card-slot",
        type=int,
        default=None,
        help="posizione della card Invisibility Spell (0 = primo slot, default config)",
    )
    attack_run.add_argument(
        "--clones",
        type=int,
        default=None,
        help="Clone Spell da lanciare sui draghi (default: attack.clone_spells)",
    )
    attack_run.add_argument(
        "--clone-card-slot",
        type=int,
        default=None,
        help="posizione della card Clone Spell (0 = primo slot, default config)",
    )
    attack_run.add_argument(
        "--ignore-caps",
        action="store_true",
        help="ignora il cap delle storage (default: salta il raid se oro+elisir sono pieni)",
    )
    attack_run.add_argument(
        "--early-exit-damage",
        type=int,
        default=0,
        help="se >0: durante la battaglia esce quando 'Overall Damage' raggiunge questa %%",
    )
    attack_run.set_defaults(func=cmd_attack_run)

    attack_farm = sub.add_parser(
        "attack-farm",
        help="loop di raid ripetuti con tetto di spesa e stop automatico (dry-run di default)",
    )
    attack_farm.add_argument("--config", default="config/config.example.yaml")
    attack_farm.add_argument(
        "--allow-spend",
        action="store_true",
        help="esegue davvero i raid (~1100 oro per ricerca/Next); default dry-run",
    )
    attack_farm.add_argument("--cycles", type=int, default=2)
    attack_farm.add_argument("--max-searches", type=int, default=1)
    attack_farm.add_argument("--dragons", type=int, default=13)
    attack_farm.add_argument("--no-heroes", action="store_true")
    attack_farm.add_argument("--spells", type=int, default=5)
    attack_farm.add_argument(
        "--strategy",
        choices=["dragon_corner", "dragon_clone", "dragon_spam"],
        default=None,
        help="strategia di deploy (default: attack.strategy in config)",
    )
    attack_farm.add_argument("--clones", type=int, default=None, help="Clone Spell sui draghi (default config)")
    attack_farm.add_argument("--clone-card-slot", type=int, default=None, help="posizione card Clone Spell")
    attack_farm.add_argument(
        "--corner",
        choices=["random", "nw", "ne", "sw", "se"],
        default=None,
        help="angolo di deploy per dragon_corner (default config)",
    )
    attack_farm.add_argument(
        "--invisibility",
        type=int,
        default=None,
        help="Invisibility Spell sui draghi (default: attack.invisibility_spells)",
    )
    attack_farm.add_argument(
        "--invisibility-card-slot",
        type=int,
        default=None,
        help="posizione della card Invisibility Spell (default config)",
    )
    attack_farm.add_argument(
        "--early-exit-damage",
        type=int,
        default=40,
        help="soglia 'Overall Damage' per l'early-exit (0 = disattivo)",
    )
    attack_farm.add_argument(
        "--max-gold-spend",
        type=int,
        default=2200,
        help="tetto di spesa stimata in oro per l'intero farm (1100 per ricerca/Next)",
    )
    attack_farm.set_defaults(func=cmd_attack_farm)

    auto_run = sub.add_parser(
        "auto-run",
        help=(
            "loop unico: farm fino a depositi pieni, poi upgrade per priorità, stop con "
            "builder occupati + depositi pieni"
        ),
    )
    auto_run.add_argument("--config", default="config/config.example.yaml")
    auto_run.add_argument(
        "--allow-spend",
        action="store_true",
        help="esegue davvero raid e upgrade (default: dry-run di sola simulazione)",
    )
    auto_run.add_argument("--cycles", type=int, default=None, help="numero massimo di azioni")
    auto_run.add_argument("--max-searches", type=int, default=1, help="ricerche max per raid di farm")
    auto_run.add_argument("--dragons", type=int, default=13)
    auto_run.add_argument("--no-heroes", action="store_true")
    auto_run.add_argument("--spells", type=int, default=0)
    auto_run.add_argument("--clones", type=int, default=None)
    auto_run.add_argument(
        "--strategy", choices=["dragon_corner", "dragon_clone", "dragon_spam"], default=None
    )
    auto_run.add_argument("--clone-card-slot", type=int, default=None)
    auto_run.add_argument(
        "--corner", choices=["random", "nw", "ne", "sw", "se"], default=None
    )
    auto_run.add_argument("--invisibility", type=int, default=None)
    auto_run.add_argument("--invisibility-card-slot", type=int, default=None)
    auto_run.add_argument("--early-exit-damage", type=int, default=0)
    auto_run.add_argument("--max-gold", type=int, default=None, help="tetto upgrade: oro per ciclo")
    auto_run.add_argument("--max-elixir", type=int, default=None, help="tetto upgrade: elisir per ciclo")
    auto_run.add_argument("--max-dark", type=int, default=None, help="tetto upgrade: dark per ciclo")
    auto_run.add_argument("--max-upgrades", type=int, default=None, help="tetto upgrade: numero massimo")
    auto_run.add_argument(
        "--require-lab-pets",
        action="store_true",
        help="stop solo se laboratorio e famigli risultano al lavoro (sperimentale)",
    )
    auto_run.add_argument("--sleep-between-s", type=float, default=None)
    auto_run.add_argument("--wait-between-s", type=float, default=None)
    auto_run.set_defaults(func=cmd_auto_run)

    hud = sub.add_parser(
        "hud",
        help="legge stato schermo e risorse/builder (sola lettura: nessun tap, nessuna spesa)",
    )
    hud.add_argument("--config", default="config/config.example.yaml")
    hud.add_argument("--json", action="store_true", help="output JSON (una riga, per la GUI)")
    hud.set_defaults(func=cmd_hud)

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
