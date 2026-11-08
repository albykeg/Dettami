# Dettami

Dettatura vocale con AI per Windows e Mac: parli, e in **qualsiasi campo di testo** (Word, WhatsApp, browser, Claude, Outlook, terminale, Esplora file…) compare il testo già ripulito: niente "ehm", autocorrezioni applicate, punteggiatura ed elenchi a posto.

> **Su Mac** (beta, processore Intel) si installa con `Installa Dettami.command` dallo zip `Dettami-Mac`: le istruzioni, compresi i permessi da dare a macOS, sono nel suo `LEGGIMI.txt`. Il tasto è **Option destro (⌥)** invece di Ctrl destro, l'icona è nella barra dei menu in alto e si incolla con ⌘V. Tutto il resto di questa guida vale uguale.

---

## Installazione su Windows (2 minuti, senza permessi di amministratore)

1. Tasto destro sullo zip `Dettami-Setup` → **Estrai tutto**.
2. Doppio clic su **`Installa.bat`**. Se Windows mostra un avviso: *Ulteriori informazioni* → *Esegui comunque*.
3. Si apre una finestra per la **chiave Groq gratuita**: clicca il link, registrati (nessuna carta), crea la chiave, incollala e premi *Verifica e salva*.

Python e tutti i componenti sono già nel pacchetto: non serve installare altro e non tocca altri programmi. Dettami finisce in `%LOCALAPPDATA%\Programs\Dettami`, compare nel menu Start e in *Impostazioni → App installate* (da lì si disinstalla). Dalla versione 1.3 **si aggiorna da sola** (vedi sotto); in alternativa lanci `Installa.bat` della nuova versione: impostazioni, chiave e cronologia restano.

Avevi la vecchia **Dettatura** (fino alla 1.2)? Installa Dettami nello stesso modo: chiave, impostazioni, dizionario e cronologia vengono spostati da soli e la vecchia versione viene tolta.

**Ognuno deve usare la propria chiave Groq**: le quote gratuite sono per account, se la condividi finiscono subito per tutti.

---

## Come si usa

| Cosa fai | Cosa succede |
|---|---|
| **Tieni premuto Ctrl destro**, parli, rilasci | Il testo ripulito viene inserito dove c'è il cursore |
| **Doppio tocco** di Ctrl destro | Modalità **mani libere**: parli quanto vuoi, un altro tocco per finire |
| Premi **Shift** mentre registri | Il testo viene **tradotto** (lingua scelta dal menu, di default inglese) |
| **Esc** mentre registri | Annulla |
| Ctrl destro + un'altra lettera (es. Ctrl+C) | Funziona come sempre: la registrazione viene scartata |

Puoi anche dare comandi a voce: *"a capo"*, *"nuovo paragrafo"*, *"punto interrogativo"*, *"tra virgolette"*. E se ti correggi mentre parli (*"alle 5, anzi no, alle 6"*) resta solo la versione giusta.

**Lo stile si adatta da solo al programma in cui scrivi:**
- **Chat** (WhatsApp, Telegram, Messenger, Slack…): tono colloquiale, niente punto finale sui messaggi brevi
- **Email** (Gmail, Outlook…): paragrafi curati, saluto e chiusura su righe separate
- **Prompt per AI** (Claude, ChatGPT…): richieste messe in ordine logico, requisiti in elenco
- **Tecnico** (VS Code, terminale…): nomi di file e comandi lasciati esatti

### Quanto riscrivere le tue frasi

Dalla dashboard (pagina **Riscrittura**) o dal menu dell'icona scegli il livello:
- **Fedele**: toglie esitazioni e ripetizioni e sistema la punteggiatura, ma le frasi restano le tue.
- **Chiara** (consigliata): riformula le frasi contorte o poco chiare, mette in ordine le idee e toglie i concetti ripetuti.
- **Ottimizzata**: riscrive il testo perché sia scorrevole e ben strutturato, ideale per email e documenti.
- **Solo trascrizione**: nessuna AI, le tue parole esatte.

Nella stessa pagina scrivi una frase come la diresti a voce e confronti i tre livelli fianco a fianco prima di scegliere. In tutti i livelli fatti, numeri, nomi e richieste restano quelli che hai detto, e se detti una domanda (*"scrivimi una mail per…"*) viene scritta, non eseguita.

### L'indicatore a schermo

Mentre detti compare una pillola in basso al centro dello schermo, sopra tutte le finestre:
**rossa** con le barre della voce = ti sto ascoltando (con il tempo trascorso), **viola** = ascolto e traduco,
**arancione** = sto scrivendo, **verde** = testo inserito (con il numero di parole) e pulsante **Copia**.
Con *Copia* il testo appena dettato va negli appunti e lo incolli dove vuoi con Ctrl+V; il cursore resta dov'era.
La pillola verde resta 5 secondi, e finché ci tieni sopra il mouse non sparisce; un clic sul resto della pillola la chiude.
Durante l'ascolto non prende mai il cursore né i clic. Si può spostare in alto, togliere il pulsante o spegnere dalla dashboard.

### La dashboard

Si apre con l'icona **Dettami** sul Desktop o nel menu Start, oppure con un clic sull'icona vicino all'orologio.
- **Panoramica**: parole dettate oggi, tempo risparmiato, grafico delle ultime due settimane, quota gratuita di Groq rimasta per ogni modello.
- **Cronologia**: tutte le dettature, con ricerca e tasto *Copia*.
- **Dizionario**: le parole da scrivere sempre giuste e le scorciatoie vocali.
- **Riscrittura**: il livello di riscrittura, con esempi e una prova con le tue frasi.
- **Impostazioni**: tasto, lingue, indicatore, microfono (con prova), aggiornamenti, avvio con Windows, chiave Groq.

### L'icona nella barra

Colore: **grigio-blu** = pronta, **rossa** = ti sto ascoltando, **viola** = ascolto e traduco, **arancione** = sto scrivendo.

Clic sull'icona: apre la dashboard. Tasto destro: copiare l'ultima dettatura, riprovare una dettatura fallita, scegliere la lingua di traduzione e il livello di riscrittura, installare un aggiornamento disponibile, cambiare la API key.

---

## Personalizzare

Le cose di tutti i giorni si cambiano dalla **dashboard**. Le opzioni avanzate stanno in **`config.toml`** (dashboard → Impostazioni → Avanzate, poi *Ricarica impostazioni* dal menu dell'icona); `config.esempio.toml` contiene sempre tutte le opzioni dell'ultima versione. Le scelte fatte nella dashboard sono salvate in `impostazioni.json` e hanno la precedenza.

- **`dizionario`**: nomi e termini da scrivere sempre giusti (i tuoi progetti, clienti, marchi).
- **`scorciatoie`**: dici *"la mia mail"* e viene inserito l'indirizzo completo.
- **`[stili]`**: quali programmi usano quale stile; **`[istruzioni_stile]`**: come scrive in ciascuno stile.
- **`dettatura`**: cambia tasto (es. `"f8"`, `"alt_gr"`, `"caps_lock"`) se il tuo portatile non ha Ctrl destro.
- **`metodo = "digita"`**: per i rari campi che bloccano l'incolla.
- Vuoi riscrivere completamente le regole dell'AI? Crea un file `prompt.txt` nella cartella: sostituisce quelle predefinite.

---

## Se qualcosa non va

- **Non funziona in un programma avviato come amministratore** (es. Gestione attività, alcuni installer): è una protezione di Windows. Avvia anche Dettami come amministratore (menu Start → tasto destro su *Dettami* → *Esegui come amministratore*).
- **Non ti sente, o scrive con il rumore di fondo**: menu dell'icona → *Prova microfono*, guarda il "livello voce" e regola `soglia_silenzio`; per scegliere un microfono specifico scrivi parte del suo nome in `microfono`.
- **Taglia la prima parola**: metti `microfono_sempre_aperto = true`.
- **L'antivirus la segnala**: legge i tasti premuti per riconoscere Ctrl destro, come ogni app di dettatura o di scorciatoie. Il codice è tutto qui, leggibile.
- **Altro**: menu → *Apri log*.

---

## Aggiornamenti automatici

Ogni 6 ore Dettami controlla se su GitHub c'è una versione nuova. Se c'è, la scarica e la installa da sola quando non stai dettando da qualche minuto: si chiude, si aggiorna e si riapre in pochi secondi, e la pillola ti dice cosa è cambiato. Se preferisci decidere tu, spegni *Installa da solo gli aggiornamenti* in Impostazioni: ti avviserà e aggiornerai con un clic.

Sicurezza: ogni aggiornamento è **firmato digitalmente** e Dettami installa solo pacchetti con una firma valida; se la nuova versione non parte, torna da sola a quella di prima. Impostazioni, chiave, dizionario e cronologia non vengono mai toccati. Quando cambia Python o una libreria, la dashboard ti propone di scaricare il nuovo installer.

## Costi: zero

Con il **piano gratuito di Groq** non paghi nulla: per passare a pagamento bisogna aggiungere di proposito un metodo di pagamento. Se non lo aggiungi, al massimo arrivi al limite e devi aspettare che si liberi.

Limiti gratuiti indicativi:
- **Trascrizione**: 2.000 dettature o 8 ore di audio al giorno per ciascuno dei due modelli Whisper (il secondo entra in gioco da solo).
- **Rifinitura AI**: circa 200 dettature al giorno per ciascun modello. I modelli in `config.toml` sono tre, ognuno con la propria quota, quindi circa 600 al giorno. Le frasi di 1–2 parole non passano dall'AI e non consumano quota.

Quando un modello finisce la quota, l'app passa da sola al successivo e ti avvisa una volta sola. Se li finissi tutti, continua a scrivere con la sola trascrizione di Whisper, che ha già punteggiatura e maiuscole. Per vedere quanto hai usato: <https://console.groq.com/settings/limits>.

## Privacy

L'audio viene inviato a Groq solo per la trascrizione e sul PC non viene salvato, tranne quando una dettatura fallisce (cartella `audio_non_elaborati`, così puoi riprovare). La cronologia (`cronologia.jsonl`) resta solo sul tuo computer; la dashboard è raggiungibile solo da questo PC e solo con un codice che cambia a ogni avvio.

---

## Struttura (per modificarla con Claude Code)

| File | Cosa contiene |
|---|---|
| `dettami.py` | App Windows: tasto globale, microfono, icona, inserimento del testo, dati per la dashboard |
| `indicatore.py` | La pillola a schermo (finestra Windows trasparente, disegnata con Pillow) |
| `dashboard.py`, `dashboard.html` | Server locale della dashboard (solo 127.0.0.1, con codice segreto) e la pagina |
| `motore.py` | Trascrizione, prompt AI, riserva tra modelli, logica del tasto (non dipende da Windows). Qui c'è anche `VERSIONE` |
| `config.toml` | Impostazioni predefinite |
| `chiave.ps1` | Finestra per inserire e verificare la API key |
| `installer/` | Installazione, disinstallazione e istruzioni per i colleghi |
| `aggiornamenti.py`, `aggiorna.py` | Controllo, verifica della firma e installazione degli aggiornamenti (con ritorno alla versione precedente) |
| `costruisci_pacchetto.py` | Crea installer e pacchetto di aggiornamento firmato: `python costruisci_pacchetto.py` → `dist/` |
| `NOVITA.md` | Le novità di ogni versione (finiscono nelle note dell'aggiornamento) |
| `test_motore.py`, `test_aggiornamenti.py` | Test: `python -m pytest -q` |

Per distribuire una nuova versione: aumenta `VERSIONE` in `motore.py`, scrivi le novità in `NOVITA.md` e lancia `python costruisci_pacchetto.py --pubblica`: chi ha già Dettami la riceve da sola.
