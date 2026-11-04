# ADR-005 — Loop attacco: menu Battle, anteprima esercito, anteprima base e battaglia (v3)

**Data:** 2026-11-04 · **Stato:** implementata e validata live fino alla **battaglia reale**
(menu Battle, My Army, anteprima base con OCR loot, stati `BATTLE`/`BATTLE_END`, uscita sicura).
**Deploy sperimentale**: 4 draghi deployati su una battaglia reale (11% danno, Defeat); il deploy
affidabile, lo skip reale e la gestione esiti non sono ancora completi.

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

## Limiti noti / da validare

- **Deploy**: funziona (6 draghi, 14% danno, bottino incassato) ma restano truppe non schierate per
  le poche tessere visibili: serve **camera pan** e/o passate multiple piu' lunghe. Eroi/spell:
  tentati, non ancora deployati.
- **"Next"** (skip reale) non e' stato premuto live: ogni skip costa ~1100 oro.
- `SkipSession` e policy loot sono pronte ma non collegate a un loop skip+attack completo.
- I raid eseguiti sono finiti in **Defeat** (nessuna stella, ma con bottino): strategia da tarare
  (camera pan, eroi/spell, early-exit).

## Conseguenze

Prossimi passi: catturare la fase di battaglia (senza deployare, poi con deploy controllato),
implementare la sequenza di deploy Dragon Spam con early-exit, gestione esiti e ritorno in home;
collegare `SkipSession` al loop "Next finche' base buona"; poi attacco live supervisionato con
tetto di spesa per ricerca/skip.
