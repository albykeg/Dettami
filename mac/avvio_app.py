"""
Avvio di Dettami.app su macOS. L'installer lo copia dentro l'app come sitecustomize.py.

macOS apre l'app eseguendo Contents/MacOS/Dettami, che è Python stesso, senza argomenti.
Solo in quel caso questo file trasforma il processo (stesso PID, stessi permessi di
Microfono, Accessibilità e Monitoraggio input) in "Dettami dettami.py <argomenti>".

Gli argomenti arrivano da argomenti-avvio.json, perché macOS non li passa a un'app
aperta dal Finder, dal Launchpad o all'accensione.
"""
import json
import os
import sys


_SEMPLICI = {"--avvio", "--riapri-dashboard"}


def _solo_argomenti_noti(letti) -> list:
    """Accetta solo gli argomenti che Dettami conosce: il file non può far eseguire altro."""
    if not isinstance(letti, list):
        return []
    buoni, i = [], 0
    while i < len(letti):
        a = letti[i]
        if a in _SEMPLICI:
            buoni.append(a)
        elif (a == "--dopo-aggiornamento" and i + 1 < len(letti) and isinstance(letti[i + 1], str)
              and 0 < len(letti[i + 1]) < 20 and all(c.isdigit() or c == "." for c in letti[i + 1])):
            buoni += [a, letti[i + 1]]
            i += 1
        i += 1
    return buoni


def _avvia_dettami():
    try:
        if len(getattr(sys, "orig_argv", ("", ""))) != 1 or sys.flags.isolated:
            return  # Python usato per altro (pip, aggiornamenti, prove): non toccare niente
        exe = os.path.realpath(sys.executable)
        if os.path.basename(exe) != "Dettami" or "/Contents/MacOS/" not in exe:
            return
        dati = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Dettami")
        script = os.path.join(dati, "dettami.py")
        argomenti = []
        richiesta = os.path.join(dati, "argomenti-avvio.json")
        try:
            with open(richiesta, encoding="utf-8") as f:
                letti = json.load(f)
            os.remove(richiesta)
            argomenti = _solo_argomenti_noti(letti)
        except (OSError, ValueError):
            pass
        if not os.path.isfile(script):
            os.execv("/usr/bin/osascript", [
                "osascript", "-e",
                'display alert "Dettami non è installata del tutto" '
                'message "Apri di nuovo «Installa Dettami» dalla cartella che hai scaricato." as critical'])
        os.chdir(dati)
        os.execv(exe, [exe, script, *argomenti])
    except Exception:  # in caso di problemi Python parte normalmente (e si chiude subito)
        pass


_avvia_dettami()
