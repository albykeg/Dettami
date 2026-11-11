"""Il pacchetto di aggiornamento deve passare i controlli delle copie già installate (dalla 1.3.0).

Le copie installate scaricano dettami-app-<v>.zip e lo controllano con il LORO aggiornamenti.py:
un nome di file che la 1.3 non accetta (una cartella, un'estensione nuova...) fa rifiutare
l'aggiornamento a tutti. Qui si costruisce il pacchetto vero, come fa costruisci_pacchetto.py,
e lo si controlla con le regole della 1.3 copiate qui sotto (che non vanno mai cambiate) e, se la
storia di git è disponibile, con il codice stesso della 1.3.

python -m pytest test_pacchetto.py -q
"""
import importlib.util
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

import aggiornamenti
import costruisci_pacchetto as cp
import motore

QUI = Path(__file__).resolve().parent

# ---- regole di aggiornamenti.py della 1.3.0 (commit 9b9851f): copia fissa, NON aggiornarla
COMMIT_V13 = "9b9851f179948896ad86814f50da783d2eb1e5f5"
V13_MAX_PACCHETTO = 30 * 1024 * 1024
V13_MAX_FILE = 8 * 1024 * 1024
V13_NOME_VALIDO = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.(py|html|ps1|md|ico|txt|toml)$")
V13_NOMI_RISERVATI = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
V13_FILE_OBBLIGATORI = {"dettami.py", "motore.py", "aggiorna.py", "aggiornamenti.py", "versione.txt"}
V13_VIETATI = {"config.toml", ".env", "impostazioni.json"}


def problemi_v13(zip_path: Path) -> list[str]:
    """I motivi per cui la 1.3 rifiuterebbe il pacchetto (lista vuota = accettato)."""
    problemi, visti = [], set()
    if zip_path.stat().st_size > V13_MAX_PACCHETTO:
        problemi.append(f"pacchetto troppo grande: {zip_path.stat().st_size} byte")
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            nome = info.filename
            if (info.is_dir() or "/" in nome or "\\" in nome or not V13_NOME_VALIDO.match(nome)
                    or nome.lower() in V13_VIETATI or nome.split(".")[0].lower() in V13_NOMI_RISERVATI):
                problemi.append(f"nome non ammesso dalla 1.3: {nome!r}")
            if nome.lower() in visti:
                problemi.append(f"file ripetuto: {nome!r}")
            visti.add(nome.lower())
            if info.file_size > V13_MAX_FILE:
                problemi.append(f"file troppo grande: {nome}")
    mancanti = V13_FILE_OBBLIGATORI - visti
    if mancanti:
        problemi.append(f"mancano: {', '.join(sorted(mancanti))}")
    return problemi


@pytest.fixture(scope="module")
def pacchetto(tmp_path_factory) -> Path:
    """dettami-app-<v>.zip costruito con le stesse funzioni della build vera."""
    base = tmp_path_factory.mktemp("pacchetto")
    app = base / "app"
    app.mkdir()
    cp.prepara_app(app, motore.VERSIONE)
    # nella build vera requisiti-mac.txt arriva da costruisci_mac (che scarica le librerie): qui basta il nome
    cp.scrivi(app / "requisiti-mac.txt", "# Librerie per Dettami su Mac\n", crlf=False)
    zip_app = base / f"dettami-app-{motore.VERSIONE}.zip"
    cp.scrivi_zip_app(app, zip_app)
    return zip_app


def test_pacchetto_accettato_dalle_regole_v13(pacchetto):
    assert problemi_v13(pacchetto) == []


def test_pacchetto_senza_dati_utente(pacchetto):
    nomi = {n.lower() for n in zipfile.ZipFile(pacchetto).namelist()}
    assert not nomi & {"config.toml", ".env", "impostazioni.json"}
    assert "config.esempio.toml" in nomi


def test_pacchetto_accettato_dal_codice_attuale(pacchetto, tmp_path):
    nomi = aggiornamenti.prepara(pacchetto, tmp_path / "estratto", motore.VERSIONE)
    assert set(cp.FILE_APP) - {"config.toml"} <= set(nomi)


def test_pacchetto_accettato_dal_codice_della_v13(pacchetto, tmp_path):
    """Il controllo più fedele: l'aggiornamenti.py della 1.3, preso da git, prepara il pacchetto."""
    r = subprocess.run(["git", "show", f"{COMMIT_V13}:aggiornamenti.py"], cwd=QUI, capture_output=True)
    if r.returncode != 0:
        pytest.skip("storia di git non disponibile (serve un clone completo)")
    sorgente = tmp_path / "aggiornamenti_v13.py"
    sorgente.write_bytes(r.stdout)
    spec = importlib.util.spec_from_file_location("aggiornamenti_v13", sorgente)
    v13 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v13)
    assert v13.NOME_VALIDO.pattern == V13_NOME_VALIDO.pattern  # la copia qui sopra è fedele
    nomi = v13.prepara(pacchetto, tmp_path / "estratto", motore.VERSIONE)
    assert V13_FILE_OBBLIGATORI <= set(nomi)


@pytest.mark.parametrize("nome", ["mac/avvio_app.py", "dati.json", "config.toml", "con.py", "_nascosto.py"])
def test_il_controllo_v13_rifiuta_i_nomi_sbagliati(tmp_path, nome):
    zip_path = tmp_path / "prova.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for obbligatorio in V13_FILE_OBBLIGATORI:
            z.writestr(obbligatorio, "")
        z.writestr(nome, "")
    assert problemi_v13(zip_path)


def test_chiave_pubblica_invariata():
    """Le copie installate verificano le firme con questa chiave: non deve cambiare mai."""
    r = subprocess.run(["git", "show", f"{COMMIT_V13}:aggiornamenti.py"], cwd=QUI, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("storia di git non disponibile (serve un clone completo)")
    n_v13 = re.search(r'"n":\s*int\(\s*((?:"[0-9a-f]+"\s*)+),\s*16\)', r.stdout)
    assert n_v13, "chiave pubblica non trovata nella 1.3"
    assert int("".join(re.findall(r"[0-9a-f]+", n_v13.group(1))), 16) == aggiornamenti.CHIAVE_PUBBLICA["n"]
