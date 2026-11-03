"""Registra una sessione di schermate etichettate (dataset vision) con tap non invasivi.

Modalità pensata per il gioco in FULLSCREEN sul PC di sviluppo: usa coordinate canoniche
(1920x1080) note per la UI GPGPC 2026; ogni passo verifica lo stato (home vs pannello/menu) e
in caso di stato inatteso si ferma e lascia il gioco com'è (niente click alla cieca).

Produzione dataset:
    python tools/record_session.py --out dataset/raw-2026-11-03

Output:
- `<out>/NN_label.png` per ogni stato catturato (frame client, senza bordo finestra);
- `<out>/manifest.json` con etichette provvisorie, coordinate tap, misure;
- `<out>/contact-sheet.jpg` con miniature numerate (per revisione manuale);
- `<out>/INDEX.md` con la lista da revisionare (l'utente corregge le etichette).

Sicurezza: i tap sono solo su pulsanti HUD noti e su punti della mappa (edifici/erba);
mai su gemme/shop e mai su "Find a Match". Dopo ogni pannello si chiude con tap su erba.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from cocbot.capture import win32
from cocbot.capture.input_winmsg import WinMsgSink
from cocbot.capture.screen_wgc import WgcScreenSource
from cocbot.capture.window import GameWindow, find_game_window
from cocbot.core.types import GamePoint
from cocbot.vision.safe_tap import find_safe_tap_point, looks_like_home, panel_likely_open

# coordinate canoniche (1920x1080) per la UI GPGPC 2026 in fullscreen (verificate il 3 nov 2026)
TAP_BUILD = GamePoint(1809, 944)
TAP_CLOSE_BUILD = GamePoint(1892, 32)
TAP_BATTLE = GamePoint(114, 944)
TAP_CLOSE_BATTLE = GamePoint(1601, 549)  # tap sull'area villaggio accanto al menu

# punti mappa da esplorare: (punto canonico, etichetta provvisoria)
PANEL_POINTS: list[tuple[GamePoint, str]] = [
    (GamePoint(869, 177), "th_guess"),
    (GamePoint(365, 189), "hero_left_guess"),
    (GamePoint(1259, 270), "hero_right_guess"),
    (GamePoint(720, 455), "wall_upgrader_guess"),
    (GamePoint(843, 804), "army_upgrades_guess"),
    (GamePoint(600, 430), "building_guess_1"),
    (GamePoint(1500, 600), "building_guess_2"),
]

# punti di riserva per chiudere i pannelli: aree di mappa aperte (erba/bosco), verificate a mano.
# Servono quando i tap su erba "casuale" non chiudono (l'erba può essere dietro a un muro/albero).
CLOSE_FALLBACK_POINTS = [
    GamePoint(1517, 731),  # bosco a destra della base (verificato)
    GamePoint(1630, 480),  # lato destro aperto
    GamePoint(250, 760),  # lato sinistro basso aperto
]


@dataclass
class Entry:
    index: int
    file: str
    label_guess: str
    note: str
    tap: tuple[int, int] | None = None
    home: bool | None = None
    panel: bool | None = None
    extra: dict = field(default_factory=dict)


class SessionRecorder:
    def __init__(self, out_dir: Path, *, wait_s: float = 1.2) -> None:
        info = find_game_window()
        if info is None:
            raise SystemExit("Gioco non trovato: avvia GPGPC e il gioco, poi riprova.")
        self.window = GameWindow(info)
        self.out_dir = out_dir
        self.wait_s = wait_s
        self.source = WgcScreenSource(self.window, target_fps=5)
        self.sink = WinMsgSink(self.window, jitter_ms=(0, 0))
        self.rng = random.Random(12345)
        self.entries: list[Entry] = []
        self.frame_index = 0
        self._last_frame: np.ndarray | None = None

    # ------------------------------------------------------------------ util
    def grab(self) -> np.ndarray:
        frame = self.source.grab()
        self._last_frame = frame.image
        return frame.image

    def tap(self, point: GamePoint) -> None:
        self.sink.tap_canonical(point)
        time.sleep(self.wait_s)

    def capture(self, label_guess: str, note: str = "", tap: GamePoint | None = None) -> Entry:
        image = self.grab()
        self.frame_index += 1
        name = f"{self.frame_index:02d}_{label_guess}.png"
        path = self.out_dir / name
        import cv2

        cv2.imwrite(str(path), image)
        entry = Entry(
            index=self.frame_index,
            file=name,
            label_guess=label_guess,
            note=note,
            tap=(tap.x, tap.y) if tap else None,
            home=looks_like_home(image),
            panel=panel_likely_open(image),
        )
        self.entries.append(entry)
        print(f"  [{self.frame_index:02d}] {label_guess}: home={entry.home} panel={entry.panel} -> {name}")
        return entry

    def close_panel(self, max_attempts: int = 6) -> bool:
        """Chiude un pannello: tap su erba sicura e, se serve, su aree mappa aperte note."""
        for attempt in range(max_attempts):
            frame = self.grab()
            if looks_like_home(frame) and not panel_likely_open(frame):
                return True
            if attempt < 2:
                point = find_safe_tap_point(frame, rng=self.rng)
            else:
                point = CLOSE_FALLBACK_POINTS[(attempt - 2) % len(CLOSE_FALLBACK_POINTS)]
            if point is None:
                point = CLOSE_FALLBACK_POINTS[attempt % len(CLOSE_FALLBACK_POINTS)]
            self.tap(point)
        frame = self.grab()
        return looks_like_home(frame) and not panel_likely_open(frame)

    # ------------------------------------------------------------------ sessione
    def run(self) -> list[Entry]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        print(f"sessione dataset in {self.out_dir} · finestra {self.window}")

        self.capture("home", "home village, nessun pannello aperto")

        # Build menu (Buildings & Heroes)
        self.tap(TAP_BUILD)
        self.capture("build_menu", "menu Build/Buildings&Heroes", TAP_BUILD)
        self.tap(TAP_CLOSE_BUILD)
        if not self.close_panel(max_attempts=2):
            raise SystemExit("Impossibile chiudere il menu Build: mi fermo per sicurezza.")

        # Battle menu (NON toccare 'Find a Match')
        self.tap(TAP_BATTLE)
        self.capture("battle_menu", "menu Battle (Multiplayer/Single/Practice), NON avviare match", TAP_BATTLE)
        self.tap(TAP_CLOSE_BATTLE)
        if not self.close_panel(max_attempts=2):
            raise SystemExit("Impossibile chiudere il menu Battle: mi fermo per sicurezza.")

        # pannelli informativi da tap sulla mappa (sicuri: nessun acquisto)
        for point, label in PANEL_POINTS:
            if not self.close_panel(max_attempts=2):
                print("  stato non-home prima del tap: salto il punto")
                break
            self.tap(point)
            entry = self.capture(label, f"pannello aperto con tap mappa a {point.x},{point.y}", point)
            if entry.home and not entry.panel:
                print(f"  nessun pannello aperto per {label} (tap a vuoto)")
            if not self.close_panel():
                raise SystemExit(f"Impossibile chiudere il pannello {label}: mi fermo per sicurezza.")

        self.capture("home_final", "home village dopo la sessione")
        return self.entries

    def close(self) -> None:
        self.source.close()
        self.sink.close()


def build_contact_sheet(out_dir: Path, entries: list[Entry], *, thumb_w: int = 640, cols: int = 3) -> Path:
    import cv2

    tiles = []
    for entry in entries:
        image = cv2.imread(str(out_dir / entry.file))
        if image is None:
            continue
        scale = thumb_w / image.shape[1]
        thumb = cv2.resize(image, (thumb_w, int(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        banner = np.zeros((36, thumb_w, 3), dtype=np.uint8)
        cv2.putText(
            banner,
            f"{entry.index:02d}  {entry.label_guess}",
            (8, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        tiles.append(np.vstack([banner, thumb]))
    if not tiles:
        raise SystemExit("nessun frame da mettere nella contact sheet")
    tile_h = max(tile.shape[0] for tile in tiles)
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.zeros((rows * tile_h + 8, cols * (thumb_w + 8) + 8, 3), dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        y = r * tile_h + 4
        x = c * (thumb_w + 8) + 4
        sheet[y : y + tile.shape[0], x : x + tile.shape[1]] = tile
    path = out_dir / "contact-sheet.jpg"
    cv2.imwrite(str(path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return path


def write_index(out_dir: Path, entries: list[Entry]) -> Path:
    lines = [
        "# Dataset — sessione di registrazione (review manuale)",
        "",
        f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Etichette **provvisorie**: controlla i frame e correggi `label_guess` in `manifest.json`",
        "(o scrivi le correzioni e le sistemo io). La contact sheet `contact-sheet.jpg` ha i numeri.",
        "",
        "| # | file | etichetta provvisoria | note |",
        "|---|---|---|---|",
    ]
    for entry in entries:
        lines.append(f"| {entry.index:02d} | `{entry.file}` | {entry.label_guess} | {entry.note} |")
    lines += [
        "",
        "## Stati ancora mancanti (da registrare)",
        "- Hero Hall (pannello con i livelli degli eroi)",
        "- Army Recipe / Esercito (composizione e capienza)",
        "- Wall Upgrader (selezionando un muro con il flusso 'Upgrade More')",
        "- Upgrade confirm (conferma di un upgrade, senza completarlo)",
        "- Popup/event tray, error/maintenance (se capitano)",
        "",
    ]
    path = out_dir / "INDEX.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_manifest(out_dir: Path, entries: list[Entry], window: GameWindow) -> Path:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "window": {
            "client_size": [window.client_width, window.client_height],
            "dpi": window.dpi,
            "title_masked": window.title_masked,
        },
        "entries": [
            {
                "index": entry.index,
                "file": entry.file,
                "label_guess": entry.label_guess,
                "note": entry.note,
                "tap_canonical": list(entry.tap) if entry.tap else None,
                "heuristics": {"home": entry.home, "panel": entry.panel},
            }
            for entry in entries
        ],
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Registra un dataset di schermate di gioco etichettate")
    parser.add_argument("--out", type=Path, default=None, help="cartella output (default dataset/raw-<data>)")
    parser.add_argument("--wait", type=float, default=1.2, help="attesa dopo ogni tap (s)")
    args = parser.parse_args()
    win32.set_dpi_awareness()
    out_dir = args.out or (Path("dataset") / f"raw-{datetime.now().strftime('%Y%m%d-%H%M')}")
    recorder = SessionRecorder(out_dir, wait_s=args.wait)
    try:
        entries = recorder.run()
        sheet = build_contact_sheet(out_dir, entries)
        index = write_index(out_dir, entries)
        manifest = write_manifest(out_dir, entries, recorder.window)
    finally:
        recorder.close()
    print("\n== FATTO ==")
    print(f"frame:       {out_dir.resolve()}")
    print(f"contact:     {sheet}")
    print(f"indice:      {index}")
    print(f"manifest:    {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
