# ADR-002 — Backend consumer non invasivo: WGC per la cattura, messaggi Win32 per l'input

- **Data:** 3 novembre 2026 (ore 13:35)
- **Stato:** **accettato** (POC verificate a runtime su GPGPC consumer)
- **Contesto:** requisito utente **"il bot deve girare mentre uso il PC senza interferire"**
- **Sostituisce parzialmente:** ADR-001 (cattura WGC, ancora valido) e l'assunzione "input = SendInput con focus"

## Contesto

Il backend consumer GPGPC (gioco nella finestra del processo `crosvm.exe`) non espone ADB.
L'approccio originale era: cattura WGC/DXGI + input `SendInput` **forzando il focus** con
`AttachThreadInput`. Il focus forzato e il movimento del cursore **interferiscono con l'utente**
(mouse/tastiera rubati, finestra che passa davanti), quindi l'approccio non soddisfa il requisito.

## Decisione

Il backend consumer resta quello primario, con due componenti **non invasive**:

| Componente | Tecnologia | Comportamento |
|---|---|---|
| Cattura | **Windows Graphics Capture** (`windows-capture` 2.0.1) | cattura la **finestra** del gioco anche se coperta; nessun focus, nessun cursore |
| Input | **Messaggi Win32** (`WM_MOUSEMOVE` / `WM_LBUTTONDOWN` / `WM_LBUTTONUP` via `PostMessage`) | click accodati alla finestra del gioco senza portarla in foreground e senza muovere il cursore |

Implementazione: `src/cocbot/capture/screen_wgc.py` (`WgcScreenSource`) e
`src/cocbot/capture/input_winmsg.py` (`WinMsgSink`), CLI `capture --backend wgc` e `input-test`.

## Evidenze (runtime, 3 novembre 2026 13:25–13:35)

Misure reali sul PC, gioco aperto in home village, finestra del gioco **non** in foreground
(foreground = Brave), finestra client 1733×975 @ DPI 120:

| Verifica | Risultato |
|---|---|
| Cattura WGC finestra gioco (6 s) | **273 frame, 47,4 FPS**, 0 frame neri, frame con il villaggio |
| Cattura WGC "coperta" | funziona con `foreground: False` (contenuto aggiornato, non stale) |
| CLI end-to-end `capture --backend wgc` (3 s) | **132 frame, 47,7 FPS**, 0 neri, 15 PNG salvati |
| Frame WGC grezzo | 1735×1014 (include il bordo/titolo) → **crop a 1733×975** area client, offset (1, 39) |
| Input non invasivo: tap canonico (960, 540) | apre il pannello "Eagle Artillery (Level 3)" (delta frame 8,17) |
| Input: tap su erba vuota | chiude il pannello / cambia selezione come un tap reale |
| Interferenza misurata | **foreground invariato** (0x20610 = browser) e **cursore invariato** |

## Vincoli e limiti noti

1. **La finestra del gioco non deve essere minimizzata**: WGC non cattura finestre minimizzate.
   Se l'utente minimizza il gioco, il bot deve mettersi in pausa (stato `PAUSED`, non click alla cieca).
   Coprire la finestra con altre finestre invece va bene.
2. **Sandbox/integrità:** un processo a **bassa integrità** (es. sandbox DSH) riceve
   `Failed to convert item to GraphicsCaptureItem` e non può usare WGC; il bot va lanciato
   normalmente dall'utente (integrità media). I POC di sviluppo vanno eseguiti fuori dal sandbox.
3. **Fullscreen**: il caso "borderless fullscreen" è supportato per costruzione (frame e client
   coincidono → crop (0,0,2560,1440)); **da verificare a runtime** quando l'utente passa a fullscreen
   (in particolare: se GPGPC usa true fullscreen esclusivo, WGC può non funzionare → rilevare e avvisare).
4. **Tasti:** `key()` via messaggi è best-effort (il gioco può ignorare i tasti sintetici); il back/ESC
   va verificato; per ora i flussi si basano solo su tap.
5. **Fragilità:** il gioco accetta i messaggi sintetici per questa versione; va ri-verificato a ogni
   aggiornamento di GPGPC/CoC. In caso di fallimento: fallback Developer Emulator + ADB.
6. **Sicurezza/privacy:** il titolo della finestra contiene il nome account → mascherato ovunque;
   gli screenshot contengono dati account → restano locali (`out/` è in `.gitignore`).

## Alternative scartate

| Alternativa | Motivo |
|---|---|
| `SendInput` + focus forzato | interferisce (requisito utente) |
| `mss` (copia schermo) | cattura solo il visibile; con finestra coperta si cattura il browser sopra |
| `PrintWindow` | contenuto non garantito/inaffidabile (ADR-001) |
| DXGI Desktop Duplication | cattura il monitor, non la finestra coperta |

## Conseguenze sul piano

- La scelta "consumer-first" resta valida **anche senza** il vincolo del disco; il Developer Emulator
  + ADB diventa un **fallback opzionale** (utile se serve giocare con finestra minimizzata o in CI).
- Il limite del "PC occupato" del piano originale **non vale più**: il bot può girare in background;
  resta da misurare l'impatto CPU/RAM (in corso).
- La GUI minimale (start/stop + hotkey globale `Ctrl+Alt+L`) può restare in background e non ruba focus.
