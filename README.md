# Dettami

**Dettatura vocale con AI per Windows, gratuita e open source.** Tieni premuto un tasto, parli e il testo compare già scritto bene in qualsiasi campo di testo: Word, WhatsApp, Outlook, il browser, Claude, VS Code, il terminale. Niente "ehm", le autocorrezioni vengono applicate, punteggiatura ed elenchi sono già a posto. Se vuoi, riformula anche le frasi poco chiare.

Usa i modelli gratuiti di [Groq](https://console.groq.com) (Whisper per la trascrizione e modelli open per la riscrittura). Non ci sono abbonamenti e non serve una carta di credito: ognuno usa la propria chiave Groq gratuita.

> Fino alla versione 1.2 si chiamava *Dettatura*: l'installer della 1.3 porta con sé chiave, impostazioni e cronologia.
>
> Un'alternativa fai-da-te ad app di dettatura AI a pagamento, nata per uso personale e condivisa per chiunque la voglia usare o migliorare.

---

## Cosa fa

- **Funziona ovunque.** Inserisce il testo dove c'è il cursore, in qualsiasi programma.
- **Riscrittura a tre livelli.** Si sceglie dalla dashboard o dal menu dell'icona:
  - *Fedele*: toglie le esitazioni e sistema la punteggiatura.
  - *Chiara* (predefinita): riformula le frasi contorte e mette in ordine le idee.
  - *Ottimizzata*: testo scorrevole e ben strutturato, adatto a email e documenti.
  - *Solo trascrizione*: nessuna AI.

  Una pagina della dashboard confronta i tre livelli sulle tue frasi.
- **Lo stile si adatta al programma.** È colloquiale nelle chat, curato nelle email, ordinato nei prompt per le AI ed esatto nel codice e nel terminale.
- **Comandi e correzioni a voce.** Puoi dire *"a capo"*, *"nuovo paragrafo"* o *"punto interrogativo"*. Se dici *"alle 5, anzi no, alle 6"*, resta solo la versione giusta.
- **Traduzione al volo.** Premi Shift mentre detti e il testo viene scritto in inglese (o in un'altra lingua scelta).
- **Mani libere.** Con un doppio tocco del tasto parli quanto vuoi, senza tenerlo premuto.
- **Indicatore a schermo.** Una pillola mostra quando ti ascolta e quando sta scrivendo; a fine dettatura ha il pulsante *Copia*.
- **Dashboard locale.** Mostra parole dettate, tempo risparmiato, quota Groq rimasta e cronologia con ricerca. Lì gestisci anche il dizionario personale, le scorciatoie vocali e le impostazioni.
- **Aggiornamenti automatici firmati.** Si aggiorna da sola quando non stai dettando e, se la nuova versione non parte, torna a quella di prima.
- **Si installa senza permessi di amministratore.** Python e le librerie sono inclusi nel pacchetto e non toccano il resto del PC.

## Installazione

1. Scarica **`Dettami-Setup-x.y.z.zip`** dall'[ultima versione](https://github.com/albykeg/dettami/releases/latest).
2. Tasto destro sullo zip → **Estrai tutto**, poi doppio clic su **`Installa.bat`**. Se Windows mostra un avviso, scegli *Ulteriori informazioni* → *Esegui comunque*.
3. Quando l'installer lo chiede, crea la tua **chiave Groq gratuita** su [console.groq.com/keys](https://console.groq.com/keys). Basta la registrazione, nessuna carta. Incollala e premi *Verifica e salva*.

Fatto: **tieni premuto Ctrl destro, parla, rilascia.** Dettami parte con Windows e si trova nel menu Start. Si disinstalla da *Impostazioni → App installate*.

Requisiti: Windows 10 o 11 a 64 bit, un microfono e la connessione a internet (serve per Groq).

> **Ognuno deve usare la propria chiave.** Le quote gratuite di Groq sono per account: se condividi la chiave finiscono subito per tutti.

La guida completa (uso, personalizzazione, soluzione dei problemi) è in [LEGGIMI.md](LEGGIMI.md).

## Costi e limiti

Con il piano gratuito di Groq non si paga nulla: per passare a pagamento bisogna aggiungere apposta un metodo di pagamento. I limiti gratuiti bastano per un uso intenso, indicativamente:

- **Trascrizione:** circa 2.000 dettature al giorno per modello.
- **Riscrittura:** qualche centinaio di dettature al giorno.

Quando un modello esaurisce la quota, Dettami passa da sola al successivo.

## Privacy

- L'audio va solo a Groq per la trascrizione e non resta sul PC, salvo le dettature non riuscite, conservate per poterle riprovare.
- La cronologia resta sul tuo computer.
- La dashboard è raggiungibile solo da questo PC, con un codice segreto.
- Nessuna telemetria. L'unica altra connessione è il controllo degli aggiornamenti su GitHub.

## Come funzionano gli aggiornamenti

Ogni 6 ore l'app scarica `manifest.json` e `manifest.sig` dall'ultima release di questo repository:

1. Verifica la **firma RSA-3072** del manifest con la chiave pubblica scritta nel codice (`aggiornamenti.py`). La chiave privata non è nel repository.
2. Scarica il pacchetto dell'app e ne controlla dimensione e SHA-256 con i valori del manifest firmato.
3. Estrae solo file con nomi ammessi, senza cartelle, senza file eseguibili e senza file con i dati dell'utente, poi controlla che il codice compili.
4. Un processo separato (`aggiorna.py`) chiude l'app e salva i file attuali in `versione-precedente/`. Poi copia i nuovi file e riavvia l'app. Se l'app non segnala di essere partita entro 45 secondi, rimette i file di prima.

Se una versione cambia Python o le librerie, l'app non si aggiorna da sola e propone di scaricare il nuovo installer.

## Sviluppo

Il codice è Python 3.11+. La logica (`motore.py`, `aggiornamenti.py`) non dipende da Windows e si testa su qualsiasi sistema:

```bash
pip install -r requirements.txt pytest cryptography
python -m pytest -q
python dettami.py --prova      # prova microfono e API dalla console
```

| File | Cosa contiene |
|---|---|
| `dettami.py` | App Windows: tasto globale, microfono, icona, inserimento del testo, dati per la dashboard |
| `motore.py` | Trascrizione, prompt di riscrittura, riserva tra modelli, logica del tasto. Contiene `VERSIONE` |
| `indicatore.py` | La pillola a schermo (finestra Windows trasparente disegnata con Pillow) |
| `dashboard.py`, `dashboard.html` | Server locale della dashboard e la pagina |
| `aggiornamenti.py`, `aggiorna.py` | Controllo, verifica e installazione degli aggiornamenti, con ritorno alla versione precedente |
| `config.toml` | Impostazioni predefinite (stili, modelli, prompt per stile) |
| `installer/` | Installazione e disinstallazione per Windows (PowerShell, per utente) |
| `costruisci_pacchetto.py` | Crea l'installer e il pacchetto di aggiornamento firmato |

### Pubblicare una versione

```bash
# 1. aumenta VERSIONE in motore.py e scrivi le novità in NOVITA.md
# 2. crea l'installer e il pacchetto firmato, e li pubblica come release su GitHub
python costruisci_pacchetto.py --pubblica
```

La firma richiede la chiave privata in `.chiave/chiave-firma-dettami.json`, ignorata da git. Chi fa un fork per distribuire la propria versione deve fare tre cose:

1. Generare una nuova coppia di chiavi.
2. Mettere la propria chiave pubblica in `aggiornamenti.py`.
3. Cambiare `REPO` con il proprio repository.

Si possono anche lasciare gli aggiornamenti spenti con `controlla = false` in `config.toml`.

## Contribuire

Segnalazioni e proposte sono benvenute nelle [issue](https://github.com/albykeg/dettami/issues). Per una modifica al codice apri una pull request con i test che passano.

## Licenza

[MIT](LICENSE): puoi usarla, modificarla e ridistribuirla liberamente, anche per lavoro.

Dettami non è affiliata a Groq. I modelli usati hanno le proprie condizioni d'uso.
