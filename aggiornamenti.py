"""
Aggiornamenti automatici di Dettami.

1. L'app scarica manifest.json e manifest.sig dall'ultima versione pubblicata su GitHub.
2. Verifica la firma (RSA 3072, PKCS#1 v1.5, SHA-256) con la chiave pubblica qui sotto:
   solo chi ha la chiave privata può pubblicare aggiornamenti, anche se qualcuno prendesse
   il controllo dell'indirizzo da cui vengono scaricati.
3. Se la versione è più nuova scarica il pacchetto dell'app e controlla lo SHA-256 scritto
   nel manifest firmato.
4. Estrae i file in una cartella a parte, controlla che il codice si compili e lancia
   aggiorna.py, che sostituisce i file, riavvia l'app e, se la nuova versione non parte,
   rimette da solo quella precedente.

Gli aggiornamenti sostituiscono solo i file dell'app (circa 100 KB). Se una versione cambia
Python o le librerie, il manifest lo dice e l'app chiede di usare il nuovo installer.
Nessun dato dell'utente viene inviato: è solo il download di file pubblici.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = "albykeg/dettami"
URL_MANIFEST = f"https://github.com/{REPO}/releases/latest/download/manifest.json"
URL_PROGETTO = f"https://github.com/{REPO}"
URL_VERSIONI = f"https://github.com/{REPO}/releases/latest"

CHIAVE_PUBBLICA = {
    "n": int(
    "e714a27eb4a4cc2aadc06124224a7ee9e5413a136bc1a88b6d1d3b6caf17765aa6f8e4f537da1e1344934a6e32d74a6b"
    "07069e5e20392185eed6d9465d494a6b5a4260b16cab641ff86e14bd564df54a5fee9fd110e355f0b19c9d3b78d3cbe4"
    "f808182c499120c5f43bfd1de3de2b9c5d6e5a7e4034ba93772aa3c8bfbedfd4e8f2f68176e2432d30bbd24206548f56"
    "47b0a74878e57b28fd5bccb66faef862fe36bf7b891ecef1e64a436eccd6d230e5f338d6ab04ce833b3165031c8f825a"
    "dfd1c1d13ba4c9c43f6734e9fac08b7e304e848db5c11a3dfea89f1d57fc3b47e8c9b4cae69903e55fafcbb465a4532b"
    "493bb07e16632b7b2ebe0d72c5142f9f9e20ddc24942b1ade8d64b5077a947652e9ad32318814c4cafd5556638c1c11e"
    "ac30ff11392210d9a1ae79383aa74c1b7036215e4cb0c4bddac1545abe4c726b5416be29afdfc5b7ef12f991b3e35fd2"
    "6172b5c9708212eaabca8687b9a42e67ecb806da0ecdb1c79f3f9935b467207250aa7a7bd19c8cffa6b53fef3fb92999"
    , 16),
    "e": 65537,
}

MAX_MANIFEST = 64 * 1024
MAX_PACCHETTO = 30 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
NOME_VALIDO = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.(py|html|ps1|md|ico|txt|toml)$")
# nomi che Windows riserva ai dispositivi (con.py, nul.txt...): mai in un pacchetto
NOMI_RISERVATI = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
FILE_OBBLIGATORI = {"dettami.py", "motore.py", "aggiorna.py", "aggiornamenti.py", "versione.txt"}
VIETATI = {"config.toml", ".env", "impostazioni.json"}  # dati dell'utente: mai sovrascritti

# DigestInfo di SHA-256 (RFC 8017, sezione 9.2)
_PREFISSO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


class ErroreAggiornamento(Exception):
    pass


# --------------------------------------------------------------------------- firma

def _codifica(dati: bytes, k: int) -> bytes:
    t = _PREFISSO_SHA256 + hashlib.sha256(dati).digest()
    if k < len(t) + 11:
        raise ValueError("Chiave troppo corta")
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def verifica_firma(dati: bytes, firma: bytes, chiave: dict | None = None) -> bool:
    """RSASSA-PKCS1-v1_5 con SHA-256: confronta l'intera codifica attesa (niente parsing)."""
    chiave = chiave or CHIAVE_PUBBLICA
    n, e = chiave["n"], chiave["e"]
    k = (n.bit_length() + 7) // 8
    if len(firma) != k:
        return False
    s = int.from_bytes(firma, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    return hmac.compare_digest(em, _codifica(dati, k))


def firma(dati: bytes, chiave_privata: dict) -> bytes:
    n, d = chiave_privata["n"], chiave_privata["d"]
    k = (n.bit_length() + 7) // 8
    m = int.from_bytes(_codifica(dati, k), "big")
    return pow(m, d, n).to_bytes(k, "big")


def leggi_chiave_privata(percorso: Path) -> dict:
    j = json.loads(Path(percorso).read_text(encoding="utf-8"))
    return {"n": int(j["n"], 16), "e": int(j["e"]), "d": int(j["d"], 16)}


# --------------------------------------------------------------------------- versioni

def versione_tupla(v: str) -> tuple[int, ...]:
    if not isinstance(v, str) or not re.fullmatch(r"\d+(\.\d+){1,3}", v.strip()):
        raise ValueError(f"Versione non valida: {v!r}")
    return tuple(int(x) for x in v.strip().split("."))


def piu_nuova(a: str, b: str) -> bool:
    """True se la versione a è più nuova di b."""
    ta, tb = versione_tupla(a), versione_tupla(b)
    lung = max(len(ta), len(tb))
    return ta + (0,) * (lung - len(ta)) > tb + (0,) * (lung - len(tb))


def impronta_requisiti(testo: str) -> str:
    """SHA-256 dell'elenco delle librerie, indipendente da a capo e spazi."""
    righe = sorted(r.strip().lower() for r in testo.splitlines() if r.strip() and not r.strip().startswith("#"))
    return hashlib.sha256("\n".join(righe).encode()).hexdigest()


# --------------------------------------------------------------------------- manifest

def _scarica_limitato(sessione, url: str, limite: int, timeout: float) -> bytes:
    with sessione.get(url, timeout=timeout, stream=True) as r:
        if r.status_code == 404:
            raise ErroreAggiornamento("Nessuna versione pubblicata")
        if r.status_code >= 400:
            raise ErroreAggiornamento(f"Errore {r.status_code} scaricando {url.rsplit('/', 1)[-1]}")
        dati = bytearray()
        for pezzo in r.iter_content(64 * 1024):
            dati += pezzo
            if len(dati) > limite:
                raise ErroreAggiornamento("File più grande del previsto")
        return bytes(dati)


def valida_manifest(m) -> dict:
    if not isinstance(m, dict) or m.get("app") != "dettami":
        raise ErroreAggiornamento("Manifest non valido")
    versione_tupla(m.get("versione", ""))
    p = m.get("pacchetto")
    if not isinstance(p, dict) or not str(p.get("url", "")).startswith("https://"):
        raise ErroreAggiornamento("Manifest senza pacchetto valido")
    if not re.fullmatch(r"[0-9a-f]{64}", str(p.get("sha256", ""))):
        raise ErroreAggiornamento("Manifest senza impronta valida")
    if not isinstance(p.get("dimensione"), int) or not 0 < p["dimensione"] <= MAX_PACCHETTO:
        raise ErroreAggiornamento("Dimensione del pacchetto non valida")
    if not isinstance(m.get("note", []), list):
        raise ErroreAggiornamento("Note non valide")
    return m


def controlla(versione_attuale: str, url: str = URL_MANIFEST, sessione=None,
              chiave: dict | None = None, timeout: float = 15) -> dict | None:
    """Ritorna il manifest della versione più nuova (firma verificata) oppure None."""
    import requests
    sessione = sessione or requests.Session()
    base = url.rsplit("/", 1)[0]
    dati = _scarica_limitato(sessione, url, MAX_MANIFEST, timeout)
    sig = _scarica_limitato(sessione, base + "/manifest.sig", 4096, timeout)
    if not verifica_firma(dati, sig, chiave):
        raise ErroreAggiornamento("Firma dell'aggiornamento non valida: ignorato")
    try:
        m = valida_manifest(json.loads(dati.decode("utf-8")))
    except ValueError as e:
        raise ErroreAggiornamento(f"Manifest non valido: {e}") from e
    return m if piu_nuova(m["versione"], versione_attuale) else None


def richiede_installer(m: dict, cartella_app: Path) -> bool:
    """True se la nuova versione cambia Python o le librerie: serve il nuovo installer."""
    if m.get("richiede_installer"):
        return True
    runtime = Path(cartella_app) / "python" / "versione-runtime.txt"
    if m.get("runtime") and runtime.exists() and runtime.read_text(encoding="utf-8").strip() != m["runtime"]:
        return True
    req = Path(cartella_app) / "requisiti-windows.txt"
    if m.get("requisiti_sha256") and req.exists():
        if impronta_requisiti(req.read_text(encoding="utf-8")) != m["requisiti_sha256"]:
            return True
    return False


# --------------------------------------------------------------------------- pacchetto

def scarica(m: dict, cartella: Path, sessione=None, timeout: float = 60) -> Path:
    import requests
    sessione = sessione or requests.Session()
    p = m["pacchetto"]
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    try:
        dati = _scarica_limitato(sessione, p["url"], p["dimensione"], timeout)
    except ErroreAggiornamento as e:
        if "più grande" not in str(e):
            raise
        dati = b""
    if len(dati) != p["dimensione"] or hashlib.sha256(dati).hexdigest() != p["sha256"]:
        raise ErroreAggiornamento("Il pacchetto scaricato non corrisponde a quello firmato")
    destinazione = cartella / f"dettami-app-{m['versione']}.zip"
    destinazione.write_bytes(dati)
    return destinazione


def prepara(zip_path: Path, cartella: Path, versione: str) -> list[str]:
    """Estrae e controlla il pacchetto. Ritorna i nomi dei file pronti da installare."""
    cartella = Path(cartella)
    if cartella.exists():
        shutil.rmtree(cartella)
    cartella.mkdir(parents=True)
    nomi = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            nome = info.filename
            if (info.is_dir() or "/" in nome or "\\" in nome or not NOME_VALIDO.match(nome)
                    or nome.lower() in VIETATI or nome.split(".")[0].lower() in NOMI_RISERVATI):
                raise ErroreAggiornamento(f"File non ammesso nel pacchetto: {nome!r}")
            if nome.lower() in {n.lower() for n in nomi}:  # su Windows "A.py" e "a.py" sono lo stesso file
                raise ErroreAggiornamento(f"File ripetuto nel pacchetto: {nome!r}")
            if info.file_size > MAX_FILE:
                raise ErroreAggiornamento(f"File troppo grande nel pacchetto: {nome}")
            (cartella / nome).write_bytes(z.read(info))
            nomi.append(nome)
    mancanti = FILE_OBBLIGATORI - set(nomi)
    if mancanti:
        raise ErroreAggiornamento(f"Pacchetto incompleto: mancano {', '.join(sorted(mancanti))}")
    if (cartella / "versione.txt").read_text(encoding="utf-8").strip() != versione:
        raise ErroreAggiornamento("La versione del pacchetto non corrisponde al manifest")
    for nome in nomi:
        if nome.endswith(".py"):
            try:
                compile((cartella / nome).read_bytes(), nome, "exec")
            except SyntaxError as e:
                raise ErroreAggiornamento(f"Errore nel codice di {nome}: {e}") from e
    return sorted(nomi)


def avvia_installazione(cartella_app: Path, cartella_nuova: Path, versione: str, precedente: str,
                        riapri_dashboard: bool = False) -> subprocess.Popen:
    """
    Lancia aggiorna.py (una copia, così può sostituire anche se stesso) e ritorna subito.
    Chi chiama deve poi chiudere l'app: aggiorna.py aspetta che il processo esca.
    """
    cartella_app = Path(cartella_app)
    copia = Path(cartella_nuova).parent / "aggiorna-in-corso.py"
    shutil.copy2(cartella_app / "aggiorna.py", copia)
    eseguibile = Path(sys.executable)
    pythonw = eseguibile.with_name("pythonw.exe")
    if os.name == "nt" and pythonw.exists():
        eseguibile = pythonw
    argomenti = [str(eseguibile), "-I", str(copia), "--app", str(cartella_app), "--nuova", str(cartella_nuova),
                 "--pid", str(os.getpid()), "--python", str(eseguibile), "--versione", versione,
                 "--precedente", precedente]
    if riapri_dashboard:
        argomenti.append("--riapri-dashboard")
    opzioni = {}
    if os.name == "nt":
        opzioni["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED, NEW_GROUP, NO_WINDOW
    else:
        opzioni["start_new_session"] = True
    return subprocess.Popen(argomenti, cwd=str(cartella_app), close_fds=True, **opzioni)
