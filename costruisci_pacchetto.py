"""
Costruisce una versione di Dettami:
  dist/Dettami-Setup-<versione>.zip          installer completo (Python e librerie inclusi)
  dist/aggiornamento/dettami-app-<v>.zip     solo i file dell'app, per gli aggiornamenti automatici
  dist/aggiornamento/manifest.json + .sig      descrizione della versione, firmata

Pubblicare su GitHub (serve GitHub CLI con accesso al repository):
    python costruisci_pacchetto.py --pubblica
La firma richiede la chiave privata (.chiave/chiave-firma-dettami.json, mai su GitHub).

Contiene Python per Windows e tutte le librerie già scaricate, quindi l'installazione
funziona anche su PC senza Python e con internet limitato (serve solo per Groq).

Uso (da qualsiasi sistema con Python 3.11+ e internet):
    python costruisci_pacchetto.py
Dopo una modifica al codice: aumenta VERSIONE in motore.py e rilancia.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
import aggiornamenti  # noqa: E402

CHIAVE_PREDEFINITA = QUI / ".chiave" / "chiave-firma-dettami.json"
PYTHON_WINDOWS = "3.14.10"   # Python ufficiale (pacchetto NuGet della Python Software Foundation)
TOGLI_DA_PYTHON = ("include/", "libs/", "Lib/test/", "Lib/idlelib/", "Lib/turtledemo/", "Lib/turtle.py")


def versione_app() -> str:
    m = re.search(r'^VERSIONE\s*=\s*"([^"]+)"', (QUI / "motore.py").read_text(encoding="utf-8"), re.M)
    if not m:
        sys.exit("VERSIONE non trovata in motore.py")
    return m.group(1)


def prepara_python(cache: Path) -> Path:
    destinazione = cache / f"python-{PYTHON_WINDOWS}-win64.zip"
    if destinazione.exists():
        return destinazione
    nupkg = cache / f"python.{PYTHON_WINDOWS}.nupkg"
    if not nupkg.exists():
        url = f"https://api.nuget.org/v3-flatcontainer/python/{PYTHON_WINDOWS}/python.{PYTHON_WINDOWS}.nupkg"
        print(f"Scarico Python {PYTHON_WINDOWS} per Windows...")
        urllib.request.urlretrieve(url, nupkg)
    print("Preparo Python portatile...")
    with zipfile.ZipFile(nupkg) as src, zipfile.ZipFile(destinazione, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for nome in src.namelist():
            if not nome.startswith("tools/") or nome.endswith("/"):
                continue
            relativo = nome[len("tools/"):]
            if relativo.startswith(TOGLI_DA_PYTHON) or "__pycache__" in relativo:
                continue
            out.writestr("python/" + relativo, src.read(nome))
    return destinazione


def prepara_librerie(cache: Path) -> Path:
    cartella = cache / "wheels"
    requisiti = QUI / "installer" / "requisiti-windows.txt"
    pacchetti = [r.strip() for r in requisiti.read_text().splitlines() if r.strip() and not r.startswith("#")]
    cartella.mkdir(parents=True, exist_ok=True)
    presenti = {p.name.split("-")[0].lower().replace("_", "-") + "==" + p.name.split("-")[1] for p in cartella.glob("*.whl")}
    mancanti = [p for p in pacchetti if p.lower().replace("_", "-") not in presenti]
    if not mancanti:
        return cartella
    print(f"Scarico {len(mancanti)} librerie per Windows...")
    abi = "cp" + PYTHON_WINDOWS.split(".")[0] + PYTHON_WINDOWS.split(".")[1]
    for p in mancanti:
        base = [sys.executable, "-m", "pip", "download", "-q", "--no-deps", "-d", str(cartella)]
        windows = ["--only-binary=:all:", "--platform", "win_amd64", "--python-version",
                   ".".join(PYTHON_WINDOWS.split(".")[:2]), "--implementation", "cp",
                   "--abi", abi, "--abi", "abi3", "--abi", "none"]
        if subprocess.run(base + windows + [p]).returncode != 0:
            # libreria senza "wheel" pubblicato (pura Python): la costruiamo noi
            subprocess.run([sys.executable, "-m", "pip", "wheel", "-q", "--no-deps", "-w", str(cartella), p], check=True)
    return cartella


def scrivi(percorso: Path, testo: str, bom: bool = False, crlf: bool = True) -> None:
    testo = testo.replace("\r\n", "\n").lstrip("﻿")
    if crlf:
        testo = testo.replace("\n", "\r\n")
    percorso.write_bytes(("﻿" if bom else "").encode("utf-8") + testo.encode("utf-8"))


FILE_APP = ("dettami.py", "motore.py", "indicatore.py", "dashboard.py", "dashboard.html",
            "aggiornamenti.py", "aggiorna.py", "config.toml", "LEGGIMI.md")


def note_versione(versione: str) -> list[str]:
    """Le righe "- ..." sotto "## <versione>" in NOVITA.md."""
    testo = (QUI / "NOVITA.md").read_text(encoding="utf-8") if (QUI / "NOVITA.md").exists() else ""
    m = re.search(rf"^##\s+{re.escape(versione)}\b.*?$(.*?)(?=^##\s|\Z)", testo, re.M | re.S)
    if not m:
        return []
    return [r.strip()[2:].strip() for r in m.group(1).splitlines() if r.strip().startswith("- ")]


def pacchetto_aggiornamento(app: Path, versione: str, runtime: str, chiave: Path) -> Path | None:
    """Zip dei soli file dell'app + manifest firmato."""
    if not chiave.exists():
        print(f"ATTENZIONE: chiave di firma non trovata ({chiave}): niente pacchetto di aggiornamento.")
        return None
    uscita = QUI / "dist" / "aggiornamento"
    if uscita.exists():
        shutil.rmtree(uscita)
    uscita.mkdir(parents=True)
    zip_app = uscita / f"dettami-app-{versione}.zip"
    with zipfile.ZipFile(zip_app, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(app.iterdir()):
            nome = "config.esempio.toml" if f.name == "config.toml" else f.name
            info = zipfile.ZipInfo(nome, date_time=(2026, 1, 1, 0, 0, 0))  # zip riproducibile
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    dati = zip_app.read_bytes()
    manifest = {
        "app": "dettami",
        "versione": versione,
        "data": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": note_versione(versione),
        "pacchetto": {
            "url": f"https://github.com/{aggiornamenti.REPO}/releases/download/v{versione}/{zip_app.name}",
            "sha256": hashlib.sha256(dati).hexdigest(),
            "dimensione": len(dati),
        },
        "runtime": runtime,
        "requisiti_sha256": aggiornamenti.impronta_requisiti((app / "requisiti-windows.txt").read_text(encoding="utf-8")),
        "setup_url": aggiornamenti.URL_VERSIONI,
    }
    grezzo = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    privata = aggiornamenti.leggi_chiave_privata(chiave)
    if privata["n"] != aggiornamenti.CHIAVE_PUBBLICA["n"]:
        sys.exit("La chiave privata non corrisponde alla chiave pubblica scritta in aggiornamenti.py")
    sig = aggiornamenti.firma(grezzo, privata)
    assert aggiornamenti.verifica_firma(grezzo, sig)
    (uscita / "manifest.json").write_bytes(grezzo)
    (uscita / "manifest.sig").write_bytes(sig)
    # controllo finale: il pacchetto si prepara come lo farebbe l'app
    aggiornamenti.prepara(zip_app, uscita / "_prova", versione)
    shutil.rmtree(uscita / "_prova")
    print(f"Aggiornamento: {zip_app.name} ({len(dati) / 1000:.0f} KB), manifest firmato")
    return uscita


def pubblica(versione: str, setup_zip: Path, cartella_agg: Path) -> None:
    note = note_versione(versione)
    corpo = "\n".join(f"- {n}" for n in note) or "Correzioni e miglioramenti."
    corpo += ("\n\n**Prima installazione:** scarica `" + setup_zip.name + "`, fai *Estrai tutto* e apri `Installa.bat`."
              "\nChi ha già Dettami 1.3 o successiva la riceve da sola.")
    file_note = QUI / "dist" / "note-versione.md"
    file_note.write_text(corpo, encoding="utf-8")
    comando = ["gh", "release", "create", f"v{versione}", "--repo", aggiornamenti.REPO,
               "--title", f"Dettami {versione}", "--notes-file", str(file_note), "--latest",
               str(setup_zip), *(str(cartella_agg / n) for n in
                                 (f"dettami-app-{versione}.zip", "manifest.json", "manifest.sig"))]
    print("Pubblico su GitHub:", " ".join(comando[:4]))
    subprocess.run(comando, check=True)


def costruisci(cache: Path, chiave: Path = CHIAVE_PREDEFINITA, da_pubblicare: bool = False) -> Path:
    versione = versione_app()
    cache.mkdir(parents=True, exist_ok=True)
    py_zip = prepara_python(cache)
    wheels = prepara_librerie(cache)

    nome = f"Dettami-Setup-{versione}"
    dist = QUI / "dist"
    radice = dist / nome
    if radice.exists():
        shutil.rmtree(radice)
    app = radice / "setup" / "app"
    runtime = radice / "setup" / "runtime"
    app.mkdir(parents=True)
    (runtime / "wheels").mkdir(parents=True)

    leggi = lambda p: (QUI / p).read_text(encoding="utf-8")  # noqa: E731
    # file per Windows: script PowerShell in UTF-8 con BOM (accenti corretti su PowerShell 5.1), CRLF
    scrivi(radice / "Installa.bat", leggi("installer/Installa.bat"))
    scrivi(radice / "LEGGIMI.txt", leggi("installer/LEGGIMI.txt"), bom=True)
    scrivi(radice / "setup" / "installa.ps1", leggi("installer/installa.ps1"), bom=True)
    scrivi(app / "disinstalla.ps1", leggi("installer/disinstalla.ps1"), bom=True)
    scrivi(app / "chiave.ps1", leggi("chiave.ps1"), bom=True)
    scrivi(app / "requisiti-windows.txt", leggi("installer/requisiti-windows.txt"))
    scrivi(app / "versione.txt", versione + "\n")
    for f in FILE_APP:
        scrivi(app / f, leggi(f), crlf=False)
    shutil.copy2(QUI / "icona.ico", app / "icona.ico")
    shutil.copy2(py_zip, runtime / py_zip.name)
    for w in wheels.glob("*.whl"):
        shutil.copy2(w, runtime / "wheels" / w.name)

    zip_finale = dist / f"{nome}.zip"
    zip_finale.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_finale, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(radice.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(dist))
    print(f"Pronto: {zip_finale}  ({zip_finale.stat().st_size / 1e6:.0f} MB)")
    cartella_agg = pacchetto_aggiornamento(app, versione, py_zip.name, chiave)
    if da_pubblicare:
        if not cartella_agg:
            sys.exit("Per pubblicare serve la chiave di firma.")
        pubblica(versione, zip_finale, cartella_agg)
    return zip_finale


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=QUI / ".cache_pacchetto",
                    help="dove tenere Python e librerie scaricati (si riusano tra una build e l'altra)")
    ap.add_argument("--chiave", type=Path, default=CHIAVE_PREDEFINITA, help="chiave privata di firma")
    ap.add_argument("--pubblica", action="store_true", help="crea la release su GitHub")
    a = ap.parse_args()
    costruisci(a.cache, a.chiave, a.pubblica)
