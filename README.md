# cocbot — agente di automazione visiva per Clash of Clans (Google Play Games on PC)

> **Progetto personale/didattico.** Automatizzare Clash of Clans viola la Safe and Fair Play Policy e i
> Termini di Servizio di Supercell e può comportare il ban dell'account. Usare solo con un account
> dedicato, sessioni brevi e nessuna distribuzione. Vedi `../progetto-bot-coc/05-RISCHI-SICUREZZA-ETICA-LEGALE.md`.

Repository di sviluppo del bot. Il piano completo è in [`../progetto-bot-coc/`](../progetto-bot-coc/00-PIANO-GENERALE.md).

## Decisioni correnti (3 novembre 2026, sera)

| Tema | Decisione |
|---|---|
| **Backend primario** | **GPGPC consumer** (nessuna installazione extra): cattura **Windows Graphics Capture** + input `SendInput` con focus; fallback DXGI/schermo in foreground. |
| **Backend secondario (opzionale)** | **Developer Emulator + ADB**: codice pronto; ora installabile (D: ~94 GB liberi, aggiornato 3 nov) ma non installato. Consigliato se serve funzionamento in background/CI. **Mai** patch del consumer. |
| **Lingua gioco** | **Inglese** (impostata dall'utente il 3 nov — da verificare al primo screenshot); l'italiano resta supportato come secondo profilo. |
| **Account** | Si usa l'account **esistente** dell'utente (non dedicato): rischio ban dichiarato e accettato. |
| **Priorità** | Bot funzionante prima; materiale d'esame dopo (non guida le scelte tecniche). |
| **Sicurezza** | `dry_run` di default; GemGuard (mai gemme); kill switch; niente IAP; niente guerre/CWL. |
| **Avvio del gioco** | **Manuale** dell'utente: il bot rileva la finestra di gioco già aperta e si aggancia; **non avvia** GPGPC né il gioco. |
| **Avvio/stop del bot** | **Manuale**, da GUI con hotkey globale configurabile ("tipo Ctrl+L"; default proposto `Ctrl+Alt+L` per non rubare scorciatoie ai browser). |
| **Zero interferenza** | Il bot deve girare **mentre il PC è in uso**, senza rubare focus/mouse/tastiera. Richiede input non invasivo: POC sul consumer GPGPC; fallback **Developer Emulator + ADB**. |
| **Limiti** | **Nessuno di default** (sessione illimitata); limiti solo se impostati dalla GUI. **Auto-stop** automatico quando non c'è più nulla da fare: mura max + tutti i muratori occupati + risorse max. |
| **Backup git** | Remote da configurare (approvato); al momento `cocbot/` ha solo commit locali e nessun `origin`. |

## Stato

- [x] Piano completo (7 documenti) in `../progetto-bot-coc/`
- [x] POC: finestra gioco GPGPC consumer individuata (`crosvm`, 16:9, DPI 125%), input `SendInput` verificato, cattura foreground funzionante, `PrintWindow` scartato (contenuto non affidabile)
- [x] Scaffold repo: config, tipi/contratti, finestra, input, cattura mss, backend ADB, CLI
- [ ] GUI minimale (start/stop + hotkey globale + stato)
- [ ] POC input non invasivo sul consumer (o Developer Emulator + ADB) per girare senza interferire
- [ ] POC Windows Graphics Capture (WGC) ≥10 FPS
- [ ] Dataset schermate (EN) + classifier stati
- [ ] Loop attacco (skip + dragon spam)
- [ ] Upgrade + wall check + GemGuard
- [ ] GUI PySide6

## Quick start

```powershell
# 1) dipendenze (Python 3.12+; su questo PC c'e' 3.14 con le dipendenze installate)
python -m pip install -e ".[dev]"

# 2) controlla che la finestra del gioco sia visibile
python -m cocbot probe

# 3) controlla la config
python -m cocbot config-check --path config/config.example.yaml

# 4) cattura alcuni frame dalla finestra (test cattura; richiede il gioco/launcher visibile)
python -m cocbot capture --seconds 4 --out out/captures

# 5) backend ADB opzionale (se installi il Developer Emulator)
python -m cocbot adb-check
```

> Il comando `probe` è **solo lettura** (nessun click). `capture` salva PNG in `out/` (ignorata da git).

## Struttura

```text
config/config.example.yaml   configurazione (backend, sicurezza, attacco, upgrade, mura)
src/cocbot/
  __main__.py                CLI: probe | capture | config-check | adb-check
  core/                      tipi e contratti (ScreenSource, InputSink, Device)
  config/                    modelli pydantic + loader
  capture/
    win32.py                 wrapper ctypes (DPI, finestre, input SendInput)
    window.py                scoperta finestra gioco + coordinate canoniche
    input_sendinput.py       input consumer (tap/key/focus)
    screen_mss.py            cattura foreground (mss) con health check
    adb.py                   backend ADB (Developer Emulator / emulatori Android)
tests/                       unit test (config, coordinate, titoli)
tools/                       (in arrivo: record_session, calibrate, benchmark WGC)
```

## Note di sicurezza

- Il bot **non deve mai** cliccare aree gemme/shop/offerte: vedi `GemGuard` nel piano.
- Il titolo della finestra contiene il nome account: non va loggato/mostrato (qui viene mascherato).
- Nessuna credenziale viene salvata dal bot (login manuale nell'emulatore/client).
