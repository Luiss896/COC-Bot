# ADR-005 — Loop attacco: v1 in sola lettura (menu Battle + policy loot)

**Data:** 2026-11-04 · **Stato:** Accettato — v1 implementata e testata off-line, **validata live
sul menu Battle** (apertura/chiusura, CLI `attack-scan`); **nessun raid lanciato**. Skip + deploy
dragon spam sono pianificati ma non implementati: servono frame reali di anteprima/battaglia.

## Contesto

Il progetto prevede l'auto-battaglia (`progetto-bot-coc/02-ARCHITETTURA-E-DESIGN.md` §6.1):
aprire Battaglia → anteprima/base → **skip delle basi sotto soglia loot** → attaccare → tornare in
home. Il rischio maggiore non e' nel codice di vision ma nell'**esecuzione** (deploy, esiti,
imprevisti a schermo): senza frame reali di anteprima/battaglia qualsiasi OCR/deploy sarebbe
indovinato. Inoltre le regole di progetto vietano gemme/shop e guerre/CWL.

## Decisione

V1 in **sola lettura**, in quattro parti:

1. **Stato `BATTLE_MENU`** riconosciuto senza OCR: la UI del menu Battle e' identica in windowed e
   fullscreen (frazioni), e il pulsante arancione "Find a Match" e' un marker geometrico stabile.
   `ui.find_find_match_button` filtra colore giallo/arancio, regione (x<0.30 W, y 0.58–0.83 H),
   dimensione (0.10–0.30 W, 0.06–0.14 H) e aspetto (w/h ≥ 2.2) per non confondere blob gialli
   della mappa. Misura sul frame fullscreen del dataset: rect `(119, 898, 462, 136)` su 2452×1379
   → centro ≈ (0.142 W, 0.701 H).
2. **Policy loot pura** `attack_engine.evaluate_loot(gold, elixir, dark, thresholds, weights)`:
   si attacca solo se oro/elisir/dark raggiungono le soglie **e** lo score pesato (dark ×100 di
   default) raggiunge `score_min`; **bottino illeggibile → mai attaccare**; `dark=None` non blocca
   (il bottino dark puo' mancare). E' una funzione pura, usata dall'engine e testata off-line.
   Insieme: `SkipSession` (contatori puri di `loot.max_skip_per_attack` e `loot.skip_timeout_s`,
   con motivo d'arresto) — il collegamento al flusso live arrivera' con i frame di anteprima.
3. **`AttackEngine`** (sottoclasse di `UpgradeEngine`, che riusa navigazione prudente e recovery):
   `open_battle_menu()` (tap sul pulsante Battle, attesa `BATTLE_MENU`), `close_battle_menu()`
   (tap target invisibile in alto a destra, validato live; ESC di ripiego; fallback
   `recover_home`), `scan_battle_menu()` (apre/legge/chiude).
   **Non preme mai "Find a Match"**: in v1 nessun raid viene avviato.
4. **CLI `python -m cocbot attack-scan`**: stampa stato, riquadro/centro del pulsante e note;
   nessuna spesa, nessuna battaglia.
5. **`ARMY_REVIEW`** (pannello "My Army" pre-battaglia): tap su "Find a Match" → pannello esercito
   con X rossa e pulsante verde "Attack!". `AttackEngine.open_army_panel()` / `close_army_panel()`
   validati live (2 cicli); la ricerca base (a pagamento, ~1100 oro) parte solo da "Attack!",
   che **non viene premuto** in v1.

## Evidenze

- Frame reale fullscreen `dataset/raw-20261103-1408/03_battle_menu.png`: classificato
  `BATTLE_MENU`; il pulsante "Find a Match" individuato nella posizione attesa.
- **Validato live il 4 nov** (finestra 1733×975): **2 cicli** apri → `BATTLE_MENU` → chiudi → home,
  e `python -m cocbot attack-scan` completato (exit 0). "Find a Match" misurato live:
  rect `(84, 634, 327, 96)` → frazioni (0,048 W, 0,650 H, 0,189 W, 0,098 H), coerenti col frame
  fullscreen. Frame live windowed salvato in `dataset/build-win-20261103/battle-menu-window.png`.
- **Chiusura del menu Battle**: non c'e' una X visibile; l'area di chiusura e' un tap target
  trasparente in alto a destra a (0,986 W, 0,025 H). ESC via messaggio **e** ESC via SendInput con
  focus **non** chiudono (verificato live). `ui.find_battle_menu_close` restituisce il punto solo
  se il frame e' davvero `BATTLE_MENU` (mai tappare l'angolo gemme della home).
- `UpgradeEngine.grab`: retry breve sui primi frame neri WGC (artefatto transitorio di sessione);
  `WgcScreenSource.grab` attende un frame **nuovo** (evita frame stantii) e l'engine ricrea la
  sessione WGC se riceve frame neri ripetuti.
- **Pannello "My Army" (`ARMY_REVIEW`)**: riconosciuto da X rossa + pulsante verde "Attack!".
  Live 4 nov: 2 cicli apri/chiudi pannello (home → army_review → home), nessuna spesa. Frame live
  windowed salvato in `dataset/build-win-20261103/army-review-window.png`.
- Nessun falso positivo su `01_home.png` e `02_build_menu.png` (pulsante assente).
- Policy loot: casi buono / sotto soglia / score insufficiente / bottino illeggibile /
  dark assente / pesi da config.
- **Test: 14 dedicati** (`tests/test_attack_engine.py`) + 1 sul frame live windowed; suite totale
  **137 verdi**, ruff pulito.

## Limiti noti / da validare a runtime

- **ESC non e' una via di chiusura** in questa versione del gioco: usare solo il tap target in alto
  a destra (implementato).
- **Anteprima/base e battaglia** (loot OCR, pulsanti Next/Surrender/End Battle, timer): nessun
  frame reale acquisito finora → non implementati.
- **Skip policy** (`loot.max_skip_per_attack`, `skip_timeout_s`): contatori pronti (`SkipSession`)
  ma non collegati al flusso live; **deploy dragon spam** (`attack.use_heroes`,
  `heroes_require_ready`) non implementato.
- Nessun raid avviato: la v1 non tocca bottino/trofei e non spende risorse.

## Conseguenze

Prossimi passi: acquisire frame reali di anteprima (Find a Match → screenshot → Next/Return Home
senza deployare), implementare OCR loot multi-frame + skip policy, poi deploy dragon spam,
gestione esiti e ritorno in home; solo dopo, attacco live supervisionato.
