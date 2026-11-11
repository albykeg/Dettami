"""Simulazione end-to-end di dettatura.App con moduli Windows finti."""
import contextlib
import enum
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np

RADICE = Path(__file__).resolve().parent.parent   # cartella del progetto
SCRATCH = RADICE / "prove" / "_output" / "windows"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(RADICE))

# ---------------- pynput finto
class Key(enum.Enum):
    ctrl = "ctrl"; ctrl_l = "ctrl_l"; ctrl_r = "ctrl_r"; shift = "shift"; shift_r = "shift_r"
    esc = "esc"; enter = "enter"; alt_gr = "alt_gr"; f8 = "f8"

class KeyCode:
    def __init__(self, char): self.char = char

AZIONI = []

class Controller:
    @contextlib.contextmanager
    def pressed(self, *keys):
        for k in keys: AZIONI.append(("giu", k))
        yield
        for k in keys: AZIONI.append(("su", k))
    def press(self, k): AZIONI.append(("press", k))
    def release(self, k): AZIONI.append(("release", k))
    def type(self, s): AZIONI.append(("type", s))

class Listener:
    def __init__(self, on_press, on_release): self.on_press, self.on_release = on_press, on_release; self.daemon = False
    def start(self): pass
    def stop(self): pass

kb = types.ModuleType("pynput.keyboard"); kb.Key = Key; kb.KeyCode = KeyCode; kb.Controller = Controller; kb.Listener = Listener
pn = types.ModuleType("pynput"); pn.keyboard = kb
sys.modules["pynput"] = pn; sys.modules["pynput.keyboard"] = kb

# ---------------- pystray finto
NOTIFICHE = []
class Icon:
    def __init__(self, nome, img, titolo, menu): self.icon, self.title, self.menu = img, titolo, menu
    def run(self, setup): setup(self)
    def notify(self, m, t=None): NOTIFICHE.append(m)
    def update_menu(self): pass
    def stop(self): pass
class MenuItem:
    def __init__(self, text, action, **kw): self.text, self.action, self.kw = text, action, kw
class Menu:
    SEPARATOR = object()
    def __init__(self, *items): self.items = items
ps = types.ModuleType("pystray"); ps.Icon = Icon; ps.MenuItem = MenuItem; ps.Menu = Menu
sys.modules["pystray"] = ps

# ---------------- pyperclip finto
APPUNTI = {"v": "VECCHIO CONTENUTO"}
pc = types.ModuleType("pyperclip")
pc.copy = lambda s: APPUNTI.__setitem__("v", s)
pc.paste = lambda: APPUNTI["v"]
sys.modules["pyperclip"] = pc

# ---------------- sounddevice finto (genera "voce" o silenzio)
MODO_AUDIO = {"voce": True, "freq_ok": True}
class InputStream:
    def __init__(self, samplerate, channels, dtype, device, callback, latency, blocksize=0):
        if samplerate == 16000 and not MODO_AUDIO["freq_ok"]:
            raise RuntimeError("Invalid sample rate")
        self.fs, self.cb, self.active, self._t = samplerate, callback, False, None
    def _loop(self):
        n = int(self.fs * 0.03); i = 0
        while self.active:
            t = (np.arange(n) + i) / self.fs
            amp = 4000 if MODO_AUDIO["voce"] else 5
            self.cb((np.sin(2 * np.pi * 220 * t) * amp).astype(np.int16).reshape(-1, 1), n, None, None)
            i += n; time.sleep(0.03)
    def start(self): self.active = True; self._t = threading.Thread(target=self._loop, daemon=True); self._t.start()
    def stop(self): self.active = False
    def close(self): pass
sd = types.ModuleType("sounddevice")
sd.InputStream = InputStream
sd.query_devices = lambda *a: {"default_samplerate": 48000.0, "name": "Mic finto", "max_input_channels": 1} if a else [{"name": "Mic finto", "max_input_channels": 1}]
sd.play = lambda *a, **k: None
sd.default = types.SimpleNamespace(device=(0, 0))
sys.modules["sounddevice"] = sd

# ---------------- import app e client finto
import motore  # noqa: E402
import dettami as dettatura  # noqa: E402

for nome in ("FILE_CRONOLOGIA", "FILE_CRONOLOGIA_TXT", "FILE_STATO", "FILE_LOG", "FILE_IMPOSTAZIONI",
             "FILE_USO", "FILE_SESSIONE", "FILE_STATO_AGG", "FILE_AVVIO_OK", "FILE_AGG_FALLITO", "CARTELLA_AGG"):
    setattr(dettatura, nome, SCRATCH / Path(getattr(dettatura, nome)).name)
dettatura.CARTELLA_FALLITI = SCRATCH / "falliti"
for n in ("impostazioni.json", "cronologia.jsonl", "cronologia-vecchia.txt", "uso.json", "sessione.json", "stato.json"):
    (SCRATCH / n).unlink(missing_ok=True)
# dati della versione 1.0 da migrare
(SCRATCH / "cronologia.txt").write_text("[2026-10-28 13:50] whatsapp · 4 parole · 1.2 s\nCiao, arrivo alle sei\n\n", encoding="utf-8")
(SCRATCH / "stato.json").write_text('{"lingua_traduzione": "spagnolo", "ai_attiva": true}', encoding="utf-8")

CHIAMATE = []
class ClientFinto:
    fallisci = False
    def __init__(self, cfg, key):
        self.quote, self.uso = {}, None
    def scalda(self): pass
    def trascrivi(self, audio, cfg):
        CHIAMATE.append(("trascrivi", round(audio.size / 16000, 2)))
        if self.uso:
            self.uso.registra("whisper-large-v3-turbo", secondi_audio=10)
        if ClientFinto.fallisci:
            raise motore.ErroreAPI("Connessione non riuscita. Sei online?")
        return "ehm allora ciao a tutti questo è un test"
    def rifinisci(self, sistema, grezzo, cfg, livello="chiara"):
        CHIAMATE.append(("rifinisci", "TRADUZIONE" in sistema))
        LIVELLI.append(livello)
        if "TRADUZIONE" in sistema:
            return "Hello everyone, this is a test."
        return {"fedele": "Ciao a tutti, questo è un test.", "chiara": "Ciao a tutti, questo è un test.",
                "ottimizzata": "Ciao a tutti: questo è un test."}[livello]
LIVELLI = []
motore.ClientAI = ClientFinto

# ---------------- aggiornamenti finti (niente rete)
import aggiornamenti  # noqa: E402
AGG = {"manifest": None, "chiamate": [], "installer": False}
def _controlla_finto(versione, url, *a, **k):
    AGG["chiamate"].append(("controlla", versione, url))
    return AGG["manifest"]
aggiornamenti.controlla = _controlla_finto
aggiornamenti.richiede_installer = lambda m, c: AGG["installer"]
aggiornamenti.scarica = lambda m, c, *a, **k: AGG["chiamate"].append(("scarica", m["versione"])) or Path(c) / "x.zip"
aggiornamenti.prepara = lambda z, c, v: AGG["chiamate"].append(("prepara", v)) or ["dettami.py"]
aggiornamenti.avvia_installazione = lambda app, nuova, v, prec, **k: AGG["chiamate"].append(("installa", v, prec))
for p in [SCRATCH / n for n in ("stato-aggiornamenti.json", "avvio-ok.json", "aggiornamento-fallito.json")]:
    p.unlink(missing_ok=True)

cfg = motore.carica_config()
app = dettatura.App(cfg, "gsk_finta")
app.avvia()  # chiama _setup con l'icona finta
STATI_PILLOLA = []
ULTIMA_PILLOLA = {}
_mostra_orig = app.indicatore.mostra
def _spia(tipo, testo, **kw):
    STATI_PILLOLA.append(tipo)
    ULTIMA_PILLOLA.clear(); ULTIMA_PILLOLA.update(kw, tipo=tipo, testo=testo)
    _mostra_orig(tipo, testo, **kw)
app.indicatore.mostra = _spia

def premi(k): app._on_press(k)
def rilascia(k): app._on_release(k)
def attendi_lavori(t=3.0):
    fine = time.time() + t
    time.sleep(0.2)
    while (app.in_elaborazione or not app.lavori.empty()) and time.time() < fine:
        time.sleep(0.05)
    time.sleep(0.8)  # ripristino appunti
def incollati():
    return [a for a in AZIONI if a == ("press", "v")]
risultati = []
def verifica(nome, cond):
    risultati.append((nome, cond)); print(("OK   " if cond else "FAIL ") + nome)

verifica("0 migrazione 1.0: cronologia e lingua", (SCRATCH / "cronologia-vecchia.txt").exists()
         and app.lingua_trad == "spagnolo" and not (SCRATCH / "stato.json").exists())
app.lingua_trad = "inglese"; app._salva_stato()

# 1) tenuto premuto
AZIONI.clear(); CHIAMATE.clear(); APPUNTI["v"] = "VECCHIO CONTENUTO"; STATI_PILLOLA.clear()
premi(Key.ctrl_r); time.sleep(0.9); rilascia(Key.ctrl_r); attendi_lavori()
verifica("1 tenuto: incolla una volta", len(incollati()) == 1 and ("giu", Key.ctrl) in AZIONI)
verifica("1 tenuto: appunti ripristinati", APPUNTI["v"] == "VECCHIO CONTENUTO")
verifica("1 tenuto: ultimo testo", app.ultimo_testo == "Ciao a tutti, questo è un test.")
verifica("1 tenuto: durata audio ~0.9-1.2s", 0.85 <= CHIAMATE[0][1] <= 1.3)
verifica("1 pillola: ascolto -> scrive -> inserito", STATI_PILLOLA == ["ascolto", "elabora", "fatto"])
verifica("1 pillola finale con pulsante Copia e il testo dettato", ULTIMA_PILLOLA.get("pulsante") == "Copia"
         and ULTIMA_PILLOLA.get("dato") == app.ultimo_testo and ULTIMA_PILLOLA.get("durata") == 5.0)
APPUNTI["v"] = "altro"
app._copia_da_pillola(ULTIMA_PILLOLA["dato"])  # come il clic su "Copia"
verifica("1 clic su Copia: testo negli appunti e conferma", APPUNTI["v"] == app.ultimo_testo
         and ULTIMA_PILLOLA["testo"].startswith("Copiato"))
APPUNTI["v"] = "VECCHIO CONTENUTO"

# 2) scorciatoia Ctrl+C con ctrl destro
AZIONI.clear(); CHIAMATE.clear(); STATI_PILLOLA.clear()
premi(Key.ctrl_r); time.sleep(0.05); premi(KeyCode("c")); rilascia(KeyCode("c")); time.sleep(0.6); rilascia(Key.ctrl_r); attendi_lavori(1)
verifica("2 ctrl+c: niente trascrizione e niente pillola", not CHIAMATE and not incollati() and "ascolto" not in STATI_PILLOLA)

# 3) autorepeat: tante pressioni durante la tenuta
AZIONI.clear(); CHIAMATE.clear()
premi(Key.ctrl_r)
for _ in range(10): time.sleep(0.07); premi(Key.ctrl_r)
rilascia(Key.ctrl_r); attendi_lavori()
verifica("3 ripetizione automatica ignorata", len(incollati()) == 1 and len([c for c in CHIAMATE if c[0] == "trascrivi"]) == 1)

# 4) doppio tocco -> mani libere -> tocco per finire
time.sleep(0.6)
AZIONI.clear(); CHIAMATE.clear()
premi(Key.ctrl_r); time.sleep(0.08); rilascia(Key.ctrl_r); time.sleep(0.12)
premi(Key.ctrl_r); time.sleep(0.08); rilascia(Key.ctrl_r)
time.sleep(0.2)
verifica("4 mani libere attiva", app.macchina.modo == "mani_libere")
time.sleep(1.2)
premi(Key.ctrl_r); time.sleep(0.08); rilascia(Key.ctrl_r); attendi_lavori()
verifica("4 mani libere: incollato e durata > 1.2s", len(incollati()) == 1 and CHIAMATE[0][1] >= 1.2)

# 5) traduzione con shift
AZIONI.clear(); CHIAMATE.clear(); STATI_PILLOLA.clear()
premi(Key.ctrl_r); time.sleep(0.3); premi(Key.shift); time.sleep(0.05); rilascia(Key.shift); time.sleep(0.5); rilascia(Key.ctrl_r); attendi_lavori()
verifica("5 traduzione richiesta all'AI", ("rifinisci", True) in CHIAMATE and app.ultimo_testo.startswith("Hello"))
verifica("5 pillola viola 'traduci'", "traduci" in STATI_PILLOLA and STATI_PILLOLA[-1] == "fatto")

# 6) esc annulla
AZIONI.clear(); CHIAMATE.clear(); STATI_PILLOLA.clear()
premi(Key.ctrl_r); time.sleep(0.5); premi(Key.esc); rilascia(Key.esc); time.sleep(0.3); rilascia(Key.ctrl_r); attendi_lavori(1)
verifica("6 esc: niente, pillola 'annullato'", not CHIAMATE and not incollati() and STATI_PILLOLA[-1] == "annullato")

# 7) silenzio
MODO_AUDIO["voce"] = False; AZIONI.clear(); CHIAMATE.clear(); STATI_PILLOLA.clear()
premi(Key.ctrl_r); time.sleep(0.8); rilascia(Key.ctrl_r); attendi_lavori(1)
verifica("7 silenzio: nessuna chiamata API", not CHIAMATE and not incollati() and STATI_PILLOLA[-1] == "silenzio")
MODO_AUDIO["voce"] = True

# 8) errore di rete -> audio salvato -> riprova
ClientFinto.fallisci = True; AZIONI.clear(); CHIAMATE.clear(); NOTIFICHE.clear()
premi(Key.ctrl_r); time.sleep(0.8); rilascia(Key.ctrl_r); attendi_lavori()
verifica("8 errore: audio salvato e notifica", app.fallito is not None and any("Riprova" in n for n in NOTIFICHE)
         and any(dettatura.CARTELLA_FALLITI.glob("*.wav")))
ClientFinto.fallisci = False
app._riprova(app.icon, None); attendi_lavori()
verifica("8 riprova: incollato", len(incollati()) == 1 and app.fallito is None)

# 9) modalità digita con a capo -> shift+invio
app.cfg["inserimento"]["metodo"] = "digita"; AZIONI.clear()
app.inserisci("Riga uno\nRiga due", None)
verifica("9 digita: shift+invio tra le righe",
         AZIONI == [("type", "Riga uno"), ("giu", Key.shift), ("press", Key.enter), ("release", Key.enter), ("su", Key.shift), ("type", "Riga due")])
app.cfg["inserimento"]["metodo"] = "incolla"

# 10) microfono che non supporta 16 kHz (registra a 48k e converte)
MODO_AUDIO["freq_ok"] = False
app.reg.chiudi(); app.reg = dettatura.Registratore(app.cfg); AZIONI.clear(); CHIAMATE.clear()
premi(Key.ctrl_r); time.sleep(0.9); rilascia(Key.ctrl_r); attendi_lavori()
verifica("10 mic 48 kHz: convertito e incollato", app.reg.freq == 48000 and len(incollati()) == 1 and 0.85 <= CHIAMATE[0][1] <= 1.3)
MODO_AUDIO["freq_ok"] = True

# 11) cronologia e dati per la dashboard
voci = motore.leggi_cronologia(dettatura.FILE_CRONOLOGIA)
verifica("11 cronologia jsonl (con voce migrata)", voci[0]["testo"] == "Ciao, arrivo alle sei"
         and any(v["grezzo"].startswith("ehm allora") for v in voci) and any(v["tradotto"] for v in voci))
verifica("11 stato menu", "oggi" in app._testo_stato())
st = app.statistiche()
verifica("11 statistiche per la dashboard", st["parole_oggi"] > 0 and len(st["quota"]) == 5
         and st["quota"][0]["richieste_oggi"] > 0)
verifica("11 stato per la dashboard", app.stato()["stato"] == "pronto" and app.stato()["contatore"] >= 5)
imp = app.impostazioni()
verifica("11 impostazioni per la dashboard", imp["valori"]["tasto"] == "ctrl_r" and imp["opzioni"]["microfoni"][1]["nome"] == "Mic finto")
app.salva_impostazioni({"tasto": "f8", "dizionario": ["Acme"]})
verifica("11 salva dalla dashboard: tasto e dizionario attivi subito", app.tasto == "f8"
         and "Acme" in motore.costruisci_prompt(app.cfg, "normale"))
AZIONI.clear()
premi(Key.f8); time.sleep(0.9); rilascia(Key.f8); attendi_lavori()
verifica("11 il nuovo tasto F8 funziona", len(incollati()) == 1)
app.salva_impostazioni({"tasto": "ctrl_r", "pulsante_copia": False})
premi(Key.ctrl_r); time.sleep(0.9); rilascia(Key.ctrl_r); attendi_lavori()
verifica("11 pulsante Copia spento dalla dashboard", ULTIMA_PILLOLA.get("tipo") == "fatto" and "pulsante" not in ULTIMA_PILLOLA)
app.salva_impostazioni({"pulsante_copia": True})
verifica("11 sessione scritta per riaprire la dashboard", "url" in motore.leggi_json(dettatura.FILE_SESSIONE, {}))
from playwright.sync_api import sync_playwright  # noqa: E402
with sync_playwright() as pw:
    b = pw.chromium.launch(); pg = b.new_page(); errori = []
    pg.on("pageerror", lambda e: errori.append(str(e)))
    pg.on("console", lambda m: errori.append(m.text) if m.type == "error" else None)
    pg.goto(app.server.url); pg.wait_for_selector("#quota .modello"); pg.wait_for_timeout(300)
    ok_pan = pg.inner_text("#paroleOggi") not in ("", "0") and pg.locator("#recenti li .testo").count() > 0
    pg.click("nav button[data-vista=impostazioni]"); pg.wait_for_selector("#i-mic option", state="attached")
    ok_imp = "Mic finto" in pg.inner_text("#i-mic") and pg.input_value("#i-tasto") == "ctrl_r"
    pg.click("#i-suoni"); pg.wait_for_timeout(300)
    ok_salva = app.cfg["audio"]["suoni"] is False
    pg.screenshot(path=str(SCRATCH / "dash_app_vera.png"), full_page=True)
    b.close()
verifica("13 dashboard vera: dati reali, impostazione salvata, nessun errore JS", ok_pan and ok_imp and ok_salva and not errori)
if not (ok_pan and ok_imp and ok_salva): print("   ", ok_pan, ok_imp, ok_salva)
if errori: print("   ", errori[:3])
app.server.chiudi()

# 14) riscrittura dal menu dell'icona
def voce_menu(menu, testo):
    for it in menu.items:
        if isinstance(it, MenuItem):
            t = it.text(it) if callable(it.text) else it.text
            if t == testo:
                return it
            if isinstance(it.action, Menu):
                trovata = voce_menu(it.action, testo)
                if trovata:
                    return trovata
    return None
menu = app._menu()
sotto = voce_menu(menu, "Riscrittura").action
verifica("14 menu Riscrittura: 4 scelte, Chiara selezionata",
         [i.text for i in sotto.items] == ["Solo trascrizione", "Fedele", "Chiara", "Ottimizzata"]
         and [i.kw["checked"](i) for i in sotto.items] == [False, False, True, False])
voce_menu(menu, "Ottimizzata").action(app.icon, None)
AZIONI.clear(); LIVELLI.clear()
premi(Key.ctrl_r); time.sleep(0.9); rilascia(Key.ctrl_r); attendi_lavori()
verifica("14 Ottimizzata: salvata e usata nella dettatura", app.cfg["ai"]["riscrittura"] == "ottimizzata"
         and LIVELLI == ["ottimizzata"] and app.ultimo_testo == "Ciao a tutti: questo è un test."
         and motore.leggi_json(dettatura.FILE_IMPOSTAZIONI, {}).get("ai", {}).get("riscrittura") == "ottimizzata")
voce_menu(menu, "Solo trascrizione").action(app.icon, None)
CHIAMATE.clear()
premi(Key.ctrl_r); time.sleep(0.9); rilascia(Key.ctrl_r); attendi_lavori()
verifica("14 Solo trascrizione: niente AI", not app.ai_attiva and ("rifinisci", False) not in CHIAMATE
         and sotto.items[0].kw["checked"](sotto.items[0]))
voce_menu(menu, "Chiara").action(app.icon, None)
verifica("14 di nuovo Chiara con AI attiva", app.ai_attiva and app.cfg["ai"]["riscrittura"] == "chiara")

# 15) confronto dei livelli per la dashboard
LIVELLI.clear()
conf = app.confronta_riscrittura("ehm allora ciao a tutti questo è un test", "normale")
verifica("15 confronto: tre livelli in ordine, attuale chiara",
         [r["livello"] for r in conf["risultati"]] == ["fedele", "chiara", "ottimizzata"]
         and sorted(LIVELLI) == ["chiara", "fedele", "ottimizzata"] and conf["attuale"] == "chiara"
         and conf["risultati"][2]["testo"] == "Ciao a tutti: questo è un test.")
if not all("testo" in r for r in conf["risultati"]): print("   ", conf)

# 16) aggiornamenti
verifica("16 avvio-ok.json scritto per l'aggiornatore",
         motore.leggi_json(dettatura.FILE_AVVIO_OK, {}).get("versione") == motore.VERSIONE)
st = app.controlla_aggiornamenti(manuale=True)
verifica("16 nessuna novità: 'aggiornata', URL di GitHub", st["stato"] == "aggiornata" and st["disponibile"] is None
         and AGG["chiamate"][-1][2] == "https://github.com/albykeg/dettami/releases/latest/download/manifest.json")
verifica("16 voce 'Aggiorna' nascosta", not voce_menu(app._menu(), "Aggiorna alla versione ") or
         not voce_menu(app._menu(), "Aggiorna alla versione ").kw["visible"](None))
AGG["manifest"] = {"app": "dettami", "versione": "9.9.0", "note": ["Novità A", "Novità B"], "data": "2026-11-06",
                   "pacchetto": {"url": "https://x", "sha256": "0" * 64, "dimensione": 10}}
NOTIFICHE.clear()
app.cfg["aggiornamenti"]["automatici"] = False
st = app.controlla_aggiornamenti()
voce = voce_menu(app._menu(), "Aggiorna alla versione 9.9.0")
verifica("16 nuova versione: stato, note, voce nel menu, notifica se non automatici",
         st["stato"] == "disponibile" and st["disponibile"] == "9.9.0" and st["note"] == ["Novità A", "Novità B"]
         and voce is not None and voce.kw["visible"](None) and any("9.9.0" in n for n in NOTIFICHE))
app.cfg["aggiornamenti"]["automatici"] = True
verifica("16 automatici: da installare quando sei inattivo", app._deve_installare_da_solo()
         and not app._inattivo_da(180) and app._inattivo_da(0))
AGG["installer"] = True; APERTI = []
app.apri = lambda cosa: APERTI.append(cosa)
app.controlla_aggiornamenti(); app.installa_aggiornamento(manuale=True)
verifica("16 serve il nuovo installer: apre la pagina e non installa", APERTI == ["setup"]
         and not app._deve_installare_da_solo() and not any(c[0] == "scarica" for c in AGG["chiamate"]))
AGG["installer"] = False; app.controlla_aggiornamenti()
USCITE = []
app._esci = lambda icon, item: USCITE.append(True)
import os  # noqa: E402
os._exit = lambda codice: USCITE.append(("uscita forzata", codice))
app.installa_aggiornamento(manuale=True)
time.sleep(1.5)
verifica("16 installazione: scarica, prepara, passa all'aggiornatore e chiude l'app",
         [c[0] for c in AGG["chiamate"][-3:]] == ["scarica", "prepara", "installa"]
         and AGG["chiamate"][-1][1:] == ("9.9.0", motore.VERSIONE) and USCITE == [True]
         and ULTIMA_PILLOLA.get("testo", "").startswith("Aggiorno Dettami alla 9.9.0")
         and motore.leggi_json(dettatura.FILE_STATO_AGG, {}).get("note_installate") == ["Novità A", "Novità B"])
# installazione che fallisce (pacchetto rotto): la versione viene saltata
app.agg["stato"] = "disponibile"
def _rotto(*a, **k): raise aggiornamenti.ErroreAggiornamento("Il pacchetto scaricato non corrisponde a quello firmato")
aggiornamenti.scarica = _rotto
app.installa_aggiornamento(manuale=True); time.sleep(1.0)
st = app.stato_aggiornamenti()
time.sleep(7)
verifica("16 uscita forzata di riserva se l'app non si chiude", ("uscita forzata", 0) in USCITE)
verifica("16 pacchetto rotto: errore mostrato, versione saltata, niente più installazioni automatiche",
         st["saltata"] and "non corrisponde" in (st["errore"] or "") and not app._deve_installare_da_solo()
         and ULTIMA_PILLOLA.get("tipo") == "errore")
# esito al riavvio dopo un aggiornamento
motore.scrivi_json(dettatura.FILE_AGG_FALLITO, {"versione": "9.9.1", "precedente": motore.VERSIONE, "motivo": "test"})
NOTIFICHE.clear(); app._esito_aggiornamento_precedente()
verifica("16 rollback avvenuto: avviso e 9.9.1 saltata", any("non è riuscito" in n for n in NOTIFICHE)
         and "9.9.1" in motore.leggi_json(dettatura.FILE_STATO_AGG, {})["saltate"]
         and not dettatura.FILE_AGG_FALLITO.exists())
app.dopo_aggiornamento = "1.2.0"; NOTIFICHE.clear(); app._esito_aggiornamento_precedente()
ua = app.stato_aggiornamenti()["ultimo_aggiornamento"]
verifica("16 dopo un aggiornamento riuscito: pillola, notifica con la prima novità",
         ua["da"] == "1.2.0" and ua["a"] == motore.VERSIONE and ua["note"] == ["Novità A", "Novità B"]
         and any("Novità A" in n for n in NOTIFICHE) and ULTIMA_PILLOLA.get("tipo") == "info")

# 12) ricarica impostazioni
app._ricarica(app.icon, None)
verifica("12 ricarica ok", any("ricaricate" in n for n in NOTIFICHE))

print(f"\n{sum(c for _, c in risultati)}/{len(risultati)} verifiche superate")
