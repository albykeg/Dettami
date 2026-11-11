"""
Prova dell'installer Mac su Linux: esegue davvero "Installa Dettami.command" e "Disinstalla Dettami.command"
con comandi di macOS finti (uname, sw_vers, osascript, xattr, open, curl, pkill, clear), il Python standalone
per Linux al posto di quello per Mac e librerie Linux + un wheel finto per i moduli che esistono solo su Mac.

Prima: python costruisci_pacchetto.py   (serve dist/Dettami-Mac-<versione>/)
Uso:   python prove/prova_installer_mac.py [--cache CARTELLA]   (la stessa cache della build)
"""
import argparse
import base64
import hashlib
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
import costruisci_pacchetto as cp  # noqa: E402
import motore  # noqa: E402

OUT = RADICE / "prove" / "_output" / "installer_mac"
CACHE = RADICE / "prove" / "_output" / "cache_linux"
PBS_LINUX = f"cpython-{cp.PYTHON_MAC}+{cp.PBS_RILASCIO}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
LIBRERIE_LINUX = ["numpy", "pillow", "requests", "certifi", "charset-normalizer", "idna", "urllib3", "pyperclip"]

risultati = []


def verifica(nome, ok, dettaglio=""):
    risultati.append(bool(ok))
    print(("OK   " if ok else "FAIL ") + nome + ("" if ok or not dettaglio else f"\n     -> {dettaglio}"))


def python_linux(cache_build: Path) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.prepara_python_mac(cache_build)  # scarica anche l'elenco SHA256SUMS del rilascio
    somme = cache_build / "mac" / "runtime" / f"SHA256SUMS-{cp.PBS_RILASCIO}"
    attesa = next(r.split()[0] for r in somme.read_text().splitlines() if r.endswith("  " + PBS_LINUX))
    f = CACHE / PBS_LINUX
    if not f.exists():
        print("Scarico il Python standalone per Linux (solo per la prova)...")
        with urllib.request.urlopen(cp.URL_PBS + PBS_LINUX.replace("+", "%2B"), timeout=300) as r, open(f, "wb") as d:
            shutil.copyfileobj(r, d)
    assert hashlib.sha256(f.read_bytes()).hexdigest() == attesa, "impronta del Python per Linux sbagliata"
    return f


def librerie_linux() -> list[Path]:
    cartella = CACHE / "wheels"
    cartella.mkdir(parents=True, exist_ok=True)
    versioni = dict(r.split("==") for r in (RADICE / "mac" / "requisiti-mac.txt").read_text().splitlines()
                    if "==" in r and not r.startswith("#"))
    voluti = [f"{n}=={versioni[n]}" for n in LIBRERIE_LINUX]
    if len(list(cartella.glob("*.whl"))) < len(voluti):
        subprocess.run([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                        "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313", "--abi", "abi3",
                        "--abi", "none", "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_17_x86_64",
                        "--platform", "manylinux_2_28_x86_64", "--platform", "any", "-d", str(cartella), *voluti],
                       check=True)
    return sorted(cartella.glob("*.whl"))


def wheel_finto(destinazione: Path) -> Path:
    """Quartz, AppKit, ApplicationServices (solo Mac) e pystray, sounddevice (che su Linux senza schermo/audio non si caricano)."""
    nome = "moduli_mac_finti-1.0"
    w = destinazione / f"{nome}-py3-none-any.whl"
    file = {m: "" for m in ("Quartz.py", "AppKit.py", "ApplicationServices.py", "pystray.py", "sounddevice.py")}
    file[f"{nome}.dist-info/METADATA"] = "Metadata-Version: 2.1\nName: moduli-mac-finti\nVersion: 1.0\n"
    file[f"{nome}.dist-info/WHEEL"] = "Wheel-Version: 1.0\nGenerator: prova\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record = []
    with zipfile.ZipFile(w, "w") as z:
        for n, c in file.items():
            z.writestr(n, c)
            h = base64.urlsafe_b64encode(hashlib.sha256(c.encode()).digest()).rstrip(b"=").decode()
            record.append(f"{n},sha256={h},{len(c.encode())}")
        record.append(f"{nome}.dist-info/RECORD,,")
        z.writestr(f"{nome}.dist-info/RECORD", "\n".join(record) + "\n")
    return w


def comandi_finti(cartella: Path, registro: Path) -> None:
    cartella.mkdir(parents=True)
    script = {
        "uname": 'case "$1" in -s) echo Darwin;; -m) echo x86_64;; *) echo Darwin;; esac',
        "sw_vers": "echo 14.6.1",
        "osascript": f'echo "osascript $*" >> "{registro}"\ncase "$*" in *"default answer"*) echo "  gsk_ChiaveDiProvaPerIlMac1234 ";; esac',
        "curl": f'echo "curl $*" >> "{registro}"\necho 200',
        **{c: f'echo "{c} $*" >> "{registro}"' for c in ("xattr", "open", "clear", "tccutil")},
        "pkill": f'echo "pkill $*" >> "{registro}"\nexit 1',  # come su Mac quando Dettami non è aperta
    }
    for nome, corpo in script.items():
        f = cartella / nome
        f.write_text("#!/bin/sh\n" + corpo + "\n")
        f.chmod(0o755)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=RADICE / ".cache_pacchetto", help="cache di costruisci_pacchetto.py")
    cache_build = ap.parse_args().cache
    pacchetto = RADICE / "dist" / f"Dettami-Mac-{motore.VERSIONE}"
    if not pacchetto.exists():
        sys.exit(f"Manca {pacchetto}: lancia prima  python costruisci_pacchetto.py")
    shutil.rmtree(OUT, ignore_errors=True)
    prova = OUT / pacchetto.name
    shutil.copytree(pacchetto, prova)
    runtime = prova / "setup" / "runtime"
    for f in runtime.iterdir():
        f.unlink()
    shutil.copy(python_linux(cache_build), runtime / cp.RUNTIME_MAC)  # stesso nome di quello per Mac
    ruote = prova / "setup" / "wheels"
    shutil.rmtree(ruote)
    ruote.mkdir()
    for w in librerie_linux():
        shutil.copy(w, ruote)
    wheel_finto(ruote)
    righe = ["# prova su Linux"]
    for f in sorted(ruote.glob("*.whl")):
        n, v = f.name.split("-")[:2]
        righe.append(f"{n.replace('_', '-')}=={v} --hash=sha256:{hashlib.sha256(f.read_bytes()).hexdigest()}")
    (prova / "setup" / "app" / "requisiti-mac.txt").write_text("\n".join(righe) + "\n")

    casa, registro = OUT / "home", OUT / "comandi.log"
    casa.mkdir()
    comandi_finti(OUT / "bin", registro)
    ambiente = {**os.environ, "HOME": str(casa), "PATH": f"{OUT / 'bin'}:{os.environ['PATH']}"}
    app = casa / "Applications" / "Dettami.app"
    dati = casa / "Library" / "Application Support" / "Dettami"
    agente = casa / "Library" / "LaunchAgents" / "io.github.albykeg.dettami.plist"

    def installa():
        r = subprocess.run(["bash", str(prova / "Installa Dettami.command")], env=ambiente, cwd=prova,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

    codice, uscita = installa()
    verifica("prima installazione riuscita", codice == 0 and "Fatto: Dettami" in uscita, uscita[-800:])
    verifica("Dettami.app: Python come eseguibile, avvio, Info.plist, icona",
             os.access(app / "Contents" / "MacOS" / "Dettami", os.X_OK)
             and (app / "Contents" / "lib" / "python3.13" / "site-packages" / "sitecustomize.py").exists()
             and plistlib.loads((app / "Contents" / "Info.plist").read_bytes())["CFBundleIdentifier"] == "io.github.albykeg.dettami"
             and (app / "Contents" / "Resources" / "Dettami.icns").exists())
    verifica("dati: app, config Mac (Option destro), versione del Python, disinstallazione",
             (dati / "dettami.py").exists() and 'dettatura = "alt_r"' in (dati / "config.toml").read_text()
             and (dati / "versione-runtime.txt").read_text().strip() == cp.RUNTIME_MAC
             and os.access(dati / "disinstalla.command", os.X_OK))
    verifica("chiave Groq ripulita e salvata solo per l'utente",
             (dati / ".env").read_text() == "GROQ_API_KEY=gsk_ChiaveDiProvaPerIlMac1234\n"
             and stat.S_IMODE((dati / ".env").stat().st_mode) == 0o600)
    verifica("avvio al login impostato", plistlib.loads(agente.read_bytes())["RunAtLoad"] is True)
    log = registro.read_text()
    verifica("apre la pagina delle chiavi e poi Dettami", "open https://console.groq.com/keys" in log
             and f"open {app}" in log and "xattr -dr com.apple.quarantine" in log)
    r = subprocess.run([str(app / "Contents" / "MacOS" / "Dettami")], env=ambiente, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    verifica("doppio clic sull'app: Python passa a dettami.py (qui su Linux dice che è per Windows e Mac)",
             "pensata per Windows e Mac" in r.stdout, r.stdout + r.stderr)

    (dati / "config.toml").write_text((dati / "config.toml").read_text() + "\n# mia modifica\n")
    registro.write_text("")
    codice, uscita = installa()
    verifica("reinstallazione: tiene config e chiave, non richiede la chiave", codice == 0
             and (dati / "config.toml").read_text().endswith("# mia modifica\n")
             and "Chiave Groq già impostata" in uscita and "default answer" not in registro.read_text(), uscita[-500:])
    verifica("nessuna cartella temporanea lasciata", [p.name for p in (casa / "Applications").iterdir()] == ["Dettami.app"])

    subprocess.run(["bash", str(prova / "Disinstalla Dettami.command")], env=ambiente, stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=60)
    verifica("disinstallazione: via app, dati e avvio al login",
             not app.exists() and not dati.exists() and not agente.exists())
    print(f"\n{sum(risultati)}/{len(risultati)} verifiche superate (installer Mac)")
    sys.exit(0 if all(risultati) else 1)


if __name__ == "__main__":
    main()
