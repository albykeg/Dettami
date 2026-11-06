"""
Installa un aggiornamento di Dettami già scaricato e verificato (vedi aggiornamenti.py).

Gira come processo separato, da una copia temporanea, con la sola libreria standard:
  1. aspetta che l'app si chiuda;
  2. salva i file attuali in "versione-precedente";
  3. copia i nuovi file;
  4. riavvia l'app e aspetta che segnali di essere partita (avvio-ok.json);
  5. se non parte entro il tempo massimo, rimette i file di prima e riavvia la versione precedente.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ATTESA_CHIUSURA = 25     # secondi per lasciar chiudere la vecchia app
ATTESA_AVVIO = 45        # secondi entro cui la nuova app deve dire "sono partita"


def registra(app: Path, testo: str) -> None:
    try:
        with open(app / "aggiornamento.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {testo}\n")
    except OSError:
        pass


def processo_vivo(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102  # WAIT_TIMEOUT: ancora vivo
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # su Linux un processo terminato ma non ancora raccolto è uno "zombie"
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ")[-1][:1] != "Z"
    except OSError:
        return True


def aspetta_chiusura(pid: int, secondi: float) -> bool:
    fine = time.monotonic() + secondi
    while time.monotonic() < fine:
        if not processo_vivo(pid):
            return True
        time.sleep(0.2)
    return not processo_vivo(pid)


def copia_sicura(sorgente: Path, destinazione: Path) -> None:
    temporaneo = destinazione.with_name(destinazione.name + ".nuovo")
    shutil.copy2(sorgente, temporaneo)
    for tentativo in range(10):  # su Windows un antivirus può tenere il file aperto un attimo
        try:
            os.replace(temporaneo, destinazione)
            return
        except PermissionError:
            time.sleep(0.3 * (tentativo + 1))
    os.replace(temporaneo, destinazione)


def avvia_app(app: Path, python: str, *extra: str) -> subprocess.Popen:
    opzioni = {}
    if os.name == "nt":
        opzioni["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS, NEW_PROCESS_GROUP
    else:
        opzioni["start_new_session"] = True
    return subprocess.Popen([python, str(app / "dettami.py"), "--avvio", *extra],
                            cwd=str(app), close_fds=True, **opzioni)


def partita(app: Path, processo: subprocess.Popen, versione: str, secondi: float) -> tuple[bool, str]:
    segnale = app / "avvio-ok.json"
    fine = time.monotonic() + secondi
    while time.monotonic() < fine:
        try:
            dati = json.loads(segnale.read_text(encoding="utf-8"))
            if dati.get("versione") == versione and dati.get("pid") == processo.pid:
                return True, ""
        except (OSError, ValueError):
            pass
        codice = processo.poll()
        if codice is not None:
            return False, f"la nuova versione si è chiusa all'avvio (codice {codice})"
        time.sleep(0.3)
    return False, f"la nuova versione non è partita entro {int(secondi)} secondi"


def ripristina(app: Path, backup: Path, nuovi: list[str]) -> None:
    for f in backup.iterdir():
        if f.is_file() and f.name != "elenco.json":
            copia_sicura(f, app / f.name)
    for nome in nuovi:  # file che la versione precedente non aveva
        try:
            (app / nome).unlink()
        except FileNotFoundError:
            pass


def installa(app: Path, nuova: Path, pid: int, python: str, versione: str, precedente: str,
             riapri_dashboard: bool = False, attesa_avvio: float = ATTESA_AVVIO) -> bool:
    registra(app, f"Aggiornamento {precedente} -> {versione}: inizio")
    if not aspetta_chiusura(pid, ATTESA_CHIUSURA):
        registra(app, "L'app non si è chiusa: aggiornamento annullato")
        return False

    file_nuovi = sorted(f.name for f in nuova.iterdir() if f.is_file())
    backup = app / "versione-precedente"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir()
    mai_esistiti = []
    for nome in file_nuovi:
        attuale = app / nome
        if attuale.exists():
            shutil.copy2(attuale, backup / nome)
        else:
            mai_esistiti.append(nome)
    (backup / "elenco.json").write_text(json.dumps({"versione": precedente, "nuovi": mai_esistiti}), encoding="utf-8")

    extra = ["--dopo-aggiornamento", precedente]
    if riapri_dashboard:
        extra.append("--riapri-dashboard")
    try:
        for nome in file_nuovi:
            copia_sicura(nuova / nome, app / nome)
        (app / "avvio-ok.json").unlink(missing_ok=True)
        processo = avvia_app(app, python, *extra)
        ok, motivo = partita(app, processo, versione, attesa_avvio)
    except Exception as e:  # file bloccati, disco pieno...
        processo, ok, motivo = None, False, f"errore durante la copia: {e}"

    if ok:
        registra(app, f"Aggiornamento a {versione} riuscito")
        # via i file scaricati (la cartella _aggiornamento contiene solo roba temporanea)
        shutil.rmtree(nuova.parent if nuova.parent.name == "_aggiornamento" else nuova, ignore_errors=True)
        return True

    registra(app, f"Aggiornamento a {versione} non riuscito: {motivo}. Ripristino {precedente}")
    if processo is not None and processo.poll() is None:
        processo.kill()
        try:
            processo.wait(5)
        except subprocess.TimeoutExpired:
            pass
    ripristina(app, backup, mai_esistiti)
    (app / "aggiornamento-fallito.json").write_text(
        json.dumps({"versione": versione, "precedente": precedente, "motivo": motivo}, ensure_ascii=False),
        encoding="utf-8")
    try:
        avvia_app(app, python, *(["--riapri-dashboard"] if riapri_dashboard else []))
    except Exception as e:
        registra(app, f"Riavvio della versione precedente non riuscito: {e}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--nuova", required=True, type=Path)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--python", required=True)
    ap.add_argument("--versione", required=True)
    ap.add_argument("--precedente", required=True)
    ap.add_argument("--riapri-dashboard", action="store_true")
    a = ap.parse_args()
    try:
        return 0 if installa(a.app, a.nuova, a.pid, a.python, a.versione, a.precedente, a.riapri_dashboard) else 1
    except Exception as e:
        registra(a.app, f"Errore imprevisto: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
