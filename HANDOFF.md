# Passaggio a Claude Code — stato al 11/11/2026

In breve: **la 1.3.0 per Windows è pubblicata e in uso**. La **1.4.0**, che aggiunge la versione **Mac (beta, Intel)**,
è pronta su `main` ma **non è ancora pubblicata**: aspetta la prova sul Mac Intel di un amico di Alberto.

Le regole di lavoro e i comandi sono in `CLAUDE.md`.

## Dove siamo

| Cosa | Stato |
|---|---|
| Release su GitHub | `v1.3.0` è la "latest", con 4 file: `Dettami-Setup-1.3.0.zip`, `dettami-app-1.3.0.zip`, `manifest.json`, `manifest.sig`. Verificata: download e firma ok |
| Codice su `main` | 1.4.0 (`motore.VERSIONE`), Windows + Mac. Tutte le prove passano (vedi sotto) |
| Utenti Windows | Alberto e i suoi colleghi. Chi ha la 1.3.0 si aggiorna da solo; chi ha ancora la vecchia "Dettatura" 1.2 deve installare a mano una volta |
| Mac | Lo zip `Dettami-Mac-1.4.0.zip` è stato consegnato ad Alberto l'8/11. La guida per l'amico è un documento Claude ("Dettami sul Mac: istruzioni facili", https://claude.ai/artifact/LqQ9QGvMrt8CG9p9aRP7in), privato finché Alberto non lo condivide. **Esito della prova: non ancora arrivato** |
| Chiave di firma | Pubblica in `aggiornamenti.py`. La privata ce l'ha solo Alberto (file `chiave-firma-dettatura-PRIVATA.json` che gli è stato consegnato). Non è nel repository |

Prove che passano su `main` (Linux): `pytest` 104, `prove/simula_windows.py` 47/47, `prove/prova_dashboard.py` 33/33,
`prove/simula_mac.py base` 33/33, `prove/simula_mac.py permessi` 13/13, `prove/prova_installer_mac.py` 10/10,
`controlla_ps1.py` ok su tutti gli script, shellcheck senza avvisi, pyflakes pulito.

## Primo avvio

**Sul PC di Alberto (consigliato: è l'unico posto dove si può firmare e pubblicare):**

1. `git clone https://github.com/albykeg/Dettami.git` e poi `cd Dettami`.
2. Crea la cartella `.chiave` e copiaci la chiave privata con il nome `chiave-firma-dettami.json`. La cartella è
   già in `.gitignore`: **non va mai committata**.
3. Installa Python 3.11 o più recente, poi `pip install -r requirements.txt pytest cryptography pyflakes`.
4. `gh auth login` (GitHub CLI): serve per `costruisci_pacchetto.py --pubblica`.
5. Lancia `claude` nella cartella.

Su Windows le simulazioni in `prove/` non girano, perché `dettami.py` userebbe le API vere di Windows: servono
WSL, Linux o un Mac. Su Windows funzionano `pytest`, la build e l'app vera (`python dettami.py`).

**Su Claude Code nel web (claude.ai/code), con il repository collegato:** va bene per il codice e per tutte le prove.
Però non può creare release su GitHub, perché la sessione lo blocca, e non può eseguire PowerShell. La chiave privata
non va caricata lì: la build firmata e la release si fanno dal PC di Alberto.

### Primo messaggio da incollare in Claude Code

> Leggi CLAUDE.md e HANDOFF.md. Poi lancia i test e le prove elencati in CLAUDE.md e dimmi in due righe se
> passano. Il prossimo lavoro è la prova di Dettami sul Mac del mio amico: ti incollo cosa è successo e il file
> dettami.log, e tu sistemi quello che non va.

## Cosa c'è da fare, in ordine

1. **Prova sul Mac Intel dell'amico.** Raccogliere:
   - la foto della finestra del Terminale durante l'installazione;
   - il file `~/Library/Application Support/Dettami/dettami.log`;
   - cosa è successo a ogni passo.

   Le parti più a rischio sono quelle sotto "Non ancora provato davvero".
2. **Correggere.** Ogni correzione va in una nuova versione (per esempio 1.4.1), con `VERSIONE` e `NOVITA.md`
   aggiornati. Prima di fare la release rifai tutte le prove.
3. **Pubblicare la release** con i 7 file (`CLAUDE.md` → "Pubblicare una versione"). Così i Windows 1.3.0 si
   aggiornano da soli: è la **prima volta che l'aggiornamento automatico gira davvero** sui PC. Sul PC di Alberto
   controllare:
   - `%LOCALAPPDATA%\Programs\Dettami\aggiornamento.log`;
   - la versione mostrata nella dashboard;
   - che non ci sia `aggiornamento-fallito.json`.
4. **Riscrittura con Groq vero.** I tre livelli (Fedele, Chiara, Ottimizzata) non sono mai stati provati con il
   modello vero: da qui non c'era una chiave. Alberto li prova nella pagina *Riscrittura* della dashboard. Se un
   livello riscrive troppo o troppo poco, si interviene in `motore.py`: `PROMPT_BASE`, `ISTRUZIONI_LIVELLO`,
   `ESEMPI_LIVELLO`, `_ESEMPI_EXTRA`.
5. **Rimandati da Alberto. Non iniziarli se non li chiede lui:**
   - login con account;
   - modalità comandi vocali;
   - dizionario condiviso con la squadra;
   - pulsante "segnala un problema".

Idee da proporre più avanti:
- Mac nativo per i chip Apple (Python standalone `aarch64-apple-darwin`; su arm64 serve almeno la firma ad-hoc,
  che si fa gratis sul Mac con `codesign -s -`);
- test automatici su GitHub Actions (non servono segreti);
- argomenti del repository su GitHub, da impostare a mano: `speech-to-text`, `dictation`, `whisper`, `groq`,
  `windows`, `italiano`.

## Non ancora provato davvero (rischi)

**Mac**: tutto è stato provato solo su Linux, con librerie Apple finte e comandi di macOS finti. Da verificare su un Mac vero:
- i permessi: macOS deve associare Microfono, Accessibilità e Monitoraggio input a "Dettami", un'app senza firma;
- la riapertura automatica dopo i permessi;
- la pillola: schermo scelto con `NSScreen.mainScreen()`, posizione, clic su Copia, app a tutto schermo;
- la registrazione a 16 kHz con PortAudio su CoreAudio (se fallisce c'è già un ripiego con ricampionamento);
- il tasto Fn: su Mac recenti può aprire le emoji. La guida spiega di impostare "Non fare nulla";
- i macOS vecchi che all'avvio passano `-psn_…` all'app: Python lo rifiuterebbe come opzione;
- le notifiche, che con `osascript` compaiono come "Script Editor";
- l'icona nella barra dei menu, un cerchio pieno di 22 pixel: forse troppo grande;
- se Dettami è già aperta e la si riapre dal Finder, non succede niente: è documentato.

**Windows**:
- gli script PowerShell non sono mai stati eseguiti qui, solo controllati nella struttura;
- da confermare con Alberto: la migrazione dalla vecchia cartella `Programs\Dettatura` a `Programs\Dettami`
  (installer 1.3);
- il primo aggiornamento automatico vero (1.3.0 → 1.4.0).

## Come funziona (riassunto)

- **Dettatura:**
  1. tasto tenuto premuto (Windows `ctrl_r`, Mac `alt_r`), oppure doppio tocco per le mani libere;
  2. registrazione a 16 kHz;
  3. Whisper su Groq (`whisper-large-v3-turbo`, poi `whisper-large-v3`);
  4. riscrittura (`openai/gpt-oss-120b`, poi `gpt-oss-20b`, poi `qwen/qwen3.8-27b`) con lo stile adatto all'app in
     primo piano, al livello scelto, con dizionario e scorciatoie;
  5. incolla, oppure scrittura carattere per carattere; poi gli appunti tornano com'erano.

  Shift durante la dettatura traduce; Esc annulla.
- **Aggiornamenti:**
  1. ogni 6 ore l'app scarica `manifest*.json` + `.sig` da `releases/latest`;
  2. verifica la firma RSA-3072 con la chiave pubblica;
  3. scarica lo zip dell'app (dimensione e SHA-256 dal manifest);
  4. lo estrae con la lista dei nomi ammessi e controlla che compili;
  5. `aggiorna.py`, in un processo separato, aspetta che l'app si chiuda, fa il backup in `versione-precedente/`,
     copia i file nuovi e riavvia l'app;
  6. se entro 45 s non trova `avvio-ok.json`, rimette la versione precedente.

  L'installazione parte da sola dopo 3 minuti senza dettare. Su Mac l'app si riapre con `open -n -a`.
- **Avvio su Mac:**
  1. `Dettami.app/Contents/MacOS/Dettami` è il Python standalone stesso;
  2. aperto senza argomenti, `sitecustomize.py` (cioè `mac/avvio_app.py`) esegue `execv` su
     `~/Library/Application Support/Dettami/dettami.py` nello stesso processo, così i permessi di macOS restano
     all'app;
  3. gli argomenti arrivano da `argomenti-avvio.json`.

| Dove sta | Windows | Mac |
|---|---|---|
| App + dati | `%LOCALAPPDATA%\Programs\Dettami\` (codice, `config.toml`, `.env`, cronologia, log) | `~/Applications/Dettami.app` (Python + librerie) e `~/Library/Application Support/Dettami/` (codice e dati) |
| Avvio automatico | Collegamento in Esecuzione automatica (`--avvio`) | `~/Library/LaunchAgents/io.github.albykeg.dettami.plist` |
| Disinstallazione | Impostazioni → App installate (registro `HKCU\…\Uninstall\Dettami`) | Menu → Disinstalla Dettami…, oppure `Disinstalla Dettami.command` |
| Python | 3.14.10 ufficiale (NuGet), incluso | 3.13.17 standalone di Astral (rilascio 20261021), incluso |

## Decisioni prese

| Quando | Decisione |
|---|---|
| ott 2026 | Costruire un'alternativa gratuita a Typeless. **Solo modelli gratuiti di Groq**, chiave personale per ognuno |
| ott 2026 | Windows prima di tutto: funziona in ogni campo di testo e si installa su più PC senza amministratore, Python incluso |
| 1.1 – 1.2 | Dashboard locale, pillola a schermo, pulsante Copia |
| nov 2026 | Priorità: riscrittura migliore (tre livelli, predefinito Chiara) e aggiornamenti automatici. Login e il resto rimandati |
| nov 2026 | Progetto **open source su GitHub (MIT)**, aperto a tutti gli "smanettoni" |
| nov 2026 | Nome: **Dettatura → Dettami**. L'installer porta i dati dalla vecchia versione |
| nov 2026 | Le release le crea Alberto dal browser oppure con `--pubblica` dal suo PC (le sessioni cloud non possono) |
| nov 2026 | Versione **Mac beta per Intel, senza firma Apple** (niente 99 $ l'anno), per ora solo per amici |

## Fuori dal repository

- **Chiave privata di firma**: solo da Alberto. Se si perde, le copie già installate non riceveranno più
  aggiornamenti automatici: servirebbe una chiave nuova e far reinstallare tutti a mano.
- **Guida Mac per l'amico**: il documento Claude citato sopra.
- `dist/` e `.cache_pacchetto/` si ricreano con `python costruisci_pacchetto.py`, che scarica di nuovo Python e le
  librerie e ne controlla le impronte.
