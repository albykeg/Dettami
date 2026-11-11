"""
Simulazione di Dettami "su Mac" su Linux: sys.platform = darwin e librerie Apple finte
(Quartz, AppKit, ApplicationServices, Foundation, objc, PyObjCTools), pystray finto che fa
girare un vero "thread principale". Esegue il codice Mac di dettami.py, sistema_mac.py e
indicatore_mac.py dall'inizio alla fine.

Uso: python simula_mac.py base | permessi
"""
import json
import os
import plistlib
import queue
import stat
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "base"
RADICE = Path(__file__).resolve().parent.parent   # cartella del progetto
SCRATCH = RADICE / "prove" / "_output" / f"mac_{SCENARIO}"
import shutil  # noqa: E402
shutil.rmtree(SCRATCH, ignore_errors=True)
(SCRATCH / "home").mkdir(parents=True)
os.environ["HOME"] = str(SCRATCH / "home")
REGISTRO = SCRATCH / "comandi.log"

# comandi di sistema finti: registrano gli argomenti; osascript risponde alle finestre
FINTO = SCRATCH / "bin"
FINTO.mkdir()
(FINTO / "open").write_text(f"#!/bin/sh\necho \"open $*\" >> '{REGISTRO}'\n")
(FINTO / "osascript").write_text(f"""#!{sys.executable}
import sys
open({str(REGISTRO)!r}, "a").write("osascript " + " ".join(sys.argv[1:]).replace("\\n", " ") + "\\n")
testo = " ".join(sys.argv[1:])
if "default answer" in testo:
    print(open({str(SCRATCH / 'risposta.txt')!r}).read().strip())
""")
for f in FINTO.iterdir():
    f.chmod(0o755)

# librerie standard e di terze parti caricate prima di fingere di essere su Mac
import concurrent.futures, fcntl, hashlib, hmac, http.cookiejar, http.server, logging.handlers, shlex  # noqa: E401,E402
import socketserver, subprocess, tomllib, urllib.request, wave, webbrowser, zipfile  # noqa: E401,E402
import requests, PIL.Image, PIL.ImageDraw, PIL.ImageFont  # noqa: E401,E402
sys.platform = "darwin"
sys.path.insert(0, str(RADICE))
PRINCIPALE = threading.main_thread()
CODA_PRINCIPALE: "queue.Queue" = queue.Queue()
FUORI_DAL_PRINCIPALE = []   # chiamate AppKit fatte dal thread sbagliato

def _sul_principale(nome):
    if threading.current_thread() is not PRINCIPALE:
        FUORI_DAL_PRINCIPALE.append(nome)

# ---------------------------------------------------------------- Quartz finto
POSTATI, RICHIESTE = [], []
PERMESSI = {"accessibilita": SCENARIO != "permessi", "monitoraggio": SCENARIO != "permessi"}
TAP = {"callback": None, "riabilitato": 0, "creati": 0}

class Ciclo:
    def __init__(self): self.fermo = threading.Event()

Q = types.ModuleType("Quartz")
Q.kCGEventKeyDown, Q.kCGEventKeyUp, Q.kCGEventFlagsChanged = 10, 11, 12
Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput = 0xFFFFFFFE, 0xFFFFFFFF
Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionListenOnly = 1, 0, 1
Q.kCGKeyboardEventKeycode, Q.kCFRunLoopCommonModes = 9, "comuni"
Q.kCGEventSourceStateCombinedSessionState, Q.kCGAnnotatedSessionEventTap = 0, 2
Q.CGEventMaskBit = lambda t: 1 << t
def _tap(dove, posto, opzioni, maschera, callback, refcon):
    if not PERMESSI["monitoraggio"]:
        return None
    TAP["creati"] += 1
    if maschera != (1 << 12):  # (1 << 12) = la prova di sistema_mac.puo_ascoltare
        TAP["callback"] = callback
    return f"tap{TAP['creati']}"
Q.CGEventTapCreate = _tap
Q.CFMachPortCreateRunLoopSource = lambda *a: "sorgente"
Q.CFMachPortInvalidate = lambda t: None
Q.CFRunLoopGetCurrent = Ciclo
Q.CFRunLoopAddSource = lambda *a: None
def _abilita(tap, si):
    if si:
        TAP["riabilitato"] += 1
Q.CGEventTapEnable = _abilita
_ciclo_attuale = {}
def _run():
    c = Ciclo(); _ciclo_attuale["c"] = c
    while not c.fermo.wait(0.1):
        pass
Q.CFRunLoopRun = _run
Q.CFRunLoopStop = lambda loop: _ciclo_attuale.get("c") and _ciclo_attuale["c"].fermo.set()
Q.CGEventGetIntegerValueField = lambda e, campo: e["codice"]
Q.CGEventGetFlags = lambda e: e.get("flags", 0)
Q.CGEventSourceCreate = lambda stato: "fonte"
Q.CGEventCreateKeyboardEvent = lambda fonte, codice, giu: {"codice": codice, "giu": giu, "flags": None, "testo": None}
def _flag(e, f): e["flags"] = f
Q.CGEventSetFlags = _flag
Q.CGEventPost = lambda dove, e: POSTATI.append(dict(e))
def _unicode(e, n, s):
    assert n == len(s.encode("utf-16-le")) // 2 and n <= 16, (n, s)
    e["testo"] = s
Q.CGEventKeyboardSetUnicodeString = _unicode
Q.CGPreflightListenEventAccess = lambda: PERMESSI["monitoraggio"]
Q.CGRequestListenEventAccess = lambda: RICHIESTE.append("monitoraggio")
sys.modules["Quartz"] = Q

# ---------------------------------------------------------------- ApplicationServices finto
AS = types.ModuleType("ApplicationServices")
AS.kAXTrustedCheckOptionPrompt, AS.kAXFocusedWindowAttribute, AS.kAXTitleAttribute = "prompt", "finestra", "titolo"
AS.AXIsProcessTrusted = lambda: PERMESSI["accessibilita"]
AS.AXIsProcessTrustedWithOptions = lambda opz: RICHIESTE.append(("accessibilita", opz.get("prompt")))
AS.AXUIElementCreateApplication = lambda pid: ("app", pid)
AS.AXUIElementSetMessagingTimeout = lambda el, t: None
FRONTE = {"pid": 4242, "nome": "Mail", "id": "com.apple.mail", "titolo": "Nuovo messaggio"}
AS.AXUIElementCopyAttributeValue = lambda el, attr, _: (0, "FIN") if attr == "finestra" else (0, FRONTE["titolo"])
sys.modules["ApplicationServices"] = AS

# ---------------------------------------------------------------- AppKit / Foundation / objc finti
class Rett:
    def __init__(self, x, y, w, h):
        self.origin = types.SimpleNamespace(x=x, y=y)
        self.size = types.SimpleNamespace(width=w, height=h)

class Registra:
    """Oggetto che accetta qualsiasi metodo e lo registra."""
    def __init__(self, nome): self._nome, self.chiamate = nome, []
    def __getattr__(self, a):
        if a.startswith("_"):
            raise AttributeError(a)
        def f(*args):
            _sul_principale(f"{self._nome}.{a}")
            self.chiamate.append((a, args))
        return f

class Pannello(Registra):
    def __init__(self):
        super().__init__("NSPanel"); self.visibile = False; self.cornice = None; self.vista = None; self.ignora = True
    def setFrame_display_(self, r, d): _sul_principale("setFrame"); self.cornice = r
    def setContentView_(self, v): self.vista = v
    def setIgnoresMouseEvents_(self, si): self.ignora = si
    def orderFrontRegardless(self): _sul_principale("orderFront"); self.visibile = True
    def orderOut_(self, x): _sul_principale("orderOut"); self.visibile = False
    def isVisible(self): return self.visibile

PANNELLI = []
class NSPanel:
    @classmethod
    def alloc(cls): return cls()
    def initWithContentRect_styleMask_backing_defer_(self, r, s, b, d):
        _sul_principale("NSPanel.init"); p = Pannello(); PANNELLI.append(p); return p

class NSView:
    @classmethod
    def alloc(cls): return cls.__new__(cls)
    def initWithFrame_(self, r): self._cornice = r; return self
    def bounds(self): return Rett(0, 0, self._cornice.size.width, self._cornice.size.height)
    def setFrame_(self, r): self._cornice = r
    def setNeedsDisplay_(self, si): _sul_principale("setNeedsDisplay")
    def convertPoint_fromView_(self, p, v): return p

class Immagine:
    @classmethod
    def alloc(cls): return cls()
    def initWithData_(self, dati): assert dati[:4] == b"\x89PNG"; self.dati = dati; return self
    def setSize_(self, s): self.dimensione = s

SCHERMO = types.SimpleNamespace(backingScaleFactor=lambda: 2.0, visibleFrame=lambda: Rett(0, 25, 1440, 850))
MOUSE = {"x": -1, "y": -1}
AK = types.ModuleType("AppKit")
AK.NSPanel, AK.NSView, AK.NSImage = NSPanel, NSView, Immagine
AK.NSMakeRect = Rett
AK.NSColor = types.SimpleNamespace(clearColor=lambda: "trasparente")
AK.NSScreen = types.SimpleNamespace(mainScreen=lambda: SCHERMO, screens=lambda: [SCHERMO])
AK.NSEvent = types.SimpleNamespace(mouseLocation=lambda: types.SimpleNamespace(**MOUSE))
for i, n in enumerate(["NSWindowStyleMaskBorderless", "NSWindowStyleMaskNonactivatingPanel", "NSBackingStoreBuffered",
                       "NSStatusWindowLevel", "NSWindowCollectionBehaviorCanJoinAllSpaces",
                       "NSWindowCollectionBehaviorStationary", "NSWindowCollectionBehaviorFullScreenAuxiliary",
                       "NSWindowCollectionBehaviorIgnoresCycle"]):
    setattr(AK, n, 1 << i)
class _AppFronte:
    def processIdentifier(self): return FRONTE["pid"]
    def localizedName(self): return FRONTE["nome"]
    def bundleIdentifier(self): return FRONTE["id"]
AK.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: types.SimpleNamespace(frontmostApplication=lambda: _AppFronte()))
sys.modules["AppKit"] = AK
FN = types.ModuleType("Foundation"); FN.NSData = types.SimpleNamespace(dataWithBytes_length_=lambda b, n: b[:n])
sys.modules["Foundation"] = FN
MIC = {"stato": 3}
OB = types.ModuleType("objc"); OB.super = super; OB.loadBundle = lambda *a, **k: None
OB.lookUpClass = lambda n: types.SimpleNamespace(authorizationStatusForMediaType_=lambda t: MIC["stato"])
sys.modules["objc"] = OB
AH = types.ModuleType("PyObjCTools.AppHelper"); AH.callAfter = lambda f, *a: CODA_PRINCIPALE.put((f, a))
PT = types.ModuleType("PyObjCTools"); PT.AppHelper = AH
sys.modules["PyObjCTools"] = PT; sys.modules["PyObjCTools.AppHelper"] = AH

# ---------------------------------------------------------------- pystray finto con thread principale vero
NOTIFICHE_PYSTRAY, AGGIORNAMENTI_ICONA = [], []
class Icon:
    def __init__(self, nome, img, titolo, menu):
        self._icon, self.title, self.menu, self._fermo, self._visible = img, titolo, menu, False, False
    @property
    def icon(self): return self._icon
    @icon.setter
    def icon(self, v): _sul_principale("icon.icon"); self._icon = v
    @property
    def visible(self): return self._visible
    @visible.setter
    def visible(self, v): _sul_principale("icon.visible"); self._visible = v
    def run(self, setup):
        threading.Thread(target=setup, args=(self,), name="setup").start()
        while not self._fermo:
            try:
                f, a = CODA_PRINCIPALE.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                f(*a)
            except Exception as e:
                ERRORI_PRINCIPALE.append(repr(e))
    def notify(self, m, t=None): NOTIFICHE_PYSTRAY.append(m)
    def update_menu(self): _sul_principale("update_menu"); AGGIORNAMENTI_ICONA.append(threading.current_thread().name)
    def stop(self): _sul_principale("icon.stop"); self._fermo = True
ERRORI_PRINCIPALE = []
class MenuItem:
    def __init__(self, text, action, **kw): self.text, self.action, self.kw = text, action, kw
class Menu:
    SEPARATOR = object()
    def __init__(self, *items): self.items = items
ps = types.ModuleType("pystray"); ps.Icon, ps.MenuItem, ps.Menu = Icon, MenuItem, Menu
sys.modules["pystray"] = ps

APPUNTI = {"v": "VECCHIO CONTENUTO"}
pc = types.ModuleType("pyperclip"); pc.copy = lambda s: APPUNTI.__setitem__("v", s); pc.paste = lambda: APPUNTI["v"]
sys.modules["pyperclip"] = pc
VOCE = {"si": True}
class InputStream:
    def __init__(self, samplerate, channels, dtype, device, callback, latency, blocksize=0):
        self.fs, self.cb, self.attivo = samplerate, callback, False
    def _ciclo(self):
        n, i = int(self.fs * 0.03), 0
        while self.attivo:
            t = (np.arange(n) + i) / self.fs
            self.cb((np.sin(2 * np.pi * 220 * t) * (4000 if VOCE["si"] else 0)).astype(np.int16).reshape(-1, 1), n, None, None)
            i += n; time.sleep(0.03)
    def start(self): self.attivo = True; threading.Thread(target=self._ciclo, daemon=True).start()
    def stop(self): self.attivo = False
    def close(self): pass
sd = types.ModuleType("sounddevice"); sd.InputStream = InputStream; sd.play = lambda *a, **k: None
sd.query_devices = lambda *a: {"default_samplerate": 48000.0, "name": "MacBook Pro Microphone", "max_input_channels": 1} if a else [{"name": "MacBook Pro Microphone", "max_input_channels": 1}]
sd.default = types.SimpleNamespace(device=(0, 0))
sys.modules["sounddevice"] = sd

# ---------------------------------------------------------------- import dell'app
import motore  # noqa: E402
import sistema_mac  # noqa: E402
import dettami  # noqa: E402
import aggiornamenti  # noqa: E402
sistema_mac.OPEN = str(FINTO / "open")
sistema_mac.OSASCRIPT = str(FINTO / "osascript")
CARTELLA = SCRATCH / "dati"
CARTELLA.mkdir()
dettami.CARTELLA = CARTELLA
for nome in ("FILE_CRONOLOGIA", "FILE_LOG", "FILE_IMPOSTAZIONI", "FILE_USO", "FILE_SESSIONE", "FILE_STATO_AGG",
             "FILE_AVVIO_OK", "FILE_AGG_FALLITO", "FILE_ENV", "FILE_STATO", "FILE_CRONOLOGIA_TXT"):
    setattr(dettami, nome, CARTELLA / Path(getattr(dettami, nome)).name)
dettami.CARTELLA_AGG = CARTELLA / "_aggiornamento"
dettami.CARTELLA_FALLITI = CARTELLA / "falliti"
dettami.configura_log()
aggiornamenti.controlla = lambda *a, **k: None

RISPOSTE = {"testo": "Ciao Marco, ci vediamo domani alle 6."}
class ClientFinto:
    def __init__(self, cfg, key): self.quote, self.uso, self.key = {}, None, key
    def scalda(self): pass
    def trascrivi(self, audio, cfg): return "ehm ciao marco ci vediamo domani alle 6"
    def rifinisci(self, sistema, grezzo, cfg, livello="chiara"):
        return "Hello Marco, see you tomorrow at 6." if "TRADUZIONE" in sistema else RISPOSTE["testo"]
    def verifica_chiave(self): return (self.key.startswith("gsk_"), "API key non valida")
motore.ClientAI = ClientFinto

RISULTATI = []
def verifica(nome, ok, dettaglio=""):
    RISULTATI.append((nome, bool(ok)))
    print(("OK   " if ok else "FAIL ") + nome + ("" if ok or not dettaglio else f"\n     -> {dettaglio}"))

def comandi():
    return REGISTRO.read_text() if REGISTRO.exists() else ""

def attendi(cond, s=5.0):
    fine = time.monotonic() + s
    while time.monotonic() < fine:
        if cond():
            return True
        time.sleep(0.05)
    return cond()

def evento(codice, flags=None, tipo=None):
    if tipo is None:
        tipo = Q.kCGEventFlagsChanged if codice in sistema_mac.MASCHERE_MODIFICATORI else Q.kCGEventKeyDown
    TAP["callback"](None, tipo, {"codice": codice, "flags": flags or 0}, None)

def detta(secondi=0.9, mentre=None):
    evento(61, 0x40)               # Option destro giù
    time.sleep(secondi / 2)
    if mentre:
        mentre()
    time.sleep(secondi / 2)
    evento(61, 0)                  # su

def finito(app):
    time.sleep(0.3)
    return attendi(lambda: app.in_elaborazione == 0 and not app.macchina.registrando, 6)

# ================================================================= scenario base
def scenario_base(app):
    verifica("tap della tastiera creato in ascolto, nessun errore",
             attendi(lambda: TAP["callback"] is not None and app.listener.pronto.is_set()) and app.listener.errore is None)
    verifica("tasto predefinito Option destro", app.tasto == "alt_r" and app._nome_tasto() == "Option destro (⌥)")
    verifica("pillola di benvenuto con il nome del tasto Mac",
             attendi(lambda: PANNELLI and PANNELLI[0].visibile)
             and "Option destro" in (app.indicatore.stato_attuale.testo if app.indicatore.stato_attuale else ""))
    p = PANNELLI[0]
    c = p.cornice
    verifica("pillola centrata in basso, in punti (Retina 2x)",
             abs(c.origin.x + c.size.width / 2 - 720) < 1 and c.origin.y == 25 + 28 and 75 < c.size.width < 420,
             f"{c.origin.x},{c.origin.y} {c.size.width}x{c.size.height}")
    POSTATI.clear()
    detta()
    finito(app)
    v = [e for e in POSTATI if e["codice"] == 9]
    verifica("dettatura → Cmd+V (tasto V con solo Command)", len(v) == 2 and all(e["flags"] == 0x100000 for e in v)
             and [e["giu"] for e in v] == [True, False], POSTATI)
    verifica("testo inserito e appunti rimessi com'erano",
             app.ultimo_testo == RISPOSTE["testo"] and attendi(lambda: APPUNTI["v"] == "VECCHIO CONTENUTO", 2))
    voce = motore.leggi_cronologia(dettami.FILE_CRONOLOGIA)[-1]
    verifica("contesto Mac: app 'mail', stile email (com.apple.mail)", voce["app"] == "mail" and voce["stile"] == "email", voce)
    verifica("pillola finale con pulsante Copia", app.indicatore.stato_attuale and app.indicatore.stato_attuale.pulsante == "Copia")
    # clic sul pulsante Copia
    attendi(lambda: PANNELLI[0].vista is not None and app.indicatore._rett_pulsante is not None, 2)
    verifica("pannello cliccabile solo con il pulsante", attendi(lambda: PANNELLI[0].ignora is False, 2))
    r = app.indicatore._rett_pulsante
    APPUNTI["v"] = "altro"
    vista = PANNELLI[0].vista
    CODA_PRINCIPALE.put((vista.mouseUp_, (types.SimpleNamespace(locationInWindow=lambda: types.SimpleNamespace(
        x=(r[0] + r[2]) / 2, y=vista.bounds().size.height - (r[1] + r[3]) / 2)),)))
    verifica("clic su Copia → testo negli appunti", attendi(lambda: APPUNTI["v"] == RISPOSTE["testo"], 3), APPUNTI)
    # traduzione con Shift
    detta(1.0, mentre=lambda: evento(56, 0x40 | 0x02))
    finito(app)
    verifica("Shift mentre detti → traduzione", app.ultimo_testo.startswith("Hello"))
    # Esc annulla
    POSTATI.clear()
    evento(61, 0x40); time.sleep(0.5); evento(53); time.sleep(0.2); evento(61, 0)
    finito(app); time.sleep(0.3)
    verifica("Esc annulla: niente incollato", not [e for e in POSTATI if e["codice"] == 9])
    # cambio app mentre scrive → appunti
    POSTATI.clear()
    def cambia_app():
        FRONTE.update(pid=5151, nome="Safari", id="com.apple.Safari")
    detta(0.9, mentre=cambia_app)
    finito(app)
    verifica("cambi app prima dell'inserimento → resta negli appunti con avviso ⌘V",
             not [e for e in POSTATI if e["codice"] == 9] and APPUNTI["v"].strip() == RISPOSTE["testo"]
             and attendi(lambda: "premi ⌘V" in comandi(), 3), (APPUNTI, POSTATI))
    FRONTE.update(pid=4242, nome="Mail", id="com.apple.mail")
    # metodo "digita" con due righe
    POSTATI.clear()
    app.cfg["inserimento"]["metodo"] = "digita"
    RISPOSTE["testo"] = "Prima riga con àccenti e emoji 🙂 abbastanza lunga da dividere\nSeconda riga"
    detta(); finito(app)
    scritti = "".join(e["testo"] for e in POSTATI if e["testo"] and e["giu"])
    invii = [e for e in POSTATI if e["codice"] == 36]
    verifica("metodo digita: testo intero a blocchi + Shift+Invio tra le righe",
             scritti == RISPOSTE["testo"].replace("\n", "") + " " and len(invii) == 2 and invii[0]["flags"] == 0x20000,
             (scritti, invii))
    app.cfg["inserimento"]["metodo"] = "incolla"
    RISPOSTE["testo"] = "Ciao Marco, ci vediamo domani alle 6."
    # macOS spegne il tap se è lento: va riacceso
    prima = TAP["riabilitato"]
    TAP["callback"](None, Q.kCGEventTapDisabledByTimeout, {"codice": 0}, None)
    verifica("tap spento da macOS → riacceso", TAP["riabilitato"] == prima + 1)
    # microfono bloccato: macOS manda solo silenzio
    MIC["stato"], VOCE["si"] = 2, False
    detta(); finito(app)
    verifica("microfono negato → avviso chiaro e pannello Privacy_Microphone",
             "Microfono bloccato" in (app.indicatore.stato_attuale.testo if app.indicatore.stato_attuale else "")
             and "Privacy_Microphone" in comandi())
    MIC["stato"], VOCE["si"] = 3, True
    # tasto non valido su Mac
    app.cfg["tasti"]["dettatura"] = "scroll_lock"; app._imposta_tasti()
    verifica("tasto non disponibile su Mac → Option destro", app.tasto == "alt_r"
             and attendi(lambda: "non usabile su Mac: uso Option destro" in comandi(), 3))
    app.cfg["tasti"]["dettatura"] = "cmd_r"; app._imposta_tasti()
    verifica("si può scegliere Command destro", app.tasto == "cmd_r")
    app.cfg["tasti"]["dettatura"] = "alt_r"; app._imposta_tasti()
    # dashboard: dati per Mac
    imp, st = app.impostazioni(), app.stato()
    verifica("dashboard: sistema mac, tasti Mac, microfono predefinito di macOS",
             imp["sistema"] == "mac" and st["sistema"] == "mac" and st["tasto_nome"] == "Option destro (⌥)"
             and [t["valore"] for t in imp["opzioni"]["tasti"]][:3] == ["alt_r", "cmd_r", "fn"]
             and imp["opzioni"]["microfoni"][0]["nome"] == "Predefinito di macOS")
    try:
        motore.valida_impostazioni({"tasto": "fn"}, app.cfg)
        ok_fn = True
    except ValueError:
        ok_fn = False
    verifica("impostazione tasto fn valida su Mac", ok_fn)
    # avvio al login
    stato_on = app.avvio_automatico(True)
    agente = plistlib.loads(sistema_mac.AGENTE.read_bytes())
    comando = agente["ProgramArguments"][2]
    verifica("avvio al login: LaunchAgent che apre Dettami.app con --avvio",
             stato_on and agente["RunAtLoad"] and agente["AssociatedBundleIdentifiers"] == [sistema_mac.ID_APP]
             and '["--avvio"]' in comando and "open -a" in comando and "Dettami.app" in comando
             and app.impostazioni()["avvio_automatico"], comando)
    verifica("avvio al login spento", app.avvio_automatico(False) is False and not sistema_mac.AGENTE.exists())
    # chiave Groq dalla finestra di macOS
    (SCRATCH / "risposta.txt").write_text("  gsk_ChiaveNuova1234567890  ")
    app.api_key = ""
    app._imposta_chiave()
    verifica("chiave da finestra macOS: verificata, salvata (solo per te)",
             attendi(lambda: dettami.FILE_ENV.exists(), 4)
             and dettami.FILE_ENV.read_text() == "GROQ_API_KEY=gsk_ChiaveNuova1234567890\n"
             and stat.S_IMODE(dettami.FILE_ENV.stat().st_mode) == 0o600 and app.api_key.startswith("gsk_")
             and "console.groq.com/keys" in comandi())
    # aprire file e siti
    app.apri("progetto"); app.apri("config")
    verifica("apri GitHub e config.toml (editor di testo)", attendi(lambda: "open https://github.com/albykeg/dettami" in comandi()
             and "open -t" in comandi() and "config.toml" in comandi(), 3))
    verifica("notifiche con osascript", "display notification" in comandi())
    # aggiornamenti: manifest per Mac
    verifica("su Mac gli aggiornamenti leggono manifest-mac.json",
             aggiornamenti.URL_MANIFEST.endswith("/manifest-mac.json") and aggiornamenti.FILE_REQUISITI == "requisiti-mac.txt")
    verifica("menu: voci Mac visibili", all(any(getattr(i, "text", None) == t and i.kw.get("visible", True) is True
                                                 for i in app._menu().items)
                                             for t in ("Permessi di macOS", "Disinstalla Dettami…")))
    # disinstallazione dal menu: conferma (osascript finto = OK), lancia lo script e chiude l'app
    script = CARTELLA / "disinstalla.command"
    script.write_text(f"#!/bin/bash\necho \"disinstalla $*\" >> '{REGISTRO}'\n")
    app._disinstalla_mac()
    verifica("Disinstalla: chiede conferma, lancia lo script e chiude l'app",
             attendi(lambda: "disinstalla --senza-conferma" in comandi() and app.icon._fermo, 5), comandi()[-200:])

# ================================================================= scenario permessi
def scenario_permessi(app):
    verifica("senza Monitoraggio input il tap non si crea (errore registrato)",
             attendi(lambda: app.listener.pronto.is_set()) and app.listener.errore)
    verifica("chiede i permessi a macOS e apre il pannello Accessibilità",
             attendi(lambda: "monitoraggio" in RICHIESTE and ("accessibilita", True) in RICHIESTE
                     and "Privacy_Accessibility" in comandi(), 4), (RICHIESTE, comandi()))
    verifica("pillola che spiega cosa consentire",
             "Accessibilità e Monitoraggio input" in (app.indicatore.stato_attuale.testo if app.indicatore.stato_attuale else ""))
    PERMESSI["accessibilita"] = True
    verifica("Accessibilità data → apre il pannello Monitoraggio input",
             attendi(lambda: "Privacy_ListenEvent" in comandi(), 5), comandi())
    PERMESSI["monitoraggio"] = True
    verifica("tutti i permessi → prepara la riapertura con --avvio e chiude questa copia",
             attendi(lambda: app.icon._fermo, 8)
             and json.loads((CARTELLA / "argomenti-avvio.json").read_text()) == ["--avvio"])
    verifica("segno anti-ciclo dei riavvii salvato", (CARTELLA / "riavvio-permessi.json").exists())
    # la riapertura aspetta che la copia vecchia sia chiusa: provata con un processo che esce subito
    import subprocess as sp
    codice = (f"import sys; sys.path.insert(0, {str(RADICE)!r}); import sistema_mac; "
              f"sistema_mac.OPEN = {str(FINTO / 'open')!r}; sistema_mac.riapri_dopo({str(SCRATCH)!r}, ['--avvio'])")
    inizio = time.monotonic()
    sp.run([sys.executable, "-c", codice], check=True, env={**os.environ, "PYTHONPATH": ""})
    verifica("riapre con open -n -a appena la copia vecchia si chiude",
             attendi(lambda: "open -n -a" in comandi() and "Dettami.app" in comandi(), 4)
             and time.monotonic() - inizio < 3, comandi()[-200:])
    # finché la copia vecchia è viva, non riapre
    lunga = sp.Popen([sys.executable, "-c", codice + "; import time; time.sleep(2.5)"])
    time.sleep(1.5)
    righe_prima = comandi().count("open -n -a")
    lunga.wait()
    verifica("finché la copia vecchia è aperta aspetta, poi riapre",
             attendi(lambda: comandi().count("open -n -a") == righe_prima + 1, 4) and righe_prima == 1)

# ================================================================= avvio
# come nell'installazione Mac: tasto Option destro (il config.toml per Mac lo ha già)
motore.scrivi_json(dettami.FILE_IMPOSTAZIONI, {"tasti": {"dettatura": "alt_r"}})
cfg = motore.carica_config(dettami.FILE_CONFIG, dettami.FILE_IMPOSTAZIONI)
app = dettami.App(cfg, "gsk_chiavefinta1234567890", apri_dashboard=False)
assert dettami.istanza_unica()
verifica("istanza unica con file di blocco e PID", (CARTELLA / "istanza.lock").read_text() == str(os.getpid())
         and sistema_mac.pid_in_esecuzione(CARTELLA) == os.getpid())

def guida():
    try:
        attendi(lambda: app.server is not None, 8)
        (scenario_base if SCENARIO == "base" else scenario_permessi)(app)
    except Exception:
        import traceback
        traceback.print_exc()
        RISULTATI.append(("eccezione", False))
    finally:
        CODA_PRINCIPALE.put((app.icon.stop, ()))
scenario = threading.Thread(target=guida, name="scenario", daemon=True)
scenario.start()
app.avvia()     # blocca il thread principale finché l'app non si chiude (come su Mac)
scenario.join(15)
verifica("AppKit usato solo dal thread principale", not FUORI_DAL_PRINCIPALE, sorted(set(FUORI_DAL_PRINCIPALE)))
verifica("icona aggiornata solo sul thread principale", AGGIORNAMENTI_ICONA and set(AGGIORNAMENTI_ICONA) == {"MainThread"},
         set(AGGIORNAMENTI_ICONA))
verifica("nessun errore sul thread principale", not ERRORI_PRINCIPALE, ERRORI_PRINCIPALE)
errori_log = [r for r in dettami.FILE_LOG.read_text().splitlines() if " ERROR " in r] if dettami.FILE_LOG.exists() else []
verifica("nessun errore nel log", not errori_log, errori_log[:5])
ok = sum(1 for _, v in RISULTATI if v)
print(f"\n{ok}/{len(RISULTATI)} verifiche superate ({SCENARIO})")
os._exit(0 if ok == len(RISULTATI) else 1)
