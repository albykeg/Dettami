"""
Costruisce una versione di Dettami:
  dist/Dettami-Setup-<versione>.zip          installer per Windows (Python e librerie inclusi)
  dist/Dettami-Mac-<versione>.zip            installer per Mac Intel (Python e librerie inclusi)
  dist/aggiornamento/dettami-app-<v>.zip     solo i file dell'app, per gli aggiornamenti automatici
  dist/aggiornamento/manifest.json + .sig      descrizione della versione per Windows, firmata
  dist/aggiornamento/manifest-mac.json + .sig  la stessa per Mac (stesso pacchetto, altro Python)

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
import plistlib
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
# Mac: Python "standalone" di Astral (python-build-standalone), autonomo e spostabile, per Intel
PYTHON_MAC = "3.13.17"
PBS_RILASCIO = "20261021"
RUNTIME_MAC = f"cpython-{PYTHON_MAC}+{PBS_RILASCIO}-x86_64-apple-darwin-install_only_stripped.tar.gz"
URL_PBS = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RILASCIO}/"
# piattaforme accettate per le librerie Mac: tutte quelle che funzionano da macOS 10.15 (Catalina)
PIATTAFORME_MAC = [f"macosx_10_{v}_{a}" for v in range(9, 16) for a in ("x86_64", "universal2", "intel")]
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


def _scarica(url: str, destinazione: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as r, open(destinazione, "wb") as f:
        shutil.copyfileobj(r, f)


def prepara_python_mac(cache: Path) -> Path:
    """Python per Mac Intel, controllato con l'impronta pubblicata da Astral."""
    cartella = cache / "mac" / "runtime"
    cartella.mkdir(parents=True, exist_ok=True)
    somme = cartella / f"SHA256SUMS-{PBS_RILASCIO}"
    if not somme.exists():
        _scarica(URL_PBS + "SHA256SUMS", somme)
    attesa = next((r.split()[0] for r in somme.read_text().splitlines() if r.endswith("  " + RUNTIME_MAC)), None)
    if not attesa:
        sys.exit(f"{RUNTIME_MAC} non è nell'elenco SHA256SUMS del rilascio {PBS_RILASCIO}")
    destinazione = cartella / RUNTIME_MAC
    if not destinazione.exists():
        print(f"Scarico Python {PYTHON_MAC} per Mac Intel...")
        _scarica(URL_PBS + RUNTIME_MAC.replace("+", "%2B"), destinazione)
    if hashlib.sha256(destinazione.read_bytes()).hexdigest() != attesa:
        destinazione.unlink()
        sys.exit("Python per Mac: impronta SHA-256 sbagliata, file cancellato. Rilancia.")
    return destinazione


def _nome_wheel(f: Path) -> str:
    nome, versione = f.name.split("-")[:2]
    return re.sub(r"[-_.]+", "-", nome).lower() + "==" + versione


def prepara_librerie_mac(cache: Path) -> tuple[list[Path], str]:
    """Librerie per Mac Intel e il file dei requisiti con le impronte (pip --require-hashes)."""
    cartella = cache / "mac" / "wheels"
    cartella.mkdir(parents=True, exist_ok=True)
    righe = (QUI / "mac" / "requisiti-mac.txt").read_text(encoding="utf-8").splitlines()
    pacchetti = [r.strip() for r in righe if r.strip() and not r.startswith("#")]
    for p in pacchetti:
        normale = re.sub(r"[-_.]+", "-", p.split("==")[0]).lower() + "==" + p.split("==")[1]
        if any(_nome_wheel(w) == normale for w in cartella.glob("*.whl")):
            continue
        print(f"Scarico {p} per Mac...")
        comando = [sys.executable, "-m", "pip", "download", "-q", "--no-deps", "-d", str(cartella),
                   "--only-binary=:all:", "--python-version", ".".join(PYTHON_MAC.split(".")[:2]),
                   "--implementation", "cp", "--abi", "cp" + "".join(PYTHON_MAC.split(".")[:2]),
                   "--abi", "abi3", "--abi", "none"]
        for piattaforma in PIATTAFORME_MAC:
            comando += ["--platform", piattaforma]
        subprocess.run(comando + [p], check=True)
    scelte, requisiti = [], [righe[0] if righe and righe[0].startswith("#") else "# Librerie per Dettami su Mac"]
    for p in pacchetti:
        normale = re.sub(r"[-_.]+", "-", p.split("==")[0]).lower() + "==" + p.split("==")[1]
        wheel = next((w for w in sorted(cartella.glob("*.whl")) if _nome_wheel(w) == normale), None)
        if wheel is None:
            sys.exit(f"Manca la libreria per Mac {p}")
        scelte.append(wheel)
        requisiti.append(f"{p} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
    return scelte, "\n".join(requisiti) + "\n"


def scrivi(percorso: Path, testo: str, bom: bool = False, crlf: bool = True) -> None:
    testo = testo.replace("\r\n", "\n").lstrip("﻿")
    if crlf:
        testo = testo.replace("\n", "\r\n")
    percorso.write_bytes(("﻿" if bom else "").encode("utf-8") + testo.encode("utf-8"))


FILE_APP = ("dettami.py", "motore.py", "indicatore.py", "dashboard.py", "dashboard.html",
            "aggiornamenti.py", "aggiorna.py", "config.toml", "LEGGIMI.md",
            "sistema_mac.py", "indicatore_mac.py")


def note_versione(versione: str) -> list[str]:
    """Le righe "- ..." sotto "## <versione>" in NOVITA.md."""
    testo = (QUI / "NOVITA.md").read_text(encoding="utf-8") if (QUI / "NOVITA.md").exists() else ""
    m = re.search(rf"^##\s+{re.escape(versione)}\b.*?$(.*?)(?=^##\s|\Z)", testo, re.M | re.S)
    if not m:
        return []
    return [r.strip()[2:].strip() for r in m.group(1).splitlines() if r.strip().startswith("- ")]


def prepara_app(app: Path, versione: str) -> None:
    """Scrive in app/ i file dell'app per Windows: gli stessi che finiscono nel pacchetto di aggiornamento."""
    leggi = lambda p: (QUI / p).read_text(encoding="utf-8")  # noqa: E731
    # script PowerShell in UTF-8 con BOM (accenti corretti su PowerShell 5.1), CRLF
    scrivi(app / "disinstalla.ps1", leggi("installer/disinstalla.ps1"), bom=True)
    scrivi(app / "chiave.ps1", leggi("chiave.ps1"), bom=True)
    scrivi(app / "requisiti-windows.txt", leggi("installer/requisiti-windows.txt"))
    scrivi(app / "versione.txt", versione + "\n")
    for f in FILE_APP:
        scrivi(app / f, leggi(f), crlf=False)
    shutil.copy2(QUI / "icona.ico", app / "icona.ico")


def scrivi_zip_app(app: Path, zip_app: Path) -> None:
    """Il pacchetto di aggiornamento: i file di app/ in piano, config.toml come config.esempio.toml."""
    with zipfile.ZipFile(zip_app, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(app.iterdir()):
            nome = "config.esempio.toml" if f.name == "config.toml" else f.name
            info = zipfile.ZipInfo(nome, date_time=(2026, 1, 1, 0, 0, 0))  # zip riproducibile
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())


def pacchetto_aggiornamento(app: Path, versione: str, runtime: str, chiave: Path,
                            runtime_mac: str | None = None) -> Path | None:
    """Zip dei soli file dell'app + manifest firmati (uno per Windows e, se c'è, uno per Mac)."""
    if not chiave.exists():
        print(f"ATTENZIONE: chiave di firma non trovata ({chiave}): niente pacchetto di aggiornamento.")
        return None
    uscita = QUI / "dist" / "aggiornamento"
    if uscita.exists():
        shutil.rmtree(uscita)
    uscita.mkdir(parents=True)
    zip_app = uscita / f"dettami-app-{versione}.zip"
    scrivi_zip_app(app, zip_app)
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
        "sistema": "windows",
        "runtime": runtime,
        "requisiti_sha256": aggiornamenti.impronta_requisiti((app / "requisiti-windows.txt").read_text(encoding="utf-8")),
        "setup_url": aggiornamenti.URL_VERSIONI,
    }
    privata = aggiornamenti.leggi_chiave_privata(chiave)
    if privata["n"] != aggiornamenti.CHIAVE_PUBBLICA["n"]:
        sys.exit("La chiave privata non corrisponde alla chiave pubblica scritta in aggiornamenti.py")
    manifesti = {"manifest": manifest}
    if runtime_mac:
        manifesti["manifest-mac"] = {
            **manifest, "sistema": "mac", "runtime": runtime_mac,
            "requisiti_sha256": aggiornamenti.impronta_requisiti((app / "requisiti-mac.txt").read_text(encoding="utf-8")),
        }
    for nome, contenuto in manifesti.items():
        grezzo = json.dumps(contenuto, ensure_ascii=False, indent=2).encode("utf-8")
        sig = aggiornamenti.firma(grezzo, privata)
        assert aggiornamenti.verifica_firma(grezzo, sig)
        (uscita / f"{nome}.json").write_bytes(grezzo)
        (uscita / f"{nome}.sig").write_bytes(sig)
    # controllo finale: il pacchetto si prepara come lo farebbe l'app
    aggiornamenti.prepara(zip_app, uscita / "_prova", versione)
    shutil.rmtree(uscita / "_prova")
    print(f"Aggiornamento: {zip_app.name} ({len(dati) / 1000:.0f} KB), manifest firmato")
    return uscita


def costruisci_mac(cache: Path, versione: str, dist: Path) -> tuple[Path, str]:
    """dist/Dettami-Mac-<versione>.zip: installer per Mac Intel. Ritorna lo zip e i requisiti con impronte."""
    runtime = prepara_python_mac(cache)
    wheels, requisiti = prepara_librerie_mac(cache)
    nome = f"Dettami-Mac-{versione}"
    radice = dist / nome
    if radice.exists():
        shutil.rmtree(radice)
    app, mac = radice / "setup" / "app", radice / "setup" / "mac"
    for c in (app, mac, radice / "setup" / "runtime", radice / "setup" / "wheels"):
        c.mkdir(parents=True)
    leggi = lambda p: (QUI / p).read_text(encoding="utf-8")  # noqa: E731
    for f in FILE_APP:
        testo = leggi(f)
        if f == "config.toml":  # su Mac il tasto predefinito è Option destro
            assert '\ndettatura = "ctrl_r"' in testo
            testo = testo.replace('\ndettatura = "ctrl_r"', '\ndettatura = "alt_r"')
        scrivi(app / f, testo, crlf=False)
    scrivi(app / "versione.txt", versione + "\n", crlf=False)
    scrivi(app / "requisiti-mac.txt", requisiti, crlf=False)
    scrivi(mac / "avvio_app.py", leggi("mac/avvio_app.py"), crlf=False)
    scrivi(mac / "disinstalla.command", leggi("mac/Disinstalla Dettami.command"), crlf=False)
    with open(mac / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleDevelopmentRegion": "it", "CFBundleDisplayName": "Dettami", "CFBundleName": "Dettami",
            "CFBundleExecutable": "Dettami", "CFBundleIconFile": "Dettami",
            "CFBundleIdentifier": "io.github.albykeg.dettami", "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": versione, "CFBundleVersion": versione,
            "LSMinimumSystemVersion": "10.15", "LSUIElement": True, "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Dettami ascolta il microfono solo mentre tieni premuto il tasto "
                                            "di dettatura, per trascrivere quello che dici.",
        }, f)
    import dettami  # icona disegnata dal codice, come icona.ico
    dettami.disegna_icona("pronto", 1024).save(mac / "Dettami.icns")
    shutil.copy2(runtime, radice / "setup" / "runtime" / runtime.name)
    for w in wheels:
        shutil.copy2(w, radice / "setup" / "wheels" / w.name)
    scrivi(radice / "Installa Dettami.command", leggi("mac/Installa Dettami.command"), crlf=False)
    scrivi(radice / "Disinstalla Dettami.command", leggi("mac/Disinstalla Dettami.command"), crlf=False)
    scrivi(radice / "LEGGIMI.txt", leggi("mac/LEGGIMI.txt"), crlf=False)

    zip_finale = dist / f"{nome}.zip"
    zip_finale.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_finale, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(radice.rglob("*")):
            if not f.is_file():
                continue
            info = zipfile.ZipInfo(str(f.relative_to(dist)), date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3  # Unix: il Mac rispetta i permessi (gli script restano eseguibili)
            permessi = 0o755 if f.suffix == ".command" else 0o644
            info.external_attr = (0o100000 | permessi) << 16
            info.compress_type = zipfile.ZIP_STORED if f.suffix in (".gz", ".whl") else zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    print(f"Pronto: {zip_finale}  ({zip_finale.stat().st_size / 1e6:.0f} MB)")
    return zip_finale, requisiti


def pubblica(versione: str, setup_zip: Path, cartella_agg: Path, mac_zip: Path | None = None) -> None:
    note = note_versione(versione)
    corpo = "\n".join(f"- {n}" for n in note) or "Correzioni e miglioramenti."
    corpo += ("\n\n**Prima installazione su Windows:** scarica `" + setup_zip.name +
              "`, fai *Estrai tutto* e apri `Installa.bat`.")
    if mac_zip:
        corpo += ("\n\n**Prima installazione su Mac (beta, Intel):** scarica `" + mac_zip.name +
                  "`, aprilo e fai doppio clic su `Installa Dettami.command` (istruzioni in LEGGIMI.txt).")
    corpo += "\n\nChi ha già Dettami 1.3 o successiva (su Mac 1.4 o successiva) la riceve da sola."
    file_note = QUI / "dist" / "note-versione.md"
    file_note.write_text(corpo, encoding="utf-8")
    comando = ["gh", "release", "create", f"v{versione}", "--repo", aggiornamenti.REPO,
               "--title", f"Dettami {versione}", "--notes-file", str(file_note), "--latest",
               str(setup_zip), *(str(cartella_agg / n) for n in
                                 (f"dettami-app-{versione}.zip", "manifest.json", "manifest.sig"))]
    if mac_zip:
        comando += [str(mac_zip), str(cartella_agg / "manifest-mac.json"), str(cartella_agg / "manifest-mac.sig")]
    print("Pubblico su GitHub:", " ".join(comando[:4]))
    subprocess.run(comando, check=True)


def costruisci(cache: Path, chiave: Path = CHIAVE_PREDEFINITA, da_pubblicare: bool = False,
               con_mac: bool = True) -> Path:
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
    prepara_app(app, versione)
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
    mac_zip, runtime_mac = None, None
    if con_mac:
        mac_zip, requisiti_mac = costruisci_mac(cache, versione, dist)
        scrivi(app / "requisiti-mac.txt", requisiti_mac, crlf=False)  # va anche nel pacchetto di aggiornamento
        runtime_mac = RUNTIME_MAC
    cartella_agg = pacchetto_aggiornamento(app, versione, py_zip.name, chiave, runtime_mac)
    if da_pubblicare:
        if not cartella_agg:
            sys.exit("Per pubblicare serve la chiave di firma.")
        pubblica(versione, zip_finale, cartella_agg, mac_zip)
    return zip_finale


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=QUI / ".cache_pacchetto",
                    help="dove tenere Python e librerie scaricati (si riusano tra una build e l'altra)")
    ap.add_argument("--chiave", type=Path, default=CHIAVE_PREDEFINITA, help="chiave privata di firma")
    ap.add_argument("--pubblica", action="store_true", help="crea la release su GitHub")
    ap.add_argument("--senza-mac", action="store_true", help="non costruisce la versione per Mac")
    a = ap.parse_args()
    costruisci(a.cache, a.chiave, a.pubblica, con_mac=not a.senza_mac)
