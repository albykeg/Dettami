"""
Dettami — dettatura vocale con AI per Windows, in qualsiasi campo di testo.

  Tieni premuto CTRL DESTRO e parla, poi rilascia: il testo ripulito viene
  inserito dove si trova il cursore, in qualunque programma.

  Doppio tocco di CTRL DESTRO  -> mani libere (un altro tocco per finire)
  SHIFT mentre registri          -> il testo viene tradotto
  ESC mentre registri            -> annulla

Avvio:   pythonw dettami.py            (apre anche la dashboard)
         pythonw dettami.py --avvio    (all'accensione: parte in silenzio)
Prova:   python dettami.py --prova
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler

import numpy as np

import aggiornamenti
import dashboard
import indicatore
import motore
from motore import CARTELLA, FREQ

log = logging.getLogger("dettami")
WINDOWS = sys.platform == "win32"

FILE_CONFIG = CARTELLA / "config.toml"
FILE_ENV = CARTELLA / ".env"
FILE_STATO = CARTELLA / "stato.json"          # versione 1.0 (migrato in impostazioni.json)
FILE_IMPOSTAZIONI = CARTELLA / "impostazioni.json"
FILE_CRONOLOGIA = CARTELLA / "cronologia.jsonl"
FILE_CRONOLOGIA_TXT = CARTELLA / "cronologia.txt"  # versione 1.0 (migrata)
FILE_USO = CARTELLA / "uso.json"
FILE_SESSIONE = CARTELLA / "sessione.json"
FILE_STATO_AGG = CARTELLA / "stato-aggiornamenti.json"
FILE_AVVIO_OK = CARTELLA / "avvio-ok.json"
FILE_AGG_FALLITO = CARTELLA / "aggiornamento-fallito.json"
CARTELLA_AGG = CARTELLA / "_aggiornamento"
FILE_LOG = CARTELLA / "dettami.log"
CARTELLA_FALLITI = CARTELLA / "audio_non_elaborati"

# Nomi amichevoli accettati in config.toml -> nomi dei tasti di pynput
ALIAS_TASTI = {
    "ctrl destro": "ctrl_r", "right ctrl": "ctrl_r", "ctrl_destro": "ctrl_r",
    "ctrl sinistro": "ctrl_l", "alt gr": "alt_gr", "altgr": "alt_gr",
    "maiusc": "shift", "shift destro": "shift_r", "bloc maiusc": "caps_lock",
    "caps lock": "caps_lock", "ins": "insert", "menu": "menu", "pausa": "pause",
    "bloc scorr": "scroll_lock",
}
MODIFICATORI = {"ctrl", "ctrl_l", "ctrl_r", "shift", "shift_l", "shift_r",
                "alt", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r"}


def normalizza_nome(nome: str) -> str:
    n = (nome or "").strip().lower()
    return ALIAS_TASTI.get(n, n.replace(" ", "_"))


def corrisponde(nome_tasto: str, voluto: str) -> bool:
    """'shift' corrisponde sia a shift sinistro che destro."""
    return nome_tasto == voluto or nome_tasto.startswith(voluto + "_")


# --------------------------------------------------------------------------- #
#  Log
# --------------------------------------------------------------------------- #

def configura_log() -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(FILE_LOG, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stderr is not None:  # con pythonw non c'è console
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


# --------------------------------------------------------------------------- #
#  Windows: finestra attiva e istanza unica
# --------------------------------------------------------------------------- #

if WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]


def finestra_in_primo_piano() -> int | None:
    return _user32.GetForegroundWindow() if WINDOWS else None


def finestra_attiva() -> motore.Contesto:
    if not WINDOWS:
        return motore.Contesto()
    try:
        hwnd = _user32.GetForegroundWindow()
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        processo = ""
        h = _kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            dim = wintypes.DWORD(1024)
            pbuf = ctypes.create_unicode_buffer(1024)
            if _kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(dim)):
                processo = os.path.basename(pbuf.value).lower()
            _kernel32.CloseHandle(h)
        return motore.Contesto(hwnd=hwnd, processo=processo, titolo=buf.value)
    except Exception:
        log.exception("Lettura finestra attiva non riuscita")
        return motore.Contesto()


_mutex = None


def istanza_unica() -> bool:
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, "Local\\Dettami_istanza_unica")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def apri_file(percorso) -> None:
    try:
        if str(percorso).endswith((".toml", ".txt", ".log", ".env")):
            subprocess.Popen(["notepad.exe", str(percorso)])
        else:
            os.startfile(str(percorso))  # type: ignore[attr-defined]
    except Exception:
        log.exception("Impossibile aprire %s", percorso)


def collegamento_avvio() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                        "Dettami.lnk")


def imposta_avvio_automatico(attivo: bool) -> bool:
    """Crea o toglie il collegamento in Esecuzione automatica. Ritorna lo stato finale."""
    lnk = collegamento_avvio()
    if not attivo:
        try:
            os.remove(lnk)
        except FileNotFoundError:
            pass
        return os.path.exists(lnk)
    import base64
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    q = lambda x: str(x).replace("'", "''")  # noqa: E731  (virgolette per PowerShell)
    comando = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
        f"$s.TargetPath='{q(pythonw)}';"
        f"$s.Arguments='\"{q(CARTELLA / 'dettami.py')}\" --avvio';"
        f"$s.WorkingDirectory='{q(CARTELLA)}';"
        f"$s.IconLocation='{q(CARTELLA / 'icona.ico')}';$s.Save()"
    )
    codificato = base64.b64encode(comando.encode("utf-16-le")).decode()
    subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", codificato],
                   creationflags=0x08000000, timeout=30)
    return os.path.exists(lnk)


# --------------------------------------------------------------------------- #
#  Appunti (con nuovi tentativi: a volte un'altra app li tiene bloccati)
# --------------------------------------------------------------------------- #

def appunti_copia(testo: str) -> None:
    import pyperclip
    for i in range(5):
        try:
            pyperclip.copy(testo)
            return
        except Exception:
            time.sleep(0.05 * (i + 1))
    pyperclip.copy(testo)


def appunti_leggi() -> str | None:
    import pyperclip
    for i in range(3):
        try:
            return pyperclip.paste()
        except Exception:
            time.sleep(0.05 * (i + 1))
    return None


# --------------------------------------------------------------------------- #
#  Suoni
# --------------------------------------------------------------------------- #

def _tono(freqs, durata=0.07, volume=0.12, fs=44100) -> np.ndarray:
    parti = []
    for f in freqs:
        t = np.arange(int(fs * durata)) / fs
        onda = np.sin(2 * np.pi * f * t)
        fade = min(int(fs * 0.006), t.size // 2)
        inv = np.ones_like(onda)
        inv[:fade] = np.linspace(0, 1, fade)
        inv[-fade:] = np.linspace(1, 0, fade)
        parti.append(onda * inv)
    return (np.concatenate(parti) * volume).astype(np.float32)


SUONI = {
    "inizio": _tono([660, 990]),
    "fine": _tono([990, 660]),
    "mani_libere": _tono([660, 990, 1320]),
    "traduci": _tono([1320, 1760], durata=0.05),
    "annulla": _tono([440, 330]),
    "errore": _tono([220, 196], durata=0.12),
}


class Suoni:
    def __init__(self, attivi: bool):
        self.attivi = attivi

    def __call__(self, nome: str) -> None:
        if not self.attivi:
            return
        try:
            import sounddevice as sd
            sd.play(SUONI[nome], 44100)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Microfono
# --------------------------------------------------------------------------- #

def trova_microfono(nome: str):
    import sounddevice as sd
    if not nome:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and nome.lower() in d["name"].lower():
            return i
    log.warning("Microfono '%s' non trovato: uso quello predefinito di Windows", nome)
    return None


def elenco_microfoni() -> list[str]:
    """Nomi dei microfoni, senza doppioni né voci tecniche di Windows."""
    import sounddevice as sd
    nomi, visti = [], set()
    for d in sd.query_devices():
        n = d["name"].strip()
        if d["max_input_channels"] <= 0 or n.lower() in visti:
            continue
        if any(x in n.lower() for x in ("mapper", "primary sound", "primario", "driver di acquisizione")):
            continue
        visti.add(n.lower())
        nomi.append(n)
    return nomi


class Registratore:
    def __init__(self, cfg: dict):
        a = cfg["audio"]
        self.dispositivo = trova_microfono(a.get("microfono", ""))
        self.sempre_aperto = bool(a.get("microfono_sempre_aperto"))
        self.coda = max(0, a.get("coda_ms", 150)) / 1000
        self.freq = FREQ
        self._lock = threading.Lock()
        self._blocchi: list[np.ndarray] = []
        self._preroll: deque[np.ndarray] = deque()
        self._preroll_campioni = 0
        self._attivo = False
        self._stream = None
        self._livelli: deque[float] = deque(maxlen=12)  # per le barre dell'indicatore
        if self.sempre_aperto:
            self._apri()

    def livelli(self) -> list[float]:
        return list(self._livelli)

    def _cb(self, indata, frames, time_info, status):
        dati = indata[:, 0].copy()
        with self._lock:
            if self._attivo:
                self._blocchi.append(dati)
                rms = float(np.sqrt(np.mean(dati.astype(np.float32) ** 2))) if dati.size else 0.0
                self._livelli.append(min(1.0, (rms / 2500) ** 0.7))
            elif self.sempre_aperto:  # tiene gli ultimi 300 ms per non perdere la prima sillaba
                self._preroll.append(dati)
                self._preroll_campioni += dati.size
                while self._preroll and self._preroll_campioni - self._preroll[0].size > self.freq * 0.3:
                    self._preroll_campioni -= self._preroll.popleft().size

    def _apri(self):
        import sounddevice as sd
        try:
            s = sd.InputStream(samplerate=FREQ, channels=1, dtype="int16", blocksize=FREQ // 20,
                               device=self.dispositivo, callback=self._cb, latency="low")
            self.freq = FREQ
        except Exception:
            info = sd.query_devices(self.dispositivo, "input")
            freq = int(info["default_samplerate"])
            log.info("Il microfono non supporta 16 kHz: registro a %d Hz e converto", freq)
            s = sd.InputStream(samplerate=freq, channels=1, dtype="int16", blocksize=freq // 20,
                               device=self.dispositivo, callback=self._cb, latency="low")
            self.freq = freq
        s.start()
        self._stream = s

    def _chiudi(self):
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                log.exception("Chiusura microfono")

    def avvia(self) -> None:
        if self._stream is None or not self._stream.active:
            self._chiudi()
            self._apri()
        with self._lock:
            self._blocchi = list(self._preroll) if self.sempre_aperto else []
            self._preroll.clear()
            self._preroll_campioni = 0
            self._livelli.clear()
            self._attivo = True

    def ferma(self, scarta: bool = False) -> np.ndarray:
        if not scarta and self.coda:
            time.sleep(self.coda)  # cattura anche l'ultima sillaba dopo il rilascio
        with self._lock:
            self._attivo = False
            blocchi, self._blocchi = self._blocchi, []
        if not self.sempre_aperto:
            self._chiudi()
        if scarta or not blocchi:
            return np.zeros(0, dtype=np.int16)
        audio = np.concatenate(blocchi)
        return motore.ricampiona(audio, self.freq, FREQ)

    def chiudi(self):
        with self._lock:
            self._attivo = False
        self._chiudi()


NOMI_RISCRITTURA = {
    "spenta": "Solo trascrizione",
    "fedele": "Fedele",
    "chiara": "Chiara",
    "ottimizzata": "Ottimizzata",
}


def breve_errore(e: Exception) -> str:
    stato = getattr(e, "stato", None)
    if stato == 429:
        return "Limite gratuito raggiunto"
    if stato == 401:
        return "Chiave Groq non valida"
    if "Connessione" in str(e):
        return "Nessuna connessione a internet"
    return "Errore: riprova"


# --------------------------------------------------------------------------- #
#  Icona nella barra di sistema
# --------------------------------------------------------------------------- #

COLORI = {
    "pronto": (71, 85, 105),       # ardesia
    "registra": (220, 38, 38),     # rosso
    "traduci": (124, 58, 237),     # viola
    "elabora": (217, 119, 6),      # ambra
    "errore": (120, 120, 120),     # grigio
}


def disegna_icona(stato: str, lato: int = 64):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (lato, lato), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, lato - 1, lato - 1), fill=COLORI.get(stato, COLORI["pronto"]) + (255,))
    s = lato / 64
    bianco = (255, 255, 255, 255)
    d.rounded_rectangle((24 * s, 12 * s, 40 * s, 38 * s), radius=8 * s, fill=bianco)  # capsula
    d.arc((17 * s, 22 * s, 47 * s, 46 * s), 0, 180, fill=bianco, width=max(2, int(3 * s)))  # supporto
    d.line((32 * s, 46 * s, 32 * s, 52 * s), fill=bianco, width=max(2, int(3 * s)))
    d.line((25 * s, 52 * s, 39 * s, 52 * s), fill=bianco, width=max(2, int(3 * s)))
    return img


def crea_file_icona() -> None:
    img = disegna_icona("pronto", 256)
    img.save(CARTELLA / "icona.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])


# --------------------------------------------------------------------------- #
#  Applicazione
# --------------------------------------------------------------------------- #

class App:
    def __init__(self, cfg: dict, api_key: str, apri_dashboard: bool = False,
                 dopo_aggiornamento: str | None = None):
        self.icon = None
        self.listener = None
        self.tastiera = None
        self.server = None
        self.apri_dashboard = apri_dashboard
        self.dopo_aggiornamento = dopo_aggiornamento  # versione da cui si è appena aggiornato
        self._ultima_attivita = time.monotonic()
        self._lock_agg = threading.Lock()
        self._sveglia_agg = threading.Event()
        self.agg = {"stato": "nessuno", "ultimo_controllo": None, "errore": None, "manifest": None,
                    "pronto": None, "richiede_installer": False}
        self._agg_salvato = motore.leggi_json(FILE_STATO_AGG, {})
        if not isinstance(self._agg_salvato, dict):
            self._agg_salvato = {}
        self._migra_versione_1()
        try:
            cfg = motore.carica_config(FILE_CONFIG, FILE_IMPOSTAZIONI)
        except motore.ErroreConfig:
            pass
        self.cfg = cfg
        self.api_key = api_key
        self.uso = motore.Uso(FILE_USO)
        self.client = self._nuovo_client()
        self.suona = Suoni(cfg["audio"]["suoni"])
        self.reg: Registratore | None = None
        self._reg_in_uso: Registratore | None = None
        self._anteprima_fino = 0.0
        self.indicatore = indicatore.Indicatore(cfg["indicatore"]["attivo"], cfg["indicatore"]["posizione"],
                                                livelli=self._livelli_indicatore, al_clic=self._copia_da_pillola)
        self.lingua_trad = cfg["ai"]["lingua_traduzione"]
        self.ai_attiva = cfg["ai"]["attiva"]
        self.contatore = 0  # aumenta a ogni dettatura: la dashboard sa quando aggiornarsi

        self.eventi: queue.Queue = queue.Queue()
        self.lavori: queue.Queue = queue.Queue()
        self.macchina = self._crea_macchina()
        self._imposta_tasti()

        self.contesto = motore.Contesto()
        self.traduci = False
        self.ultimo_testo = ""
        self.fallito: tuple | None = None
        self.parole_oggi = motore.statistiche(motore.leggi_cronologia(FILE_CRONOLOGIA))["parole_oggi"]
        self.giorno = datetime.now().date()
        self.in_elaborazione = 0
        self._premuti: set[str] = set()
        self._tasto_giu = False
        self._ignora = False
        self._lock_cron = threading.Lock()
        self._avvisi: dict[str, float] = {}

    # ----- impostazioni -----

    def _crea_macchina(self) -> motore.MacchinaTasto:
        t = self.cfg["tasti"]
        return motore.MacchinaTasto(
            self,
            tenuta_minima=t["tenuta_minima_ms"] / 1000,
            finestra_doppio=t["finestra_doppio_tocco_ms"] / 1000,
            doppio_attivo=t["doppio_tocco_mani_libere"],
        )

    def _imposta_tasti(self):
        from pynput import keyboard
        t = self.cfg["tasti"]
        self.tasto = normalizza_nome(t["dettatura"])
        if self.tasto not in keyboard.Key.__members__:
            log.warning("Tasto '%s' non riconosciuto: uso ctrl_r", t["dettatura"])
            self.notifica(f"Tasto '{t['dettatura']}' non riconosciuto: uso Ctrl destro.")
            self.tasto = "ctrl_r"
        # nome "canonico" (alcuni tasti hanno alias, es. alt_r/alt_gr)
        self.tasto = keyboard.Key[self.tasto].name
        self.tasto_traduci = normalizza_nome(t["modificatore_traduzione"])
        self.tasto_annulla = normalizza_nome(t["annulla"])

    def _nuovo_client(self) -> motore.ClientAI:
        c = motore.ClientAI(self.cfg, self.api_key)
        c.uso = self.uso
        return c

    @staticmethod
    def _migra_versione_1():
        """Dalla 1.0: cronologia in testo -> jsonl, stato.json -> impostazioni.json."""
        try:
            n = motore.migra_cronologia_txt(FILE_CRONOLOGIA_TXT, FILE_CRONOLOGIA)
            if n:
                log.info("Cronologia convertita: %d dettature", n)
        except Exception:
            log.exception("Conversione cronologia")
        try:
            if FILE_STATO.exists():
                vecchio = json.loads(FILE_STATO.read_text(encoding="utf-8"))
                nuovo = motore.leggi_json(FILE_IMPOSTAZIONI, {})
                ai = nuovo.setdefault("ai", {})
                if "lingua_traduzione" in vecchio:
                    ai.setdefault("lingua_traduzione", vecchio["lingua_traduzione"])
                if "ai_attiva" in vecchio:
                    ai.setdefault("attiva", vecchio["ai_attiva"])
                motore.scrivi_json(FILE_IMPOSTAZIONI, nuovo)
                FILE_STATO.unlink()
        except Exception:
            log.exception("Conversione stato.json")

    def _salva_stato(self):
        """Scelte fatte dal menu dell'icona: finiscono in impostazioni.json come quelle della dashboard."""
        try:
            motore.salva_impostazioni(FILE_IMPOSTAZIONI, {"lingua_traduzione": self.lingua_trad,
                                                          "ai_attiva": self.ai_attiva}, self.cfg)
            self.cfg["ai"]["lingua_traduzione"] = self.lingua_trad
            self.cfg["ai"]["attiva"] = self.ai_attiva
        except Exception:
            log.exception("Salvataggio impostazioni")

    # ----- avvio -----

    def avvia(self):
        import pystray
        self.icon = pystray.Icon("dettami", disegna_icona("pronto"), "Dettami", self._menu())
        self.icon.run(setup=self._setup)

    def _setup(self, icon):
        icon.visible = True
        from pynput import keyboard
        self.tastiera = keyboard.Controller()
        try:
            self.reg = Registratore(self.cfg)
        except Exception as e:
            log.exception("Microfono")
            self.notifica(f"Microfono non disponibile: {e}")
        threading.Thread(target=self._ciclo_eventi, daemon=True, name="eventi").start()
        threading.Thread(target=self._ciclo_lavori, daemon=True, name="lavori").start()
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.daemon = True
        self.listener.start()
        threading.Thread(target=self.client.scalda, daemon=True).start()
        try:
            vecchia = motore.leggi_json(FILE_SESSIONE, {})
            vecchia = vecchia if isinstance(vecchia, dict) else {}
            self.server = dashboard.ServerDashboard(self, porta=int(vecchia.get("porta") or 0),
                                                    token=vecchia.get("token"))
            motore.scrivi_json(FILE_SESSIONE, {"url": self.server.url, "pid": os.getpid(),
                                               "porta": self.server.porta, "token": self.server.token})
        except Exception:
            log.exception("Dashboard non disponibile")
        self._aggiorna_icona()
        if not self.api_key:
            self.notifica("Manca la API key di Groq: si apre la finestra per inserirla.")
            self._imposta_chiave()
        else:
            self.indicatore.mostra("info", f"Dettami è pronta: tieni premuto {self._nome_tasto()}")
        if self.apri_dashboard:
            self.apri_finestra_dashboard()
        self._esito_aggiornamento_precedente()
        threading.Thread(target=self._ciclo_aggiornamenti, daemon=True, name="aggiornamenti").start()
        log.info("Avviata %s (tasto: %s)", motore.VERSIONE, self.tasto)
        # segnale per aggiorna.py: la nuova versione è partita davvero
        try:
            motore.scrivi_json(FILE_AVVIO_OK, {"versione": motore.VERSIONE, "pid": os.getpid()})
        except OSError:
            log.exception("Scrittura avvio-ok")

    def apri_finestra_dashboard(self, *_):
        if self.server:
            dashboard.apri_finestra(self.server.url)

    def _nome_tasto(self) -> str:
        return motore.TASTI_AMMESSI.get(self.tasto, self.tasto.upper())

    def _livelli_indicatore(self) -> list[float]:
        if time.monotonic() < self._anteprima_fino:  # anteprima dalla dashboard: onda finta
            t = time.monotonic()
            return [0.25 + 0.6 * abs(np.sin(t * 3 + i * 0.7)) for i in range(10)]
        reg = self._reg_in_uso or self.reg
        return reg.livelli() if reg else []

    # ----- tastiera (thread dell'hook: solo cose velocissime) -----

    @staticmethod
    def _nome(key) -> str:
        from pynput import keyboard
        return key.name if isinstance(key, keyboard.Key) else "carattere"

    def _on_press(self, key):
        try:
            if self._ignora:
                return
            n = self._nome(key)
            self._premuti.add(n)
            t = time.monotonic()
            if n == self.tasto:
                if not self._tasto_giu:  # ignora la ripetizione automatica
                    self._tasto_giu = True
                    self.eventi.put(("premi", t))
            elif corrisponde(n, self.tasto_traduci):
                self.eventi.put(("traduci", t))
            elif n == self.tasto_annulla:
                self.eventi.put(("annulla", t))
            elif self._tasto_giu:
                self.eventi.put(("altro", t))
        except Exception:
            log.exception("on_press")

    def _on_release(self, key):
        try:
            n = self._nome(key)
            self._premuti.discard(n)
            if self._ignora:
                return
            if n == self.tasto:
                self._tasto_giu = False
                self.eventi.put(("rilascia", time.monotonic()))
        except Exception:
            log.exception("on_release")

    # ----- ciclo eventi (thread dedicato) -----

    def _ciclo_eventi(self):
        while True:
            tipo, dato = self.eventi.get()
            try:
                m = self.macchina
                if tipo == "premi":
                    m.premi(dato)
                elif tipo == "rilascia":
                    m.rilascia(dato)
                elif tipo == "altro":
                    m.altro_tasto()
                elif tipo == "annulla":
                    m.annulla()
                elif tipo == "traduci":
                    if m.registrando and not self.traduci:
                        self.traduci = True
                        self.suona("traduci")
                        self._aggiorna_icona()
                        self.indicatore.mostra("traduci", f"Traduco in {self.lingua_trad}", timer=True)
                elif tipo == "conferma":
                    m.conferma_scaduta(dato)
                elif tipo == "limite":
                    m.limite_scaduto(dato)
            except Exception:
                log.exception("Evento %s", tipo)

    def _timer(self, secondi: float, evento: str, sessione: int):
        t = threading.Timer(secondi, lambda: self.eventi.put((evento, sessione)))
        t.daemon = True
        t.start()

    # ----- azioni chiamate da MacchinaTasto -----

    def inizia(self, sessione: int) -> bool:
        self._ultima_attivita = time.monotonic()
        if self.reg is None:
            try:
                self.reg = Registratore(self.cfg)
            except Exception as e:
                self.suona("errore")
                self.notifica(f"Microfono non disponibile: {e}")
                return False
        self.contesto = finestra_attiva()
        self.traduci = False
        try:
            self.reg.avvia()
        except Exception as e:
            log.exception("Avvio registrazione")
            self.suona("errore")
            self.notifica(f"Microfono non disponibile: {e}")
            return False
        self._timer(self.macchina.tenuta_minima, "conferma", sessione)
        self._timer(self.cfg["audio"]["durata_massima_min"] * 60, "limite", sessione)
        return True

    def conferma(self):
        self.suona("inizio")
        self._aggiorna_icona()
        if self.traduci:
            self.indicatore.mostra("traduci", f"Traduco in {self.lingua_trad}", timer=True)
        else:
            self.indicatore.mostra("ascolto", "In ascolto", timer=True)

    def mani_libere(self):
        self.suona("mani_libere")
        self._aggiorna_icona()
        self.indicatore.mostra("traduci" if self.traduci else "mani_libere",
                               f"Traduco in {self.lingua_trad}" if self.traduci else "Mani libere", timer=True)

    def scarta(self, silenzioso: bool = True):
        if self.reg:
            self.reg.ferma(scarta=True)
        if not silenzioso:
            self.suona("annulla")
            self.indicatore.mostra("annullato", "Annullato")
        elif not self.in_elaborazione:
            self.indicatore.nascondi_se("ascolto", "mani_libere", "traduci")
        else:
            self.indicatore.mostra("elabora", "Sto scrivendo…", durata=None)
        self.traduci = False
        self._aggiorna_icona()

    def termina(self):
        self._ultima_attivita = time.monotonic()
        audio = self.reg.ferma() if self.reg else np.zeros(0, np.int16)
        self.suona("fine")
        self.in_elaborazione += 1
        self._aggiorna_icona()
        self.indicatore.mostra("elabora", "Sto scrivendo…", durata=None)
        self.lavori.put((audio, self.contesto, self.traduci, True))
        self.traduci = False

    def _esito_a_schermo(self, tipo: str, testo: str, **opzioni):
        """Mostra l'esito solo se nel frattempo non è partita un'altra dettatura."""
        if self.macchina.registrando:
            return
        if self.in_elaborazione > 1 and tipo in ("fatto", "silenzio"):
            return  # ci sono altre dettature in coda: resta "Sto scrivendo"
        self.indicatore.mostra(tipo, testo, **opzioni)

    def _con_pulsante_copia(self, testo: str) -> dict:
        ind = self.cfg["indicatore"]
        if not ind.get("pulsante_copia", True):
            return {}
        return {"pulsante": "Copia", "dato": testo, "durata": float(ind.get("secondi_copia", 5))}

    def _copia_da_pillola(self, testo: str | None):
        """Clic su "Copia" nella pillola: il testo va negli appunti, il cursore resta dov'era."""
        if not testo:
            return
        try:
            appunti_copia(testo)
            self.indicatore.mostra("fatto", "Copiato: incollalo dove vuoi")
        except Exception:
            log.exception("Copia dalla pillola")
            self.indicatore.mostra("errore", "Copia non riuscita")

    # ----- elaborazione (thread dedicato) -----

    def _ciclo_lavori(self):
        while True:
            audio, ctx, traduci, controlla_finestra = self.lavori.get()
            try:
                self._elabora(audio, ctx, traduci, controlla_finestra)
            except motore.ErroreAPI as e:
                self.suona("errore")
                self._salva_fallito(audio, ctx, traduci)
                self._esito_a_schermo("errore", breve_errore(e))
                self.notifica(f"{e}\nL'audio è salvato: menu → Riprova.")
            except Exception as e:
                log.exception("Elaborazione")
                self.suona("errore")
                self._salva_fallito(audio, ctx, traduci)
                self._esito_a_schermo("errore", "Errore: riprova")
                self.notifica(f"Errore imprevisto: {e}")
            finally:
                self.in_elaborazione = max(0, self.in_elaborazione - 1)
                self._aggiorna_icona()

    def _elabora(self, audio, ctx: motore.Contesto, traduci: bool, controlla_finestra: bool):
        soglia = self.cfg["audio"]["soglia_silenzio"]
        if not motore.c_e_voce(audio, soglia):
            log.info("Nessuna voce rilevata (livello %.0f, soglia %s)", motore.livello(audio), soglia)
            self._esito_a_schermo("silenzio", "Non ho sentito niente")
            return
        if not self.api_key:
            raise motore.ErroreAPI("Manca la API key: menu → Imposta API key.")
        stile = motore.stile_per(self.cfg, ctx)
        r = motore.elabora(self.client, self.cfg, audio, stile, traduci, self.lingua_trad, self.ai_attiva)
        self.uso.salva()
        if not r.testo:
            log.info("Trascrizione vuota")
            self._esito_a_schermo("silenzio", "Non ho sentito niente")
            return
        testo = r.testo
        if self.cfg["inserimento"]["spazio_finale"] and not testo.endswith(("\n", " ")):
            testo += " "
        esito = self.inserisci(testo, ctx.hwnd if controlla_finestra else None)
        self.ultimo_testo = r.testo
        self.fallito = None
        self._conta_parole(r.testo)
        self._scrivi_cronologia(r, ctx, esito)
        n = len(r.testo.split())
        parole = "1 parola" if n == 1 else f"{n} parole"
        if esito == "appunti":
            self._esito_a_schermo("fatto", "Negli appunti: premi Ctrl+V")
        elif r.tradotto:
            self._esito_a_schermo("fatto", f"Tradotto: {parole}", **self._con_pulsante_copia(r.testo))
        else:
            self._esito_a_schermo("fatto", f"Inserito: {parole}", **self._con_pulsante_copia(r.testo))
        log.info("OK %s | %.1fs audio | trascr %.2fs | ai %.2fs (%s) | stile %s",
                 ctx.processo, r.secondi_audio, r.t_trascrizione, r.t_ai, r.modello or "-", stile)
        trascr = self.cfg["trascrizione"].get("modelli") or []
        if trascr and r.modello_trascrizione and r.modello_trascrizione != trascr[0]:
            self.notifica_una_volta(
                f"Quota gratuita di {trascr[0]} finita per ora: uso {r.modello_trascrizione}.")
        principale = self.cfg["ai"]["modelli"][0]
        if r.ai_usata and r.modello and r.modello != principale:
            self.notifica_una_volta(
                f"Quota gratuita di {principale} finita per ora: uso il modello di riserva {r.modello}.")
        if r.avviso:
            self.notifica_una_volta(r.avviso)
        if esito == "appunti":
            self.notifica("Hai cambiato finestra: il testo è negli appunti, premi Ctrl+V dove vuoi.")

    # ----- inserimento del testo -----

    def _attendi_modificatori(self, massimo: float = 1.5):
        fine = time.monotonic() + massimo
        while self._premuti & MODIFICATORI and time.monotonic() < fine:
            time.sleep(0.02)

    def inserisci(self, testo: str, hwnd_origine) -> str:
        ins = self.cfg["inserimento"]
        if ins["solo_stessa_finestra"] and hwnd_origine and finestra_in_primo_piano() != hwnd_origine:
            appunti_copia(testo)
            return "appunti"
        self._attendi_modificatori()
        from pynput.keyboard import Key
        self._ignora = True
        try:
            if ins["metodo"] == "digita":
                righe = testo.split("\n")
                for i, riga in enumerate(righe):
                    if riga:
                        self.tastiera.type(riga)
                    if i < len(righe) - 1:  # Shift+Invio: va a capo senza inviare nelle chat
                        with self.tastiera.pressed(Key.shift):
                            self.tastiera.press(Key.enter)
                            self.tastiera.release(Key.enter)
                return "digitato"

            vecchio = appunti_leggi() if ins["ripristina_appunti"] else None
            appunti_copia(testo)
            time.sleep(0.05)
            with self.tastiera.pressed(Key.ctrl):
                self.tastiera.press("v")
                self.tastiera.release("v")
            time.sleep(0.05)
            self._ignora = False
            if vecchio:  # rimette com'erano gli appunti (solo testo)
                time.sleep(0.6)
                if appunti_leggi() == testo:
                    appunti_copia(vecchio)
            return "incollato"
        finally:
            if self._ignora:
                time.sleep(0.05)
                self._ignora = False

    # ----- cronologia, statistiche, errori -----

    def _conta_parole(self, testo: str):
        oggi = datetime.now().date()
        if oggi != self.giorno:
            self.giorno, self.parole_oggi = oggi, 0
        self.parole_oggi += len(testo.split())

    def _scrivi_cronologia(self, r: motore.Risultato, ctx: motore.Contesto, esito: str):
        voce = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "app": ctx.processo.removesuffix(".exe"),
            "stile": r.stile,
            "testo": r.testo,
            "grezzo": r.grezzo if r.ai_usata and r.grezzo != r.testo else "",
            "parole": len(r.testo.split()),
            "secondi_audio": round(r.secondi_audio, 1),
            "t_elaborazione": round(r.t_trascrizione + r.t_ai, 2),
            "tradotto": r.tradotto,
            "lingua": self.lingua_trad if r.tradotto else "",
            "esito": esito,
        }
        try:
            motore.aggiungi_cronologia(FILE_CRONOLOGIA, voce)
        except OSError:
            log.exception("Scrittura cronologia")
        self.contatore += 1

    def _salva_fallito(self, audio, ctx, traduci):
        if audio is None or audio.size == 0:
            return
        try:
            CARTELLA_FALLITI.mkdir(exist_ok=True)
            p = CARTELLA_FALLITI / f"{datetime.now():%Y%m%d_%H%M%S}.wav"
            p.write_bytes(motore.in_wav(audio))
            self.fallito = (audio, ctx, traduci)
            log.info("Audio salvato in %s", p)
        except Exception:
            log.exception("Salvataggio audio non elaborato")

    # ----- interfaccia -----

    def notifica_una_volta(self, testo: str, intervallo: float = 900):
        """Non ripete lo stesso avviso a ogni dettatura (es. quota esaurita)."""
        chiave = testo[:40]
        ora = time.monotonic()
        if ora - self._avvisi.get(chiave, -1e9) >= intervallo:
            self._avvisi[chiave] = ora
            self.notifica(testo)

    def notifica(self, testo: str):
        log.info("Notifica: %s", testo)
        try:
            if self.icon is not None:
                self.icon.notify(testo, "Dettami")
        except Exception:
            pass

    def _stato_corrente(self) -> str:
        if self.macchina.registrando:
            return "traduci" if self.traduci else "registra"
        if self.in_elaborazione:
            return "elabora"
        return "pronto" if self.api_key else "errore"

    def _aggiorna_icona(self):
        if self.icon is None:
            return
        try:
            stato = self._stato_corrente()
            self.icon.icon = disegna_icona(stato)
            self.icon.title = f"Dettami — {self._testo_stato()}"
            self.icon.update_menu()
        except Exception:
            pass

    def _testo_stato(self, *_):
        s = self._stato_corrente()
        if s == "registra":
            return "Sto ascoltando…"
        if s == "traduci":
            return f"Ascolto (traduco in {self.lingua_trad})…"
        if s == "elabora":
            return "Sto scrivendo…"
        if s == "errore":
            return "Manca la API key"
        return f"Dettami {motore.VERSIONE} · {self._nome_tasto()} · oggi {self.parole_oggi} parole"

    def _menu(self):
        import pystray
        I = pystray.MenuItem

        def lingua(nome):
            def scegli(icon, item):
                self.lingua_trad = nome
                self._salva_stato()
                self._aggiorna_icona()
            return I(nome.capitalize(), scegli, checked=lambda item: self.lingua_trad == nome, radio=True)

        def riscrittura(valore, nome):
            def scegli(icon, item):
                self._imposta_riscrittura(valore)
            attuale = lambda item: (not self.ai_attiva) if valore == "spenta" else (  # noqa: E731
                self.ai_attiva and motore.livello_riscrittura(self.cfg) == valore)
            return I(nome, scegli, checked=attuale, radio=True)

        lingue = self.cfg["ai"]["lingue_traduzione"]
        return pystray.Menu(
            I(self._testo_stato, None, enabled=False),
            pystray.Menu.SEPARATOR,
            I("Apri dashboard", self.apri_finestra_dashboard, default=True),
            I("Copia ultima dettatura", lambda icon, item: appunti_copia(self.ultimo_testo),
              enabled=lambda item: bool(self.ultimo_testo)),
            I("Riprova dettatura non riuscita", self._riprova,
              visible=lambda item: self.fallito is not None),
            I(lambda item: f"Aggiorna alla versione {self._versione_disponibile()}",
              lambda icon, item: self.installa_aggiornamento(manuale=True),
              visible=lambda item: bool(self._versione_disponibile()) and not self.agg["richiede_installer"]),
            I("Traduci in (tieni Shift mentre detti)", pystray.Menu(*[lingua(n) for n in lingue])),
            I("Riscrittura", pystray.Menu(*[riscrittura(v, n) for v, n in NOMI_RISCRITTURA.items()])),
            pystray.Menu.SEPARATOR,
            I("Impostazioni avanzate (file)", lambda icon, item: apri_file(FILE_CONFIG)),
            I("Ricarica impostazioni", self._ricarica),
            I("Prova microfono", self._prova_microfono),
            I("Imposta API key", self._imposta_chiave),
            I("Apri log", lambda icon, item: apri_file(FILE_LOG)),
            pystray.Menu.SEPARATOR,
            I("Esci", self._esci),
        )

    def _imposta_riscrittura(self, valore: str):
        """valore: "spenta" (solo trascrizione) oppure uno dei livelli."""
        dati = {"ai_attiva": False} if valore == "spenta" else {"ai_attiva": True, "riscrittura": valore}
        try:
            self.salva_impostazioni(dati)
        except ValueError as e:
            self.notifica(str(e))

    def _alterna_ai(self, icon, item):
        self.ai_attiva = not self.ai_attiva
        self._salva_stato()
        self._aggiorna_icona()

    def _riprova(self, icon, item):
        if self.fallito:
            audio, ctx, traduci = self.fallito
            self.fallito = None
            self.in_elaborazione += 1
            self._aggiorna_icona()
            # incolla nella finestra attiva ora (non quella di allora)
            self.lavori.put((audio, ctx, traduci, False))

    def _imposta_chiave(self, icon=None, item=None):
        """Apre la finestra per incollare e verificare la API key, poi la ricarica."""
        script = CARTELLA / "chiave.ps1"
        if not script.exists():  # ripiego: modifica a mano del file .env
            if not FILE_ENV.exists():
                FILE_ENV.write_text("GROQ_API_KEY=\n", encoding="utf-8")
            apri_file(FILE_ENV)
            self.notifica("Incolla la chiave dopo l'uguale, salva, poi menu → Ricarica impostazioni.")
            return

        def attendi():
            try:
                esito = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                if esito.returncode == 0:
                    self.api_key = motore.leggi_api_key(FILE_ENV)
                    self.client = motore.ClientAI(self.cfg, self.api_key)
                    self._aggiorna_icona()
                    self.notifica(f"API key salvata. Tieni premuto {self._nome_tasto()} e parla.")
            except Exception:
                log.exception("Finestra API key")

        threading.Thread(target=attendi, daemon=True).start()

    def _prova_microfono(self, icon=None, item=None):
        python = os.path.join(os.path.dirname(sys.executable), "python.exe")
        if not os.path.exists(python):
            python = sys.executable
        try:
            subprocess.Popen([python, str(CARTELLA / "dettami.py"), "--prova", "--pausa"],
                             cwd=str(CARTELLA), creationflags=0x00000010)  # CREATE_NEW_CONSOLE
        except Exception:
            log.exception("Prova microfono")

    def _ricarica(self, icon=None, item=None):
        if self.macchina.registrando:
            self.notifica("Finisci la dettatura in corso, poi riprova.")
            return
        try:
            nuova = motore.carica_config(FILE_CONFIG, FILE_IMPOSTAZIONI)
        except motore.ErroreConfig as e:
            self.notifica(str(e))
            return
        self.api_key = motore.leggi_api_key(FILE_ENV)
        self._applica_config(nuova, riapri_microfono=True)
        self.notifica("Impostazioni ricaricate.")

    def _applica_config(self, nuova: dict, riapri_microfono: bool = False):
        audio_cambiato = riapri_microfono or any(
            nuova["audio"][k] != self.cfg["audio"][k] for k in ("microfono", "microfono_sempre_aperto"))
        self.cfg = nuova
        self.lingua_trad = nuova["ai"]["lingua_traduzione"]
        self.ai_attiva = nuova["ai"]["attiva"]
        self.client = self._nuovo_client()
        self.suona.attivi = nuova["audio"]["suoni"]
        self.indicatore.configura(nuova["indicatore"]["attivo"], nuova["indicatore"]["posizione"])
        self._imposta_tasti()
        self.macchina = self._crea_macchina()
        if audio_cambiato:
            if self.reg:
                self.reg.chiudi()
            try:
                self.reg = Registratore(self.cfg)
            except Exception as e:
                self.reg = None
                self.notifica(f"Microfono non disponibile: {e}")
        threading.Thread(target=self.client.scalda, daemon=True).start()
        self._aggiorna_icona()

    def _esci(self, icon, item):
        log.info("Chiusura")
        try:
            if self.listener:
                self.listener.stop()
            if self.reg:
                self.reg.chiudi()
            self.uso.salva()
            self.indicatore.chiudi()
            if self.server:
                self.server.chiudi()
        finally:
            icon.stop()

    # ===================================================================== #
    #  Aggiornamenti automatici
    # ===================================================================== #

    def _url_aggiornamenti(self) -> str:
        return self.cfg["aggiornamenti"].get("url") or aggiornamenti.URL_MANIFEST

    def _versione_disponibile(self) -> str:
        m = self.agg.get("manifest")
        return m["versione"] if m else ""

    def _salva_stato_agg(self):
        try:
            motore.scrivi_json(FILE_STATO_AGG, self._agg_salvato)
        except OSError:
            log.exception("Salvataggio stato aggiornamenti")

    def _esito_aggiornamento_precedente(self):
        """All'avvio: dice se l'ultimo aggiornamento è riuscito o se si è tornati alla versione di prima."""
        fallito = motore.leggi_json(FILE_AGG_FALLITO, None)
        if isinstance(fallito, dict):
            v = str(fallito.get("versione", ""))
            self._agg_salvato["saltate"] = sorted(set(self._agg_salvato.get("saltate", [])) | {v})
            self._salva_stato_agg()
            FILE_AGG_FALLITO.unlink(missing_ok=True)
            log.warning("Aggiornamento a %s fallito: %s", v, fallito.get("motivo"))
            self.notifica(f"L'aggiornamento alla {v} non è riuscito: resti sulla {motore.VERSIONE}. "
                          "Non lo riproverò da solo; lo trovi nella dashboard.")
        elif self.dopo_aggiornamento:
            note = [str(x) for x in self._agg_salvato.get("note_installate") or []]
            self._agg_salvato["ultimo_aggiornamento"] = {"da": self.dopo_aggiornamento, "a": motore.VERSIONE,
                                                         "ts": datetime.now().isoformat(timespec="seconds"),
                                                         "note": note}
            self._salva_stato_agg()
            self.indicatore.mostra("info", f"Dettami aggiornata alla {motore.VERSIONE}")
            self.notifica(f"Aggiornata alla versione {motore.VERSIONE}." + (" " + note[0] if note else ""))

    def _inattivo_da(self, secondi: float) -> bool:
        return (not self.macchina.registrando and not self.in_elaborazione and self._reg_in_uso is None
                and time.monotonic() - self._ultima_attivita >= secondi)

    def _deve_installare_da_solo(self) -> bool:
        m = self.agg.get("manifest")
        return bool(m and self.cfg["aggiornamenti"].get("automatici", True)
                    and not self.agg["richiede_installer"] and self.agg["stato"] != "installazione"
                    and m["versione"] not in self._agg_salvato.get("saltate", []))

    def _ciclo_aggiornamenti(self):
        time.sleep(25)  # lascia partire tutto il resto
        prossimo = 0.0
        while True:
            try:
                a = self.cfg["aggiornamenti"]
                if a.get("controlla", True) and time.monotonic() >= prossimo:
                    self.controlla_aggiornamenti()
                    ore = float(a.get("ore_tra_controlli", 6) or 6)
                    prossimo = time.monotonic() + (ore * 3600 if self.agg["errore"] is None else 1800)
                if self._deve_installare_da_solo() and self._inattivo_da(180):
                    self.installa_aggiornamento(manuale=False)
            except Exception:
                log.exception("Ciclo aggiornamenti")
            self._sveglia_agg.wait(30)
            self._sveglia_agg.clear()

    def controlla_aggiornamenti(self, manuale: bool = False) -> dict:
        import requests
        with self._lock_agg:
            if self.agg["stato"] == "installazione":
                return self.stato_aggiornamenti()
            self.agg["stato"] = "controllo"
        m, errore = None, None
        try:
            m = aggiornamenti.controlla(motore.VERSIONE, self._url_aggiornamenti())
        except aggiornamenti.ErroreAggiornamento as e:
            errore = None if str(e).startswith("Nessuna versione") else str(e)
        except requests.RequestException:
            errore = "Nessuna connessione a GitHub"
        except Exception as e:
            log.exception("Controllo aggiornamenti")
            errore = f"Controllo non riuscito: {e}"
        nuovo = False
        with self._lock_agg:
            self.agg["ultimo_controllo"] = time.time()
            self.agg["errore"] = errore
            if m:
                nuovo = not self.agg["manifest"] or self.agg["manifest"]["versione"] != m["versione"]
                self.agg["manifest"] = m
                self.agg["richiede_installer"] = aggiornamenti.richiede_installer(m, CARTELLA)
                self.agg["stato"] = "disponibile"
            elif errore is None:
                self.agg["manifest"] = None
                self.agg["stato"] = "aggiornata"
            else:
                self.agg["stato"] = "disponibile" if self.agg["manifest"] else "errore"
        if m and nuovo:
            log.info("Disponibile la versione %s", m["versione"])
            if not manuale and not self._deve_installare_da_solo():
                self.notifica_una_volta(f"È disponibile Dettami {m['versione']}: aggiorna dalla dashboard.", 86400)
        self._aggiorna_icona()
        return self.stato_aggiornamenti()

    def installa_aggiornamento(self, manuale: bool = False):
        with self._lock_agg:
            m = self.agg.get("manifest")
            if not m or self.agg["stato"] == "installazione":
                return
            if self.agg["richiede_installer"]:
                if manuale:
                    self.apri("setup")
                return
            self.agg["stato"] = "installazione"
            self.agg["errore"] = None

        def lavoro():
            try:
                for _ in range(240):  # se stai dettando, aspetta che la dettatura finisca
                    if self._inattivo_da(0):
                        break
                    time.sleep(0.5)
                nuova = CARTELLA_AGG / "nuova"
                zip_path = aggiornamenti.scarica(m, CARTELLA_AGG)
                aggiornamenti.prepara(zip_path, nuova, m["versione"])
                self._agg_salvato["note_installate"] = list(m.get("note", []))
                self._salva_stato_agg()
                log.info("Installo l'aggiornamento %s", m["versione"])
                self.indicatore.mostra("info", f"Aggiorno Dettami alla {m['versione']}…", durata=None)
                aggiornamenti.avvia_installazione(CARTELLA, nuova, m["versione"], motore.VERSIONE)
                time.sleep(0.6)
                # l'aggiornatore aspetta che questo processo finisca: se qualcosa lo tiene vivo, lo chiudiamo noi
                uscita_forzata = threading.Timer(8, lambda: os._exit(0))
                uscita_forzata.daemon = True
                uscita_forzata.start()
                self._esci(self.icon, None)
            except Exception as e:
                log.exception("Installazione aggiornamento")
                with self._lock_agg:
                    self.agg["stato"] = "disponibile"
                    self.agg["errore"] = f"Installazione non riuscita: {e}"
                if isinstance(e, aggiornamenti.ErroreAggiornamento):  # pacchetto rotto: non riprovare da solo
                    self._agg_salvato["saltate"] = sorted(set(self._agg_salvato.get("saltate", [])) | {m["versione"]})
                    self._salva_stato_agg()
                self.indicatore.mostra("errore", "Aggiornamento non riuscito")
                if manuale:
                    self.notifica(f"Aggiornamento non riuscito: {e}")
                self._aggiorna_icona()

        threading.Thread(target=lavoro, daemon=True, name="installa-aggiornamento").start()

    def stato_aggiornamenti(self) -> dict:
        m = self.agg.get("manifest")
        a = self.cfg["aggiornamenti"]
        return {
            "versione": motore.VERSIONE,
            "stato": self.agg["stato"],
            "ultimo_controllo": self.agg["ultimo_controllo"],
            "errore": self.agg["errore"],
            "disponibile": m["versione"] if m else None,
            "note": [str(x) for x in m.get("note", [])] if m else [],
            "data": m.get("data") if m else None,
            "richiede_installer": self.agg["richiede_installer"],
            "saltata": bool(m and m["versione"] in self._agg_salvato.get("saltate", [])),
            "automatici": bool(a.get("automatici", True)),
            "controlla": bool(a.get("controlla", True)),
            "ultimo_aggiornamento": self._agg_salvato.get("ultimo_aggiornamento"),
            "progetto": aggiornamenti.URL_PROGETTO,
        }

    # ===================================================================== #
    #  Fornitore dei dati per la dashboard (chiamato dal thread del server)
    # ===================================================================== #

    def stato(self) -> dict:
        s = self._stato_corrente()
        return {
            "stato": {"registra": "ascolto"}.get(s, s),
            "tasto_nome": self._nome_tasto(),
            "versione": motore.VERSIONE,
            "chiave_presente": bool(self.api_key),
            "contatore": self.contatore,
            "parole_oggi": self.parole_oggi,
            "aggiornamento": self._versione_disponibile(),
            "aggiornamento_in_corso": self.agg["stato"] == "installazione",
        }

    def statistiche(self) -> dict:
        st = motore.statistiche(motore.leggi_cronologia(FILE_CRONOLOGIA))
        st["quota"] = motore.riepilogo_quota(self.cfg, self.client.quote, self.uso.istantanea())
        return st

    def cronologia(self, q: str, limite: int) -> list[dict]:
        return motore.cerca_cronologia(motore.leggi_cronologia(FILE_CRONOLOGIA), q, limite)

    def cancella_cronologia(self):
        motore.cancella_cronologia(FILE_CRONOLOGIA)
        self.parole_oggi = 0
        self.contatore += 1
        self._aggiorna_icona()

    def impostazioni(self) -> dict:
        valori = motore.valori_impostazioni(self.cfg)
        try:
            microfoni = elenco_microfoni()
        except Exception:
            microfoni = []
        if valori["microfono"] and valori["microfono"] not in microfoni:
            microfoni.insert(0, valori["microfono"])
        chiave = self.api_key
        return {
            "valori": valori,
            "esempio": {"detto": motore.ESEMPIO_DETTO, **motore.ESEMPI_LIVELLO},
            "opzioni": {
                "tasti": [{"valore": k, "nome": v} for k, v in motore.TASTI_AMMESSI.items()],
                "lingue": [{"valore": k, "nome": v} for k, v in motore.LINGUE_PARLATE.items()],
                "lingue_traduzione": [{"valore": x, "nome": x.capitalize()} for x in self.cfg["ai"]["lingue_traduzione"]],
                "microfoni": [{"valore": "", "nome": "Predefinito di Windows"}] +
                             [{"valore": m, "nome": m} for m in microfoni],
            },
            "chiave": {"presente": bool(chiave),
                       "mascherata": f"{chiave[:4]}…{chiave[-4:]}" if len(chiave) > 12 else ""},
            "avvio_automatico": os.path.exists(collegamento_avvio()),
            "cartella": str(CARTELLA),
            "versione": motore.VERSIONE,
        }

    def salva_impostazioni(self, dati: dict) -> dict:
        if self.macchina.registrando:
            raise ValueError("Finisci la dettatura in corso, poi riprova.")
        motore.salva_impostazioni(FILE_IMPOSTAZIONI, dati, self.cfg)
        try:
            nuova = motore.carica_config(FILE_CONFIG, FILE_IMPOSTAZIONI)
        except motore.ErroreConfig as e:
            raise ValueError(str(e)) from e
        self._applica_config(nuova)
        return {"valori": motore.valori_impostazioni(self.cfg)}

    def cambia_chiave(self):
        self._imposta_chiave()

    def confronta_riscrittura(self, testo: str, stile: str) -> dict:
        """Riscrive lo stesso testo nei tre livelli (in parallelo), per la pagina Riscrittura."""
        from concurrent.futures import ThreadPoolExecutor
        testo = (testo or "").strip()
        if not testo:
            raise ValueError("Scrivi prima una frase da provare.")
        if len(testo) > 4000:
            raise ValueError("Testo troppo lungo per la prova: massimo 4000 caratteri.")
        if stile not in ("normale", *self.cfg.get("stili", {}).keys()):
            stile = "normale"
        if not self.api_key:
            raise ValueError("Manca la chiave Groq: inseriscila in Impostazioni.")

        def uno(livello):
            t0 = time.perf_counter()
            try:
                uscita, avviso = motore.riscrivi(self.client, self.cfg, testo, stile, livello=livello)
            except motore.ErroreAPI as e:
                return {"livello": livello, "testo": "", "errore": str(e), "secondi": 0}
            return {"livello": livello, "testo": uscita, "errore": avviso,
                    "secondi": round(time.perf_counter() - t0, 2)}

        with ThreadPoolExecutor(max_workers=3) as ex:
            risultati = list(ex.map(uno, motore.LIVELLI_RISCRITTURA))
        self.uso.salva()
        return {"risultati": risultati, "attuale": motore.livello_riscrittura(self.cfg) if self.ai_attiva else "spenta"}

    def avvio_automatico(self, attivo: bool) -> bool:
        return imposta_avvio_automatico(attivo)

    def apri(self, cosa: str):
        destinazioni = {"config": FILE_CONFIG, "log": FILE_LOG, "cartella": CARTELLA}
        indirizzi = {"consumi": "https://console.groq.com/settings/limits",
                     "progetto": aggiornamenti.URL_PROGETTO, "setup": aggiornamenti.URL_VERSIONI}
        if cosa in indirizzi:
            os.startfile(indirizzi[cosa])  # type: ignore[attr-defined]
        elif cosa in destinazioni:
            apri_file(destinazioni[cosa])
        else:
            raise ValueError("Non so cosa aprire")

    def anteprima_indicatore(self):
        def sequenza():
            self._anteprima_fino = time.monotonic() + 2.4
            self.indicatore.mostra("ascolto", "In ascolto", timer=True, durata=2.4)
            time.sleep(2.4)
            self.indicatore.mostra("elabora", "Sto scrivendo…", durata=1.2)
            time.sleep(1.2)
            self.indicatore.mostra("fatto", "Inserito: 24 parole", pulsante="Copia",
                                   dato="Questo è un testo di prova copiato dall'anteprima di Dettami.",
                                   durata=5.0)
        if not self.macchina.registrando:
            threading.Thread(target=sequenza, daemon=True).start()

    def prova_microfono(self) -> dict:
        if self.macchina.registrando:
            raise ValueError("Finisci la dettatura in corso, poi riprova.")
        if not self.api_key:
            raise ValueError("Manca la chiave Groq: inseriscila qui sotto, in Chiave Groq.")
        reg = Registratore(self.cfg)
        self._reg_in_uso = reg
        try:
            self.indicatore.mostra("ascolto", "Prova: parla adesso", timer=True, durata=None)
            reg.avvia()
            time.sleep(4)
            audio = reg.ferma()
        finally:
            reg.chiudi()
            self._reg_in_uso = None
        livello = round(motore.livello(audio))
        if not motore.c_e_voce(audio, self.cfg["audio"]["soglia_silenzio"]):
            self.indicatore.mostra("silenzio", "Non ho sentito niente")
            return {"voce": False, "livello": livello}
        self.indicatore.mostra("elabora", "Sto scrivendo…", durata=None)
        try:
            r = motore.elabora(self.client, self.cfg, audio, "normale", False, self.lingua_trad, self.ai_attiva)
        except motore.ErroreAPI as e:
            self.indicatore.mostra("errore", breve_errore(e))
            raise ValueError(str(e)) from e
        self.uso.salva()
        self.indicatore.mostra("fatto", "Prova riuscita")
        return {"voce": True, "livello": livello, "grezzo": r.grezzo, "testo": r.testo,
                "t_trascrizione": round(r.t_trascrizione, 2), "t_ai": round(r.t_ai, 2)}


# --------------------------------------------------------------------------- #
#  Modalità prova (console)
# --------------------------------------------------------------------------- #

def modalita_prova(cfg: dict, api_key: str) -> None:
    import sounddevice as sd
    print("\n=== PROVA DETTAMI ===\n")
    print("Microfoni disponibili:")
    predef = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            segno = "  <- predefinito" if i == predef else ""
            print(f"  [{i}] {d['name']}{segno}")
    if not api_key:
        print("\n!! Manca la API key: icona Dettami → Imposta API key")
        return
    reg = Registratore(cfg)
    print("\nParla per 6 secondi (prova a dire qualcosa con qualche 'ehm' e un'autocorrezione)...")
    Suoni(True)("inizio")
    time.sleep(0.2)
    reg.avvia()
    time.sleep(6)
    audio = reg.ferma()
    reg.chiudi()
    Suoni(True)("fine")
    lv = motore.livello(audio)
    print(f"\nLivello voce: {lv:.0f}  (soglia silenzio attuale: {cfg['audio']['soglia_silenzio']})")
    if not motore.c_e_voce(audio, cfg["audio"]["soglia_silenzio"]):
        print("!! Non ho sentito voce: controlla il microfono o abbassa 'soglia_silenzio' in config.toml")
        return
    client = motore.ClientAI(cfg, api_key)
    try:
        r = motore.elabora(client, cfg, audio, "normale", False, cfg["ai"]["lingua_traduzione"], True)
    except motore.ErroreAPI as e:
        print(f"\n!! Errore: {e}")
        return
    print(f"\nTRASCRIZIONE GREZZA ({r.t_trascrizione:.2f} s):\n  {r.grezzo}")
    print(f"\nTESTO FINALE ({r.t_ai:.2f} s di AI):\n  {r.testo}")
    if r.avviso:
        print(f"\nAvviso: {r.avviso}")
    print("\nTutto ok: avvia l'app con avvia.bat")


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Dettatura vocale con AI")
    ap.add_argument("--prova", action="store_true", help="prova microfono e API dalla console")
    ap.add_argument("--icona", action="store_true", help="crea icona.ico")
    ap.add_argument("--pausa", action="store_true", help="attende Invio alla fine della prova")
    ap.add_argument("--avvio", action="store_true", help="avvio automatico: non apre la dashboard")
    ap.add_argument("--dopo-aggiornamento", metavar="VERSIONE", help="(uso interno) appena aggiornata")
    ap.add_argument("--riapri-dashboard", action="store_true", help="(uso interno) riapre la dashboard")
    args = ap.parse_args()

    if args.icona:
        crea_file_icona()
        return

    configura_log()
    try:
        cfg = motore.carica_config(FILE_CONFIG, FILE_IMPOSTAZIONI)
    except motore.ErroreConfig as e:
        log.error(str(e))
        if WINDOWS:
            ctypes.windll.user32.MessageBoxW(None, str(e), "Dettami", 0x10)
        return
    api_key = motore.leggi_api_key(FILE_ENV)

    if args.prova:
        try:
            modalita_prova(cfg, api_key)
        except Exception as e:
            print(f"\n!! Errore: {e}")
        if args.pausa:
            input("\nPremi Invio per chiudere...")
        return
    if not WINDOWS:
        print("Questa app è pensata per Windows. Su altri sistemi puoi usare: python dettami.py --prova")
        return
    if not istanza_unica():
        # già aperta: cliccare l'icona di Dettami apre la sua dashboard
        if not args.avvio:
            sessione = motore.leggi_json(FILE_SESSIONE, {})
            if isinstance(sessione, dict) and sessione.get("url"):
                dashboard.apri_finestra(sessione["url"])
        return
    indicatore.rendi_consapevole_dpi()
    App(cfg, api_key, apri_dashboard=args.riapri_dashboard or not args.avvio,
        dopo_aggiornamento=args.dopo_aggiornamento).avvia()


if __name__ == "__main__":
    main()
