# ADR-005 — Loop attacco: v1 in sola lettura (menu Battle + policy loot)

**Data:** 2026-11-04 · **Stato:** Accettato — v1 implementata e testata off-line; **nessun raid
lanciato**. Skip + deploy dragon spam sono pianificati ma non implementati: servono frame reali di
anteprima/battaglia.

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
3. **`AttackEngine`** (sottoclasse di `UpgradeEngine`, che riusa navigazione prudente e recovery):
   `open_battle_menu()` (tap sul pulsante Battle, attesa `BATTLE_MENU`), `close_battle_menu()`
   (ESC via messaggio Win32, fallback `recover_home`), `scan_battle_menu()` (apre/legge/chiude).
   **Non preme mai "Find a Match"**: in v1 nessun raid viene avviato.
4. **CLI `python -m cocbot attack-scan`**: stampa stato, riquadro/centro del pulsante e note;
   nessuna spesa, nessuna battaglia.

## Evidenze

- Frame reale fullscreen `dataset/raw-20261103-1408/03_battle_menu.png`: classificato
  `BATTLE_MENU`; il pulsante "Find a Match" individuato nella posizione attesa.
- Nessun falso positivo su `01_home.png` e `02_build_menu.png` (pulsante assente).
- Policy loot: casi buono / sotto soglia / score insufficiente / bottino illeggibile /
  dark assente / pesi da config.
- 10 test dedicati (`tests/test_attack_engine.py`), suite totale verde, ruff pulito.

## Limiti noti / da validare a runtime

- **Chiusura del menu Battle live**: ESC via messaggio + fallback `recover_home` sono ragionevoli
  ma **non ancora esercitati** su schermo reale.
- **Anteprima/base e battaglia** (loot OCR, pulsanti Next/Surrender/End Battle, timer): nessun
  frame reale acquisito finora → non implementati.
- **Skip policy** (`loot.max_skip_per_attack`, `skip_timeout_s`) e **deploy dragon spam**
  (`attack.use_heroes`, `heroes_require_ready`) non implementati.
- Nessun raid avviato: la v1 non tocca bottino/trofei e non spende risorse.

## Conseguenze

Prossimi passi: acquisire frame reali di anteprima (Find a Match → screenshot → Next/Return Home
senza deployare), implementare OCR loot multi-frame + skip policy, poi deploy dragon spam,
gestione esiti e ritorno in home; solo dopo, attacco live supervisionato.
