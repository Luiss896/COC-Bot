# ADR-006 — Bulk walls ("Select ROW" / "Upgrade MORE"): valutazione e decisione

**Data:** 2026-11-04 · **Stato:** Accettato — **bulk NON supportato in v1** (decisione motivata,
condizioni per introdurlo definite sotto).

## Contesto

Il pannello azioni del muro ("Wall Upgrader", catturato in
`dataset/build-win-20261103/wall-upgrader-panel.png`) offre, oltre ai due `Upgrade` (oro/elisir):

- `Select ROW` (seleziona piu' muri);
- `Upgrade MORE` (upgrade multiplo in un colpo).

Il ciclo attuale aggiorna **un muro alla volta** dal pannello, con queste protezioni: dialogo di
conferma verificato (nome/livello/costo), budget cumulativo per valuta con riserve, limite
`walls.max_wall_batches_per_cycle` per ciclo, mai `Finish Now`/gemme.

## Decisione

**Non supportare il bulk in v1.** Motivi:

1. **Rischio di spesa aggregata non verificato**: l'upgrade multiplo richiede un dialogo con costo
   totale; nome/livello/costo "per riga" non sarebbero piu' verificabili come oggi e un errore di
   lettura potrebbe spendere molto in un solo tap.
2. **Valore marginale**: il muro e' istantaneo ma una mura costa 750 000–800 000; 2–3 muri per
   ciclo (limite gia' configurabile) coprono il ritmo di gioco, e la spesa resta tracciabile.
3. **Regola di progetto**: nessuna spesa senza budget esplicito e verificabile; il flusso bulk non
   e' stato validato a runtime (ne' il dialogo aggregato ne' i tetti).
4. Il flusso "New building" e il bulk sono gia' esclusi dalla v1 per lo stesso principio
   conservativo (vedi ADR-004).

## Condizioni per introdurlo in futuro

- config **opt-in** con default spento: `walls.bulk.enabled: false`,
  `walls.bulk.max_total_cost` per valuta, `walls.bulk.max_rows`;
- lettura e **verifica del dialogo aggregato** (costo totale atteso = somma dei muri selezionati)
  prima di qualunque conferma;
- prima un `--dry-run`/`check_only` che mostri il piano bulk, poi esecuzione solo con budget
  esplicito approvato dall'utente;
- test con frame reali del pannello e del dialogo aggregato (dataset dedicato).

## Conseguenze

- Nessun codice bulk in v1; `config.example.yaml` e README lo dichiarano esplicitamente.
- Il pannello muro resta supportato per upgrade singolo (validato a runtime il 3 nov: muro 12→13,
  −750 000 elisir, gemme invariate).
