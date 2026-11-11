"""
Banco di prova della riscrittura: passa una decina di frasi "dettate" nei tre livelli
(fedele, chiara, ottimizzata) con i prompt veri di motore.py e i modelli gratuiti di Groq,
poi mostra i risultati affiancati.

La chiave si legge dalla variabile d'ambiente GROQ_API_KEY (oppure dal .env del progetto,
come fa l'app). Nessuna chiave è scritta qui.

Uso:
    export GROQ_API_KEY=...                    # Windows PowerShell: $env:GROQ_API_KEY="..."
    python prove/confronta_riscrittura.py
    python prove/confronta_riscrittura.py --frasi 1,4,7 --livelli fedele,ottimizzata
    python prove/confronta_riscrittura.py --file mie_frasi.txt   # una frase per riga (stile:frase facoltativo)
    python prove/confronta_riscrittura.py --modello openai/gpt-oss-20b
    python prove/confronta_riscrittura.py --finto              # senza rete: controlla solo lo script

Risultati in prove/_output/riscrittura/: confronto.html (tabella affiancata), confronto.md e
confronto.json. Con 10 frasi e 3 livelli sono 30 richieste: ben dentro la quota gratuita.
"""
import argparse
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))

import motore  # noqa: E402

USCITA = RADICE / "prove" / "_output" / "riscrittura"

# (stile, testo come esce da Whisper): casi tipici di chi detta
FRASI = [
    ("normale", "allora ehm volevo dire che domani non ci sono perché devo portare la moto dal meccanico "
                "per il tagliando cioè quello dei ventimila chilometri e quindi niente ci vediamo giovedì"),
    ("chat", "ci vediamo alle cinque anzi no alle sei davanti al bar quello vicino alla stazione ok"),
    ("email", "buongiorno Marco ti scrivo per la fattura di ottobre praticamente l'importo è di "
              "milleduecentocinquanta euro più iva e la scadenza è il trenta novembre se hai domande "
              "scrivimi a alberto punto rossi chiocciola gmail punto com grazie a presto"),
    ("prompt", "scrivimi una funzione in python che legge un file csv e poi tipo filtra le righe dove la "
               "colonna prezzo è maggiore di cento e poi le salva in un altro file ah e deve gestire anche "
               "il caso in cui il file non esiste"),
    ("normale", "le cose da fare per l'appartamento sono primo cambiare le lenzuola secondo controllare che "
                "il wifi funzioni poi lasciare le chiavi nella cassetta e inoltre comprare il caffè per gli ospiti"),
    ("chat", "ma tu cosa ne pensi della nuova versione dell'app secondo me è più veloce no"),
    ("normale", "il cliente diciamo che vorrebbe un'automazione che cioè quando arriva una mail con un ordine "
                "la cosa la legge e la mette nel gestionale però non sempre perché a volte l'ordine è in pdf "
                "e quindi bisogna leggere il pdf insomma un casino ma si può fare"),
    ("email", "gentile signora Bianchi le confermo il check in per sabato quindici dalle quindici alle venti "
              "il codice della porta glielo mando il giorno prima nuovo paragrafo per qualsiasi cosa mi "
              "chiami al tre tre tre uno due tre quattro cinque sei sette cordiali saluti"),
    ("tecnico", "devo fare il push sul branch main però prima devo lanciare pytest e controllare che passi "
                "e poi aggiornare il file novità punto md con la versione uno punto quattro"),
    ("normale", "allora per il viaggio in Giappone pensavo di partire ad aprile perché c'è la fioritura dei "
                "ciliegi ehm però costa di più quindi forse maggio ma maggio c'è la golden week che è pieno "
                "di gente quindi boh forse aprile alla fine conviene comunque"),
]


class ClientFinto:
    """Risponde senza rete: serve solo a provare lo script (--finto)."""
    ultimo_modello = "finto"

    def rifinisci(self, sistema, grezzo, cfg, livello="chiara"):
        assert f"QUANTO RISCRIVERE: {livello.upper()[:5]}" in sistema
        testo = grezzo.replace("ehm ", "").replace("allora ", "")
        return f"[{livello}] {testo[:1].upper()}{testo[1:]}."


def leggi_frasi(percorso: Path) -> list[tuple[str, str]]:
    frasi = []
    for riga in percorso.read_text(encoding="utf-8-sig").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        stile, sep, testo = riga.partition(":")
        if sep and stile.strip() in ("normale", "chat", "email", "prompt", "tecnico"):
            frasi.append((stile.strip(), testo.strip()))
        else:
            frasi.append(("normale", riga))
    return frasi


def scegli(frasi, filtro: str):
    if not filtro:
        return list(enumerate(frasi, 1))
    numeri = {int(n) for n in filtro.split(",") if n.strip()}
    return [(i, f) for i, f in enumerate(frasi, 1) if i in numeri]


def esegui(client, cfg, frasi, livelli, pausa: float) -> list[dict]:
    risultati = []
    totale = len(frasi) * len(livelli)
    fatte = 0
    for n, (stile, grezzo) in frasi:
        voce = {"n": n, "stile": stile, "grezzo": grezzo, "livelli": {}}
        for livello in livelli:
            fatte += 1
            print(f"  [{fatte}/{totale}] frase {n} · {livello}…", end="", flush=True)
            t0 = time.perf_counter()
            testo, avviso = motore.riscrivi(client, cfg, grezzo, stile, livello=livello)
            secondi = time.perf_counter() - t0
            voce["livelli"][livello] = {
                "testo": testo, "avviso": avviso, "secondi": round(secondi, 2),
                "modello": getattr(client, "ultimo_modello", "") if avviso is None else "",
                "caratteri": len(testo),
            }
            print(f" {secondi:.1f}s" + (f"  ⚠ {avviso}" if avviso else ""))
            if pausa and fatte < totale:
                time.sleep(pausa)  # resta sotto il limite di richieste al minuto
        risultati.append(voce)
    return risultati


def stampa(risultati, livelli) -> None:
    for v in risultati:
        print(f"\n━━ Frase {v['n']} · stile {v['stile']} ━━")
        print(f"  DETTO        {v['grezzo']}")
        for livello in livelli:
            r = v["livelli"][livello]
            print(f"  {livello.upper():<12} {r['testo']}".replace("\n", "\n               "))


def scrivi_html(risultati, livelli, info: dict) -> str:
    def cella(testo):
        return html.escape(testo).replace("\n", "<br>")

    testata = "".join(f"<th>{html.escape(l.capitalize())}</th>" for l in livelli)
    righe = []
    for v in risultati:
        celle = []
        for livello in livelli:
            r = v["livelli"][livello]
            nota = (f'<div class="avviso">⚠ {cella(r["avviso"])}</div>' if r["avviso"]
                    else f'<div class="meta">{r["secondi"]} s · {r["caratteri"]} car. · {cella(r["modello"])}</div>')
            celle.append(f"<td>{cella(r['testo'])}{nota}</td>")
        righe.append(
            f'<tr><td class="detto"><div class="num">#{v["n"]} · {cella(v["stile"])}</div>'
            f'{cella(v["grezzo"])}<div class="meta">{len(v["grezzo"])} car.</div></td>{"".join(celle)}</tr>'
        )
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confronto riscrittura</title>
<style>
:root {{ --sfondo:#f7f7f5; --carta:#fff; --testo:#1d1d1f; --tenue:#6b6b70; --bordo:#e2e2e0; --detto:#f0efe9; --avviso:#b45309; }}
@media (prefers-color-scheme: dark) {{ :root {{ --sfondo:#141416; --carta:#1e1e21; --testo:#ececee; --tenue:#9a9aa0; --bordo:#33333a; --detto:#25252a; --avviso:#f59e0b; }} }}
body {{ margin:0; padding:24px 16px; background:var(--sfondo); color:var(--testo); font:15px/1.5 system-ui, sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }} p.info {{ color:var(--tenue); margin:0 0 20px; font-size:13px; }}
.tab {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; min-width:900px; background:var(--carta); }}
th, td {{ border:1px solid var(--bordo); padding:10px 12px; vertical-align:top; text-align:left; width:25%; }}
th {{ position:sticky; top:0; background:var(--carta); font-size:13px; text-transform:uppercase; letter-spacing:.04em; }}
td.detto {{ background:var(--detto); color:var(--tenue); font-style:italic; }}
.num {{ font-style:normal; font-weight:600; color:var(--testo); margin-bottom:4px; font-size:13px; }}
.meta {{ color:var(--tenue); font-size:12px; margin-top:8px; font-style:normal; }}
.avviso {{ color:var(--avviso); font-size:12px; margin-top:8px; }}
</style></head><body>
<h1>Confronto dei livelli di riscrittura</h1>
<p class="info">Dettami {html.escape(info["versione"])} · {html.escape(info["data"])} · modelli: {html.escape(", ".join(info["modelli"]))}</p>
<div class="tab"><table><thead><tr><th>Detto (trascrizione)</th>{testata}</tr></thead>
<tbody>{"".join(righe)}</tbody></table></div>
</body></html>
"""


def scrivi_md(risultati, livelli, info: dict) -> str:
    def cella(testo):
        return testo.replace("|", "\\|").replace("\n", "<br>")

    righe = [f"# Confronto riscrittura · Dettami {info['versione']} · {info['data']}", "",
             f"Modelli: {', '.join(info['modelli'])}", "",
             "| # | Detto | " + " | ".join(l.capitalize() for l in livelli) + " |",
             "|---|---|" + "---|" * len(livelli)]
    for v in risultati:
        celle = [cella(v["livelli"][l]["testo"]) + (" ⚠" if v["livelli"][l]["avviso"] else "") for l in livelli]
        righe.append(f"| {v['n']} ({v['stile']}) | {cella(v['grezzo'])} | " + " | ".join(celle) + " |")
    return "\n".join(righe) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Confronta i tre livelli di riscrittura di Dettami.")
    ap.add_argument("--frasi", default="", help="numeri delle frasi da usare, es. 1,3,5 (predefinito: tutte)")
    ap.add_argument("--file", type=Path, help="file con le tue frasi, una per riga (facoltativo 'stile: frase')")
    ap.add_argument("--livelli", default=",".join(motore.LIVELLI_RISCRITTURA),
                    help="livelli da confrontare (predefinito: fedele,chiara,ottimizzata)")
    ap.add_argument("--modello", default="", help="usa solo questo modello (niente riserva su altri)")
    ap.add_argument("--pausa", type=float, default=2.0, help="secondi tra una richiesta e l'altra (predefinito 2)")
    ap.add_argument("--finto", action="store_true", help="niente rete: risposte finte, per provare lo script")
    a = ap.parse_args()

    livelli = [l.strip() for l in a.livelli.split(",") if l.strip()]
    sbagliati = [l for l in livelli if l not in motore.LIVELLI_RISCRITTURA]
    if sbagliati or not livelli:
        print(f"Livelli non validi: {', '.join(sbagliati) or '(nessuno)'}. "
              f"Usa: {', '.join(motore.LIVELLI_RISCRITTURA)}")
        return 2

    frasi = scegli(leggi_frasi(a.file) if a.file else FRASI, a.frasi)
    if not frasi:
        print("Nessuna frase da provare.")
        return 2

    cfg = motore.carica_config()
    if a.modello:
        cfg["ai"]["modelli"] = [a.modello]

    if a.finto:
        client, pausa = ClientFinto(), 0.0
    else:
        chiave = motore.leggi_api_key()
        if not chiave:
            print("Manca la chiave Groq. Impostala prima di lanciare lo script:\n"
                  "  macOS/Linux:  export GROQ_API_KEY=la_tua_chiave\n"
                  "  Windows:      $env:GROQ_API_KEY=\"la_tua_chiave\"\n"
                  "La chiave gratuita si crea su https://console.groq.com/keys")
            return 2
        client, pausa = motore.ClientAI(cfg, chiave), a.pausa
        ok, msg = client.verifica_chiave()
        if not ok:
            print(f"Chiave Groq non utilizzabile: {msg}")
            return 2

    print(f"Confronto di {len(frasi)} frasi × {len(livelli)} livelli con {', '.join(cfg['ai']['modelli'])}")
    try:
        risultati = esegui(client, cfg, frasi, livelli, pausa)
    except motore.ErroreAPI as e:
        print(f"\nInterrotto: {e}")
        return 1
    stampa(risultati, livelli)

    info = {"versione": motore.VERSIONE, "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "modelli": ["finto"] if a.finto else cfg["ai"]["modelli"]}
    USCITA.mkdir(parents=True, exist_ok=True)
    (USCITA / "confronto.html").write_text(scrivi_html(risultati, livelli, info), encoding="utf-8")
    (USCITA / "confronto.md").write_text(scrivi_md(risultati, livelli, info), encoding="utf-8")
    (USCITA / "confronto.json").write_text(
        json.dumps({"info": info, "risultati": risultati}, ensure_ascii=False, indent=2), encoding="utf-8")

    avvisi = sum(1 for v in risultati for r in v["livelli"].values() if r["avviso"])
    print(f"\nFatto. Confronto affiancato: {USCITA / 'confronto.html'}")
    if avvisi:
        print(f"Attenzione: {avvisi} risposte non usate (testo originale al loro posto), vedi ⚠ nel confronto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
