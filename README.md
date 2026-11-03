# cocbot — agente di automazione visiva per Clash of Clans (Google Play Games on PC)

> **Progetto personale/didattico.** Automatizzare Clash of Clans viola la Safe and Fair Play Policy e i
> Termini di Servizio di Supercell e può comportare il ban dell'account. Usare solo con un account
> dedicato, sessioni brevi e nessuna distribuzione. Vedi `../progetto-bot-coc/05-RISCHI-SICUREZZA-ETICA-LEGALE.md`.

Repository di sviluppo del bot. Il piano completo è in [`../progetto-bot-coc/`](../progetto-bot-coc/00-PIANO-GENERALE.md).

## Decisioni correnti (3 novembre 2026 — aggiornate 13:35)

| Tema | Decisione |
|---|---|
| **Backend primario** | **GPGPC consumer**: cattura **WGC** (finestra anche coperta, 47 FPS misurati) + input **messaggi Win32** (nessun focus, nessun cursore). Vedi [ADR-002](docs/ADR-002-backend-consumer-non-invasivo.md). |
| **Backend secondario (opzionale)** | **Developer Emulator + ADB**: codice pronto, non installato; fallback se serve giocare con finestra minimizzata/CI. **Mai** patch del consumer. |
| **Lingua gioco** | **Inglese — verificata** al primo screenshot (HUD `Battle`/`Build`/`Shop`); l'italiano resta supportato come secondo profilo. |
| **Account** | Si usa l'account **esistente** dell'utente (non dedicato): rischio ban dichiarato e accettato. |
| **Priorità** | Bot funzionante prima; materiale d'esame dopo (non guida le scelte tecniche). |
| **Sicurezza** | `dry_run` di default; GemGuard (mai gemme); kill switch; niente IAP; niente guerre/CWL. |
| **Avvio del gioco** | **Manuale** dell'utente: il bot rileva la finestra di gioco già aperta e si aggancia; **non avvia** GPGPC né il gioco. |
| **Avvio/stop del bot** | **Manuale**, da GUI con hotkey globale configurabile: default `Ctrl+Alt+L` (config `gui.hotkey_start_stop`). |
| **Zero interferenza** | **Validato**: WGC cattura anche coperta (47,4 FPS, 0 neri) e i click via messaggi aprono/chiudono pannelli **senza cambiare foreground né cursore**. |
| **Vincolo finestra** | Il gioco **non deve essere minimizzato** (WGC non cattura finestre minimizzate): il bot va in pausa. Coperta sì; fullscreen borderless da testare. |
| **Limiti** | **Nessuno di default** (sessione illimitata); limiti solo se impostati dalla GUI. **Auto-stop** quando non c'è più nulla da fare: mura max + tutti i muratori occupati + risorse max. |
| **Builder/mura** | Preset **A**: 1 builder libero riservato alle mura (upgrade istantaneo); passaggio automatico a **B** quando tutte le mura sono max (tutti i builder lavorano). Config `walls.*`. |
| **Backup git** | Remote configurato: `git@github.com:Luiss896/COC-Bot.git` (SSH, branch `main`). |

## Stato

- [x] Piano completo (7 documenti) in `../progetto-bot-coc/`
- [x] POC: finestra gioco GPGPC consumer individuata (`crosvm`, 16:9, DPI 125%), input `SendInput` verificato, cattura foreground funzionante, `PrintWindow` scartato (contenuto non affidabile)
- [x] Scaffold repo: config, tipi/contratti, finestra, cattura mss, backend ADB, CLI
- [x] **POC WGC ≥10 FPS**: 47,4 FPS sulla finestra anche coperta, 0 frame neri (vedi ADR-002)
- [x] **POC input non invasivo**: click via messaggi Win32 senza focus/cursore; apre e chiude pannelli
- [x] **Moduli produzione**: `WgcScreenSource` (crop area client) + `WinMsgSink` (coordinate canoniche), CLI aggiornata, test
- [ ] GUI minimale (start/stop + hotkey globale + stato)
- [ ] Dataset schermate (EN) + classifier stati
- [ ] Loop attacco (skip + dragon spam)
- [ ] Upgrade + wall check + GemGuard
- [ ] GUI PySide6

## Quick start

```powershell
# 0) dipendenze + extra WGC (windows-capture)
python -m pip install -e ".[dev,wgc]"

# 1) controlla che la finestra del gioco sia aperta (non minimizzata)
python -m cocbot probe

# 2) controlla la config
python -m cocbot config-check --path config/config.example.yaml

# 3) cattura frame con WGC (funziona anche a finestra coperta, non minimizzata)
python -m cocbot capture --seconds 4 --fps 10 --backend wgc --out out/captures

# 4) verifica un tap non invasivo (dry-run; --execute per inviarlo davvero)
python -m cocbot input-test --x 960 --y 540

# 5) backend ADB opzionale (se installi il Developer Emulator)
python -m cocbot adb-check
```

> `probe` è **solo lettura**. `capture`/`input-test` non rubano focus né muovono il cursore.
> PNG e log restano in `out/` (ignorata da git). Nota: `windows-capture` richiede un processo a
> integrità media (avvia il bot normalmente, non dentro sandbox/AppContainer).

## Struttura

```text
config/config.example.yaml   configurazione (backend, sicurezza, attacco, upgrade, mura, GUI)
src/cocbot/
  __main__.py                CLI: probe | capture | input-test | config-check | adb-check
  core/                      tipi e contratti (ScreenSource, InputSink, Device)
  config/                    modelli pydantic + loader
  capture/
    win32.py                 wrapper ctypes (DPI, finestre, input SendInput e messaggi Win32)
    window.py                scoperta finestra gioco + coordinate canoniche
    screen_wgc.py            cattura WGC per-finestra (anche coperta) + crop area client
    screen_mss.py            cattura foreground (mss) di fallback
    input_winmsg.py          input non invasivo via messaggi Win32 (default)
    input_sendinput.py       input con focus forzato (solo test supervisionati)
    adb.py                   backend ADB (Developer Emulator / emulatori Android)
docs/ADR-002-...             decisione backend non invasivo (evidenze e limiti)
tests/                       unit test (config, coordinate, WGC crop, winmsg)
tools/                       POC (poc_wgc.py, poc_bg_input.py); in arrivo record_session, calibrate
```


## Note di sicurezza

- Il bot **non deve mai** cliccare aree gemme/shop/offerte: vedi `GemGuard` nel piano.
- Il titolo della finestra contiene il nome account: non va loggato/mostrato (qui viene mascherato).
- Nessuna credenziale viene salvata dal bot (login manuale nell'emulatore/client).
