# ADR-005 — Loop attacco: menu Battle, anteprima esercito e anteprima base (v2)

**Data:** 2026-11-04 · **Stato:** implementata e **validata live fino all'anteprima base**
(menu Battle, pannello My Army, anteprima base con OCR loot, decisione e uscita sicura).
**Nessun deploy eseguito**: battaglia, skip reale e gestione esiti non sono implementati.

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

## Limiti noti / da validare

- **Deploy e battaglia reale** non implementati: mancano i frame della fase di battaglia (timer
  "Battle starts in", barra truppe, deploy dragon spam) e la gestione esiti/trofei.
- **"Next"** (skip reale) non e' stato premuto live: ogni skip costa ~1100 oro, da autorizzare
  nel piano di spesa del loop.
- Timer di preparazione: osservato "Battle starts in: 26s"; la fase di battaglia vera non e' stata
  catturata (uscita prima del countdown).
- `SkipSession` e policy loot sono pronte ma non collegate a un loop skip+attack completo.
- Nessun raid completato: nessun deploy, bottino/trofei dell'account invariati.

## Conseguenze

Prossimi passi: catturare la fase di battaglia (senza deployare, poi con deploy controllato),
implementare la sequenza di deploy Dragon Spam con early-exit, gestione esiti e ritorno in home;
collegare `SkipSession` al loop "Next finche' base buona"; poi attacco live supervisionato con
tetto di spesa per ricerca/skip.
