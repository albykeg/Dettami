"""
Dettami su macOS: tutto quello che tocca il sistema.

  - tasto di dettatura letto con un "event tap" di Quartz (solo ascolto, nessun tasto bloccato)
  - incolla (Cmd+V) e scrittura del testo con eventi di tastiera
  - app e finestra in primo piano, per scegliere lo stile
  - permessi: Accessibilità, Monitoraggio input, Microfono
  - istanza unica, avvio al login, notifiche, finestre di dialogo

Il resto di Dettami (trascrizione, riscrittura, dashboard, aggiornamenti) è lo stesso di Windows.
Le librerie di sistema (PyObjC) si importano solo dentro le funzioni: il modulo si carica
anche su Linux per i test.
"""
from __future__ import annotations

import json
import logging
import os
import plistlib
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from motore import TASTI_MAC

log = logging.getLogger("dettami")
MAC = sys.platform == "darwin"

ID_APP = "io.github.albykeg.dettami"
DATI = Path.home() / "Library" / "Application Support" / "Dettami"
APP = Path.home() / "Applications" / "Dettami.app"
AGENTE = Path.home() / "Library" / "LaunchAgents" / f"{ID_APP}.plist"
FILE_ARGOMENTI = "argomenti-avvio.json"   # letto da mac/avvio_app.py quando l'app si apre
OPEN = "/usr/bin/open"
OSASCRIPT = "/usr/bin/osascript"

# Tasti che si possono usare per dettare (nome -> come si vede nella dashboard)
TASTI_DETTATURA = TASTI_MAC

# codice del tasto (kVK_*) -> nome (gli stessi nomi di pynput usati su Windows)
NOMI_TASTI = {
    61: "alt_r", 58: "alt_l", 54: "cmd_r", 55: "cmd_l", 62: "ctrl_r", 59: "ctrl_l",
    60: "shift_r", 56: "shift", 63: "fn", 57: "caps_lock", 53: "esc", 36: "enter", 76: "enter",
    49: "space", 48: "tab", 51: "backspace",
    122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7", 100: "f8", 101: "f9",
    109: "f10", 103: "f11", 111: "f12", 105: "f13", 107: "f14", 113: "f15", 106: "f16", 64: "f17",
    79: "f18", 80: "f19", 90: "f20",
}
# per i modificatori macOS manda solo "flags changed": il bit dice se il tasto è giù o su
MASCHERE_MODIFICATORI = {
    61: 0x40, 58: 0x20,          # Option destro / sinistro
    54: 0x10, 55: 0x08,          # Command destro / sinistro
    62: 0x2000, 59: 0x01,        # Control destro / sinistro
    60: 0x04, 56: 0x02,          # Shift destro / sinistro
    63: 0x800000,                # Fn (kCGEventFlagMaskSecondaryFn)
}
TASTO_V, TASTO_INVIO = 9, 36
FLAG_CMD, FLAG_SHIFT = 0x100000, 0x20000

PANNELLI = {
    "accessibilita": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "monitoraggio": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "microfono": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}
NOMI_PERMESSI = {"accessibilita": "Accessibilità", "monitoraggio": "Monitoraggio input", "microfono": "Microfono"}


# --------------------------------------------------------------------------- thread principale

def sul_thread_principale(funzione, *argomenti) -> None:
    """AppKit va usato solo dal thread principale (quello del menu nella barra in alto)."""
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(funzione, *argomenti)
    except Exception:
        log.exception("Chiamata sul thread principale")


# --------------------------------------------------------------------------- tastiera

class AscoltoTasti(threading.Thread):
    """
    Ascolta la tastiera di tutto il Mac senza bloccare niente (come pynput.keyboard.Listener).
    Chiama on_press(nome) / on_release(nome) con nomi come "alt_r", "shift", "esc".
    Non traduce i tasti in caratteri: niente chiamate che macOS vuole solo sul thread principale.
    """

    def __init__(self, on_press, on_release):
        super().__init__(daemon=True, name="tastiera")
        self.on_press, self.on_release = on_press, on_release
        self.pronto = threading.Event()
        self.errore: str | None = None
        self._tap = None
        self._loop = None

    def run(self):
        try:
            import Quartz
            eventi = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                      | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
            self._tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                                Quartz.kCGEventTapOptionListenOnly, eventi, self._evento, None)
            if self._tap is None:
                self.errore = "macOS non permette ancora a Dettami di leggere il tasto (Monitoraggio input)"
                return
            sorgente = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._loop, sorgente, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(self._tap, True)
            self.pronto.set()
            Quartz.CFRunLoopRun()
        except Exception as e:
            log.exception("Ascolto della tastiera")
            self.errore = str(e)
        finally:
            self.pronto.set()

    def _evento(self, proxy, tipo, evento, refcon):
        try:
            import Quartz
            if tipo in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self._tap, True)  # macOS lo spegne se una volta risponde lento
                return evento
            codice = int(Quartz.CGEventGetIntegerValueField(evento, Quartz.kCGKeyboardEventKeycode))
            nome = NOMI_TASTI.get(codice, "carattere")
            if tipo == Quartz.kCGEventFlagsChanged:
                maschera = MASCHERE_MODIFICATORI.get(codice)
                if maschera is not None:
                    giu = bool(int(Quartz.CGEventGetFlags(evento)) & maschera)
                    (self.on_press if giu else self.on_release)(nome)
            elif tipo == Quartz.kCGEventKeyDown:
                self.on_press(nome)
            elif tipo == Quartz.kCGEventKeyUp:
                self.on_release(nome)
        except Exception:
            log.exception("Evento di tastiera")
        return evento

    def stop(self):
        try:
            import Quartz
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, False)
            if self._loop is not None:
                Quartz.CFRunLoopStop(self._loop)
        except Exception:
            pass


def _premi(codice: int, flag: int = 0) -> None:
    import Quartz
    sorgente = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    for giu in (True, False):
        e = Quartz.CGEventCreateKeyboardEvent(sorgente, codice, giu)
        Quartz.CGEventSetFlags(e, flag)  # solo questi modificatori, anche se tieni premuto Option
        Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, e)
        time.sleep(0.012)


def incolla() -> None:
    """Cmd+V nell'app in primo piano."""
    _premi(TASTO_V, FLAG_CMD)


def a_capo_morbido() -> None:
    """Shift+Invio: va a capo senza inviare il messaggio nelle chat."""
    _premi(TASTO_INVIO, FLAG_SHIFT)


def digita(testo: str) -> None:
    """Scrive il testo come se lo digitassi (per i programmi in cui incollare non va)."""
    import Quartz
    sorgente = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    blocco = ""
    for carattere in testo + "\0":
        if carattere != "\0" and len((blocco + carattere).encode("utf-16-le")) // 2 <= 16:
            blocco += carattere
            continue
        if blocco:
            for giu in (True, False):
                e = Quartz.CGEventCreateKeyboardEvent(sorgente, 0, giu)
                Quartz.CGEventSetFlags(e, 0)
                Quartz.CGEventKeyboardSetUnicodeString(e, len(blocco.encode("utf-16-le")) // 2, blocco)
                Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, e)
            time.sleep(0.008)
        blocco = carattere if carattere != "\0" else ""


# --------------------------------------------------------------------------- app in primo piano

def app_in_primo_piano() -> tuple[int | None, str, str]:
    """(pid, nome, identificativo) dell'app in cui stai scrivendo."""
    try:
        from AppKit import NSWorkspace
        a = NSWorkspace.sharedWorkspace().frontmostApplication()
        if a is None:
            return None, "", ""
        return int(a.processIdentifier()), str(a.localizedName() or ""), str(a.bundleIdentifier() or "")
    except Exception:
        log.exception("App in primo piano")
        return None, "", ""


def titolo_finestra(pid: int | None) -> str:
    """Titolo della finestra attiva (serve l'Accessibilità): distingue per esempio Gmail da un altro sito."""
    if not pid:
        return ""
    try:
        import ApplicationServices as AS
        app = AS.AXUIElementCreateApplication(pid)
        AS.AXUIElementSetMessagingTimeout(app, 0.25)
        errore, finestra = AS.AXUIElementCopyAttributeValue(app, AS.kAXFocusedWindowAttribute, None)
        if errore or finestra is None:
            return ""
        errore, titolo = AS.AXUIElementCopyAttributeValue(finestra, AS.kAXTitleAttribute, None)
        return "" if errore or titolo is None else str(titolo)
    except Exception:
        return ""


# --------------------------------------------------------------------------- permessi

def permessi() -> dict[str, bool | None]:
    """Stato dei permessi. None = non si sa (macOS troppo vecchio o lettura non riuscita)."""
    stato: dict[str, bool | None] = {"accessibilita": None, "monitoraggio": None, "microfono": None}
    try:
        import ApplicationServices as AS
        stato["accessibilita"] = bool(AS.AXIsProcessTrusted())
    except Exception:
        pass
    try:
        import Quartz
        stato["monitoraggio"] = bool(Quartz.CGPreflightListenEventAccess())
    except Exception:
        pass
    m = stato_microfono()
    stato["microfono"] = None if m in ("non_deciso", "sconosciuto") else m == "concesso"
    return stato


def mancanti(stato: dict | None = None) -> list[str]:
    stato = stato if stato is not None else permessi()
    return [k for k in ("accessibilita", "monitoraggio") if stato.get(k) is False]


def chiedi_permessi() -> None:
    """Mostra le richieste di macOS (una volta sola: poi si attivano da Impostazioni di Sistema)."""
    try:
        import ApplicationServices as AS
        AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True})
    except Exception:
        log.exception("Richiesta Accessibilità")
    try:
        import Quartz
        Quartz.CGRequestListenEventAccess()
    except Exception:
        log.exception("Richiesta Monitoraggio input")


def stato_microfono() -> str:
    """"concesso", "negato", "limitato", "non_deciso" o "sconosciuto"."""
    try:
        import objc
        objc.loadBundle("AVFoundation", {}, bundle_path="/System/Library/Frameworks/AVFoundation.framework")
        dispositivo = objc.lookUpClass("AVCaptureDevice")
        valore = int(dispositivo.authorizationStatusForMediaType_("soun"))  # AVMediaTypeAudio
        return {0: "non_deciso", 1: "limitato", 2: "negato", 3: "concesso"}.get(valore, "sconosciuto")
    except Exception:
        return "sconosciuto"


def puo_ascoltare() -> bool:
    """Prova a creare (e chiude subito) un ascolto della tastiera: dice se macOS lo permette adesso."""
    try:
        import Quartz
        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionListenOnly,
                                      Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
                                      lambda proxy, tipo, evento, refcon: evento, None)
        if tap is None:
            return False
        Quartz.CFMachPortInvalidate(tap)
        return True
    except Exception:
        return False


def apri_impostazioni(permesso: str) -> None:
    apri_indirizzo(PANNELLI.get(permesso, PANNELLI["accessibilita"]))


# --------------------------------------------------------------------------- istanza unica e riavvio

_blocco = None


def istanza_unica(cartella: Path) -> bool:
    """True se è la sola Dettami aperta. Nel file c'è il PID (serve all'aggiornatore)."""
    global _blocco
    import fcntl
    percorso = Path(cartella) / "istanza.lock"
    f = open(percorso, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _blocco = f
    return True


def pid_in_esecuzione(cartella: Path) -> int | None:
    try:
        return int((Path(cartella) / "istanza.lock").read_text().strip() or 0) or None
    except (OSError, ValueError):
        return None


def bundle_di(eseguibile: str | os.PathLike) -> Path | None:
    """…/Dettami.app/Contents/MacOS/Dettami -> …/Dettami.app"""
    p = Path(eseguibile)
    if p.parent.name == "MacOS" and p.parent.parent.name == "Contents" and p.parents[2].suffix == ".app":
        return p.parents[2]
    return None


def scrivi_argomenti(cartella: Path, argomenti: list[str]) -> None:
    (Path(cartella) / FILE_ARGOMENTI).write_text(json.dumps(argomenti), encoding="utf-8")


def riapri_dopo(cartella: Path, argomenti: list[str]) -> None:
    """Riapre Dettami appena questa copia si è chiusa (al massimo 15 s), come se la aprissi dal Finder."""
    bundle = bundle_di(sys.executable) or APP
    scrivi_argomenti(cartella, argomenti)
    comando = (f"i=0; while kill -0 {os.getpid()} 2>/dev/null && [ $i -lt 75 ]; do sleep 0.2; i=$((i+1)); done; "
               f"sleep 0.3; exec {OPEN} -n -a {shlex.quote(str(bundle))}")
    subprocess.Popen(["/bin/sh", "-c", comando], start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- avvio al login

def contenuto_agente(bundle: Path = APP, dati: Path = DATI) -> dict:
    """LaunchAgent: all'accensione apre Dettami.app con --avvio (parte in silenzio, senza dashboard)."""
    argomenti = shlex.quote(str(dati / FILE_ARGOMENTI))
    comando = (f"printf '%s' '[\"--avvio\"]' > {argomenti}; "
               f"exec {OPEN} -a {shlex.quote(str(bundle))}")
    return {
        "Label": ID_APP,
        "ProgramArguments": ["/bin/sh", "-c", comando],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "AssociatedBundleIdentifiers": [ID_APP],  # in Impostazioni compare come "Dettami"
    }


def imposta_avvio_automatico(attivo: bool, percorso: Path = AGENTE) -> bool:
    if not attivo:
        percorso.unlink(missing_ok=True)
        return percorso.exists()
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with open(percorso, "wb") as f:
        plistlib.dump(contenuto_agente(), f)
    return percorso.exists()


# --------------------------------------------------------------------------- aprire, avvisare, chiedere

def apri_indirizzo(indirizzo: str) -> None:
    subprocess.Popen([OPEN, indirizzo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apri(percorso) -> None:
    """File di testo nell'editor di testo, cartelle nel Finder."""
    p = str(percorso)
    if p.endswith((".toml", ".txt", ".log", ".env", ".json", ".md")):
        subprocess.Popen([OPEN, "-t", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen([OPEN, p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _stringa(testo: str) -> str:
    """Stringa AppleScript tra virgolette."""
    return '"' + str(testo).replace("\\", "\\\\").replace('"', '\\"') + '"'


def notifica(testo: str, titolo: str = "Dettami") -> None:
    try:
        subprocess.Popen([OSASCRIPT, "-e", f"display notification {_stringa(testo)} with title {_stringa(titolo)}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log.exception("Notifica")


def avviso(titolo: str, messaggio: str) -> None:
    try:
        subprocess.run([OSASCRIPT, "-e", f"display alert {_stringa(titolo)} message {_stringa(messaggio)} as critical"],
                       timeout=600, capture_output=True)
    except Exception:
        log.exception("Avviso")


def chiedi_testo(titolo: str, messaggio: str, pulsante: str = "Salva") -> str | None:
    """Finestra con un campo di testo. None se annulli."""
    script = (f"display dialog {_stringa(messaggio)} with title {_stringa(titolo)} default answer \"\" "
              f"buttons {{\"Annulla\", {_stringa(pulsante)}}} default button {_stringa(pulsante)} "
              f"cancel button \"Annulla\" with icon note")
    try:
        r = subprocess.run([OSASCRIPT, "-e", script, "-e", "text returned of result"],
                           capture_output=True, text=True, timeout=900)
    except Exception:
        log.exception("Finestra di testo")
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def conferma(titolo: str, messaggio: str, pulsante: str) -> bool:
    script = (f"display dialog {_stringa(messaggio)} with title {_stringa(titolo)} "
              f"buttons {{\"Annulla\", {_stringa(pulsante)}}} default button \"Annulla\" "
              f"cancel button \"Annulla\" with icon caution")
    try:
        return subprocess.run([OSASCRIPT, "-e", script], capture_output=True, timeout=600).returncode == 0
    except Exception:
        return False


def apri_finestra_dashboard(url: str) -> None:
    """In una finestra a sé se c'è un browser che lo permette (Chrome, Edge, Brave), altrimenti nel predefinito."""
    for nome in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
        if any((base / f"{nome}.app").exists() for base in (Path("/Applications"), Path.home() / "Applications")):
            try:
                subprocess.Popen([OPEN, "-na", nome, "--args", f"--app={url}", "--window-size=1200,860"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                log.exception("Apertura con %s", nome)
    apri_indirizzo(url)
