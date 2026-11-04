# ADR-004 — Vision per il menu Build: OCR + euristiche geometriche, engine upgrade

- **Data:** 2026-11-03 (agg. 15:40)
- **Stato:** accettata; implementata e verificata a runtime per scansione/piano **ed esecuzione
  reale del flusso muro** (un muro potenziato a runtime con verifica delle risorse).
  L'esecuzione reale del dialogo upgrade di edifici/eroi standard resta da validare.
- **Contesto:** serve leggere il menu Build ("Buildings & Heroes") per pianificare gli upgrade:
  nome, livello, tempo, costo e valuta di ogni riga, più risorse e builder liberi. Il menu è una
  lista lunga (~60 righe) con scroll sintetico, e contiene righe con descrizione/sottotitolo
  ("New", "Crafting Station" + bonus), eroi e mura.

## Decisione

1. **Testo via OCR** (`rapidocr` 3.10 + `onnxruntime` 1.31, già presente su Python 3.14.8), non
   template delle cifre. Motivo: il testo è variabile (nomi, tempi, costi, dialoghi) e i template
   richiederebbero molta manutenzione; l'OCR ha coperto tutti i campi critici nei frame reali.
   - OCR **solo sul pannello destro** (più veloce) e **solo quando serve** (mai per frame).
   - `use_cls=False` (il gioco non ruota il testo): **~0.93 s** per pannello 460×975 a scala 1×.
   - La scansione completa (21 posizioni) richiede **~34 s** su questo PC, una volta per ciclo di
     pianificazione: accettabile; l'OCR non gira durante cattura/input normali.
2. **Elementi UI via euristiche cromatiche/geometriche** (nessun template da versionare):
   pulsante Build/Battle (giallo in basso), X menu (rosso in alto a destra), X dialogo (rosso a
   ~0.883×0.077), CONFIRM verde (fascia bassa del dialogo), modal inattività (rettangolo scuro
   centrale + testo azzurro), modalità piazzamento (X rossa + spunta chiara).
3. **Geometria in frazioni del frame** (valida windowed e fullscreen): il pannello Build inizia a
   **~0.730–0.734 della larghezza** (misurato identico su 1733×975 e 2452×1379), le righe hanno
   passo ~0.08 dell'altezza (77–78 px windowed, 109–110 px fullscreen), l'icona valuta è nello
   slot allineato a destra (~0.986 W). Le righe non si segmentano con i separatori (fragile):
   si ancora ogni riga al **nome** e si fondono le letture multiple della stessa riga.
4. **Sicurezza del planner**: allowlist di nomi riconosciuti (`categorize`); righe con nome
   sconosciuto (tipico OCR sbagliato) o costo/valuta illeggibili vengono **scartate**, mai
   indovinate. Edifici "New" (piazzamento) e mura sono esclusi dalla v1 dell'engine.
5. **Esecuzione reale** (solo con `upgrade.dry_run=false` e `upgrade-run --execute`): naviga alla
   riga, apre il dialogo, **rilegge titolo/livello/costo** e conferma **solo se coincidono**
   esattamente con il piano; preme solo il CONFIRM verde (mai "Hammer of Building"), poi verifica
   builder consumato e risorse scese. In caso di discrepanza chiude e si ferma.
6. **Immagini di gioco non versionate**: gli screenshot contengono dati account e restano in
   `dataset/` (gitignored). I test usano i frame locali se presenti (`skipif`) e frame sintetici
   per geometria/classificatore; nel repo non entra nessuna immagine del gioco.

## Evidenze (runtime, 3 nov 2026)

### Aggiornamento 15:40 — flusso muro validato a runtime (esecuzione reale)

- Tap sulla riga `Wall x 284` del menu Build → il gioco **non apre un dialogo**: seleziona un
  muro e mostra il pannello azioni `Info / Select ROW / Upgrade MORE / Upgrade (oro) /
  Upgrade (elisir)`. Il pannello offre **due Upgrade da 750 000**: uno in **oro**, uno in
  **elisir** (le mura di questa versione si potenziano con entrambe le valute).
- `read_wall_panel` (OCR della zona basso-centro) legge livello selezionato (12), importi e
  **valuta del pulsante**; l'engine preme solo il pulsante della valuta scelta dal piano e
  **mai** `Select ROW`/`Upgrade MORE` (bulk).
- Dopo "Upgrade" compare **anche un dialogo di conferma** ("Upgrade Wall to Level 13?"):
  l'engine verifica nome/livello/costo e preme il CONFIRM verde.
- **Esecuzione reale verificata:** piano = `Wall x 284 · 750 000 elisir`; risultato:
  elisir **7 500 945 → 6 750 945** (−750 000 esatti), oro invariato (7 323 700), **gemme
  invariate (1 925)**, builder 5/5 (upgrade istantaneo), livello selezionato **12 → 13**.
  Nessun tap su altre aree; menu chiuso e ritorno in home verificati.
- Scansione completa con stabilizzazione UI: **59 righe in 21 posizioni in 87,7 s**.

### Aggiornamento 21:52 — upgrade "classico" (edificio) validato a runtime + fix livello di destinazione

- Primo tentativo su `Air Bomb x3 [lv 3] · 37 500 oro`: il dialogo reale e' `Upgrade Air Bomb to
  Level 3?` e l'engine **ha annullato senza spendere** (confronto `livello dialogo 3 != atteso 4`).
- **Causa dimostrata:** il badge della riga del catalogo e' il **livello di destinazione**, non
  quello attuale (3 coppie riga/dialogo verificate su frame reali: clan castle **8/8**, gold mine
  **15/15**, Air Bomb **3/3**; per le mura invece il pannello mostra il livello attuale e il target
  e' `selected_level + 1`). L'executor generico confrontava `row.level + 1`: off-by-one che
  bloccava qualunque upgrade di edificio/eroe.
- **Fix:** `_execute_upgrade` confronta `dialog.target_level` con `row.level`; test di regressione
  `test_catalog_row_level_is_target_level` (dataset locale). `BuildRow.level` documentato come
  livello di destinazione.
- **Esecuzione reale verificata** (budget approvato dall'utente: 37 500 oro, tetto 50 000):
  dialogo `Upgrade Air Bomb to Level 3?`, costo **37 500**, CONFIRM verde (mai l'Hammer of
  Building) → oro **7 323 700 → 7 286 200** (−37 500 esatti), **builder 5/5 → 4/5**,
  elisir 6 750 945 / dark 198 031 / **gemme 1 925 invariati**, menu chiuso e home verificata.
- **Composizione del dialogo classico** (utile per i prossimi test): due pulsanti CONFIRM
  (Hammer of Building a sinistra, grigio; costo a destra, verde) e prezzi/tempi "Gold Pass"
  barrati. `find_confirm_button` seleziona solo il verde; `ui.find_hammer_button` esiste solo per
  diagnostica e non va premuto; `read_dialog` legge il costo dal pulsante (i barrati vengono
  scartati perche' l'OCR li legge preceduti da "-").
- Scansione: **~56 righe in 21 posizioni in ~84 s** (due run live: 83,7 s e 83,8 s).

### Aggiornamento 4 nov 09:15 — upgrade eroe validato + preset A/B mura + recovery OCR nomi

- **Upgrade eroe validato a runtime** (budget: 44 000 elisir nero, tetto 50 000): riga
  `Barbarian King [lv 53] · 44 000 dark` → dialogo `Upgrade Barbarian King to Level 53?`
  verificato (nome/costo) → CONFIRM verde → **dark 198 031 → 154 031** (−44 000 esatti),
  **builder 5/5 → 4/5**, oro/elisir/gemme invariati; menu chiuso e home verificata.
- **Preset A/B mura implementato nel planner** (`walls.*`, prima solo config): con mura non max
  un builder resta libero per le mura (gli edifici/eroi usano `builders_available - 1` slot) e le
  mura non consumano slot (upgrade istantaneo); quando dalla scansione risultano **max** scatta il
  preset B (tutti i builder) con nota; `auto_stop_when_walls_max` produce una nota di auto-stop.
  Nuovo helper `walls_status` (max/available/unknown, prudente su "unknown"), 5 test dedicati.
- **OCR nomi riga**: canonicalizzazione fuzzy **conservativa** (difflib, solo nomi noti lunghi
  ≥6 caratteri e similarità ≥0,86) usata da `categorize`, merge, scanner e navigazione live:
  recupera errori piccoli tipo `Craftina Station` → `Crafting Station`; i nomi davvero illeggibili
  (`30M Os`, `OTIUN`, `NKKSP`, `TON`) restano senza categoria e vengono scartati. Test dedicati
  al recupero e all'anti-falsi-positivo.
- Test: **119 unit test verdi**, ruff pulito.

### Altri miglioramenti della stessa sessione

- **Animazione dello scroll**: la lista Build si anima per **~1,8 s** dopo ogni evento
  `WM_MOUSEWHEEL`; leggere/tappare prima produce righe mappate su posizioni sbagliate. Ora ogni
  scroll attende la **stabilizzazione del pannello** (2 frame consecutivi quasi identici) e in
  piu' verifica che il cambio sia avvenuto (con retry), sia in scansione sia in navigazione.
- **Auto-reload disconnessione**: l'engine riconosce il modal di inattivita', preme
  `RELOAD GAME`, attende il caricamento (splash → home, timeout ~200 s) e ripristina la finestra
  se il reload l'ha minimizzata. Non ancora esercitato a runtime su una disconnessione reale.
- **Priorita' aggiornate** (scelta utente): `walls → defense → army → heroes → resources →
  other`; `upgrade.include_walls` ora **true** di default; mura limitate da
  `walls.max_wall_batches_per_cycle` e dal budget cumulativo (riserve per valuta).
- **Strategia eroi per la futura auto-battaglia**: `attack.use_heroes` e
  `attack.heroes_require_ready` (se un eroe e' in upgrade non e' schierabile → la strategia lo
  deve escludere/attendere).

### Misure base (sessione precedente, riconfermate)

- OCR pannello Build, scala 1×, `use_cls=False`: **929 ms**, 40 testi; nomi tutti corretti
  (`Barbarian King`, `Clan Castle`, `Elixir Collector x 7`, `Workshop`, `Inferno Tower`).
- Lettura righe su frame reali windowed: BK `[lv 53] 44000 dark`, Clan Castle `[lv 8] 2 500 000
  elixir`, Elixir Collector `x7 [lv 15] 600 000 gold`, righe "New"; valuta riconosciuta per
  oro/elisir/elisir nero (le mura in questa versione costano **elisir**, verificato a vista).
- Dialogo upgrade: titolo `Upgrade Clan Castle to Level 8?`, nome/livello target corretti,
  costo **2 500 000** letto dal CONFIRM (evita il prezzo barrato Gold Pass 5 000 000),
  tempo **1d** (evita il barrato 4d).
- HUD in home: oro 7 089 459 · elisir 7 500 945 · dark 195 103 · gemme 1 925 · builder 5/5.
- Scansione live completa: **62 righe uniche da 21 posizioni di scroll in 33,7 s**; piano dry-run
  con 3 upgrade scelti (BK, AQ, Minion Prince) e 21 righe scartate con motivo; risorse invariate.
- Test: 119 unit test verdi (parser, geometria sintetica, dataset locale, planner/merge, livello
  di destinazione del catalogo, preset A/B mura, canonicalizzazione OCR, anti-falsi-positivi).

### Aggiornamento 4 nov 09:15 — disconnessione reale e MAINTENANCE BREAK (validazione parziale)

- Durante il lavoro di oggi il gioco ha mostrato una **disconnessione reale** con una variante
  nuova del modal: **"Connection lost" + "TRY AGAIN"** (non solo "Anyone there? / RELOAD GAME").
  `find_inactivity_modal` riconosce **entrambe**: cerca il testo azzurro del pulsante d'azione nel
  rettangolo scuro centrale (verificato sul frame reale
  `dataset/build-win-20261103/connection-lost.png`).
- **Auto-reload esercitato sul campo:** rilevato `NETWORK_ERROR` → premuto il retry → il gioco ha
  ricaricato (frame cambiato, nessuna spesa). Il ritorno in home pero' **non e' stato osservato**
  perche' il server e' entrato in **manutenzione**: dopo il reload compare la schermata
  **"MAINTENANCE BREAK"** (calendario stagionale).
- Aggiunto lo stato **`MAINTENANCE`** (`ui.find_maintenance_banner`: frazione gialla della fascia
  alta; manutenzione 0,33 contro ≤0,15 di tutte le altre schermate reali del dataset) e la
  gestione prudente: `wait_for_load` fallisce **subito** (senza attendere i 200 s),
  `recover_home` **non preme nulla** e il bot resta in pausa. Frame reale in
  `dataset/build-win-20261103/maintenance-break.png`.
- Test: **132 unit test verdi**, ruff pulito.

## Limiti noti / da verificare

- L'OCR windowed a volte non legge il tempo (`1d`) o sbaglia nomi (`30M Os`): mitigato con merge
  delle letture, allowlist e skip conservativo; in fullscreen la stessa riga era corretta.
- **Esecuzione reale del dialogo upgrade standard** (edifici/eroi: riga → dialogo → CONFIRM):
  **validata a runtime sia su un edificio sia su un eroe** (Air Bomb 37 500 oro, Barbarian King
  44 000 dark, vedi sopra). Restano da validare il lettore fullscreen live e le righe con
  sottotitolo/descrizione (Crafting Station) nel loro flusso completo.
- **Input via `PostMessage`**: le intermittenze osservate a metà sessione erano dovute a un
  **reload del gioco fatto dall'utente mentre i test giravano** (confermato dall'utente); dopo
  il chiarimento i tap/scroll sintetici hanno funzionato per tutte le scansioni ed esecuzioni
  successive. Resta da misurare l'affidabilità su sessioni molto lunghe.
- **Reload automatico: VALIDATO COMPLETO a runtime** (4 nov, disconnessione reale da inattività):
  rilevato il modal "Connection lost", premuto il retry, reload in **4,9 s** e ritorno in **home**
  verificato. Nessuna spesa. (Prima dello stesso giorno il percorso si era fermato sulla schermata
  di manutenzione server, ora gestita come stato `MAINTENANCE` in pausa sicura.)
- Selettore di riga per "New building": catturato (dataset) ma non implementato nell'engine.
- Modal di rete: due varianti riconosciute (`Connection lost/TRY AGAIN`, `Anyone there?/RELOAD GAME`)
  e gestite con retry; **MANUTENZIONE** (`MAINTENANCE BREAK`) riconosciuta e gestita in pausa
  sicura (nessun input, attesa).
- Le righe con sottotitolo (Crafting Station) possono ancora produrre letture parziali; gli
  errori OCR "di poco" sui nomi noti ora vengono recuperati, i nomi illeggibili restano scartati.

## Conseguenze

- Nuovi moduli: `vision/ocr.py`, `vision/textparse.py`, `vision/ui.py`, `vision/build_menu.py`
  (incluso `read_wall_panel`), `vision/states.py`, `app/upgrade_engine.py` (incluso flusso muro,
  auto-reload e stabilizzazione UI).
- Nuove CLI: `cocbot upgrade-scan` (sola lettura) e `cocbot upgrade-run` (dry-run di default,
  `--execute` per spendere).
- Extra opzionale `ocr` in `pyproject.toml` (`rapidocr>=3.10`, `onnxruntime>=1.20`); corretta
  la dipendenza precedente `rapidocr-onnxruntime>=1.3` che non esiste più su PyPI.
- Config: `upgrade.priority` (default mura→difese→offensiva→eroi→risorse), `upgrade.include_walls`
  (default true), `upgrade.dry_run`, `upgrade.max_scan_scrolls`, `attack.use_heroes`,
  `attack.heroes_require_ready`.

### Aggiornamento 4 nov 11:47 — planner `--only` end-to-end con `--execute` VALIDATO live

- **`upgrade-run --execute --only "<nome>"`** completa il ciclo reale planner→navigazione→dialogo→
  CONFIRM→verifica su una riga scelta: non più solo validazioni con script fuori dal planner.
- Live: `--execute --only "Gold Mine"` → riga `Gold Mine x 7 [lv 15]` (costo 600 000 elisir) →
  upgrade **confermato e verificato**; HUD **elisir 10 000 000 → 9 400 000 (−600 000)**, builder
  **4/5 → 3/5**, oro 10 000 000 invariato, dark 174 657 e gemme 1 925 invariati; report in
  `out/upgrade/run-20261104-114721.json`.
- Scelta del target: risorse **già al cap** (oro/elisir 10 000 000) → l'upgrade usa risorse che
  sarebbero comunque state sprecate; spesa piccola e tracciata (600 000 elisir).
- **GUI tkinter**: aggiunto pannello **Attacco** (dry-run raid/scout loot/raid reale con opzioni
  ricerche max, spell, eroi, cap storage) che esegue le CLI `attack-*` in un thread e ne riversa
  l'output nel log; pulsanti disabilitati durante l'esecuzione o col bot attivo. Selftest GUI ok.
