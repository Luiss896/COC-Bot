# ADR-004 — Vision per il menu Build: OCR + euristiche geometriche, engine upgrade

- **Data:** 2026-11-03
- **Stato:** accettata; implementata e verificata a runtime per scansione/piano; esecuzione reale
  degli upgrade **implementata ma mai eseguita** (dry-run di default).
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
- Test: 105 unit test verdi (parser, geometria sintetica, dataset locale, planner/merge).

## Limiti noti / da verificare

- L'OCR windowed a volte non legge il tempo (`1d`) o sbaglia nomi (`30M Os`): mitigato con merge
  delle letture, allowlist e skip conservativo; in fullscreen la stessa riga era corretta.
- L'**esecuzione reale** del CONFIRM non è mai stata eseguita (nessuna spesa): da validare in una
  sessione dedicata con un upgrade economico e budget esplicito.
- **Input via `PostMessage`**: dopo la ricarica del gioco per inattività, i messaggi sintetici
  risultano ignorati in modo intermittente (un click reale via SendInput funziona; la finestra era
  in foreground). Ipotesi: attivazione/focus della finestra o filtro anti-iniezione del client.
  Da indagare: finché non è risolto, il backend non invasivo non è garantito per sessioni lunghe.
- Modal inattività: riconosciuto (`NETWORK_ERROR`) e **non** viene premuto automaticamente
  "RELOAD GAME" in v1; il bot si ferma e lo segnala.
- Selettore di riga per "New building" e flusso wall-upgrader: catturati (dataset) ma non
  implementati nell'engine.

## Conseguenze

- Nuovi moduli: `vision/ocr.py`, `vision/textparse.py`, `vision/ui.py`, `vision/build_menu.py`,
  `vision/states.py`, `app/upgrade_engine.py`.
- Nuove CLI: `cocbot upgrade-scan` (sola lettura) e `cocbot upgrade-run` (dry-run di default,
  `--execute` per spendere).
- Extra opzionale `ocr` in `pyproject.toml` (`rapidocr>=3.10`, `onnxruntime>=1.20`); corretta
  la dipendenza precedente `rapidocr-onnxruntime>=1.3` che non esiste più su PyPI.
- Config: nuovi campi `upgrade.priority`, `upgrade.dry_run`, `upgrade.include_walls`,
  `upgrade.max_scan_scrolls`.
