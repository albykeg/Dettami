# Dettami — istruzioni per Claude Code

Dettami è un'app gratuita e open source di dettatura vocale con AI per **Windows** e **Mac** (beta, Intel).
Si tiene premuto un tasto, si parla, e il testo compare già pulito in qualsiasi campo di testo.
Trascrizione e riscrittura usano **solo i modelli gratuiti di Groq**; ognuno usa la propria chiave.
Autore: Alberto (`albykeg`). Repository: https://github.com/albykeg/Dettami. Licenza MIT.

Lo stato del lavoro, le cose aperte e la storia delle decisioni sono in **HANDOFF.md**: leggilo all'inizio.

## Come lavorare con Alberto

- **Rispondi sempre in italiano.** Anche il codice, i commenti, i messaggi dell'app e i commit sono in italiano.
- Alberto parla spesso a voce (testo trascritto): interpreta il senso, non le parole esatte.
- Livello tecnico intermedio. Vuole risultati pronti all'uso e proposte proattive, non spiegazioni lunghe.
- Le decisioni prese (vedi HANDOFF.md) non si rimettono in discussione senza motivo. Per esempio: tutto
  gratis con Groq, niente firma Apple a pagamento, niente login.

## Regole che non si rompono

1. **La chiave privata di firma non va mai su GitHub** (`.chiave/`, `*.pem`, `chiave-firma*.json` sono in
   `.gitignore`). Lo stesso vale per `.env` e per qualsiasi chiave Groq (`gsk_…`). Prima di ogni commit controlla
   `git status` e cerca `gsk_` e `"d":`.
2. **Compatibilità degli aggiornamenti.** Le copie già installate (dalla 1.3.0 in poi) scaricano i nuovi pacchetti
   e li validano con il **loro** codice. Quindi:
   - il pacchetto dell'app (`dettami-app-<v>.zip`) contiene solo file **in piano**, senza cartelle, con estensioni
     `py|html|ps1|md|ico|txt|toml` (regex `NOME_VALIDO` della 1.3). Una cartella o un'estensione nuova fanno
     rifiutare l'aggiornamento a tutti;
   - non cambiare mai `CHIAVE_PUBBLICA` in `aggiornamenti.py`: le vecchie copie non riconoscerebbero più le firme;
   - la release si chiama `v<versione>` e i file hanno nomi fissi: `manifest.json`/`.sig` (Windows),
     `manifest-mac.json`/`.sig` (Mac), `dettami-app-<v>.zip`, `Dettami-Setup-<v>.zip`, `Dettami-Mac-<v>.zip`;
   - `config.toml`, `.env` e `impostazioni.json` non vanno mai nel pacchetto: sono dati dell'utente;
   - l'app deve scrivere `avvio-ok.json` con `versione` e `pid` alla fine di `_setup`. Senza quel file
     l'aggiornatore pensa che la nuova versione non sia partita e torna a quella precedente;
   - `aggiorna.py` usa solo la libreria standard: gira da una copia temporanea, anche con Python isolato (`-I`).
3. **Windows non deve cambiare per colpa del Mac.** Il codice per Mac sta in `sistema_mac.py` e
   `indicatore_mac.py`. In `dettami.py` ogni differenza passa da `if MAC:` / `WINDOWS`. Dopo ogni modifica
   rilancia le prove per Windows.
4. **Mac:** AppKit e l'icona nella barra dei menu si usano **solo dal thread principale**, con
   `sistema_mac.sul_thread_principale(...)`. Su Mac `pynput` non si usa: il tasto si legge con l'event tap di Quartz.
   Gli argomenti di avvio arrivano solo da `argomenti-avvio.json`, che `mac/avvio_app.py` filtra.
5. Se cambi la versione di Python o le librerie (`requisiti-windows.txt`, `mac/requisiti-mac.txt`), le copie
   installate non si aggiornano da sole: chiedono di rilanciare l'installer. Va detto nelle novità.

## Struttura

| File | Cosa contiene |
|---|---|
| `dettami.py` | L'app: tasto, microfono, icona, inserimento del testo, aggiornamenti, dati per la dashboard |
| `motore.py` | Logica senza sistema operativo: trascrizione, prompt di riscrittura (livelli fedele/chiara/ottimizzata), riserva tra modelli, macchina del tasto, impostazioni. **`VERSIONE` è qui** |
| `indicatore.py` | Disegno della pillola (Pillow) e finestra trasparente su Windows |
| `sistema_mac.py`, `indicatore_mac.py` | Mac: event tap, Cmd+V, app in primo piano, permessi (TCC), LaunchAgent, NSPanel |
| `dashboard.py`, `dashboard.html` | Server locale (127.0.0.1, token) e pagina della dashboard |
| `aggiornamenti.py`, `aggiorna.py` | Controllo e verifica della firma RSA-3072 e installazione con ritorno alla versione precedente |
| `config.toml` | Impostazioni predefinite (modelli, stili per app, prompt). La build per Mac imposta il tasto `alt_r` |
| `installer/` | Installer Windows (PowerShell, per utente, senza amministratore) |
| `mac/` | Installer e disinstallazione Mac (`.command`), `avvio_app.py` (diventa `sitecustomize.py` dentro `Dettami.app`) |
| `costruisci_pacchetto.py` | Build di installer Windows e Mac, pacchetto di aggiornamento e manifest firmati; `--pubblica` crea la release |
| `NOVITA.md` | Novità per versione: diventano le note dell'aggiornamento mostrate agli utenti |
| `test_*.py`, `prove/` | Test e simulazioni (vedi sotto) |

## Comandi

```bash
pip install -r requirements.txt pytest cryptography pyflakes playwright
python -m playwright install chromium        # solo per prove/prova_dashboard.py

python -m pytest -q                           # 104 test: motore, firma, aggiornatore (anche modalità Mac)
python -m pyflakes *.py mac/*.py prove/*.py
python prove/simula_windows.py                # app vera con Windows finto: 47 verifiche
python prove/prova_dashboard.py               # dashboard in Chromium headless: 33 verifiche
python prove/simula_mac.py base               # app vera "su Mac" con librerie Apple finte: 33 verifiche
python prove/simula_mac.py permessi           # flusso dei permessi di macOS: 13 verifiche
GROQ_API_KEY=... python prove/confronta_riscrittura.py  # confronto affiancato fedele/chiara/ottimizzata (rete vera; --finto senza)
python prove/controlla_ps1.py installer/installa.ps1 installer/disinstalla.ps1 chiave.ps1
shellcheck -s bash -S warning mac/*.command   # se disponibile

python costruisci_pacchetto.py                # build in dist/ (scarica in .cache_pacchetto/ Python e librerie)
python prove/prova_installer_mac.py           # esegue l'installer Mac con comandi finti: 10 verifiche
python costruisci_pacchetto.py --pubblica     # build + release su GitHub (serve gh con accesso)
```

Le simulazioni in `prove/` sono pensate per Linux o macOS (anche WSL): su Windows `dettami.py` userebbe le API
vere di Windows. Scrivono i loro file in `prove/_output/`, che è ignorata da git.

## Pubblicare una versione

1. Aumenta `VERSIONE` in `motore.py` e scrivi la sezione in cima a `NOVITA.md`. La prima riga è quella che vede
   l'utente nella notifica.
2. Fai girare tutte le prove qui sopra.
3. `python costruisci_pacchetto.py`. La firma vuole la chiave privata in `.chiave/chiave-firma-dettami.json`;
   senza la chiave la build va comunque, ma senza pacchetto di aggiornamento.
4. Release `v<versione>` con i 7 file di `dist/`: `Dettami-Setup-<v>.zip`, `Dettami-Mac-<v>.zip` e, da
   `dist/aggiornamento/`, `dettami-app-<v>.zip`, `manifest.json`, `manifest.sig`, `manifest-mac.json`,
   `manifest-mac.sig`. Si fa con `--pubblica` sul PC di Alberto, oppure a mano dal browser: nelle sessioni cloud
   GitHub non permette di creare release.
5. Verifica: `aggiornamenti.controlla("0.0.1", aggiornamenti.URL_MANIFEST, requests.Session())` deve restituire
   il manifest della nuova versione con firma valida.
