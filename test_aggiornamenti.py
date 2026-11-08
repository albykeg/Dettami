"""Test degli aggiornamenti automatici: python -m pytest test_aggiornamenti.py -q"""
import hashlib
import http.server
import json
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

import aggiorna
import aggiornamenti as ag

QUI = Path(__file__).resolve().parent


# ---------------------------------------------------------------- chiave di prova

@pytest.fixture(scope="module")
def chiavi():
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    k = crypto.generate_private_key(public_exponent=65537, key_size=2048)
    n = k.private_numbers()
    return k, {"n": n.public_numbers.n, "e": 65537, "d": n.d}


def test_firma_compatibile_con_cryptography(chiavi):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    k, priv = chiavi
    pub = {"n": priv["n"], "e": priv["e"]}
    dati = b"manifest di prova \xe2\x82\xac"
    # firmato da noi -> verificato da cryptography
    k.public_key().verify(ag.firma(dati, priv), dati, padding.PKCS1v15(), hashes.SHA256())
    # firmato da cryptography -> verificato da noi
    assert ag.verifica_firma(dati, k.sign(dati, padding.PKCS1v15(), hashes.SHA256()), pub)


def test_firma_rifiuta_manomissioni(chiavi):
    _, priv = chiavi
    pub = {"n": priv["n"], "e": priv["e"]}
    dati = b'{"versione": "1.3.1"}'
    s = ag.firma(dati, priv)
    assert ag.verifica_firma(dati, s, pub)
    assert not ag.verifica_firma(dati + b" ", s, pub)
    assert not ag.verifica_firma(dati, s[:-1], pub)
    assert not ag.verifica_firma(dati, bytes(len(s)), pub)
    assert not ag.verifica_firma(dati, b"\xff" * len(s), pub)  # valore >= n
    s2 = bytearray(s); s2[10] ^= 1
    assert not ag.verifica_firma(dati, bytes(s2), pub)
    assert not ag.verifica_firma(dati, s)  # firmata con un'altra chiave: rifiutata da quella vera


def test_chiave_pubblica_vera_corrisponde_alla_privata():
    p = QUI / ".chiave" / "chiave-firma-dettami.json"
    if not p.exists():
        pytest.skip("chiave privata non presente su questo computer")
    priv = ag.leggi_chiave_privata(p)
    assert priv["n"] == ag.CHIAVE_PUBBLICA["n"] and ag.CHIAVE_PUBBLICA["n"].bit_length() == 3072
    assert ag.verifica_firma(b"x", ag.firma(b"x", priv))


def test_versioni():
    assert ag.piu_nuova("1.3.1", "1.3.0") and ag.piu_nuova("1.10.0", "1.9.9") and ag.piu_nuova("2.0", "1.99.99")
    assert not ag.piu_nuova("1.3.0", "1.3.0") and not ag.piu_nuova("1.2.9", "1.3") and not ag.piu_nuova("1.3", "1.3.0")
    for brutta in ("", "1", "1.x", "v1.2", "1.2.3.4.5", None):
        with pytest.raises(ValueError):
            ag.versione_tupla(brutta)


def test_impronta_requisiti_ignora_a_capo_e_ordine():
    a = ag.impronta_requisiti("numpy==2.3\r\nrequests==2.32\r\n")
    assert a == ag.impronta_requisiti("requests==2.32\n\n# commento\nnumpy==2.3")
    assert a != ag.impronta_requisiti("numpy==2.4\nrequests==2.32")


# ---------------------------------------------------------------- pacchetto e server finti

APP_V1 = {
    "dettami.py": "print('app')\n", "motore.py": "VERSIONE = '1.3.0'\n", "aggiorna.py": "x = 1\n",
    "aggiornamenti.py": "y = 2\n", "versione.txt": "1.3.0\n", "icona.ico": "ICO", "LEGGIMI.md": "# Leggimi\n",
}


def crea_zip(percorso: Path, file: dict) -> bytes:
    with zipfile.ZipFile(percorso, "w") as z:
        for nome, contenuto in file.items():
            z.writestr(nome, contenuto)
    return percorso.read_bytes()


def manifest_per(versione: str, dati_zip: bytes, url: str, **extra) -> dict:
    return {"app": "dettami", "versione": versione, "data": "2026-11-06", "note": ["Novità"],
            "pacchetto": {"url": url, "sha256": hashlib.sha256(dati_zip).hexdigest(), "dimensione": len(dati_zip)},
            "runtime": "python-3.14.10-win64.zip", "requisiti_sha256": ag.impronta_requisiti("numpy==1\n"), **extra}


@pytest.fixture()
def server(tmp_path):
    radice = tmp_path / "web"
    radice.mkdir()

    class G(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(radice), **k)

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), G)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield radice, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def pubblica_finto(radice: Path, base: str, versione: str, file: dict, priv: dict, **extra) -> dict:
    nome = f"dettami-app-{versione}.zip"
    dati = crea_zip(radice / nome, {**file, "versione.txt": versione + "\n"})
    m = manifest_per(versione, dati, f"{base}/{nome}".replace("http://", "https://"), **extra)
    grezzo = json.dumps(m).encode()
    (radice / "manifest.json").write_bytes(grezzo)
    (radice / "manifest.sig").write_bytes(ag.firma(grezzo, priv))
    return m


class SessioneHttpLocale:
    """Il pacchetto vero è su https: qui lo serviamo in http dal server locale."""
    def __init__(self):
        import requests
        self.s = requests.Session()

    def get(self, url, **kw):
        return self.s.get(url.replace("https://127.0.0.1", "http://127.0.0.1"), **kw)


def test_controlla_scarica_e_prepara(server, chiavi, tmp_path):
    radice, base = server
    _, priv = chiavi
    pub = {"n": priv["n"], "e": priv["e"]}
    pubblica_finto(radice, base, "1.3.1", APP_V1, priv)
    sess = SessioneHttpLocale()
    m = ag.controlla("1.3.0", f"{base}/manifest.json", sess, pub)
    assert m and m["versione"] == "1.3.1"
    assert ag.controlla("1.3.1", f"{base}/manifest.json", sess, pub) is None   # già aggiornata
    assert ag.controlla("1.4.0", f"{base}/manifest.json", sess, pub) is None   # mai tornare indietro
    z = ag.scarica(m, tmp_path / "giu", sess)
    nomi = ag.prepara(z, tmp_path / "nuova", "1.3.1")
    assert "dettami.py" in nomi and (tmp_path / "nuova" / "versione.txt").read_text().strip() == "1.3.1"


def test_manifest_manomesso_rifiutato(server, chiavi):
    radice, base = server
    _, priv = chiavi
    pub = {"n": priv["n"], "e": priv["e"]}
    pubblica_finto(radice, base, "1.3.1", APP_V1, priv)
    (radice / "manifest.json").write_bytes((radice / "manifest.json").read_bytes().replace(b"1.3.1", b"9.9.9"))
    with pytest.raises(ag.ErroreAggiornamento, match="Firma"):
        ag.controlla("1.3.0", f"{base}/manifest.json", SessioneHttpLocale(), pub)


def test_pacchetto_manomesso_rifiutato(server, chiavi, tmp_path):
    radice, base = server
    _, priv = chiavi
    m = pubblica_finto(radice, base, "1.3.1", APP_V1, priv)
    crea_zip(radice / "dettami-app-1.3.1.zip", {**APP_V1, "dettami.py": "import os  # cattivo\n",
                                                  "versione.txt": "1.3.1"})
    with pytest.raises(ag.ErroreAggiornamento, match="non corrisponde"):
        ag.scarica(m, tmp_path / "giu", SessioneHttpLocale())


def test_nessuna_versione_pubblicata(server):
    _, base = server
    with pytest.raises(ag.ErroreAggiornamento, match="Nessuna versione"):
        ag.controlla("1.3.0", f"{base}/manifest.json", SessioneHttpLocale())


@pytest.mark.parametrize("extra,messaggio", [
    ({"../evil.py": "x"}, "non ammesso"),
    ({"sub/x.py": "x"}, "non ammesso"),
    ({"config.toml": "x"}, "non ammesso"),
    ({"Config.toml": "x"}, "non ammesso"),
    ({"nul.txt": "x"}, "non ammesso"),
    ({"Motore.py": "x = 1\n"}, "ripetuto"),
    ({"virus.exe": "x"}, "non ammesso"),
    ({"rotto.py": "def (:\n"}, "Errore nel codice"),
])
def test_prepara_rifiuta_pacchetti_pericolosi(tmp_path, extra, messaggio):
    z = tmp_path / "p.zip"
    crea_zip(z, {**APP_V1, **extra})
    with pytest.raises(ag.ErroreAggiornamento, match=messaggio):
        ag.prepara(z, tmp_path / "nuova", "1.3.0")


def test_prepara_controlla_completezza_e_versione(tmp_path):
    z = tmp_path / "p.zip"
    crea_zip(z, {k: v for k, v in APP_V1.items() if k != "motore.py"})
    with pytest.raises(ag.ErroreAggiornamento, match="mancano motore.py"):
        ag.prepara(z, tmp_path / "n", "1.3.0")
    crea_zip(z, APP_V1)
    with pytest.raises(ag.ErroreAggiornamento, match="versione"):
        ag.prepara(z, tmp_path / "n", "1.3.1")


def test_richiede_installer(tmp_path):
    m = manifest_per("1.3.1", b"x", "https://x")
    (tmp_path / "python").mkdir()
    (tmp_path / "python" / "versione-runtime.txt").write_text("python-3.14.10-win64.zip\n")
    (tmp_path / "requisiti-windows.txt").write_text("numpy==1\r\n")
    assert not ag.richiede_installer(m, tmp_path)
    (tmp_path / "requisiti-windows.txt").write_text("numpy==2\n")
    assert ag.richiede_installer(m, tmp_path)
    (tmp_path / "requisiti-windows.txt").write_text("numpy==1\n")
    (tmp_path / "python" / "versione-runtime.txt").write_text("python-3.15.0-win64.zip")
    assert ag.richiede_installer(m, tmp_path)
    assert ag.richiede_installer({**m, "richiede_installer": True}, tmp_path / "vuota")


# ---------------------------------------------------------------- installazione vera con rollback

APP_FINTA = """import json, os, sys, time
from pathlib import Path
qui = Path(__file__).resolve().parent
v = (qui / "versione.txt").read_text().strip()
with open(qui / "avvii.log", "a") as f:
    f.write(v + " " + " ".join(sys.argv[1:]) + "\\n")
{comportamento}
"""
PARTE = APP_FINTA.format(comportamento='(qui / "avvio-ok.json").write_text(json.dumps({"versione": v, "pid": os.getpid()}))\ntime.sleep(20)')
SI_ROMPE = APP_FINTA.format(comportamento="raise SystemExit(3)")
SI_BLOCCA = APP_FINTA.format(comportamento="time.sleep(60)")


def prepara_cartelle(tmp_path, nuova_app: str):
    app = tmp_path / "Dettami"
    app.mkdir()
    (app / "dettami.py").write_text(PARTE)
    (app / "versione.txt").write_text("1.3.0\n")
    (app / "motore.py").write_text("vecchio\n")
    (app / "config.toml").write_text("mio = true\n")
    nuova = tmp_path / "_aggiornamento" / "nuova"
    nuova.mkdir(parents=True)
    (nuova / "dettami.py").write_text(nuova_app)
    (nuova / "versione.txt").write_text("1.3.1\n")
    (nuova / "motore.py").write_text("nuovo\n")
    (nuova / "file_nuovo.py").write_text("x = 1\n")
    vecchia_app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.6)"])
    return app, nuova, vecchia_app


def termina_figli(app: Path):
    """Chiude le app finte rimaste vive (lanciate staccate da aggiorna.py)."""
    try:
        dati = json.loads((app / "avvio-ok.json").read_text())
        import os
        import signal
        os.kill(dati["pid"], signal.SIGTERM)
    except Exception:
        pass


def test_installazione_riuscita(tmp_path):
    app, nuova, vecchia = prepara_cartelle(tmp_path, PARTE)
    try:
        ok = aggiorna.installa(app, nuova, vecchia.pid, sys.executable, "1.3.1", "1.3.0", attesa_avvio=10)
        assert ok
        assert (app / "versione.txt").read_text().strip() == "1.3.1"
        assert (app / "motore.py").read_text() == "nuovo\n" and (app / "file_nuovo.py").exists()
        assert (app / "config.toml").read_text() == "mio = true\n"  # impostazioni intatte
        assert (app / "versione-precedente" / "motore.py").read_text() == "vecchio\n"
        assert "1.3.1 --avvio --dopo-aggiornamento 1.3.0" in (app / "avvii.log").read_text()
        assert not nuova.exists() and not (app / "aggiornamento-fallito.json").exists()
    finally:
        termina_figli(app)


@pytest.mark.parametrize("nuova_app,attesa", [(SI_ROMPE, 10), (SI_BLOCCA, 3)])
def test_se_la_nuova_versione_non_parte_torna_quella_di_prima(tmp_path, nuova_app, attesa):
    app, nuova, vecchia = prepara_cartelle(tmp_path, nuova_app)
    try:
        ok = aggiorna.installa(app, nuova, vecchia.pid, sys.executable, "1.3.1", "1.3.0", attesa_avvio=attesa)
        assert not ok
        assert (app / "versione.txt").read_text().strip() == "1.3.0"
        assert (app / "motore.py").read_text() == "vecchio\n" and (app / "dettami.py").read_text() == PARTE
        assert not (app / "file_nuovo.py").exists()
        fallito = json.loads((app / "aggiornamento-fallito.json").read_text())
        assert fallito["versione"] == "1.3.1" and fallito["precedente"] == "1.3.0"
        time.sleep(1.0)  # la versione precedente viene riavviata
        assert (app / "avvii.log").read_text().splitlines()[-1].startswith("1.3.0 --avvio")
    finally:
        termina_figli(app)


def test_se_la_vecchia_app_non_si_chiude_non_tocca_niente(tmp_path, monkeypatch):
    app, nuova, vecchia = prepara_cartelle(tmp_path, PARTE)
    viva = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(aggiorna, "ATTESA_CHIUSURA", 0.5)
    try:
        assert not aggiorna.installa(app, nuova, viva.pid, sys.executable, "1.3.1", "1.3.0")
        assert (app / "versione.txt").read_text().strip() == "1.3.0"
    finally:
        viva.kill()


def test_avvia_installazione_usa_una_copia_dell_aggiornatore(tmp_path, monkeypatch):
    app = tmp_path / "Dettami"
    app.mkdir()
    (app / "aggiorna.py").write_text("# aggiornatore\n")
    nuova = tmp_path / "Dettami" / "_aggiornamento" / "nuova"
    nuova.mkdir(parents=True)
    lanciati = []
    monkeypatch.setattr(ag.subprocess, "Popen", lambda args, **kw: lanciati.append((args, kw)))
    ag.avvia_installazione(app, nuova, "1.3.1", "1.3.0")
    args, kw = lanciati[0]
    assert args[1] == "-I" and args[2].endswith("aggiorna-in-corso.py") and Path(args[2]).exists()
    assert args[args.index("--versione") + 1] == "1.3.1" and args[args.index("--precedente") + 1] == "1.3.0"


# ---------------------------------------------------------------- build

def test_build_crea_manifest_firmato(tmp_path, chiavi, monkeypatch):
    import costruisci_pacchetto as cp
    _, priv = chiavi
    monkeypatch.setattr(ag, "CHIAVE_PUBBLICA", {"n": priv["n"], "e": priv["e"]})
    monkeypatch.setattr(cp, "QUI", tmp_path)
    (tmp_path / "NOVITA.md").write_text("## 1.3.0\n\n- Prima cosa\n- Seconda\n\n## 1.2.0\n\n- Vecchia\n")
    chiave = tmp_path / "k.json"
    chiave.write_text(json.dumps({"n": format(priv["n"], "x"), "e": 65537, "d": format(priv["d"], "x")}))
    app = tmp_path / "app"
    app.mkdir()
    for nome, c in {**APP_V1, "config.toml": "a = 1\n", "requisiti-windows.txt": "numpy==1\r\n"}.items():
        (app / nome).write_text(c)
    uscita = cp.pacchetto_aggiornamento(app, "1.3.0", "python-3.14.10-win64.zip", chiave)
    grezzo = (uscita / "manifest.json").read_bytes()
    assert ag.verifica_firma(grezzo, (uscita / "manifest.sig").read_bytes(), ag.CHIAVE_PUBBLICA)
    m = json.loads(grezzo)
    assert m["note"] == ["Prima cosa", "Seconda"] and m["versione"] == "1.3.0"
    assert m["pacchetto"]["url"] == "https://github.com/albykeg/dettami/releases/download/v1.3.0/dettami-app-1.3.0.zip"
    nomi = zipfile.ZipFile(uscita / "dettami-app-1.3.0.zip").namelist()
    assert "config.esempio.toml" in nomi and "config.toml" not in nomi
    assert m["requisiti_sha256"] == ag.impronta_requisiti("numpy==1\n")


# ---------------------------------------------------------------- Mac: l'app si riapre con "open"

SI_BLOCCA_MAC = APP_FINTA.format(comportamento='(qui / "istanza.lock").write_text(str(os.getpid()))\ntime.sleep(60)')


def prepara_mac(tmp_path, monkeypatch, nuova_app: str):
    """Come su Mac: python = …/Dettami.app/Contents/MacOS/Dettami e un "open" finto che lancia l'app."""
    app, nuova, vecchia = prepara_cartelle(tmp_path, nuova_app)
    eseguibile = tmp_path / "Applications" / "Dettami.app" / "Contents" / "MacOS" / "Dettami"
    eseguibile.parent.mkdir(parents=True)
    eseguibile.write_text("")
    finto = tmp_path / "open"
    finto.write_text(f"""#!{sys.executable}
import json, os, subprocess, sys
app = os.environ["DETTAMI_APP_TEST"]
assert sys.argv[1:3] == ["-n", "-a"] and sys.argv[3].endswith("Dettami.app"), sys.argv
f = os.path.join(app, "argomenti-avvio.json")
argomenti = json.load(open(f))
os.remove(f)
subprocess.Popen([sys.executable, os.path.join(app, "dettami.py"), *argomenti], cwd=app, start_new_session=True)
""")
    finto.chmod(0o755)
    monkeypatch.setattr(aggiorna, "MAC", True)
    monkeypatch.setattr(aggiorna, "COMANDO_OPEN", str(finto))
    monkeypatch.setenv("DETTAMI_APP_TEST", str(app))
    return app, nuova, vecchia, str(eseguibile)


def test_bundle_riconosciuto_solo_su_mac(monkeypatch):
    p = "/Users/a/Applications/Dettami.app/Contents/MacOS/Dettami"
    assert aggiorna.bundle_di(p) is None  # qui non siamo su Mac
    monkeypatch.setattr(aggiorna, "MAC", True)
    assert aggiorna.bundle_di(p) == Path("/Users/a/Applications/Dettami.app")
    assert aggiorna.bundle_di("/usr/bin/python3") is None


def test_mac_installazione_riuscita(tmp_path, monkeypatch):
    app, nuova, vecchia, python = prepara_mac(tmp_path, monkeypatch, PARTE)
    try:
        assert aggiorna.installa(app, nuova, vecchia.pid, python, "1.3.1", "1.3.0", attesa_avvio=10)
        assert (app / "versione.txt").read_text().strip() == "1.3.1"
        assert "1.3.1 --avvio --dopo-aggiornamento 1.3.0" in (app / "avvii.log").read_text()
        assert not (app / "argomenti-avvio.json").exists()
    finally:
        termina_figli(app)


def test_mac_se_non_parte_torna_indietro_e_chiude_la_copia_bloccata(tmp_path, monkeypatch):
    app, nuova, vecchia, python = prepara_mac(tmp_path, monkeypatch, SI_BLOCCA_MAC)
    try:
        assert not aggiorna.installa(app, nuova, vecchia.pid, python, "1.3.1", "1.3.0", attesa_avvio=3)
        bloccata = int((app / "istanza.lock").read_text())
        assert aggiorna.aspetta_chiusura(bloccata, 5)  # la copia nuova bloccata è stata chiusa
        assert (app / "versione.txt").read_text().strip() == "1.3.0"
        time.sleep(1.0)
        assert (app / "avvii.log").read_text().splitlines()[-1].startswith("1.3.0 --avvio")
    finally:
        termina_figli(app)


def test_manifest_di_un_altro_sistema_rifiutato(monkeypatch):
    m = manifest_per("1.3.1", b"x", "https://x")
    assert ag.valida_manifest(m)  # senza "sistema" = Windows (manifest della 1.3)
    with pytest.raises(ag.ErroreAggiornamento, match="per mac"):
        ag.valida_manifest({**m, "sistema": "mac"})
    monkeypatch.setattr(ag, "SISTEMA", "mac")
    assert ag.valida_manifest({**m, "sistema": "mac"})


def test_firma_del_manifest_mac(server, chiavi):
    radice, base = server
    _, priv = chiavi
    pub = {"n": priv["n"], "e": priv["e"]}
    m = pubblica_finto(radice, base, "1.4.0", APP_V1, priv)
    grezzo = json.dumps({**m}).encode()
    (radice / "manifest-mac.json").write_bytes(grezzo)
    (radice / "manifest-mac.sig").write_bytes(ag.firma(grezzo, priv))
    (radice / "manifest.sig").write_bytes(b"\0" * 256)  # quella di Windows non deve servire
    assert ag.controlla("1.3.0", f"{base}/manifest-mac.json", SessioneHttpLocale(), pub)["versione"] == "1.4.0"
