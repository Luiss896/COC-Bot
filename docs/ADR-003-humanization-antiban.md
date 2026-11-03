# ADR-003 — Humanization e protezione account (anti-ban)

- **Data:** 3 novembre 2026 (~13:55)
- **Stato:** **accettato** (implementato e verificato; **non garantisce** l'immunità dal ban)
- **Richiesta utente:** "aggiungi un check antiban… pause random, click random, un modo per proteggere
  l'account"; rischio ban dichiarato e accettato.

## Contesto

L'utente usa l'account principale e ha accettato il rischio ban. Obiettivo: ridurre i **segnali
comportamentali semplici** (ritmi perfetti, sessioni continue, azioni ripetitive sullo stesso punto)
**senza** introdurre azioni rischiose in gioco (mai gemme/shop/guerre, mai stati "impossibili").

## Cosa NON possiamo promettere (onestà)

- **Nessuna garanzia**: Supercell può rilevare l'automazione lato server, da pattern di input e tempi,
  da incongruenze di sessione o da segnalazioni manuali. Le misure sotto riducono solo **alcune** euristiche.
- La protezione più efficace resta **non automatizzare** o usare un **account dedicato**; il rischio
  residuo sull'account principale è dichiarato e accettato dall'utente.

## Cosa è stato implementato

| Misura | Modulo | Comportamento |
|---|---|---|
| Ritmi variabili | `safety/humanize.py` (`Humanizer`) | ritardo tra azioni 350–1200 ms, distribuzione sbilanciata (più corti frequenti, coda lunga); minimo 0,25 s |
| Pause brevi casuali | `Humanizer.maybe_break_s` | ~2% per azione, 8–45 s ("distrazione") |
| Pause lunghe periodiche | `Humanizer.long_break_due` | ogni 25 min, 60–180 s |
| Tap a vuoto "umani" | `vision/safe_tap.py` + `Humanizer.maybe_idle_tap` | ~5%, **solo su erba vuota** (colore HSV + margini UI + patch uniforme), mai su gemme/shop |
| Gate di sicurezza | `vision/safe_tap.looks_like_home` | i tap a vuoto avvengono solo se la schermata "sembra home" (verde + pulsanti gialli Battle/Build) |
| Rate limit | `safety/humanize.py` (`AntiBanMonitor`) | max 30 azioni/minuto, attesa automatica |
| Rilevazione pattern | `AntiBanMonitor.warnings` | stesso punto ripetuto >8 volte, poca varietà di click, sessioni lunghe senza pause → avvisi in GUI |
| Kill switch | `gui/hotkey.py` | hotkey globale `Ctrl+Alt+K` (F12 è occupato su questo PC) + pulsante Stop |
| Trasparenza | GUI | mostra azioni, pause, sessioni e avvisi anti-ban in tempo reale |

Non usiamo tecniche invasive (lettura di memoria del gioco, injection, patch del client) né azioni che un
umano non potrebbe fare (rate impossibili, click in pixel non visibili, ecc.).

## Impatto sulle prestazioni (requisito "non interferire")

Misurato con `python -m cocbot bench --seconds 20 --fps 5`:
- CPU processo: **6,6% di un core** (dopo il throttle WGC `minimum_update_interval`; prima era 65%);
- RAM working set: **~74 MB**; frame stale/neri: 0; cattura 4,9 FPS (sufficiente per il bot).

## Rischi residui e limiti

1. L'euristica "home" è provvisoria: il **classifier stati** (prossimo passo) renderà i gate molto più
   affidabili e ridurrà tap inutili in stati sconosciuti (`UNKNOWN → nessun tap`).
2. I tap a vuoto non addestrano il gioco ma non sono "invisibili": un osservatore umano può notare un bot.
3. Le pause riducono il throughput: con pause umanizzate il bot è più lento (accettato).
4. Se l'utente interagisce col PC, il bot continua a catturare e a fare tap a vuoto **senza rubare
   focus/cursore**; il gioco resta in background.

## Verifica

- Test automatici: **33 verdi** (inclusi humanizer, anti-ban, hotkey parsing, euristiche safe-tap su frame reale).
- `ruff check src tests` pulito; `config-check` valido; GUI `--selftest` OK (hotkey registrate).
- Bench come sopra.
