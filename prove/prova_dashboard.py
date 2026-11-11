"""Prova della dashboard: server reale + dati finti + Chromium headless."""
import json
import random
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent   # cartella del progetto
sys.path.insert(0, str(RADICE))
import dashboard  # noqa: E402
import motore  # noqa: E402

OUT = RADICE / "prove" / "_output" / "dashboard"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(7)

FRASI = [
    ("whatsapp", "chat", "Ciao Marco, arrivo verso le sei e mezza, tienimi un posto"),
    ("outlook", "email", "Buongiorno Giulia,\n\nle confermo la riunione di giovedì alle 10:30. Porterò il preventivo aggiornato con le modifiche richieste.\n\nCordiali saluti"),
    ("claude", "prompt", "Crea uno script Python che:\n- legga il file CSV delle prenotazioni\n- calcoli l'occupazione mensile\n- esporti un grafico in PNG"),
    ("winword", "normale", "Il preventivo comprende la sostituzione dei dischi freno anteriori e il tagliando dei 20.000 km."),
    ("chrome", "normale", "Vorrei sapere se la camera è disponibile dal 14 al 17 novembre per due persone."),
    ("telegram", "chat", "Perfetto, ci sentiamo domani mattina"),
]
voci = []
oggi = datetime(2026, 10, 28, 16, 0)
for giorni_fa in range(13, -1, -1):
    n = 0 if giorni_fa in (6, 7) else random.randint(2, 9)
    for _ in range(n):
        app, stile, testo = random.choice(FRASI)
        ts = (oggi - timedelta(days=giorni_fa)).replace(hour=random.randint(8, 15), minute=random.randint(0, 59))
        parole = len(testo.split())
        voci.append({"ts": ts.isoformat(timespec="seconds"), "app": app, "stile": stile, "testo": testo,
                     "grezzo": "ehm allora " + testo.lower().replace(",", "") if random.random() < .6 else "",
                     "parole": parole, "secondi_audio": round(parole / 2.3, 1), "t_elaborazione": 1.1,
                     "tradotto": False})
voci.sort(key=lambda v: v["ts"])
cfg = motore.carica_config()


class Finto:
    def __init__(self):
        self.cfg = cfg
        self.salvati = []
        self.contatore = 3

    def stato(self):
        return {"stato": "pronto", "tasto_nome": "Ctrl destro", "versione": motore.VERSIONE,
                "chiave_presente": True, "contatore": self.contatore, "parole_oggi": 0,
                "aggiornamento": self.agg["disponibile"] if not self.agg["richiede_installer"] else None,
                "aggiornamento_in_corso": self.agg["stato"] == "installazione"}

    def statistiche(self):
        st = motore.statistiche(voci, oggi)
        uso = {"whisper-large-v3-turbo": {"richieste": 41, "secondi_audio": 410},
               "openai/gpt-oss-120b": {"richieste": 38, "token": 41200}}
        quote = {"whisper-large-v3-turbo": {"rimaste": 1959, "limite": 2000},
                 "openai/gpt-oss-120b": {"rimaste": 962, "limite": 1000}}
        st["quota"] = motore.riepilogo_quota(cfg, quote, uso)
        return st

    def cronologia(self, q, limite):
        return motore.cerca_cronologia(voci, q, limite)

    def impostazioni(self):
        return {"valori": motore.valori_impostazioni(self.cfg),
                "opzioni": {"tasti": [{"valore": k, "nome": v} for k, v in motore.TASTI_AMMESSI.items()],
                            "lingue": [{"valore": k, "nome": v} for k, v in motore.LINGUE_PARLATE.items()],
                            "lingue_traduzione": [{"valore": x, "nome": x.capitalize()} for x in cfg["ai"]["lingue_traduzione"]],
                            "microfoni": [{"valore": "", "nome": "Predefinito di Windows"},
                                          {"valore": "Microfono (Realtek Audio)", "nome": "Microfono (Realtek Audio)"}]},
                "chiave": {"presente": True, "mascherata": "gsk_…a1B2"}, "avvio_automatico": True,
                "cartella": r"C:\Users\alberto\AppData\Local\Programs\Dettami", "versione": motore.VERSIONE,
                "esempio": {"detto": motore.ESEMPIO_DETTO, **motore.ESEMPI_LIVELLO}}

    def salva_impostazioni(self, dati):
        self.salvati.append(dati)
        motore.valida_impostazioni(dati, self.cfg)
        nuovi = motore.valida_impostazioni(dati, self.cfg)
        for sez, v in nuovi.items():
            self.cfg[sez].update(v)
        return {"valori": motore.valori_impostazioni(self.cfg)}

    def cancella_cronologia(self): pass
    def cambia_chiave(self): self.salvati.append("chiave")
    def anteprima_indicatore(self): self.salvati.append("anteprima")
    def avvio_automatico(self, a): return a
    def apri(self, cosa): self.salvati.append(("apri", cosa))
    agg = {"versione": motore.VERSIONE, "stato": "aggiornata", "ultimo_controllo": None, "errore": None,
           "disponibile": None, "note": [], "data": None, "richiede_installer": False, "saltata": False,
           "automatici": True, "controlla": True, "ultimo_aggiornamento": None,
           "progetto": "https://github.com/albykeg/dettami"}

    def stato_aggiornamenti(self):
        return dict(self.agg)

    def controlla_aggiornamenti(self, manuale=False):
        import time
        self.agg.update(stato="disponibile", ultimo_controllo=time.time(), disponibile="1.4.0",
                        note=["Riscrittura ancora più naturale", "Correzioni varie"], data="2026-11-20")
        return dict(self.agg)

    def installa_aggiornamento(self, manuale=False):
        self.salvati.append("installa")
        self.agg["stato"] = "installazione"

    def confronta_riscrittura(self, testo, stile):
        if not testo.strip():
            raise ValueError("Scrivi prima una frase da provare.")
        self.salvati.append(("confronta", testo, stile))
        out = {"fedele": testo.capitalize() + ".", "chiara": "Versione chiara.", "ottimizzata": "Versione ottimizzata."}
        return {"risultati": [{"livello": l, "testo": out[l], "errore": None, "secondi": 0.8} for l in motore.LIVELLI_RISCRITTURA],
                "attuale": motore.livello_riscrittura(self.cfg) if self.cfg["ai"]["attiva"] else "spenta"}

    def prova_microfono(self):
        return {"voce": True, "livello": 1840, "grezzo": "ehm prova uno due tre", "testo": "Prova uno, due, tre.",
                "t_trascrizione": 0.42, "t_ai": 0.61}


f = Finto()
srv = dashboard.ServerDashboard(f)
base = f"http://127.0.0.1:{srv.porta}"
esiti = []


def ok(nome, cond):
    esiti.append(cond)
    print(("OK   " if cond else "FAIL ") + nome)


def richiesta(percorso, token=None, host=None, dati=None):
    req = urllib.request.Request(base + percorso, data=json.dumps(dati).encode() if dati is not None else None)
    if token:
        req.add_header("X-Token", token)
    if host:
        req.add_header("Host", host)
    if dati is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ---- sicurezza del server
ok("pagina servita", richiesta("/")[0] == 200)
ok("API senza codice rifiutata", richiesta("/api/statistiche")[0] == 403)
ok("API con codice sbagliato rifiutata", richiesta("/api/statistiche", token="x" * 32)[0] == 403)
ok("Host estraneo rifiutato (DNS rebinding)", richiesta("/api/stato", token=srv.token, host="evil.com")[0] == 400)
ok("API con codice ok", richiesta("/api/stato", token=srv.token)[0] == 200)
ok("impostazione non valida -> 400", richiesta("/api/impostazioni", token=srv.token, dati={"tasto": "q"})[0] == 400)
ok("percorso sconosciuto -> 404", richiesta("/api/boh", token=srv.token)[0] == 404)

# ---- interfaccia
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    for schema in ("light", "dark"):
        ctx = b.new_context(viewport={"width": 1200, "height": 900}, color_scheme=schema, locale="it-IT",
                            permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        errori = []
        pg.on("console", lambda m: errori.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errori.append(str(e)))
        pg.goto(srv.url)
        pg.wait_for_selector("#quota .modello")
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(OUT / f"dash_panoramica_{schema}.png"), full_page=True)
        if schema == "light":
            ok("parole di oggi mostrate", pg.inner_text("#paroleOggi") != "0")
            ok("14 barre nell'onda", pg.locator("#barre .b").count() == 14)
            ok("5 righe di quota", pg.locator("#quota .modello").count() == 5)
            ok("stato 'Pronta'", pg.inner_text("#statoTesto") == "Pronta")
            pg.click("nav button[data-vista=cronologia]")
            pg.wait_for_selector("#lista .voci li")
            pg.screenshot(path=str(OUT / "dash_cronologia.png"), full_page=False)
            pg.fill("#cerca", "preventivo")
            pg.wait_for_timeout(500)
            testi = pg.locator("#lista .testo").all_inner_texts()
            ok("ricerca filtra", len(testi) > 0 and all("preventivo" in t.lower() for t in testi))
            pg.locator("#lista button:has-text('Copia')").first.click()
            ok("copia negli appunti", "preventivo" in pg.evaluate("navigator.clipboard.readText()").lower())
            pg.click("nav button[data-vista=dizionario]")
            pg.fill("#nuovaParola", "Acme S.r.l.")
            pg.click("#formParola button")
            pg.wait_for_timeout(300)
            ok("parola aggiunta e salvata", "Acme S.r.l." in pg.inner_text("#parole")
               and {"dizionario": cfg["personale"]["dizionario"]} in f.salvati)
            pg.click("#aggiungiScorciatoia")
            ins = pg.locator(".scorciatoia input")
            ins.nth(0).fill("la mia mail")
            ins.nth(1).fill("nome@esempio.it")
            ins.nth(1).dispatch_event("change")
            pg.wait_for_timeout(300)
            ok("scorciatoia salvata", cfg["personale"]["scorciatoie"] == {"la mia mail": "nome@esempio.it"})
            pg.screenshot(path=str(OUT / "dash_dizionario.png"))
            pg.click("nav button[data-vista=impostazioni]")
            pg.wait_for_selector("#i-tasto option", state="attached")
            pg.select_option("#i-tasto", "f8")
            pg.wait_for_timeout(300)
            ok("tasto cambiato", cfg["tasti"]["dettatura"] == "f8")
            ok("riassunto livello in impostazioni", pg.inner_text("#riassuntoLivello") == "Adesso: Chiara")
            pg.wait_for_selector("#aggVersione:not(:empty)")
            ok("versione e stato aggiornamenti", pg.inner_text("#aggVersione") == motore.VERSIONE
               and "primo controllo" in pg.inner_text("#aggStato") and pg.is_hidden("#aggDisponibile"))
            pg.click("#aggControlla")
            pg.wait_for_selector("#aggDisponibile:not([hidden])")
            ok("controllo manuale: novità della 1.4.0", "1.4.0" in pg.inner_text("#aggTitolo")
               and pg.locator("#aggNote li").count() == 2 and "da sola" in pg.inner_text("#aggSpiega"))
            pg.wait_for_selector("#avvisoAgg:not([hidden])", state="attached")
            ok("banner 'disponibile la versione' nella panoramica",
               "1.4.0" in pg.evaluate("document.querySelector('#avvisoAggTesto').textContent"))
            pg.click("#aggInstalla")
            pg.wait_for_timeout(600)
            ok("installa dalla dashboard", "installa" in f.salvati and "Sto aggiornando" in pg.inner_text("#aggStato")
               and pg.is_disabled("#aggInstalla"))
            pg.screenshot(path=str(OUT / "dash_aggiornamenti.png"), full_page=True)
            f.agg.update(stato="disponibile", richiede_installer=True)
            pg.click("#aggControlla"); pg.wait_for_timeout(300)
            f.agg["richiede_installer"] = True
            pg.evaluate("caricaAggiornamenti()"); pg.wait_for_timeout(300)
            pg.click("#aggInstalla"); pg.wait_for_timeout(300)
            ok("nuovo installer richiesto: apre la pagina di download", ("apri", "setup") in f.salvati)
            # pagina Riscrittura
            pg.click("[data-vai=riscrittura]")
            pg.wait_for_selector("#es-chiara:not(:empty)")
            ok("pagina Riscrittura con esempi e livello attuale", pg.is_visible("#livelli")
               and pg.inner_text("#es-ottimizzata") == motore.ESEMPI_LIVELLO["ottimizzata"]
               and pg.is_checked("#livelli input[value=chiara]") and "ottantina" in pg.inner_text("#esDetto"))
            pg.check("#livelli input[value=ottimizzata]"); pg.wait_for_timeout(300)
            ok("livello Ottimizzata salvato", cfg["ai"]["riscrittura"] == "ottimizzata" and cfg["ai"]["attiva"] is True)
            pg.check("#livelli input[value=spenta]"); pg.wait_for_timeout(300)
            ok("Solo trascrizione = AI spenta", cfg["ai"]["attiva"] is False)
            pg.click("#confronta"); pg.wait_for_timeout(200)
            ok("confronto senza testo: avviso, nessuna chiamata", not any(isinstance(x, tuple) and x[0] == "confronta" for x in f.salvati))
            pg.fill("#provaTesto", "allora volevo dirti che domani passo")
            pg.select_option("#provaStile", "email")
            pg.click("#confronta")
            pg.wait_for_selector("#risultati .risultato")
            ok("confronto: tre risultati, stile passato", pg.locator("#risultati .risultato").count() == 3
               and ("confronta", "allora volevo dirti che domani passo", "email") in f.salvati
               and "Versione chiara." in pg.inner_text("#risultati"))
            pg.locator("#risultati .risultato").nth(1).locator("button:has-text('Usa questo livello')").click()
            pg.wait_for_timeout(300)
            ok("'Usa questo livello' salva Chiara", cfg["ai"]["riscrittura"] == "chiara" and cfg["ai"]["attiva"] is True
               and pg.is_checked("#livelli input[value=chiara]")
               and "il livello che usi adesso" in pg.locator("#risultati .risultato").nth(1).inner_text())
            pg.screenshot(path=str(OUT / "dash_riscrittura.png"), full_page=True)
            pg.click("nav button[data-vista=impostazioni]")
            pg.click("#prova")
            pg.wait_for_selector("#esitoProva .testo")
            ok("prova microfono mostra il testo", "Prova uno" in pg.inner_text("#esitoProva"))
            pg.click("[data-azione=anteprima]")
            pg.wait_for_timeout(200)
            ok("anteprima indicatore richiesta", "anteprima" in f.salvati)
            pg.screenshot(path=str(OUT / "dash_impostazioni.png"), full_page=True)
            # schermo stretto
            pg.set_viewport_size({"width": 420, "height": 900})
            larghezze = []
            for v in ("riscrittura", "panoramica"):
                pg.click(f"nav button[data-vista={v}]")
                pg.wait_for_timeout(300)
                larghezze.append(pg.evaluate("document.documentElement.scrollWidth"))
                if v == "riscrittura":
                    pg.screenshot(path=str(OUT / "dash_riscrittura_mobile.png"), full_page=True)
            ok("nessuno scorrimento orizzontale su schermo stretto", max(larghezze) <= 420)
            pg.screenshot(path=str(OUT / "dash_mobile.png"), full_page=False)
        ok(f"nessun errore JavaScript ({schema})", not errori)
        if errori:
            print("   ", errori[:3])
        ctx.close()
    b.close()

srv.chiudi()
print(f"\n{sum(esiti)}/{len(esiti)} verifiche superate")
sys.exit(0 if all(esiti) else 1)  # codice d'uscita per la CI
