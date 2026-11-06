"""
Server della dashboard: HTTP solo su 127.0.0.1, porta casuale, con un codice segreto
che cambia a ogni avvio. Nessun altro computer (e nessun sito web) può leggere i tuoi dati.

Il server non sa nulla di Windows: chiede tutto a un "fornitore" (l'app) con questi metodi:
  stato(), statistiche(), cronologia(q, limite), impostazioni(), salva_impostazioni(dati),
  cancella_cronologia(), cambia_chiave(), confronta_riscrittura(testo, stile),
  prova_microfono(), anteprima_indicatore(),
  avvio_automatico(attivo), apri(cosa)
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("dettami")
CARTELLA = Path(__file__).resolve().parent
MAX_CORPO = 1_000_000


class ServerDashboard:
    def __init__(self, fornitore, pagina: Path | None = None, porta: int = 0, token: str | None = None):
        """porta e token di una sessione precedente: le finestre della dashboard già aperte
        si ricollegano da sole dopo un riavvio (per esempio dopo un aggiornamento)."""
        self.fornitore = fornitore
        self.pagina = pagina or CARTELLA / "dashboard.html"
        self.token = token if token and len(token) >= 24 else secrets.token_urlsafe(24)
        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", porta or 0), self._gestore())
        except OSError:  # porta già occupata: se ne sceglie un'altra
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._gestore())
        self.httpd.daemon_threads = True
        self.porta = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="dashboard")
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}/?t={self.token}"

    def chiudi(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass

    def _gestore(self):
        server = self

        class Gestore(BaseHTTPRequestHandler):
            server_version = "Dettami"
            sys_version = ""

            def log_message(self, *a):  # niente log su console
                pass

            # ---------- utilità ----------
            def _host_valido(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{server.porta}", f"localhost:{server.porta}")

            def _autorizzato(self) -> bool:
                dato = self.headers.get("X-Token") or ""
                return hmac.compare_digest(dato.encode(), server.token.encode())

            def _invia(self, codice: int, corpo: bytes, tipo: str):
                self.send_response(codice)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                if tipo.startswith("text/html"):
                    self.send_header("Content-Security-Policy",
                                     "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                     "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
                                     "frame-ancestors 'none'")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corpo)

            def _json(self, codice: int, dati):
                self._invia(codice, json.dumps(dati, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")

            def _leggi_corpo(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_CORPO:
                    raise ValueError("Richiesta troppo grande")
                grezzo = self.rfile.read(n) if n else b"{}"
                return json.loads(grezzo or b"{}")

            # ---------- metodi ----------
            def do_GET(self):
                if not self._host_valido():
                    return self._invia(400, b"", "text/plain")
                u = urlparse(self.path)
                if u.path in ("/", "/index.html"):
                    try:
                        return self._invia(200, server.pagina.read_bytes(), "text/html; charset=utf-8")
                    except OSError:
                        return self._invia(500, "Pagina della dashboard mancante".encode(), "text/plain; charset=utf-8")
                if not u.path.startswith("/api/"):
                    return self._invia(404, b"", "text/plain")
                if not self._autorizzato():
                    return self._json(403, {"errore": "Non autorizzato: riapri la dashboard dall'icona di Dettami."})
                q = parse_qs(u.query)
                f = server.fornitore
                try:
                    if u.path == "/api/stato":
                        return self._json(200, f.stato())
                    if u.path == "/api/statistiche":
                        return self._json(200, f.statistiche())
                    if u.path == "/api/cronologia":
                        limite = min(1000, int((q.get("limite") or ["300"])[0]))
                        return self._json(200, f.cronologia((q.get("q") or [""])[0], limite))
                    if u.path == "/api/impostazioni":
                        return self._json(200, f.impostazioni())
                    if u.path == "/api/aggiornamenti":
                        return self._json(200, f.stato_aggiornamenti())
                except Exception as e:
                    log.exception("Dashboard GET %s", u.path)
                    return self._json(500, {"errore": str(e)})
                return self._json(404, {"errore": "Non trovato"})

            def do_POST(self):
                if not self._host_valido():
                    return self._invia(400, b"", "text/plain")
                if not self._autorizzato():
                    return self._json(403, {"errore": "Non autorizzato"})
                u = urlparse(self.path)
                f = server.fornitore
                try:
                    dati = self._leggi_corpo()
                    if u.path == "/api/impostazioni":
                        return self._json(200, f.salva_impostazioni(dati))
                    if u.path == "/api/cronologia/cancella":
                        f.cancella_cronologia()
                        return self._json(200, {"ok": True})
                    if u.path == "/api/chiave":
                        f.cambia_chiave()
                        return self._json(200, {"ok": True})
                    if u.path == "/api/prova":
                        return self._json(200, f.prova_microfono())
                    if u.path == "/api/aggiornamenti/controlla":
                        return self._json(200, f.controlla_aggiornamenti(manuale=True))
                    if u.path == "/api/aggiornamenti/installa":
                        f.installa_aggiornamento(manuale=True)
                        return self._json(200, {"ok": True})
                    if u.path == "/api/riscrivi":
                        return self._json(200, f.confronta_riscrittura(str(dati.get("testo", "")),
                                                                     str(dati.get("stile", "normale"))))
                    if u.path == "/api/anteprima":
                        f.anteprima_indicatore()
                        return self._json(200, {"ok": True})
                    if u.path == "/api/avvio":
                        return self._json(200, {"attivo": f.avvio_automatico(bool(dati.get("attivo")))})
                    if u.path == "/api/apri":
                        f.apri(str(dati.get("cosa", "")))
                        return self._json(200, {"ok": True})
                except ValueError as e:
                    return self._json(400, {"errore": str(e)})
                except Exception as e:
                    log.exception("Dashboard POST %s", u.path)
                    return self._json(500, {"errore": str(e)})
                return self._json(404, {"errore": "Non trovato"})

        return Gestore


def trova_edge() -> str | None:
    candidati = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in candidati:
        if c and os.path.exists(c):
            return c
    return shutil.which("msedge")


def apri_finestra(url: str) -> None:
    """Apre la dashboard in una finestra a sé (Edge in modalità app), altrimenti nel browser."""
    edge = trova_edge()
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1200,860"])
            return
        except OSError:
            log.exception("Apertura con Edge")
    import webbrowser
    webbrowser.open(url)
