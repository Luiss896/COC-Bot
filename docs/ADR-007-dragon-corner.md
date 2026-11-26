# ADR-007 — Strategia d'attacco DRAGON CORNER: angoli casuali, deploy immediato, invisibilità

**Data:** 2026-11-23 · **Stato:** implementata e **validata live** (23 nov 2026); aggiornata dopo il live con deploy adattivo, nuovo dialogo SURRENDER e layout card nov 2026
**Sostituisce:** il deploy di default DRAGON CLONE di ADR-005 (che resta selezionabile).

## Contesto (richiesta utente, 23 nov 2026)

Tre problemi osservati giocando con il bot:

1. **Deploy che non parte**: i punti scelti dal bot finiscono molto spesso in zone delimitate da
   edifici/mura; il tap lì apre solo l'ispezione e i draghi/gli eroi **non vengono schierati**.
2. **Attesa del countdown**: trovata la base, il bot aspetta la fine dei ~30 s del countdown
   `"Battle starts in: Ns"` prima di deployare. L'utente vuole che **inizi subito a deployare
   tutto**.
3. **Soglie di bottino**: deve attaccare solo villaggi con **oro ≥ 800k E elisir ≥ 800k** (oggi
   le soglie erano 350k/350k e il dark a 2000 era un requisito aggiuntivo).

Inoltre l'utente vuole: angolo della mappa **scelto a caso** fra i 4, **tutti i draghi in un'unica
volta** in quel punto, poi le **Invisibility Spell** ("le relative invisibilità") e gli eroi.

## Decisione

1. **Nuova strategia default `dragon_corner`** (`attack.strategy`), con `dragon_clone` e
   `dragon_spam` ancora selezionabili (config/CLI/GUI).
2. **Angolo casuale** (`attack.corner: random|nw|ne|sw|se`): a ogni raid si sceglie uno dei 4
   angoli (`pick_deploy_corner`, RNG iniettabile nei test; `--corner`/GUI possono forzarlo).
3. **Panno camera verso l'angolo** (`attack.corner_pan`, deltas `CORNER_PAN_DELTAS`): il drag via
   messaggi Win32 è già validato (ADR-005) e sposta la vista verso la fascia esterna della mappa.
4. **Punto di deploy su erba libera, mai su edifici**: `ui.grass_deploy_blobs` estrae i blob di
   erba del campo **filtrando le zone vietate** (`ui.BATTLE_FORBIDDEN_TAP_ZONES`: barra truppe,
   `Available Loot`, HUD risorse, `End Battle`/`Boost Army`, `Next`/`Overall Damage`, timer);
   `ui.find_corner_deploy_point` prende, nella metà del frame dell'angolo scelto, il blob di erba
   **più vicino all'angolo**. Fallback: erba globale → punto di griglia sicuro. Il tap su erba
   deploya sempre (meccanica validata live il 4 nov), quindi il problema "zona con edifici" è
   risolto per costruzione; in più il filtro impedisce tap accidentali su pulsanti che spendono.
5. **Deploy in un'unica volta**: card draghi selezionata una volta e N tap sullo **stesso punto**
   (intervallo `attack.deploy_interval_s`), come per Dragon Clone ma sull'angolo.
6. **Invisibility Spell sui draghi** (`attack.invisibility_spells`, default 5;
   `attack.invisibility_card_slot`, default 0 = primo slot): una card+tap per spell, con target
   che seguono il gruppo dal punto di deploy verso il centro del villaggio (ogni target passa il
   filtro delle zone vietate: in dubbio si riusa il punto dei draghi).
7. **Eroi dietro ai draghi** (offset del 4% verso il centro), come nelle strategie precedenti.
8. **Deploy immediato, senza aspettare il countdown**: `deploy_corner_phase` deploya **subito**
   mentre lo stato è `PREVIEW` (davanti al countdown). Se il gioco accetta i tap la battaglia parte
   immediatamente e si risparmiano ~30 s; se li ignora (taps innocui: solo erba/punti filtrati) il
   bot attende l'inizio della battaglia con polling ~0,2 s e **ripete il deploy**: il raid attacca
   in ogni caso. Nel report: `deploy_phase` (`preview`/`battle`), `battle_started_by_deploy`,
   `preview_deploy_ignored`, `deploy_started_after_s`, `battle_wait_s`, `corner`, `deploy_point`,
   `deploy_on_grass`.
9. **Soglie loot richieste** (`loot.thresholds`): `gold_min: 800000`, `elixir_min: 800000`,
   `dark_min: 0` (il dark è un bonus, non blocca la base), `score_min: 1600000` (= somma oro+elisir
   con i pesi 1.0 quando il dark non c'è). Il fallback "solo dark" a storage piene resta attivo.

## Implementazione

- `vision/ui.py`: `CORNER_NAMES`, `BATTLE_CORNER_ANCHORS`, `BATTLE_FORBIDDEN_TAP_ZONES`,
  `battle_tap_is_safe`, `battle_corner_anchor`, `grass_deploy_blobs`, `find_corner_deploy_point`.
- `app/attack_engine.py`: `ATTACK_STRATEGIES`, `CORNER_PAN_DELTAS`, `CornerDeploy`,
  `pick_deploy_corner`, `AttackEngine.__init__` (RNG), `pan_camera_towards_corner`,
  `_corner_deploy_point`, `_offset_towards_center`, `_invisibility_targets`,
  `deploy_dragon_corner`, `deploy_corner_phase`; `run_attack`/`run_farm` con i parametri
  `strategy`, `corner`, `invisibility`, `invisibility_card_slot`.
- `config/models.py` + `config/config.example.yaml`: nuovi campi e soglie 800k.
- `__main__.py`: `--corner`, `--invisibility`, `--invisibility-card-slot` per
  `attack-run`/`attack-farm`/`auto-run`; `--strategy` accetta `dragon_corner`; output con
  angolo/fase del deploy.
- `gui/app.py`: campi **Invisibilità** e **Angolo mappa**, strategia `dragon_corner` di default,
  messaggi di conferma con angolo/invisibilità, argomenti CLI aggiornati.
- `app/auto_engine.py`: passa i nuovi parametri ai raid di farm; il riepilogo farm include
  `corner`/`deploy_phase`.
- `tests/test_attack_corner.py`: 17 test (angolo casuale/forzato, pan, filtro zone vietate, erba
  per angolo, frame reali, ordine dei tap, fallback, fase immediata + fallback countdown, CLI,
  config).

## Aggiornamento dopo il live del 23 nov 2026 (gioco aperto, 3 raid di test)

Cosa ha insegnato il gioco reale (finestra 1733×975, UI nov 2026):

1. **Il deploy in anteprima NON è possibile**: durante il countdown "Battle starts in" il gioco
   **ignora i tap** (testato: tap su erba con card selezionata → nessuna truppa schierata).
   Il bot quindi non tenta più tap in anteprima: attende l'inizio con polling ~0,2 s e deploya
   al primo istante utile (`deploy_phase="battle"`, `battle_wait_s` nel report). È il minimo
   imposto dal gioco, quei ~30 s non sono eliminabili.
2. **Si può deployare solo sull'erba FUORI dalle mura**: i tap dentro il villaggio aprono
   l'ispezione e non schierano (era la causa dei "draghi/eroi non deployati"). Verificati live:
   alto-centro (0,50 W · 0,12 H), lato sinistro (0,10 · 0,50) e lato destro (0,90 · 0,50)
   deployano; centro, basso e angolo alto-destra (fuori mappa/edifici) no.
3. **Deploy adattivo**: per non dipendere da un singolo punto, ogni tap viene verificato dal
   **contatore "xN" della card** (diff immagine): se la truppa non scende si passa al candidato
   successivo (max `draghi+5` tentativi). Il live ha confermato la bontà del rilevamento
   (diff 0,0 sui tap a vuoto vs 14-96 sui deploy riusciti).
4. **Layout card cambiato**: la barra truppe ora include il **Barbarian King**: draghi 0,164 ·
   King 0,237 · Queen 0,310 · Warden 0,383 · spell 0,446 (prima spell a 0,383). Il bot ora
   deploya **3 eroi**.
5. **Nuovo dialogo "SURRENDER?"**: il pulsante rosso in battaglia ora si chiama "Surrender" e
   apre un modal con **Cancel** (arancio) e **Okay** (verde). Aggiunto lo stato
   `BATTLE_CONFIRM`, il rilevamento `ui.find_surrender_ok` e la conferma in
   `end_battle_early`/`recover_home` (senza, il bot restava bloccato sul dialogo).
6. **Soglie 800k**: con oro/elisir ≥ 800k ciascuno le basi valide sono più rare: nei test
   6 ricerche non hanno trovato una base ≥800k (spesa ~6.600 oro, nessun attacco). Per il farm
   conviene alzare «Ricerche max» (es. 10-20) o abbassare le soglie in config.
7. Frame reali salvati in locale (gitignored): `dataset/build-win-20261123/` — usati dai test
   (`tests/test_attack_corner.py`) per classificazione SURRENDER, card e punti candidati.

## Rischi e limiti noti

- **Countdown**: il deploy immediato "vero" non esiste (lo impone il gioco); il bot deploya al
  primo frame di battaglia e lo riporta nel report. Non provare a deployare in anteprima.
- **`invisibility_card_slot`**: l'ordine delle card dipende dall'esercito; con l'esercito attuale
  l'invisibilità è lo slot 0 (x5, verificato sul frame live del 23 nov). Se cambia, aggiornare
  `attack.invisibility_card_slot`.
- **Card eroi**: le posizioni (King/Queen/Warden) sono quelle del layout nov 2026; se un eroe è
  in upgrade la barra si compatta e le posizioni possono slittare (da rivedere in quel caso).
- **Max tentativi**: se nessun candidato deploya il bot si ferma dopo `draghi+5` tap e schiera
  comunque gli eroi sul primo candidato (per non sprecare il raid).
- **Soglie alte**: con oro/elisir ≥ 800k ciascuno le basi valide sono più rare; aumentare
  «Ricerche max»/`--max-searches` (ogni ricerca costa ~1.100 oro) o abbassare le soglie se il
  farm salta troppe basi.
- **Erba non trovata**: se né l'angolo né il resto del frame hanno erba rilevabile (base enorme,
  frame anomalo) si usa un punto di griglia sicuro con possibile ispezione (log esplicito).
- I frame usati per geometria/filtri sono quelli reali del dataset locale (1733×975); le frazioni
  scalano con la finestra, ma i nuovi punti (angoli, zone vietate) vanno riconfermati in fullscreen.
