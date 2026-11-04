# cocbot — agente di automazione visiva per Clash of Clans (Google Play Games on PC)

> **Progetto personale/didattico.** Automatizzare Clash of Clans viola la Safe and Fair Play Policy e i
> Termini di Servizio di Supercell e può comportare il ban dell'account. Usare solo con un account
> dedicato, sessioni brevi e nessuna distribuzione. Vedi `../progetto-bot-coc/05-RISCHI-SICUREZZA-ETICA-LEGALE.md`.

Repository di sviluppo del bot. Il piano completo è in [`../progetto-bot-coc/`](../progetto-bot-coc/00-PIANO-GENERALE.md).

## Decisioni correnti (3 novembre 2026 — aggiornate 15:15)

| Tema | Decisione |
|---|---|
| **Backend primario** | **GPGPC consumer**: cattura **WGC** (finestra anche coperta, 47 FPS misurati) + input **messaggi Win32** (nessun focus, nessun cursore). Vedi [ADR-002](docs/ADR-002-backend-consumer-non-invasivo.md). |
| **Backend secondario (opzionale)** | **Developer Emulator + ADB**: codice pronto, non installato; fallback se serve giocare con finestra minimizzata/CI. **Mai** patch del consumer. |
| **Lingua gioco** | **Inglese — verificata** al primo screenshot (HUD `Battle`/`Build`/`Shop`); l'italiano resta supportato come secondo profilo. |
| **Account** | Si usa l'account **esistente** dell'utente (non dedicato): rischio ban dichiarato e accettato. |
| **Priorità** | Bot funzionante prima; materiale d'esame dopo (non guida le scelte tecniche). |
| **Sicurezza** | `dry_run` di default; GemGuard (mai gemme); kill switch; niente IAP; niente guerre/CWL. |
| **Avvio del gioco** | **Manuale** dell'utente: il bot rileva la finestra di gioco già aperta e si aggancia; **non avvia** GPGPC né il gioco. |
| **Avvio/stop del bot** | **Manuale**, da GUI con hotkey globale configurabile: default `Ctrl+Alt+L` (config `gui.hotkey_start_stop`). |
| **Zero interferenza** | **Validato**: WGC cattura anche coperta (47,4 FPS, 0 neri) e i click via messaggi aprono/chiudono pannelli **senza cambiare foreground né cursore**. |
| **Vincolo finestra** | Il gioco **non deve essere minimizzato** (WGC non cattura finestre minimizzate): il bot va in pausa. Coperta sì; **fullscreen verificato** (client 2452×1379, offset frame (0,29), mappatura tap corretta) ma occupa tutto lo schermo → per girare mentre lavori meglio la finestra. |
| **Anti-ban/humanization** | Ritmi variabili, pause random, tap a vuoto **solo su erba vuota** (mai gemme/shop), rate limit, avvisi anti-ban in GUI; **non garantisce** l'immunità dal ban. Vedi [ADR-003](docs/ADR-003-humanization-antiban.md). |
| **GUI/kill switch** | GUI minimale (tkinter): Start/Stop, stato e avvisi; hotkey globali **`Ctrl+Alt+L`** (start/stop) e **`Ctrl+Alt+K`** (kill switch; `F12` è occupato da un'altra app su questo PC). |
| **Limiti** | **Nessuno di default** (sessione illimitata); limiti solo se impostati dalla GUI. **Auto-stop** quando non c'è più nulla da fare: mura max + tutti i muratori occupati + risorse max. |
| **Builder/mura** | Preset **A**: 1 builder libero riservato alle mura (upgrade istantaneo); passaggio automatico a **B** quando tutte le mura sono max (tutti i builder lavorano). **Implementato nel planner** (`walls.*`: note di piano, limite builder per edifici/eroi, auto-stop a mura max). |
| **Upgrade (flusso)** | Primario dal **menu Build → "Buildings & Heroes"**: catalogo nativo (nome, livello, costo, valuta, tempo), **eroi inclusi**. Engine: legge la lista, filtra per priorità/riserve/builder, conferma solo "Upgrade" (mai "Finish Now"/gemme). **Mura validate a runtime** (riga Wall → pannello azioni → Upgrade oro **o** elisir → dialogo conferma → CONFIRM; un muro reale potenziato 12→13 con verifica risorse). **Upgrade classico (edificio/eroe) validato a runtime** (riga catalogo → dialogo di conferma → CONFIRM; Air Bomb: oro −37 500; Barbarian King: dark −44 000; builder consumato, gemme invariate). Vedi [ADR-004](docs/ADR-004-vision-ocr-engine-upgrade.md). |
| **Priorità upgrade** | Scelta utente (3 nov): **mura → difese → offensiva → eroi → risorse → other** (`upgrade.priority`); mura attive di default (`upgrade.include_walls: true`) con limite `walls.max_wall_batches_per_cycle` e budget cumulativo con riserve per valuta. |
| **Disconnessione/inattività** | L'engine riconosce i modal di rete **"Connection lost / TRY AGAIN"** e **"Anyone there? / RELOAD GAME"** e **gestisce da solo** retry + attesa caricamento + ripristino finestra se minimizzata. Riconosce anche la **manutenzione del gioco** (`MAINTENANCE BREAK`) e resta in pausa senza inviare input. Nessun avvio automatico di GPGPC. |
| **Strategia eroi (auto-battaglia)** | Opzioni pronte per il loop attacco: `attack.use_heroes` (schierare gli eroi) e `attack.heroes_require_ready` (un eroe in upgrade non è schierabile → escludi/attendi). **Loop attacco v2 validato live fino all'anteprima base**: `attack-scan` (menu Battle, sola lettura), `attack-scout` (anteprima My Army → ricerca → **OCR del loot** → decisione con soglie → "End Battle" **senza deploy**). Deploy dragon spam e skip reale ancora da implementare. Vedi [ADR-005](docs/ADR-005-attack-loop-v1.md). |
| **Vision/OCR** | Testo con **OCR** (`rapidocr` + `onnxruntime`, extra `ocr`); UI con euristiche cromatiche/geometriche. Geometria in frazioni del frame (windowed e fullscreen). OCR solo sul pannello Build e solo quando serve (~0,93 s/schermata; scansione completa ~85 s). I **piccoli errori OCR sui nomi noti** vengono recuperati con una canonicalizzazione fuzzy conservativa (`Craftina Station` → `Crafting Station`, usata anche da merge e navigazione live); i nomi davvero illeggibili restano **scartati** (mai indovinare). Immagini di gioco **non versionate** (dati account). |
| **Backup git** | Remote configurato: `git@github.com:Luiss896/COC-Bot.git` (SSH, branch `main`). |

## Stato

- [x] Piano completo (7 documenti) in `../progetto-bot-coc/`
- [x] POC: finestra gioco GPGPC consumer individuata (`crosvm`, 16:9, DPI 125%), input `SendInput` verificato, cattura foreground funzionante, `PrintWindow` scartato (contenuto non affidabile)
- [x] Scaffold repo: config, tipi/contratti, finestra, cattura mss, backend ADB, CLI
- [x] **POC WGC ≥10 FPS**: 47,4 FPS sulla finestra anche coperta, 0 frame neri (vedi ADR-002)
- [x] **POC input non invasivo**: click via messaggi Win32 senza focus/cursore; apre e chiude pannelli
- [x] **Moduli produzione**: `WgcScreenSource` (crop area client) + `WinMsgSink` (coordinate canoniche), CLI aggiornata, test
- [x] **GUI minimale** (tkinter): Start/Stop, hotkey `Ctrl+Alt+L` / kill switch `Ctrl+Alt+K`, stato e avvisi anti-ban
- [x] **Humanization/anti-ban**: ritmi variabili, pause random, tap a vuoto solo su erba vuota, rate limit, avvisi
- [x] **Impatto misurato** (`bench`): **6,6% di un core**, ~74 MB RAM, cattura 5 FPS → non interferisce
- [x] **Fullscreen verificato**: client 2452×1379, frame WGC 2452×1408, crop (0,29), mappatura tap corretta (match 0,967)
- [x] **Gate pannello**: niente tap a vuoto se nella zona basso-centro è aperto un pannello info
- [x] **Prima sessione dataset** (`tools/record_session.py`): 11 frame etichettati (home, Build, Battle, Town Hall 12, Wall, Bomb) + contact sheet per review manuale
- [x] **Dataset windowed menu Build**: scroll completo (21 posizioni), dialoghi di conferma upgrade, modalità piazzamento "New building" salvati in `dataset/build-win-20261103/` (locale, gitignored)
- [x] **Vision + OCR** (ADR-004): parser testo (importi/tempi/livelli/nomi), primitive UI (Build/Battle, X menu/dialogo, CONFIRM verde, modal inattività, piazzamento), lettura righe menu Build con merge delle letture, classifier stati (`home`, `build_menu`, `upgrade_confirm`, `placement`, `network_error`)
- [x] **Engine upgrade — scansione e piano** (`upgrade-scan`): legge tutto il catalogo (≈56 righe in 21 posizioni, ~84 s con stabilizzazione UI) e HUD (risorse + builder), filtra per priorità/riserve/builder, piano dry-run verificato a runtime (zero spese)
- [x] **Engine upgrade — esecuzione reale (muro) VALIDATA a runtime**: riga Wall → pannello azioni → Upgrade elisir → dialogo di conferma verificato → CONFIRM; elisir 7 500 945 → 6 750 945 (−750 000), gemme invariate, builder 5/5, livello muro 12→13
- [x] **Engine upgrade — esecuzione reale (edificio) VALIDATA a runtime**: riga catalogo → dialogo `Upgrade Air Bomb to Level 3?` verificato (nome/costo) → CONFIRM verde; **oro 7 323 700 → 7 286 200 (−37 500)**, builder **5/5 → 4/5**, elisir/dark/gemme invariati, HUD riletto in home. Scoperto e corretto un off-by-one: il catalogo mostra il livello di **destinazione** (non quello attuale), quindi il dialogo va confrontato con `row.level`, non `row.level + 1`
- [x] **Engine upgrade — esecuzione reale (eroe) VALIDATA a runtime**: Barbarian King → dialogo `Upgrade Barbarian King to Level 53?` verificato (costo 44 000 dark) → CONFIRM; **dark 198 031 → 154 031 (−44 000)**, **builder 5/5 → 4/5**, oro/elisir/gemme invariati
- [x] **Planner preset A/B mura** (config `walls.*`): con mura non max un builder resta riservato (gli edifici/eroi usano i restanti) e le mura non consumano slot (upgrade istantaneo); a mura max scatta il preset B (tutti i builder) + nota di auto-stop. Helper `walls_status` da scansione, test dedicati
- [x] **OCR nomi riga — canonicalizzazione conservativa**: match fuzzy solo su nomi noti lunghi (≥6 caratteri, similarità ≥0,86) per recuperare errori piccoli; nomi davvero illeggibili ancora scartati. Usata da `categorize`, merge, scanner e navigazione live
- [x] **Animazione UI gestita**: lo scroll del menu si anima ~1,8 s; engine attende la stabilizzazione (2 frame identici + verifica del cambio) prima di leggere/tappare — risolve le righe mappate su posizioni sbagliate
- [x] **Auto-reload disconnessione VALIDATO COMPLETO**: modal di rete → retry → reload (**4,9 s**) → **home** verificata su disconnessione reale da inattività (4 nov, nessuna spesa). Riconosce anche lo stato **`MAINTENANCE`** e va in pausa sicura senza input; ripristina la finestra se il reload la minimizza
- [x] **Esecuzione reale upgrade edificio/eroe** (riga → dialogo CONFIRM): **validata a runtime** (Air Bomb e Barbarian King, vedi sopra); il livello mostrato dal catalogo è quello di destinazione, non quello attuale
- [x] **Opzioni eroi per auto-battaglia**: `attack.use_heroes` + `attack.heroes_require_ready` (config, pronte per il loop attacco)
- [x] **Loop attacco v5 VALIDATO LIVE end-to-end (raid VINTO)**: `attack-scan`, `ARMY_REVIEW`, `PREVIEW` (OCR loot + End Battle/Next), `BATTLE` (timer, barra truppe), `BATTLE_END` + Return Home. **Camera pan** via `PostMessage` per rivelare la zona deployabile; **deploy completo: 13 draghi + 2 eroi (AQ+GW)**; esito **VICTORY 1 stella** (15% danno), bottino 59 023 oro / 53 271 elisir / 1 296 dark (HUD +288 399 oro / +265 118 elisir / +6 326 dark); ricerche ~1 100 oro ciascuna; **gemme mai spese** (1 925). Da completare: skip reale, OCR esiti, spell
- [ ] Dataset completo (~15 stati: Hero Hall, Army Recipe, eventi)
- [ ] Loop attacco completo (skip reale + deploy dragon spam affidabile + esiti)
- [x] **Wall bulk** (`Upgrade MORE`/`Select ROW`): **valutato e NON supportato** — decisione motivata e condizioni per introdurlo in [ADR-006](docs/ADR-006-bulk-walls-decisione.md); si aggiornano al massimo `walls.max_wall_batches_per_cycle` muri per ciclo, uno alla volta
- [ ] GUI PySide6 completa

## Quick start

```powershell
# 0) dipendenze + extra WGC (windows-capture) + OCR (rapidocr/onnxruntime)
python -m pip install -e ".[dev,wgc,ocr]"

# 1) controlla che la finestra del gioco sia aperta (non minimizzata)
python -m cocbot probe

# 2) controlla la config
python -m cocbot config-check --path config/config.example.yaml

# 3) cattura frame con WGC (funziona anche a finestra coperta, non minimizzata)
python -m cocbot capture --seconds 4 --fps 10 --backend wgc --out out/captures

# 4) verifica un tap non invasivo (dry-run; --execute per inviarlo davvero)
python -m cocbot input-test --x 960 --y 540

# 5) misura l'impatto del bot (CPU/RAM/FPS, sola lettura)
python -m cocbot bench --seconds 20 --fps 5

# 6) GUI minimale: Start/Stop + hotkey Ctrl+Alt+L / kill switch Ctrl+Alt+K
python -m cocbot gui

# 7) scansiona il menu Build e stampa il piano di upgrade (SOLA LETTURA, nessuna spesa)
python -m cocbot upgrade-scan                # report JSON in out/upgrade/

# 8) esegue gli upgrade pianificati (DRY-RUN di default; --execute preme CONFIRM e spende)
python -m cocbot upgrade-run                 # dry-run
python -m cocbot upgrade-run --execute       # attenzione: spend e risorse

# 9) registra un dataset di schermate etichettate (gioco in fullscreen, tap non invasivi)
python tools/record_session.py            # output in dataset/raw-<data>/ con contact-sheet.jpg

# 10) backend ADB opzionale (se installi il Developer Emulator)
python -m cocbot adb-check

# 11) loop attacco: menu Battle (SOLA LETTURA) e anteprima base senza deploy
python -m cocbot attack-scan
python -m cocbot attack-scout                # dry-run: apre My Army e chiude (nessuna spesa)
python -m cocbot attack-scout --allow-spend  # ricerca base (~1100 oro), legge loot, End Battle
```

> `probe` è **solo lettura**. `capture`/`input-test` non rubano focus né muovono il cursore.
> PNG e log restano in `out/` (ignorata da git). Nota: `windows-capture` richiede un processo a
> integrità media (avvia il bot normalmente, non dentro sandbox/AppContainer).

## Struttura

```text
config/config.example.yaml   configurazione (backend, sicurezza, attacco, upgrade, mura, GUI, humanize)
src/cocbot/
  __main__.py                CLI: probe | capture | input-test | gui | bench | config-check | adb-check
                             | upgrade-scan | upgrade-run | attack-scan | attack-scout
  app/controller.py          ciclo start/stop, cattura, pause, tap a vuoto umanizzati
  app/upgrade_engine.py      engine upgrade: HUD, scansione menu Build, planner, esecuzione verificata
  app/attack_engine.py       loop attacco: menu Battle, My Army, anteprima base (loot OCR) + policy
  core/                      tipi e contratti (ScreenSource, InputSink, Device)
  config/                    modelli pydantic + loader
  safety/humanize.py         humanization/anti-ban: ritmi, pause, rate limit, avvisi
  vision/safe_tap.py         euristiche: erba sicura per tap a vuoto + "sembra home"
  vision/ocr.py              wrapper OCR opzionale (rapidocr), TextItem con bounding box
  vision/textparse.py        parsing importi/tempi/livelli/nomi ("Wall x 284", "2h 30m")
  vision/ui.py               primitive UI: pulsanti, X, CONFIRM, modal inattività, pannello righe
  vision/build_menu.py       lettura righe menu Build (livello/tempo/costo/valuta) + dialogo conferma
  vision/states.py           classifier stato schermo (home/battle_menu/army_review/preview/build_menu/...)
  gui/                       GUI minimale tkinter + hotkey globali
  capture/
    win32.py                 wrapper ctypes (DPI, finestre, input SendInput e messaggi Win32)
    window.py                scoperta finestra gioco + coordinate canoniche
    screen_wgc.py            cattura WGC per-finestra (anche coperta) + crop area client
    screen_mss.py            cattura foreground (mss) di fallback
    input_winmsg.py          input non invasivo via messaggi Win32 (default)
    input_sendinput.py       input con focus forzato (solo test supervisionati)
    adb.py                   backend ADB (Developer Emulator / emulatori Android)
docs/ADR-002-...             decisione backend non invasivo (evidenze e limiti)
docs/ADR-003-...             humanization/anti-ban: cosa facciamo e cosa non possiamo garantire
docs/ADR-004-...             vision/OCR + geometria menu Build + engine upgrade (muri e upgrade classico validati a runtime)
docs/ADR-005-...             loop attacco: menu Battle, My Army e anteprima base (loot OCR) validati live; deploy da fare
docs/ADR-006-...             bulk walls: valutazione e decisione (non supportato in v1, condizioni)
tests/                       unit test (config, coordinate, WGC crop, winmsg, humanize, GUI hotkey,
                             vision/parser, dataset reale locale, planner/merge upgrade, pannello muro,
                             menu Battle + My Army + anteprima base + loot OCR + policy attacco)
tools/                       record_session.py (dataset), poc_wgc.py, poc_bg_input.py
dataset/                     sessioni dataset locali (IGNORATA da git: contiene dati account)
```

> Nota: i test che leggono i frame reali del menu Build si **saltano** se `dataset/` non c'è
> (screenshot gitignored). I test di geometria/classifier usano frame sintetici.


## Note di sicurezza

- Il bot **non deve mai** cliccare aree gemme/shop/offerte: vedi `GemGuard` nel piano.
- Il titolo della finestra contiene il nome account: non va loggato/mostrato (qui viene mascherato).
- Nessuna credenziale viene salvata dal bot (login manuale nell'emulatore/client).
