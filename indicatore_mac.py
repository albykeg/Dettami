"""
La pillola a schermo su macOS: stessa grafica di Windows (indicatore.disegna_pillola),
mostrata in un pannello AppKit che non ruba il cursore all'app in cui stai scrivendo.

Le immagini si disegnano in un thread a parte; tutto quello che tocca AppKit passa
dal thread principale (sistema_mac.sul_thread_principale).
"""
from __future__ import annotations

import io
import logging
import threading
import time

from indicatore import DURATE, SFUMATURA, Stato, disegna_pillola

log = logging.getLogger("dettami")
MARGINE = 28        # punti dal bordo dello schermo
FPS = 30

_classe_vista = None


def _vista():
    """Classe Objective-C della vista (creata una volta sola, solo su Mac)."""
    global _classe_vista
    if _classe_vista is None:
        import objc
        from AppKit import NSView

        class VistaPillolaDettami(NSView):
            def initWithFrame_(self, cornice):
                self = objc.super(VistaPillolaDettami, self).initWithFrame_(cornice)
                if self is None:
                    return None
                self.immagine = None
                self.indicatore = None
                return self

            def acceptsFirstMouse_(self, evento):
                return True  # il clic funziona anche se Dettami non è l'app attiva

            def drawRect_(self, rettangolo):
                if self.immagine is not None:
                    self.immagine.drawInRect_(self.bounds())

            def mouseUp_(self, evento):
                if self.indicatore is not None:
                    p = self.convertPoint_fromView_(evento.locationInWindow(), None)
                    self.indicatore._clic(p.x, self.bounds().size.height - p.y)

        _classe_vista = VistaPillolaDettami
    return _classe_vista


class IndicatoreMac:
    """Stessa interfaccia di indicatore.Indicatore: mostra(), nascondi(), nascondi_se(), configura(), chiudi()."""

    def __init__(self, attivo: bool = True, posizione: str = "basso", livelli=None, al_clic=None,
                 sul_principale=None):
        self.attivo = attivo
        self.posizione = posizione
        self.livelli = livelli or (lambda: [])
        self.al_clic = al_clic or (lambda dato: None)
        if sul_principale is None:
            import sistema_mac
            sul_principale = sistema_mac.sul_thread_principale
        self._principale = sul_principale
        self._stato: Stato | None = None
        self._lock = threading.Lock()
        self._sveglia_ev = threading.Event()
        self._chiuso = False
        self._pannello = None
        self._vista = None
        self._visibile = False
        self._scala = 2.0              # pixel per punto dello schermo (Retina = 2)
        self._dim_punti = (0.0, 0.0)
        self._rett_pulsante = None     # in punti, dall'angolo in alto a sinistra della pillola
        self._mouse_dentro = False
        self._sopra_pulsante = False
        self._errori = 0
        threading.Thread(target=self._ciclo, daemon=True, name="indicatore").start()

    # ----- API (thread-safe) -----

    def mostra(self, tipo: str, testo: str, timer: bool = False, durata: float | None = -1,
               pulsante: str | None = None, dato: str | None = None) -> None:
        if durata == -1:
            durata = DURATE.get(tipo)
        with self._lock:
            precedente = self._stato
            timer_da = None
            if timer:
                timer_da = precedente.timer_da if precedente and precedente.timer_da else time.monotonic()
            self._stato = Stato(tipo, testo, durata=durata, timer_da=timer_da, pulsante=pulsante, dato=dato)
        self._sveglia_ev.set()

    @property
    def stato_attuale(self) -> Stato | None:
        with self._lock:
            return self._stato

    def nascondi(self) -> None:
        with self._lock:
            self._stato = None
        self._sveglia_ev.set()

    def nascondi_se(self, *tipi: str) -> None:
        with self._lock:
            if self._stato and self._stato.tipo in tipi:
                self._stato = None
        self._sveglia_ev.set()

    def configura(self, attivo: bool, posizione: str) -> None:
        self.posizione = posizione
        self.attivo = attivo
        if not attivo:
            self.nascondi()
        self._sveglia_ev.set()

    def chiudi(self) -> None:
        self._chiuso = True
        self._visibile = False
        self._sveglia_ev.set()
        if self._pannello is not None:
            self._principale(self._nascondi_pannello)

    # ----- disegno (thread "indicatore") -----

    def _ciclo(self):
        while not self._chiuso:
            self._sveglia_ev.wait(1 / FPS if self._visibile else 0.5)
            self._sveglia_ev.clear()
            if self._chiuso:
                break
            try:
                self._passo()
                self._errori = 0
            except Exception:
                self._errori += 1
                log.exception("Indicatore (Mac)")
                if self._errori >= 5:
                    log.error("Indicatore disattivato dopo troppi errori")
                    self.attivo = False
                    self._principale(self._nascondi_pannello)
                time.sleep(0.5)

    def _passo(self):
        with self._lock:
            stato = self._stato
        if stato is None or not self.attivo:
            if self._visibile:
                self._visibile = False
                self._principale(self._nascondi_pannello)
            return
        trascorso = time.monotonic() - stato.inizio
        opacita = min(1.0, trascorso / 0.12)
        if stato.pulsante and self._mouse_dentro and stato.durata is not None:
            with self._lock:  # col mouse sopra la pillola non sparisce
                stato.durata = max(stato.durata, trascorso + 1.2)
        if stato.durata is not None:
            resta = stato.durata - trascorso
            if resta <= 0:
                with self._lock:
                    if self._stato is stato:
                        self._stato = None
                if self._visibile:
                    self._visibile = False
                    self._principale(self._nascondi_pannello)
                return
            opacita = min(opacita, resta / SFUMATURA)
        timer = ""
        if stato.timer_da is not None:
            sec = int(time.monotonic() - stato.timer_da)
            timer = f"{sec // 60}:{sec % 60:02d}"
        livelli = self.livelli() if stato.tipo in ("ascolto", "mani_libere", "traduci") else None
        scala = self._scala
        img = disegna_pillola(stato.tipo, stato.testo, trascorso, livelli, scala, opacita, timer,
                              pulsante=stato.pulsante, evidenzia=self._sopra_pulsante and bool(stato.pulsante))
        rett = img.info.get("pulsante")
        b = io.BytesIO()
        img.save(b, "PNG", compress_level=1)
        larg, alt = img.size[0] / scala, img.size[1] / scala
        rett_punti = tuple(v / scala for v in rett) if rett else None
        self._visibile = True
        self._principale(self._presenta, b.getvalue(), larg, alt, rett_punti, bool(stato.pulsante))

    # ----- AppKit (thread principale) -----

    def _crea_pannello(self):
        import AppKit
        stile = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, 200, 46), stile, AppKit.NSBackingStoreBuffered, False)
        p.setOpaque_(False)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setHasShadow_(False)
        p.setLevel_(AppKit.NSStatusWindowLevel)
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorStationary
                                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        p.setIgnoresMouseEvents_(True)
        p.setHidesOnDeactivate_(False)
        p.setFloatingPanel_(True)
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setReleasedWhenClosed_(False)
        vista = _vista().alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 200, 46))
        vista.indicatore = self
        p.setContentView_(vista)
        self._pannello, self._vista = p, vista

    def _presenta(self, png: bytes, larg: float, alt: float, rett, cliccabile: bool):
        try:
            if self._chiuso or not self._visibile:
                return
            import AppKit
            from Foundation import NSData
            if self._pannello is None:
                self._crea_pannello()
            schermo = AppKit.NSScreen.mainScreen() or AppKit.NSScreen.screens()[0]
            self._scala = float(schermo.backingScaleFactor() or 1.0)  # per l'immagine successiva
            area = schermo.visibleFrame()  # senza barra dei menu e Dock
            x = area.origin.x + (area.size.width - larg) / 2
            if self.posizione == "alto":
                y = area.origin.y + area.size.height - alt - MARGINE
            else:
                y = area.origin.y + MARGINE
            immagine = AppKit.NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(png, len(png)))
            immagine.setSize_((larg, alt))
            self._pannello.setFrame_display_(AppKit.NSMakeRect(x, y, larg, alt), False)
            self._vista.setFrame_(AppKit.NSMakeRect(0, 0, larg, alt))
            self._vista.immagine = immagine
            self._vista.setNeedsDisplay_(True)
            self._pannello.setIgnoresMouseEvents_(not cliccabile)
            self._dim_punti, self._rett_pulsante = (larg, alt), rett
            mouse = AppKit.NSEvent.mouseLocation()
            dx, dy = mouse.x - x, (y + alt) - mouse.y   # dall'angolo in alto a sinistra
            self._mouse_dentro = cliccabile and 0 <= dx < larg and 0 <= dy < alt
            self._sopra_pulsante = bool(self._mouse_dentro and rett and rett[0] <= dx <= rett[2]
                                        and rett[1] <= dy <= rett[3])
            if not self._pannello.isVisible():
                self._pannello.orderFrontRegardless()
        except Exception:
            log.exception("Indicatore (Mac): disegno")

    def _nascondi_pannello(self):
        try:
            if self._pannello is not None and not self._visibile:
                self._pannello.orderOut_(None)
                self._pannello.setIgnoresMouseEvents_(True)
            self._mouse_dentro = self._sopra_pulsante = False
        except Exception:
            log.exception("Indicatore (Mac): chiusura")

    def _clic(self, x: float, y: float):
        """Chiamata dalla vista (thread principale). x, y in punti dall'angolo in alto a sinistra."""
        with self._lock:
            stato = self._stato
        if not stato or not stato.pulsante:
            return
        r = self._rett_pulsante
        if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
            threading.Thread(target=self.al_clic, args=(stato.dato,), daemon=True).start()
        else:  # clic sul resto della pillola: la chiude
            with self._lock:
                if self._stato is stato:
                    self._stato = None
        self._sveglia_ev.set()
