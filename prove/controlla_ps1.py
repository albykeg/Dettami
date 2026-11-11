"""Controllo strutturale approssimato di script PowerShell: stringhe, commenti, bilanciamento () {} []."""
import sys
from pathlib import Path


def controlla(testo: str) -> list[str]:
    errori, pila = [], []
    i, riga, n = 0, 1, len(testo)
    coppie = {")": "(", "}": "{", "]": "["}
    modo = "codice"  # codice | sq (') | dq (") | commento_blocco
    dq_pila = []      # per $( ... ) dentro stringhe doppie
    while i < n:
        c = testo[i]
        if c == "\n":
            riga += 1
        if modo == "codice":
            if c == "#":
                while i < n and testo[i] != "\n":
                    i += 1
                continue
            if testo.startswith("<#", i):
                modo = "commento_blocco"; i += 2; continue
            if c == "'":
                modo = "sq"
            elif c == '"':
                modo = "dq"
            elif c == "`":
                i += 2; continue
            elif c in "({[":
                pila.append((c, riga))
            elif c in ")}]":
                if not pila or pila[-1][0] != coppie[c]:
                    errori.append(f"riga {riga}: '{c}' senza apertura corrispondente")
                else:
                    pila.pop()
                    if c == ")" and dq_pila and dq_pila[-1] == len(pila):
                        dq_pila.pop(); modo = "dq"
        elif modo == "commento_blocco":
            if testo.startswith("#>", i):
                modo = "codice"; i += 2; continue
        elif modo == "sq":
            if c == "'":
                if i + 1 < n and testo[i + 1] == "'":
                    i += 2; continue
                modo = "codice"
        elif modo == "dq":
            if c == "`":
                i += 2; continue
            if testo.startswith("$(", i):
                pila.append(("(", riga)); dq_pila.append(len(pila) - 1); modo = "codice"; i += 2; continue
            if c == '"':
                if i + 1 < n and testo[i + 1] == '"':
                    i += 2; continue
                modo = "codice"
        i += 1
    if modo in ("sq", "dq"):
        errori.append(f"stringa non chiusa (fine file, modo {modo})")
    for c, r in pila:
        errori.append(f"riga {r}: '{c}' non chiusa")
    return errori


ok = True
for f in sys.argv[1:]:
    e = controlla(Path(f).read_text(encoding="utf-8-sig"))
    print(("OK   " if not e else "ERR  ") + f)
    for x in e:
        print("     ", x)
    ok &= not e
sys.exit(0 if ok else 1)
