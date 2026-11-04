# ADR-005 — Loop attacco: menu Battle, anteprima esercito, anteprima base e battaglia (v7)

**Data:** 2026-11-04 · **Stato:** implementata e **validata live end-to-end**: menu Battle, My Army,
anteprima con OCR loot, **skip reale ("Next")**, battaglia con **camera pan + 13 draghi + 2 eroi +
spell**, esito (Victory), **OCR esiti**, bottino incassato e ritorno in home (gemme mai spese).
Restano: early-exit, telemetria e attacchi "cap-aware" (storage piene).

## Contesto

Il progetto prevede l'auto-battaglia (`progetto-bot-coc/02-ARCHITETTURA-E-DESIGN.md` §6.1):
aprire Battaglia → anteprima/base → **skip delle basi sotto soglia loot** → attaccare → tornare in
home. Le regole di progetto vietano gemme/shop e guerre/CWL; le azioni che spendono (ricerca base,
skip) devono essere esplicite e tracciate.

## Decisione

1. **Stato `BATTLE_MENU`** riconosciuto senza OCR: la UI e' identica in windowed e fullscreen
   (frazioni) e il pulsante arancione "Find a Match" e' un marker stabile.
   `ui.find_find_match_button` filtra colore, regione (x<0.30 W, y 0.58–0.83 H), dimensione
   (0.10–0.30 W, 0.06–0.14 H) e aspetto (w/h ≥ 2.2). Live: rect `(84, 634, 327, 96)` su 1733×975.
   Chiusura: **non c'e' una X visibile**; l'area di chiusura e' un tap target trasparente in alto
   a destra a (0,986 W, 0,025 H). ESC (messaggio e SendInput) **non** chiude.
2. **Stato `ARMY_REVIEW`** ("My Army", anteprima esercito): X rossa in alto a destra del pannello
   (0,919 W, 0,139 H) e pulsante verde "Attack!" (0,849 W, 0,852 H). Tap su "Find a Match" apre
   questo pannello; la **ricerca base a pagamento (~1100 oro) parte solo da "Attack!"**.
3. **Stato `PREVIEW`** (anteprima base): pulsante rosso "End Battle" (basso a sinistra,
   ~0,059 W / 0,790 H), pulsante arancione "Next" (basso a destra, ~0,93 W / 0,73 H), timer
   "Battle starts in: Ns" in alto al centro. Il bottino ("Available Loot") si legge con OCR nella
   regione (0,00–0,18 W, 0,10–0,24 H): **3 importi in ordine oro / elisir / dark** (verificato
   sul frame reale: 225 713 · 170 241 · 3 313).
4. **Policy loot pura** `evaluate_loot`: si attacca solo se oro/elisir/dark raggiungono le soglie
   **e** lo score pesato (dark ×100 di default) raggiunge `score_min`; bottino illeggibile → mai
   attaccare; `dark=None` non blocca. `evaluate_loot_from_config` applica `loot.thresholds`/
   `loot.weights`. `SkipSession` conta skip e timeout (`loot.max_skip_per_attack`,
   `loot.skip_timeout_s`).
5. **`AttackEngine`** (sottoclasse di `UpgradeEngine`): `open_battle_menu`/`close_battle_menu`/
   `scan_battle_menu`, `open_army_panel`/`close_army_panel`, `open_search` (spende ~1100 oro),
   `read_loot` (OCR), `next_base` (spende ~1100 oro), `end_battle` (torna in home **senza
   deployare**). `recover_home` sa uscire da `BATTLE_MENU`, `ARMY_REVIEW` e `PREVIEW`.
6. **CLI**: `python -m cocbot attack-scan` (sola lettura, nessuna spesa) e
   `python -m cocbot attack-scout` (dry-run: apre il pannello My Army e chiude; con
   `--allow-spend` avvia la ricerca, legge il loot, decide e torna in home senza deployare).

## Evidenze (live 4 nov 2026, finestra 1733×975)

- **Menu Battle**: 2 cicli apri → `BATTLE_MENU` → chiudi → home + `attack-scan` exit 0.
- **My Army**: 2 cicli apri/chiudi pannello, nessuna spesa.
- **Anteprima base (1° scout)**: loot letto = **225 713 oro · 170 241 elisir · 3 313 dark**;
  decisione con config default = **SALTA** (elisir < 350 000); "End Battle" → home senza conferma
  e **senza deploy**. Costo ricerca misurato: oro 8 687 509 → 8 686 409 (**−1 100 esatti**),
  elisir/dark/gemme invariati, builder 4/5.
- **Anteprima base (2° scout, CLI `attack-scout --allow-spend`)**: loot = 583 992 / 230 433 /
  4 922 → decisione **SALTA** (elisir sotto soglia; score 1 306 625); "End Battle" → home;
  oro 8 686 409 → 8 685 309 (−1 100), altri valori invariati.
- Frame reali salvati nel dataset locale: `battle-menu-window.png`, `army-review-window.png`,
  `scout-screen-window.png` (gitignored: dati account).
- Fix WGC trovati validando: `WgcScreenSource.grab` attende un frame **nuovo** (evita frame
  stantii); `UpgradeEngine.grab` riprova e ricrea la sessione su frame neri ripetuti.
- **Test: suite 142 verdi** (18 dedicati al loop attacco con parse loot/decisioni/geometrie),
  ruff pulito.

### Prime battaglie reali (4 nov, 10:20–10:45) — deploy parziale

- **Flusso completo validato live**: `open_search` → anteprima → (non premendo End Battle) countdown
  "Battle starts in" → **`BATTLE`** (timer "Battle ends in 3:00", barra truppe, End Battle) →
  fine battaglia → **`BATTLE_END`** (banner Defeat/Victory, "Return Home") → home. `end_battle` e
  `return_home` funzionano: uscita **immediata, senza conferma**, anche durante la battaglia.
- **Deploy**: il tap sulla card **seleziona** la truppa (la card si ingrandisce; l'hover no). Il tap
  sul campo deploya **solo su tessere di erba libera**: su edifici/muri il gioco apre l'ispezione
  (tooltip) e non deploya. Con punti fissi sbagliati → 0 truppe (Defeat 0%). Con tessere di erba
  libera (striscia in basso a destra) → **4 draghi deployati**, contatore card **x13→x9** verificato
  sui frame, **11% di danno**, Defeat, Return Home OK.
- **Limiti emersi**: il rilevamento dell'erba dipende da base/camera (in un tentativo solo 2 blob →
  0 deploy); il contatore "xN" della card **non e' leggibile via OCR** (font stilizzato) e va
  rilevato per differenza immagine. Prossimo passo: **sweep a griglia** di tap sul campo (i tap fuori
  bersaglio ispezionano soltanto) con rilevamento del contatore per diff.
- **Costi e sicurezza**: 11 ricerche base × 1 100 oro = **12 100 oro** (HUD 8 687 509 → 8 675 409);
  **gemme sempre 1 925 (mai spese)**; nessuna chiusura del gioco durante le battaglie.
- **Nota HUD**: la lettura subito dopo "Return Home" puo' capitare su un frame di transizione e
  dare valori sbagliati (visto una volta: riletta a schermo stabile → valori corretti).

### Aggiornamento 11:05 — deploy a due passate e primo raid **profittevole**

- **Due passate**: dopo la selezione (che **resta attiva**, non va ritoccata la card: un secondo tap
  rischia di deselezionarla) si prova erba rilevata + griglia; se restano truppe si attende 3 s e si
  ripassano le stesse tessere (le truppe liberano le celle). Risultato live: **6 draghi deployati**
  (contro 4 del giro singolo), contatore card x13→x7 coerente con "Troops expended x6".
- **Battaglie e bottino (live)**: con 4 draghi → 9% danno, **bottino incassato 126 794 oro /
  402 741 elisir**; con 6 draghi → 14% danno, **112 000 oro / 58 510 elisir / 154 dark**.
  Le ricerche costano 1 100 oro → i raid sono **netti positivi** in risorse; gemme sempre 1 925.
- **Limite attuale**: restano da schierare ~7 draghi perché in un solo inquadramento le tessere
  deployabili visibili sono poche (deploy zone attorno al villaggio, in parte fuori schermo).
  Prossimo passo: **pannare la camera** prima del deploy per esporre più zona deployabile, oppure
  aspettare in due/tre passate con pause più lunghe. Eroi: tentati, non ancora deployati.
- Frame risultati con bottino salvato in `dataset/build-win-20261103/battle-results-loot-window.png`.

### Aggiornamento 11:16 — camera pan + raid completo **VINTO** (13 draghi + 2 eroi)

- **Camera pan validato**: drag sul campo via `PostMessage` (`win32.post_mouse_drag`) **prima** di
  selezionare la truppa: la vista si sposta e rivela la zona deployabile (erba con tessere
  tratteggiate) attorno al villaggio. Con la truppa selezionata il drag non panna.
- **Deploy completo**: pan → selezione draghi → tap sulle tessere di erba rivelate (due passate,
  contatore verificato per diff) → **13 draghi su 13 deployati** → eroi (**AQ 65 + Grand Warden 40**
  deployati con card+tap). Risultato live: **VICTORY, 1 stella, 15% danno**; "Troops expended:
  x13 draghi + AQ + GW"; bottino battaglia **59 023 oro / 53 271 elisir / 1 296 dark**
  (HUD +288 399 oro / +265 118 elisir / +6 326 dark); ritorno in home OK; gemme 1 925 invariate.
- Frame vittoria salvato in `dataset/build-win-20261103/battle-end-victory-window.png`.
- **Il loop attacco è quindi validato end-to-end**: ricerca → My Army → battaglia → pan+deploy →
  esito (Vittoria/Sconfitta) → bottino → "Return Home".

## Limiti noti / da validare

- **Storage piene**: gestito il caso base (vedi aggiornamento 11:40). Resta da gestire la
  priorità al dark elixir quando oro/elisir sono al cap.
- **Early-exit in battaglia**: non implementato (si attende sempre la fine, max ~3 min).
- **Robustezza deploy**: dipende dal rilevamento dell'erba per-base/camera; con pan funziona, ma
  vanno provate più basi e fallback (griglia già in uso).

## Conseguenze

Prossimi passi: **early-exit** in battaglia, priorità dark a storage piene, telemetria aggregata
(storico raid), poi attacco live supervisionato con tetto di spesa per ricerca/skip.

### Aggiornamento 11:40 — attacco **cap-aware** e telemetria raid

- **Cap-aware validato live**: `run_attack` legge l'HUD **prima** di spendere una ricerca; con
  oro+elisir al cap (`attack.storage_cap_gold/elixir`, default 10 000 000) risponde
  `action=storage_full` e **non spende nulla**. Live (11:40): HUD oro/elisir 10 000 000/10 000 000 →
  capacità residua 0/0 → `storage_full`, ricerche=0, HUD invariato, gemme 1 925. `--ignore-caps`
  permette di forzare il raid.
- **Bottino incassabile**: la decisione usa `apply_capacity` (min tra loot e capacità residua), così
  non si attacca per risorse che andrebbero perse; il report riporta `incassabile_gold/elixir`.
- **Telemetria**: ogni raid salva un JSON in `out/attack/attack-<timestamp>.json` (gitignored) con
  ricerche/skip, bottini, capacità, esito OCR, HUD prima/dopo e percorso del report.

### Aggiornamento 12:03 — **early-exit in battaglia** validato live

- Implementato `run_attack(early_exit_damage=N)`: durante la battaglia legge "Overall Damage"
  (regione in basso a destra, OCR piccolo ~0,15 s) e quando il danno raggiunge la soglia preme
  **"End Battle"** (`end_battle_early`: se compare un dialogo conferma col CONFIRM verde), poi
  attende i risultati e torna in home. CLI: `attack-run --early-exit-damage 40`.
- **Live (4 nov 12:03)**: raid con 13 draghi + 2 eroi + 5 spell; early-exit scattato a **41%**
  (soglia 40); risultati raggiunti e letti (Victory, danno finale 84%) e Return Home; HUD
  **+549 872 oro / +521 730 elisir / +8 496 dark**; gemme 1 925. La lettura del bottino dal frame ha
  però restituito `None`: il frame vittoria non mostrava l'etichetta "You got:" → aggiunto al parser
  un **fallback per posizione** (importi nella fascia centrale, ≥1000, con nota) + test.

### Aggiornamento 11:45 — skip reale ("Next") e spell validati live; raid **VITTORIA 79%**

- **"Next" validato live**: anteprima A (loot 300 014 / 819 462 / 562) → "Next" (~1 100 oro) →
  anteprima B **diversa** (173 042 / 146 738 / 13 828) → End Battle. Il cambio base e la rilettura
  del loot funzionano. `run_attack` ora applica anche `SkipSession` (`loot.max_skip_per_attack`,
  `loot.skip_timeout_s`) oltre al tetto `max_searches`.
- **Spell validate live**: `deploy_spells` (card spell → tap sul campo) lancia 5 spell; nel raid:
  **13 draghi + 2 eroi + 5 spell** → **VICTORY, 79% danno**; bottino **555 000 oro / 1 093 570
  elisir / 5 958 dark** ("Troops expended" 18); Return Home OK; gemme 1 925 invariate.
- **Limite scoperto**: le risorse dell'account sono arrivate al **tetto** (oro/elisir 10 000 000):
  il bottino in eccesso va perso. Prossimo miglioramento: **leggere l'HUD prima di attaccare** e
  non sprecare raid quando le storage sono piene (o dare priorità al dark elixir).
- Frame anteprima dopo "Next" salvato in `dataset/build-win-20261103/preview-next-base.png`.

### Aggiornamento 11:27 — `attack-run`: ciclo completo live + OCR esiti

- **CLI `attack-run`** implementata: dry-run di default; con `--allow-spend --max-searches N`
  esegue ricerca (ed eventuali "Next"), pan camera, deploy draghi+eroi, attesa esiti, OCR della
  schermata risultati, ritorno in home; `--max-searches` è il tetto di spesa (≈1100 oro/ricerca).
- **OCR esiti** implementato in `vision/battle_result.py` (`BattleResult`: esito Victory/Defeat,
  % danno, bottino oro/elisir/dark, truppe spese) con parser puro + test su frame reali
  (vittoria 15% → 59 023/53 271/1 296, defeat 14% → 112 000/58 510/154).
- **Validazione live** (4 nov 11:27): una ricerca (1 100 oro) → base con loot buono (813 171 /
  813 178 / 15 668) → pan → **13 draghi + AQ/GW** (35 tap, 13/13 rilevati) → esito **defeat 2%**
  letto dall'OCR (bottino 26 675 oro / 14 941 elisir / 457 dark, truppe 13) → Return Home.
  HUD: oro 9 261 405 → 9 702 871, elisir 9 199 187 → 9 447 077, dark 160 511 → 168 099
  (include bottino raid e loot cart/collector), gemme 1 925 invariate.
