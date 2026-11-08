"""
Indicatore a schermo: una "pillola" in basso al centro che mostra cosa sta facendo Dettami.

- Sempre in primo piano, trasparente ai clic e NON prende mai il focus
  (fondamentale: il testo deve finire nella finestra in cui stai scrivendo).
- Disegnata con Pillow e mostrata con UpdateLayeredWindow (trasparenza per pixel, bordi morbidi).
- Gira in un suo thread con la sua coda di messaggi Windows; se qualcosa va storto si
  disattiva da sola senza toccare la dettatura.

La funzione disegna_pillola() non dipende da Windows (serve anche per le anteprime e i test).
"""
from __future__ import annotations

import logging
import math
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("dettami")
WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------- #
#  Aspetto
# --------------------------------------------------------------------------- #

COLORI = {
    "ascolto": (239, 68, 68),
    "mani_libere": (239, 68, 68),
    "traduci": (139, 92, 246),
    "elabora": (245, 158, 11),
    "fatto": (34, 197, 94),
    "annullato": (148, 163, 184),
    "silenzio": (148, 163, 184),
    "errore": (239, 68, 68),
    "info": (34, 197, 94),
}
DURATE = {"fatto": 1.3, "annullato": 0.9, "silenzio": 1.6, "errore": 3.5, "info": 2.0}
SFUMATURA = 0.25  # secondi di dissolvenza in uscita
FONDO = (22, 24, 30)
ALFA_FONDO = 238


def _su_fondo(colore: tuple, intensita: float) -> tuple:
    """Colore già mescolato con il fondo: Pillow sovrascrive i pixel invece di sfumarli."""
    i = max(0.0, min(1.0, intensita))
    return tuple(int(c * i + f * (1 - i)) for c, f in zip(colore, FONDO)) + (ALFA_FONDO,)
SS = 3  # sovracampionamento per bordi lisci

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(peso: str, dim: int):
    chiave = (peso, dim)
    if chiave not in _font_cache:
        mac = "/System/Library/Fonts/Supplemental/Arial" + (" Bold" if peso == "semi" else "") + ".ttf"
        nomi = (["seguisb.ttf", "segoeuib.ttf"] if peso == "semi" else ["segoeui.ttf"]) + \
               ["arial.ttf", mac, "DejaVuSans-Bold.ttf" if peso == "semi" else "DejaVuSans.ttf"]
        for n in nomi:
            try:
                _font_cache[chiave] = ImageFont.truetype(n, dim)
                break
            except OSError:
                continue
        else:
            _font_cache[chiave] = ImageFont.load_default(dim)
    return _font_cache[chiave]


def disegna_pillola(tipo: str, testo: str, t: float = 0.0, livelli: list[float] | None = None,
                    scala: float = 1.0, opacita: float = 1.0, timer: str = "",
                    pulsante: str | None = None, evidenzia: bool = False) -> Image.Image:
    """
    Ritorna l'immagine RGBA della pillola (dimensioni già in pixel reali).
    Se c'è un pulsante, il suo rettangolo (in pixel dell'immagine) è in img.info["pulsante"].
    """
    k = scala * SS
    colore = COLORI.get(tipo, COLORI["info"])
    barre = tipo in ("ascolto", "mani_libere", "traduci")

    f_testo = _font("semi", max(8, round(14.5 * k)))
    f_timer = _font("normale", max(8, round(13 * k)))
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w_testo = misura.textlength(testo, font=f_testo)
    w_timer = misura.textlength(timer, font=f_timer) if timer else 0
    f_puls = _font("semi", max(8, round(13.5 * k)))
    w_puls = (misura.textlength(pulsante, font=f_puls) + round(30 * k)) if pulsante else 0

    H = round(46 * k)
    x_testo = round(48 * k)
    W = x_testo + w_testo + round(18 * k)
    if timer:
        W += w_timer + round(12 * k)
    if barre:
        W += round(66 * k)
    if pulsante:
        W += w_puls + round(2 * k)
    W = int(min(max(W, 150 * k), 600 * k))

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # fondo
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=FONDO + (ALFA_FONDO,),
                        outline=_su_fondo((255, 255, 255), 0.14), width=max(1, round(1 * k)))

    # icona a sinistra
    cx, cy, r = round(26 * k), H // 2, round(15 * k)
    if tipo in ("ascolto", "mani_libere", "traduci"):
        pulsa = (math.sin(t * 2 * math.pi * 1.1) + 1) / 2
        rr = r * (0.72 + 0.28 * pulsa)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=_su_fondo(colore, 0.22 + 0.18 * (1 - pulsa)))
        rc = round(6.5 * k)
        d.ellipse((cx - rc, cy - rc, cx + rc, cy + rc), fill=_su_fondo(colore, 1))
    elif tipo == "elabora":
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_su_fondo(colore, 0.18))
        inizio = (t * 400) % 360
        rs = round(9 * k)
        d.arc((cx - rs, cy - rs, cx + rs, cy + rs), start=inizio, end=inizio + 260,
              fill=_su_fondo(colore, 1), width=max(2, round(2.6 * k)))
    else:
        d.ellipse((cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82), fill=_su_fondo(colore, 1))
        bianco = (255, 255, 255, ALFA_FONDO)
        sp = max(2, round(2.4 * k))
        u = k
        if tipo in ("fatto", "info"):
            d.line([(cx - 5.5 * u, cy + 0.5 * u), (cx - 1.5 * u, cy + 4.5 * u), (cx + 6 * u, cy - 4 * u)],
                   fill=bianco, width=sp, joint="curve")
        elif tipo == "errore":
            d.line([(cx, cy - 6 * u), (cx, cy + 1.5 * u)], fill=bianco, width=sp)
            d.ellipse((cx - 1.6 * u, cy + 4 * u, cx + 1.6 * u, cy + 7.2 * u), fill=bianco)
        elif tipo == "annullato":
            d.line([(cx - 4.5 * u, cy - 4.5 * u), (cx + 4.5 * u, cy + 4.5 * u)], fill=bianco, width=sp)
            d.line([(cx - 4.5 * u, cy + 4.5 * u), (cx + 4.5 * u, cy - 4.5 * u)], fill=bianco, width=sp)
        else:  # silenzio
            d.line([(cx - 5 * u, cy), (cx + 5 * u, cy)], fill=bianco, width=sp)

    # testo
    asc, disc = f_testo.getmetrics()
    y_testo = (H - (asc + disc)) // 2
    d.text((x_testo, y_testo), testo, font=f_testo, fill=(255, 255, 255, ALFA_FONDO))
    x = x_testo + w_testo + round(12 * k)
    if timer:
        a2, d2 = f_timer.getmetrics()
        d.text((x, (H - (a2 + d2)) // 2 + round(1 * k)), timer, font=f_timer, fill=_su_fondo((255, 255, 255), 0.62))
        x += w_timer + round(12 * k)

    # barre del volume (le più recenti a destra)
    if barre:
        n, larg, spazio = 10, round(3.2 * k), round(2.8 * k)
        valori = list(livelli or [])[-n:]
        valori = [0.0] * (n - len(valori)) + valori
        x0 = W - round(20 * k) - n * larg - (n - 1) * spazio
        hmax, hmin = round(24 * k), round(3.5 * k)
        for i, v in enumerate(valori):
            h = hmin + (hmax - hmin) * max(0.0, min(1.0, v))
            bx = x0 + i * (larg + spazio)
            d.rounded_rectangle((bx, cy - h / 2, bx + larg, cy + h / 2), radius=larg / 2,
                                fill=_su_fondo(colore, 0.55 + 0.45 * min(1.0, v + 0.15)))

    # pulsante a destra (es. "Copia")
    rett = None
    if pulsante:
        hp = round(30 * k)
        x1 = W - round(8 * k)
        x0 = x1 - w_puls
        y0 = (H - hp) // 2
        d.rounded_rectangle((x0, y0, x1, y0 + hp), radius=hp // 2,
                            fill=_su_fondo((255, 255, 255), 0.30 if evidenzia else 0.16))
        a3, d3 = f_puls.getmetrics()
        d.text((x0 + round(15 * k), y0 + (hp - (a3 + d3)) // 2), pulsante, font=f_puls,
               fill=(255, 255, 255, ALFA_FONDO))
        rett = (x0 / SS, y0 / SS, x1 / SS, (y0 + hp) / SS)

    img = img.resize((max(1, round(W / SS)), max(1, round(H / SS))), Image.LANCZOS)
    if opacita < 1:
        a = np.asarray(img).copy()
        a[..., 3] = (a[..., 3].astype(np.float32) * max(0.0, opacita)).astype(np.uint8)
        img = Image.fromarray(a, "RGBA")
    if rett:
        img.info["pulsante"] = tuple(round(v) for v in rett)
    return img


def bgra_premoltiplicato(img: Image.Image) -> bytes:
    """Formato richiesto da UpdateLayeredWindow: BGRA con colori premoltiplicati per l'alfa."""
    a = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    alfa = a[..., 3:4]
    rgb = (a[..., :3] * alfa + 127) // 255
    return np.concatenate([rgb[..., ::-1], alfa], axis=2).astype(np.uint8).tobytes()


@dataclass
class Stato:
    tipo: str
    testo: str
    inizio: float = field(default_factory=time.monotonic)
    durata: float | None = None      # None = resta finché non cambia
    timer_da: float | None = None    # mostra un cronometro da questo istante
    pulsante: str | None = None      # es. "Copia": rende la pillola cliccabile
    dato: str | None = None          # cosa passare al clic (il testo da copiare)


# --------------------------------------------------------------------------- #
#  Finestra Windows
# --------------------------------------------------------------------------- #

class Indicatore:
    """Uso: ind.mostra("ascolto", "In ascolto", timer=True); ind.mostra("fatto", "Inserito"); ind.nascondi()"""

    def __init__(self, attivo: bool = True, posizione: str = "basso", livelli=None, al_clic=None):
        self.attivo = attivo and WINDOWS
        self.posizione = posizione
        self.livelli = livelli or (lambda: [])
        self.al_clic = al_clic or (lambda dato: None)  # chiamata in un thread a parte
        self._cliccabile = False
        self._pos = (0, 0, 0, 0)           # x, y, larghezza, altezza della finestra
        self._rett_pulsante = None         # rettangolo del pulsante, relativo alla finestra
        self._sopra_pulsante = False
        self._stato: Stato | None = None
        self._lock = threading.Lock()
        self._hwnd = None
        self._pronto = threading.Event()
        self._visibile = False
        self._area = None
        self._scala = 1.0
        if self.attivo:
            threading.Thread(target=self._ciclo, daemon=True, name="indicatore").start()
            self._pronto.wait(3)

    # ----- API thread-safe -----

    def mostra(self, tipo: str, testo: str, timer: bool = False, durata: float | None = -1,
               pulsante: str | None = None, dato: str | None = None) -> None:
        if durata == -1:
            durata = DURATE.get(tipo)
        with self._lock:
            precedente = self._stato
            timer_da = None
            if timer:  # mantiene il cronometro se si passa da "ascolto" a "traduci"
                timer_da = precedente.timer_da if precedente and precedente.timer_da else time.monotonic()
            self._stato = Stato(tipo, testo, durata=durata, timer_da=timer_da, pulsante=pulsante, dato=dato)
        self._sveglia()

    @property
    def stato_attuale(self) -> Stato | None:
        with self._lock:
            return self._stato

    def nascondi(self) -> None:
        with self._lock:
            self._stato = None
        self._sveglia()

    def nascondi_se(self, *tipi: str) -> None:
        """Nasconde solo se in questo momento mostra uno di questi stati."""
        with self._lock:
            if self._stato and self._stato.tipo in tipi:
                self._stato = None
        self._sveglia()

    def configura(self, attivo: bool, posizione: str) -> None:
        self.posizione = posizione
        if not attivo:
            self.nascondi()
        if attivo and not self.attivo and WINDOWS and self._hwnd is None:
            self.attivo = True
            threading.Thread(target=self._ciclo, daemon=True, name="indicatore").start()
        self.attivo = attivo and WINDOWS

    def chiudi(self) -> None:
        if self._hwnd:
            try:
                _u.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

    def _sveglia(self):
        if self._hwnd:
            try:
                _u.PostMessageW(self._hwnd, WM_APP, 0, 0)
            except Exception:
                pass

    # ----- thread della finestra -----

    def _ciclo(self):
        try:
            self._crea_finestra()
        except Exception:
            log.exception("Indicatore non disponibile")
            self.attivo = False
            self._pronto.set()
            return
        self._pronto.set()
        msg = wt.MSG()
        while _u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _u.TranslateMessage(ctypes.byref(msg))
            _u.DispatchMessageW(ctypes.byref(msg))
        self._hwnd = None

    def _crea_finestra(self):
        self._proc = WNDPROC(self._wndproc)  # riferimento tenuto vivo
        hinst = _k.GetModuleHandleW(None)
        nome = "DettamiIndicatore"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = nome
        if not _u.RegisterClassExW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
            raise ctypes.WinError(ctypes.get_last_error())
        stile_ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = _u.CreateWindowExW(stile_ex, nome, "Dettami", WS_POPUP, 0, 0, 10, 10,
                                  None, None, hinst, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = hwnd

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE  # il clic non toglie il cursore alla finestra in cui scrivi
            if msg == WM_SETCURSOR and self._sopra_pulsante:
                _u.SetCursor(_u.LoadCursorW(None, IDC_HAND))
                return 1
            if msg == WM_LBUTTONUP:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                self._clic(x, y)
                return 0
            if msg == WM_APP:
                self._aggiorna(forza_posizione=True)
                return 0
            if msg == WM_TIMER:
                self._aggiorna()
                return 0
            if msg == WM_DESTROY:
                _u.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("Indicatore: errore di disegno, lo disattivo")
            self.attivo = False
            try:
                _u.KillTimer(hwnd, 1)
                _u.ShowWindow(hwnd, SW_HIDE)
            except Exception:
                pass
            return 0
        return _u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _aggiorna(self, forza_posizione: bool = False):
        with self._lock:
            stato = self._stato
        if stato is None or not self.attivo:
            self._nascondi_finestra()
            return
        trascorso = time.monotonic() - stato.inizio
        opacita = min(1.0, trascorso / 0.12)  # breve dissolvenza in entrata
        if stato.durata is not None:
            resta = stato.durata - trascorso
            if resta <= 0:
                with self._lock:
                    if self._stato is stato:
                        self._stato = None
                self._nascondi_finestra()
                return
            opacita = min(opacita, resta / SFUMATURA)
        if forza_posizione or not self._visibile:
            self._misura_schermo()
        timer = ""
        if stato.timer_da is not None:
            sec = int(time.monotonic() - stato.timer_da)
            timer = f"{sec // 60}:{sec % 60:02d}"
        livelli = self.livelli() if stato.tipo in ("ascolto", "mani_libere", "traduci") else None
        cliccabile = bool(stato.pulsante)
        self._imposta_cliccabile(cliccabile)
        if cliccabile and self._visibile:
            dentro, self._sopra_pulsante = self._mouse_sopra()
            if dentro and stato.durata is not None:  # col mouse sopra non sparisce
                with self._lock:
                    stato.durata = max(stato.durata, trascorso + 1.2)
                opacita = min(1.0, trascorso / 0.12)
        img = disegna_pillola(stato.tipo, stato.testo, trascorso, livelli, self._scala, opacita, timer,
                              pulsante=stato.pulsante, evidenzia=self._sopra_pulsante)
        self._rett_pulsante = img.info.get("pulsante")
        self._presenta(img)
        if not self._visibile:
            _u.SetTimer(self._hwnd, 1, 33, None)
            _u.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            self._visibile = True
            forza_posizione = True
        if forza_posizione:  # resta sopra anche alle finestre "sempre in primo piano" aperte dopo
            _u.SetWindowPos(self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _nascondi_finestra(self):
        if self._visibile:
            _u.KillTimer(self._hwnd, 1)
            _u.ShowWindow(self._hwnd, SW_HIDE)
            self._visibile = False
        self._imposta_cliccabile(False)

    def _clic(self, x: int, y: int):
        with self._lock:
            stato = self._stato
        if not stato or not stato.pulsante:
            return
        r = self._rett_pulsante
        if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
            dato = stato.dato
            threading.Thread(target=self.al_clic, args=(dato,), daemon=True).start()
        else:  # clic sul resto della pillola: la chiude
            with self._lock:
                if self._stato is stato:
                    self._stato = None
        self._aggiorna()

    def _imposta_cliccabile(self, si: bool):
        """Senza pulsante la pillola lascia passare i clic a ciò che c'è sotto."""
        if si == self._cliccabile or not self._hwnd:
            return
        stile = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if not si:
            stile |= WS_EX_TRANSPARENT
        _SetWindowLongPtr(self._hwnd, GWL_EXSTYLE, stile)
        _u.SetWindowPos(self._hwnd, None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        self._cliccabile = si
        if not si:
            self._sopra_pulsante = False

    def _mouse_sopra(self) -> tuple[bool, bool]:
        """(sopra la pillola, sopra il pulsante) guardando dov'è il cursore adesso."""
        pt = wt.POINT()
        if not _u.GetCursorPos(ctypes.byref(pt)):
            return False, False
        x, y, w, h = self._pos
        dentro = x <= pt.x < x + w and y <= pt.y < y + h
        r = self._rett_pulsante
        sul_pulsante = dentro and r is not None and r[0] <= pt.x - x <= r[2] and r[1] <= pt.y - y <= r[3]
        return dentro, sul_pulsante

    def _misura_schermo(self):
        """Area utile (senza barra delle applicazioni) e DPI del monitor dove stai lavorando."""
        mon = _u.MonitorFromWindow(_u.GetForegroundWindow(), 2)  # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if mon and _u.GetMonitorInfoW(mon, ctypes.byref(info)):
            self._area = (info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
        else:
            self._area = (0, 0, _u.GetSystemMetrics(0), _u.GetSystemMetrics(1))
        dpi = 96
        try:
            x, y = wt.UINT(), wt.UINT()
            if mon and _shcore.GetDpiForMonitor(mon, 0, ctypes.byref(x), ctypes.byref(y)) == 0:
                dpi = x.value
        except Exception:
            pass
        self._scala = max(1.0, dpi / 96)

    def _presenta(self, img: Image.Image):
        w, h = img.size
        l, t, r, b = self._area
        margine = round(28 * self._scala)
        x = l + (r - l - w) // 2
        y = (b - h - margine) if self.posizione != "alto" else (t + margine)
        self._pos = (x, y, w, h)
        dati = bgra_premoltiplicato(img)

        schermo = _u.GetDC(None)
        mem = _g.CreateCompatibleDC(schermo)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # dall'alto verso il basso
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        hbmp = _g.CreateDIBSection(schermo, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            if not hbmp or not bits.value:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(bits, dati, len(dati))
            vecchio = _g.SelectObject(mem, hbmp)
            blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, alfa per pixel
            ok = _u.UpdateLayeredWindow(self._hwnd, schermo, ctypes.byref(wt.POINT(x, y)),
                                        ctypes.byref(wt.SIZE(w, h)), mem, ctypes.byref(wt.POINT(0, 0)),
                                        0, ctypes.byref(blend), 2)  # ULW_ALPHA
            _g.SelectObject(mem, vecchio)
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if hbmp:
                _g.DeleteObject(hbmp)
            _g.DeleteDC(mem)
            _u.ReleaseDC(None, schermo)


def rendi_consapevole_dpi() -> None:
    """Va chiamata all'avvio, prima di creare finestre: niente immagini sfocate con lo zoom di Windows."""
    if not WINDOWS:
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # per monitor v2
            return
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Dichiarazioni Win32 (solo su Windows)
# --------------------------------------------------------------------------- #

WM_APP, WM_TIMER, WM_DESTROY = 0x8000, 0x0113, 0x0002
WM_LBUTTONUP, WM_MOUSEACTIVATE, WM_SETCURSOR = 0x0202, 0x0021, 0x0020
MA_NOACTIVATE, IDC_HAND, GWL_EXSTYLE = 3, 32649, -20
WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST = 0x00080000, 0x00000020, 0x00000008
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0004, 0x0010, 0x0020

if WINDOWS:
    import ctypes
    from ctypes import wintypes as wt

    LRESULT = wt.LPARAM
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    HWND_TOPMOST = wt.HWND(-1)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                    ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _g = ctypes.WinDLL("gdi32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _shcore = ctypes.WinDLL("shcore")
        _shcore.GetDpiForMonitor.argtypes = [wt.HMONITOR, ctypes.c_int, ctypes.POINTER(wt.UINT), ctypes.POINTER(wt.UINT)]
        _shcore.GetDpiForMonitor.restype = ctypes.c_long
    except OSError:
        _shcore = None

    def _firma(dll, nome, ritorno, argomenti):
        f = getattr(dll, nome)
        f.restype, f.argtypes = ritorno, argomenti

    _firma(_k, "GetModuleHandleW", wt.HMODULE, [wt.LPCWSTR])
    _firma(_u, "RegisterClassExW", wt.ATOM, [ctypes.POINTER(WNDCLASSEXW)])
    _firma(_u, "CreateWindowExW", wt.HWND, [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU,
                                             wt.HINSTANCE, wt.LPVOID])
    _firma(_u, "DefWindowProcW", LRESULT, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM])
    _firma(_u, "GetMessageW", wt.BOOL, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT])
    _firma(_u, "TranslateMessage", wt.BOOL, [ctypes.POINTER(wt.MSG)])
    _firma(_u, "DispatchMessageW", LRESULT, [ctypes.POINTER(wt.MSG)])
    _firma(_u, "PostMessageW", wt.BOOL, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM])
    _firma(_u, "PostQuitMessage", None, [ctypes.c_int])
    _firma(_u, "SetTimer", ctypes.c_size_t, [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p])
    _firma(_u, "KillTimer", wt.BOOL, [wt.HWND, ctypes.c_size_t])
    _firma(_u, "ShowWindow", wt.BOOL, [wt.HWND, ctypes.c_int])
    _firma(_u, "SetWindowPos", wt.BOOL, [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wt.UINT])
    _firma(_u, "GetForegroundWindow", wt.HWND, [])
    _firma(_u, "GetCursorPos", wt.BOOL, [ctypes.POINTER(wt.POINT)])
    _firma(_u, "LoadCursorW", wt.HANDLE, [wt.HINSTANCE, ctypes.c_void_p])
    _firma(_u, "SetCursor", wt.HANDLE, [wt.HANDLE])
    if hasattr(_u, "SetWindowLongPtrW"):
        _firma(_u, "SetWindowLongPtrW", ctypes.c_ssize_t, [wt.HWND, ctypes.c_int, ctypes.c_ssize_t])
        _SetWindowLongPtr = _u.SetWindowLongPtrW
    else:  # Windows a 32 bit
        _firma(_u, "SetWindowLongW", wt.LONG, [wt.HWND, ctypes.c_int, wt.LONG])
        _SetWindowLongPtr = _u.SetWindowLongW
    _firma(_u, "MonitorFromWindow", wt.HMONITOR, [wt.HWND, wt.DWORD])
    _firma(_u, "GetMonitorInfoW", wt.BOOL, [wt.HMONITOR, ctypes.POINTER(MONITORINFO)])
    _firma(_u, "GetSystemMetrics", ctypes.c_int, [ctypes.c_int])
    _firma(_u, "GetDC", wt.HDC, [wt.HWND])
    _firma(_u, "ReleaseDC", ctypes.c_int, [wt.HWND, wt.HDC])
    _firma(_u, "UpdateLayeredWindow", wt.BOOL, [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
                                                 ctypes.POINTER(wt.SIZE), wt.HDC, ctypes.POINTER(wt.POINT),
                                                 wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD])
    _firma(_g, "CreateCompatibleDC", wt.HDC, [wt.HDC])
    _firma(_g, "DeleteDC", wt.BOOL, [wt.HDC])
    _firma(_g, "CreateDIBSection", wt.HBITMAP, [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
                                                ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD])
    _firma(_g, "SelectObject", wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ])
    _firma(_g, "DeleteObject", wt.BOOL, [wt.HGDIOBJ])
