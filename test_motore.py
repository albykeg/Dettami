"""Test del motore (girano su qualsiasi sistema): python -m pytest test_motore.py -q"""
import io
import wave

import numpy as np
import pytest

import motore
from motore import FREQ, MacchinaTasto


# ---------------------------------------------------------------- config

def test_config_reale_si_carica_e_unisce_i_predefiniti():
    cfg = motore.carica_config()
    assert cfg["tasti"]["dettatura"] == "ctrl_r"
    assert cfg["trascrizione"]["modelli"] == ["whisper-large-v3-turbo", "whisper-large-v3"]
    assert cfg["ai"]["modelli"][-1] == "qwen/qwen3.8-27b"
    assert cfg["ai"]["modelli"][0] == "openai/gpt-oss-120b"
    assert "chat" in cfg["stili"] and "prompt" in cfg["istruzioni_stile"]
    assert cfg["personale"]["scorciatoie"] == {}  # esempi commentati
    assert cfg["audio"]["soglia_silenzio"] == 200


def test_config_con_bom_o_ansi(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes("﻿[personale]\ndizionario = [\"Caffè\"]\n".encode("utf-8"))
    assert motore.carica_config(p)["personale"]["dizionario"] == ["Caffè"]
    p.write_bytes("[personale]\ndizionario = [\"Caffè\"]\n".encode("cp1252"))
    assert motore.carica_config(p)["personale"]["dizionario"] == ["Caffè"]


def test_config_rotta_da_errore_chiaro(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[tasti\ndettatura = ", encoding="utf-8")
    with pytest.raises(motore.ErroreConfig):
        motore.carica_config(p)


def test_api_key_da_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("﻿# commento\nGROQ_API_KEY = \"gsk_abc\"\n", encoding="utf-8")
    assert motore.leggi_api_key(p) == "gsk_abc"
    assert motore.leggi_api_key(tmp_path / "manca.env") == ""


# ---------------------------------------------------------------- audio

def test_wav_valido():
    audio = (np.sin(np.arange(FREQ) / 10) * 3000).astype(np.int16)
    with wave.open(io.BytesIO(motore.in_wav(audio))) as w:
        assert w.getframerate() == FREQ and w.getnchannels() == 1 and w.getnframes() == FREQ


def test_ricampiona_48k_e_44k():
    a48 = np.zeros(48000, np.int16)
    assert motore.ricampiona(a48, 48000).size == 16000
    a44 = np.zeros(44100, np.int16)
    assert abs(motore.ricampiona(a44, 44100).size - 16000) <= 1


def test_rilevamento_voce():
    rng = np.random.default_rng(0)
    silenzio = (rng.normal(0, 30, FREQ)).astype(np.int16)
    voce = (np.sin(np.arange(FREQ) / 8) * 4000).astype(np.int16)
    click = silenzio.copy()
    click[1000:1100] = 20000  # un colpo isolato non conta come voce
    assert not motore.c_e_voce(silenzio, 200)
    assert not motore.c_e_voce(click, 200)
    assert motore.c_e_voce(voce, 200)
    assert not motore.c_e_voce(voce[:2000], 200)  # troppo corto


# ---------------------------------------------------------------- testo

@pytest.mark.parametrize("ingresso,atteso", [
    ("Sottotitoli creati dalla comunità Amara.org", ""),
    ("Ci vediamo domani. Sottotitoli creati dalla comunità Amara.org", "Ci vediamo domani."),
    ("Grazie per la visione.", ""),
    ("Grazie per la visione di ieri, era bella", "Grazie per la visione di ieri, era bella"),
    ("Grazie.", "Grazie."),
    ("...", ""),
])
def test_allucinazioni(ingresso, atteso):
    assert motore.rimuovi_allucinazioni(ingresso) == atteso


@pytest.mark.parametrize("ingresso,atteso", [
    ('"Ciao, come stai?"', "Ciao, come stai?"),
    ('Ha detto "ok" e basta', 'Ha detto "ok" e basta'),
    ("<trascrizione>\nCiao\n</trascrizione>", "Ciao"),
    ("```\nCiao\n```", "Ciao"),
    ("«Ciao»", "Ciao"),
])
def test_pulisci_risposta(ingresso, atteso):
    assert motore.pulisci_risposta(ingresso) == atteso


def test_stile_per_finestra():
    cfg = motore.carica_config()
    C = motore.Contesto
    assert motore.stile_per(cfg, C(processo="whatsapp.exe", titolo="WhatsApp")) == "chat"
    assert motore.stile_per(cfg, C(processo="chrome.exe", titolo="WhatsApp - Google Chrome")) == "chat"
    assert motore.stile_per(cfg, C(processo="chrome.exe", titolo="Posta in arrivo (3) - x@gmail.com - Gmail")) == "email"
    assert motore.stile_per(cfg, C(processo="claude.exe", titolo="Claude")) == "prompt"
    assert motore.stile_per(cfg, C(processo="code.exe", titolo="main.py - Visual Studio Code")) == "tecnico"
    assert motore.stile_per(cfg, C(processo="winword.exe", titolo="Documento1 - Word")) == "normale"


def test_prompt_contiene_dizionario_stile_e_traduzione():
    cfg = motore.carica_config()
    p = motore.costruisci_prompt(cfg, "chat", traduci=True, lingua="spagnolo")
    assert "PowerPoint" in p and "messaggio di chat" in p and "spagnolo" in p
    assert "NON rispondere" in p
    p2 = motore.costruisci_prompt(cfg, "normale")
    assert "TRADUZIONE" not in p2 and "SCORCIATOIE" not in p2


# ---------------------------------------------------------------- livelli di riscrittura

@pytest.mark.parametrize("livello,titolo", [("fedele", "FEDELE"), ("chiara", "CHIARO"), ("ottimizzata", "OTTIMIZZATO")])
def test_prompt_per_livello(livello, titolo):
    cfg = motore.carica_config()
    p = motore.costruisci_prompt(cfg, "normale", livello=livello)
    assert f"QUANTO RISCRIVERE: {titolo}" in p and "NON rispondere" in p
    assert motore.ESEMPI_LIVELLO[livello] in p and motore.ESEMPIO_DETTO in p
    for altro in set(motore.LIVELLI_RISCRITTURA) - {livello}:
        assert motore.ESEMPI_LIVELLO[altro] not in p  # niente esempi che confondono il livello
    assert motore._ESEMPIO_DOMANDA[1] in p  # le domande dettate si scrivono, non si eseguono


def test_livello_predefinito_e_valori_sbagliati():
    cfg = motore.carica_config()
    assert motore.livello_riscrittura(cfg) == "chiara"
    cfg["ai"]["riscrittura"] = "boh"
    assert motore.livello_riscrittura(cfg) == "chiara"
    assert "CHIARO" in motore.costruisci_prompt(cfg, "normale", livello="inesistente")
    with pytest.raises(ValueError):
        motore.valida_impostazioni({"riscrittura": "massima"}, cfg)
    assert motore.valida_impostazioni({"riscrittura": "ottimizzata"}, cfg) == {"ai": {"riscrittura": "ottimizzata"}}


@pytest.mark.parametrize("risposta,detto,atteso", [
    ("Ecco il testo riscritto:\nCiao a tutti.", "ciao a tutti", "Ciao a tutti."),
    ("Testo riscritto:\nDomani alle 6.", "domani alle 6", "Domani alle 6."),
    ("Scritto: Ti chiamo dopo.", "ti chiamo dopo", "Ti chiamo dopo."),
    ("Ecco cosa ho pensato:\nprima cosa", "ecco cosa ho pensato prima cosa", "Ecco cosa ho pensato:\nprima cosa"),
    ("Testo: va bene", "testo va bene", "Testo: va bene"),
])
def test_pulisci_preamboli(risposta, detto, atteso):
    assert motore.pulisci_risposta(risposta, detto) == atteso


class _RispostaFinta:
    status_code = 200
    headers = {}

    def json(self):
        return {"choices": [{"message": {"content": "Ok."}}], "usage": {"total_tokens": 10}}


def _client_che_registra(cfg):
    c = motore.ClientAI(cfg, "gsk_finto")
    inviati = []
    c._post = lambda percorso, **kw: inviati.append(kw["json"]) or _RispostaFinta().json()
    return c, inviati


def test_sforzo_di_ragionamento_per_livello():
    cfg = motore.carica_config()
    c, inviati = _client_che_registra(cfg)
    c.rifinisci("sistema", "testo", cfg, livello="chiara")
    c.rifinisci("sistema", "testo", cfg, livello="ottimizzata")
    assert [p["reasoning_effort"] for p in inviati] == ["low", "medium"]
    assert all(p["include_reasoning"] is False for p in inviati)
    cfg["ai"]["ragionamento"] = "high"  # chi lo imposta a mano vince
    c.rifinisci("sistema", "testo", cfg, livello="fedele")
    assert inviati[-1]["reasoning_effort"] == "high"


def test_riscrivi_usa_il_livello_scelto_e_ripiega_sul_grezzo():
    cfg = motore.carica_config()
    cfg["ai"]["riscrittura"] = "ottimizzata"
    c = ClientFinto(risposta="Testo migliore.")
    assert motore.riscrivi(c, cfg, "testo peggiore detto a voce") == ("Testo migliore.", None)
    assert c.livelli == ["ottimizzata"] and "OTTIMIZZATO" in c.chiamate_ai[0][0]
    assert motore.riscrivi(c, cfg, "altro testo", livello="fedele")[0] == "Testo migliore."
    assert c.livelli[-1] == "fedele" and "FEDELE" in c.chiamate_ai[-1][0]
    giu = ClientFinto(errore_ai=motore.ErroreAPI("quota finita", stato=429))
    testo, avviso = motore.riscrivi(giu, cfg, "il mio testo")
    assert testo == "il mio testo" and "non rifinito" in avviso
    with pytest.raises(motore.ErroreAPI):
        motore.riscrivi(ClientFinto(errore_ai=motore.ErroreAPI("chiave", stato=401)), cfg, "x y z")


# ---------------------------------------------------------------- pipeline con API finte

class ClientFinto:
    def __init__(self, trascrizione="", risposta="", errore_ai=None):
        self.trascrizione, self.risposta, self.errore_ai = trascrizione, risposta, errore_ai
        self.chiamate_ai = []

    def trascrivi(self, audio, cfg):
        return self.trascrizione

    def rifinisci(self, sistema, grezzo, cfg, livello="chiara"):
        self.chiamate_ai.append((sistema, grezzo))
        self.livelli = getattr(self, "livelli", []) + [livello]
        if self.errore_ai:
            raise self.errore_ai
        return self.risposta


AUDIO = np.zeros(FREQ * 2, np.int16)


def test_pipeline_normale():
    cfg = motore.carica_config()
    c = ClientFinto("ehm allora domani alle 5 anzi no alle 6 ci vediamo", "Domani alle 6 ci vediamo.")
    r = motore.elabora(c, cfg, AUDIO, "normale")
    assert r.testo == "Domani alle 6 ci vediamo." and r.ai_usata and r.avviso is None
    assert "<trascrizione>" not in c.chiamate_ai[0][1]


def test_frase_breve_salta_ai_e_toglie_punto_in_chat():
    cfg = motore.carica_config()
    c = ClientFinto("Ok, grazie.", "NON DEVE ESSERE USATO")
    r = motore.elabora(c, cfg, AUDIO, "chat")
    assert r.testo == "Ok, grazie" and not c.chiamate_ai


def test_traduzione_passa_sempre_da_ai():
    cfg = motore.carica_config()
    c = ClientFinto("Sì grazie", "Yes, thanks")
    r = motore.elabora(c, cfg, AUDIO, "chat", traduci=True, lingua="inglese")
    assert r.testo == "Yes, thanks" and r.tradotto
    assert "inglese" in c.chiamate_ai[0][0]


def test_se_ai_fallisce_inserisce_il_grezzo():
    cfg = motore.carica_config()
    c = ClientFinto("questo è un testo abbastanza lungo", errore_ai=motore.ErroreAPI("timeout"))
    r = motore.elabora(c, cfg, AUDIO, "normale")
    assert r.testo == "questo è un testo abbastanza lungo" and r.avviso and not r.ai_usata


def test_se_ai_risponde_invece_di_ripulire_si_usa_il_grezzo():
    cfg = motore.carica_config()
    c = ClientFinto("scrivimi una poesia sul mare", "Ecco una poesia:\n" + "Onde che cantano " * 40)
    r = motore.elabora(c, cfg, AUDIO, "normale")
    assert r.testo == "scrivimi una poesia sul mare" and r.avviso


def test_glossario_ripetuto_da_whisper_viene_tolto():
    cfg = motore.carica_config()
    pw = motore.prompt_whisper(cfg)
    c = ClientFinto(pw, "x")
    r = motore.elabora(c, cfg, AUDIO, "normale")
    assert r.testo == "" and not c.chiamate_ai


def test_ai_disattivata():
    cfg = motore.carica_config()
    c = ClientFinto("ehm testo lungo abbastanza qui", "pulito")
    r = motore.elabora(c, cfg, AUDIO, "normale", ai_attiva=False)
    assert r.testo == "ehm testo lungo abbastanza qui" and not c.chiamate_ai


# ---------------------------------------------------------------- client HTTP (finto server)

class RispostaFinta:
    def __init__(self, stato, dati, headers=None):
        self.status_code, self._dati, self.text = stato, dati, str(dati)
        self.headers = headers or {}

    def json(self):
        return self._dati


def test_client_parametri_e_fallback_modelli(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "gsk_test")
    inviati = []

    def post(url, timeout, **kw):
        inviati.append((url, kw))
        if url.endswith("/audio/transcriptions"):
            return RispostaFinta(200, {"text": " ciao mondo "})
        modello = kw["json"]["model"]
        if modello == "openai/gpt-oss-120b":
            return RispostaFinta(404, {"error": {"message": "model not found"}})
        return RispostaFinta(200, {"choices": [{"message": {"content": "Ciao mondo."}}]})

    monkeypatch.setattr(cli.s, "post", post)
    monkeypatch.setattr(motore.time, "sleep", lambda s: None)
    audio = (np.sin(np.arange(FREQ * 2) / 8) * 4000).astype(np.int16)
    assert cli.trascrivi(audio, cfg) == "ciao mondo"
    url, kw = inviati[0]
    assert kw["data"]["language"] == "it" and kw["data"]["model"] == "whisper-large-v3-turbo"
    assert "Glossario" in kw["data"]["prompt"]
    assert kw["files"]["file"][0] == "audio.wav"

    out = cli.rifinisci("sistema", "ciao mondo", cfg)
    assert out == "Ciao mondo."
    payload = inviati[-1][1]["json"]
    assert payload["model"] == "openai/gpt-oss-20b"
    assert payload["reasoning_effort"] == "low" and payload["include_reasoning"] is False


def test_client_401_non_prova_altri_modelli(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "sbagliata")
    chiamate = []

    def post(url, timeout, **kw):
        chiamate.append(1)
        return RispostaFinta(401, {"error": {"message": "invalid key"}})

    monkeypatch.setattr(cli.s, "post", post)
    with pytest.raises(motore.ErroreAPI) as e:
        cli.rifinisci("s", "t", cfg)
    assert e.value.stato == 401 and len(chiamate) == 1


def test_client_ritenta_su_errore_temporaneo(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    risposte = [RispostaFinta(503, {}), RispostaFinta(200, {"text": "ok"})]
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw: risposte.pop(0))
    monkeypatch.setattr(motore.time, "sleep", lambda s: None)
    assert cli.trascrivi(np.ones(FREQ, np.int16), cfg) == "ok"


def test_quota_gratuita_finita_passa_al_modello_dopo_e_se_lo_ricorda(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    modelli_chiamati = []
    attese = []

    def post(url, timeout, **kw):
        m = kw["json"]["model"]
        modelli_chiamati.append(m)
        if m == "openai/gpt-oss-120b":
            return RispostaFinta(429, {"error": {"message": "TPD exceeded"}}, {"retry-after": "3600"})
        return RispostaFinta(200, {"choices": [{"message": {"content": "Ok."}}]})

    monkeypatch.setattr(cli.s, "post", post)
    monkeypatch.setattr(motore.time, "sleep", lambda s: attese.append(s))
    assert cli.rifinisci("s", "t", cfg) == "Ok." and cli.ultimo_modello == "openai/gpt-oss-20b"
    assert modelli_chiamati == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"] and not attese  # nessuna attesa inutile
    modelli_chiamati.clear()
    cli.rifinisci("s", "t", cfg)
    assert modelli_chiamati == ["openai/gpt-oss-20b"]  # il 120b viene saltato finché non si libera


def test_limite_al_minuto_breve_ritenta(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    risposte = [RispostaFinta(429, {}, {"retry-after": "1"}), RispostaFinta(200, {"text": "ok"})]
    attese = []
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw: risposte.pop(0))
    monkeypatch.setattr(motore.time, "sleep", lambda s: attese.append(s))
    assert cli.trascrivi(np.ones(FREQ, np.int16), cfg) == "ok" and attese == [1.0]


def test_limite_trascrizione_giornaliero_messaggio_chiaro(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw:
                        RispostaFinta(429, {}, {"retry-after": "7200"}))
    with pytest.raises(motore.ErroreAPI) as e:
        cli.trascrivi(np.ones(FREQ, np.int16), cfg)
    assert e.value.stato == 429 and "2 ore" in str(e.value)


def test_qwen_senza_ragionamento(monkeypatch):
    cfg = motore.carica_config()
    cfg["ai"]["modelli"] = ["qwen/qwen3.8-27b"]
    cli = motore.ClientAI(cfg, "k")
    inviati = []
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw: (inviati.append(kw["json"]), RispostaFinta(
        200, {"choices": [{"message": {"content": "x"}}]}))[1])
    cli.rifinisci("s", "t", cfg)
    assert inviati[0]["reasoning_effort"] == "none" and "include_reasoning" not in inviati[0]


def test_trascrizione_passa_al_secondo_whisper_quando_finisce_la_quota(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    usati = []

    def post(url, timeout, **kw):
        m = kw["data"]["model"]
        usati.append(m)
        if m == "whisper-large-v3-turbo":
            return RispostaFinta(429, {}, {"retry-after": "5000"})
        return RispostaFinta(200, {"text": "ciao"})

    monkeypatch.setattr(cli.s, "post", post)
    audio = np.ones(FREQ, np.int16)
    assert cli.trascrivi(audio, cfg) == "ciao" and cli.ultimo_modello_trascrizione == "whisper-large-v3"
    usati.clear()
    cli.trascrivi(audio, cfg)
    assert usati == ["whisper-large-v3"]


def test_modello_dismesso_viene_saltato(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    usati = []

    def post(url, timeout, **kw):
        m = kw["json"]["model"]
        usati.append(m)
        if m == "openai/gpt-oss-120b":
            return RispostaFinta(404, {"error": {"message": "The model `openai/gpt-oss-120b` does not exist"}})
        return RispostaFinta(200, {"choices": [{"message": {"content": "Ok."}}]})

    monkeypatch.setattr(cli.s, "post", post)
    cli.rifinisci("s", "t", cfg)
    usati.clear()
    cli.rifinisci("s", "t", cfg)
    assert usati == ["openai/gpt-oss-20b"]


def test_verifica_chiave(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    monkeypatch.setattr(cli.s, "get", lambda url, timeout: RispostaFinta(200, {"data": []}))
    assert cli.verifica_chiave()[0]
    monkeypatch.setattr(cli.s, "get", lambda url, timeout: RispostaFinta(401, {"error": {"message": "x"}}))
    assert cli.verifica_chiave() == (False, "API key non valida")


def test_risultato_riporta_i_modelli_usati():
    cfg = motore.carica_config()
    c = ClientFinto("ehm testo abbastanza lungo qui", "Testo.")
    c.ultimo_modello, c.ultimo_modello_trascrizione = "openai/gpt-oss-20b", "whisper-large-v3"
    r = motore.elabora(c, cfg, AUDIO, "normale")
    assert r.modello == "openai/gpt-oss-20b" and r.modello_trascrizione == "whisper-large-v3"


def test_audio_lungo_diviso_in_pezzi(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    n = []
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw: (n.append(1), RispostaFinta(200, {"text": "pezzo"}))[1])
    audio = np.ones(FREQ * 60 * 25, np.int16)  # 25 minuti
    assert cli.trascrivi(audio, cfg) == "pezzo pezzo pezzo" and len(n) == 3


# ---------------------------------------------------------------- logica del tasto

class Azioni:
    def __init__(self, ok=True):
        self.log, self.ok = [], ok

    def inizia(self, s):
        self.log.append("inizia")
        return self.ok

    def termina(self):
        self.log.append("termina")

    def scarta(self, silenzioso):
        self.log.append("scarta" if silenzioso else "annulla")

    def mani_libere(self):
        self.log.append("mani_libere")

    def conferma(self):
        self.log.append("conferma")


def test_tenuto_lungo():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.conferma_scaduta(m.sessione)
    m.rilascia(2.0)
    assert a.log == ["inizia", "conferma", "termina"] and not m.registrando


def test_tocco_breve_scarta_e_niente_conferma():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.rilascia(0.1)
    m.conferma_scaduta(1)  # il timer scatta dopo: non deve suonare
    assert a.log == ["inizia", "scarta"]


def test_doppio_tocco_mani_libere_poi_tocco_per_finire():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0); m.rilascia(0.1)
    m.premi(0.25); m.rilascia(0.33)
    assert m.modo == MacchinaTasto.MANI_LIBERE
    m.conferma_scaduta(m.sessione)  # il timer della seconda pressione non deve fare nulla
    m.premi(10.0)
    assert m.registrando  # finisce al rilascio, non alla pressione
    m.rilascia(10.1)
    assert a.log == ["inizia", "scarta", "inizia", "mani_libere", "termina"] and not m.registrando


def test_due_tocchi_lenti_non_attivano_mani_libere():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0); m.rilascia(0.1)
    m.premi(2.0); m.rilascia(2.1)
    assert a.log == ["inizia", "scarta", "inizia", "scarta"]


def test_scorciatoia_ctrl_c_non_registra():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.altro_tasto()
    m.rilascia(0.8)
    assert a.log == ["inizia", "scarta"] and not m.registrando


def test_annulla_con_esc():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.annulla()
    m.rilascia(3.0)
    assert a.log == ["inizia", "annulla"]


def test_altro_tasto_in_mani_libere_non_interrompe():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0); m.rilascia(0.1); m.premi(0.2); m.rilascia(0.3)
    m.altro_tasto()
    assert m.modo == MacchinaTasto.MANI_LIBERE


def test_limite_durata():
    a = Azioni()
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.limite_scaduto(m.sessione)
    m.rilascia(901)
    assert a.log == ["inizia", "termina"]


def test_microfono_non_disponibile():
    a = Azioni(ok=False)
    m = MacchinaTasto(a)
    m.premi(0.0)
    m.rilascia(2.0)
    assert a.log == ["inizia"] and not m.registrando


# ================================================================ versione 1.1: dashboard

from datetime import datetime as _dt  # noqa: E402
import json as _json  # noqa: E402


def test_durata_groq():
    assert motore.durata_groq("2m59.56s") == pytest.approx(179.56)
    assert motore.durata_groq("7.66s") == pytest.approx(7.66)
    assert motore.durata_groq("1h2m3s") == 3723
    assert motore.durata_groq("120ms") == pytest.approx(0.12)
    assert motore.durata_groq("") is None and motore.durata_groq("boh") is None


def test_impostazioni_dashboard_sopra_config(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[tasti]\ndettatura = "ctrl_r"\n', encoding="utf-8")
    imp = tmp_path / "impostazioni.json"
    cfg = motore.carica_config(cfg_file, imp)
    motore.salva_impostazioni(imp, {"tasto": "f8", "ai_attiva": False,
                                    "dizionario": [" Acme ", "acme", "Mario Rossi", ""],
                                    "scorciatoie": {"la mia mail": "a@b.it", "vuota": " "}}, cfg)
    cfg2 = motore.carica_config(cfg_file, imp)
    assert cfg2["tasti"]["dettatura"] == "f8" and cfg2["ai"]["attiva"] is False
    assert cfg2["personale"]["dizionario"] == ["Acme", "Mario Rossi"]
    assert cfg2["personale"]["scorciatoie"] == {"la mia mail": "a@b.it"}
    assert cfg2["tasti"]["annulla"] == "esc"  # il resto resta
    v = motore.valori_impostazioni(cfg2)
    assert v["tasto"] == "f8" and v["indicatore"] is True and v["posizione_indicatore"] == "basso"


@pytest.mark.parametrize("dati", [
    {"tasto": "a"}, {"ai_attiva": "si"}, {"metodo": "copia"}, {"sconosciuta": 1},
    {"lingua_traduzione": "klingon"}, {"dizionario": "Acme"}, {"scorciatoie": {"x": 3}},
])
def test_impostazioni_non_valide_rifiutate(tmp_path, dati):
    cfg = motore.carica_config()
    with pytest.raises(ValueError):
        motore.salva_impostazioni(tmp_path / "imp.json", dati, cfg)
    assert not (tmp_path / "imp.json").exists()


def test_cronologia_statistiche_e_ricerca(tmp_path):
    f = tmp_path / "cronologia.jsonl"
    ora = _dt(2026, 10, 28, 15, 0)
    voci = [
        {"ts": "2026-10-28T09:00:00", "app": "whatsapp", "testo": "Ciao, arrivo alle sei", "parole": 4,
         "secondi_audio": 3.0, "t_elaborazione": 1.0},
        {"ts": "2026-10-28T10:00:00", "app": "outlook", "testo": " ".join(["parola"] * 120), "parole": 120,
         "secondi_audio": 50.0, "t_elaborazione": 2.0},
        {"ts": "2026-10-27T10:00:00", "app": "outlook", "testo": "Ieri", "parole": 1,
         "secondi_audio": 1.0, "t_elaborazione": 1.0},
        {"ts": "2026-10-10T10:00:00", "app": "word", "testo": "Vecchia", "parole": 10,
         "secondi_audio": 5.0, "t_elaborazione": 1.0},
    ]
    for v in voci:
        motore.aggiungi_cronologia(f, v)
    with open(f, "a", encoding="utf-8") as h:
        h.write("riga rovinata\n{}\n")
    lette = motore.leggi_cronologia(f)
    assert len(lette) == 4
    st = motore.statistiche(lette, ora)
    assert st["parole_oggi"] == 124 and st["dettature_oggi"] == 2
    assert st["parole_settimana"] == 125 and st["parole"] == 135 and st["dettature"] == 4
    assert st["giorni"][-1] == {"data": "2026-10-28", "etichetta": "mer 28", "parole": 124, "oggi": True}
    assert len(st["giorni"]) == 14 and st["giorni"][-2]["parole"] == 1
    assert st["minuti_risparmiati_oggi"] == 2  # 124 parole a mano = 3,1 min; a voce 53 s + 3 s
    assert st["parole_al_minuto"] == round(135 / (59 / 60))
    assert st["app"][0] == {"app": "outlook", "parole": 121}
    assert [v["testo"] for v in motore.cerca_cronologia(lette, "arrivo")] == ["Ciao, arrivo alle sei"]
    assert motore.cerca_cronologia(lette, "OUTLOOK", 1)[0]["ts"] == "2026-10-28T10:00:00"
    motore.cancella_cronologia(f)
    assert motore.leggi_cronologia(f) == [] and motore.statistiche([], ora)["parole_al_minuto"] is None


def test_migrazione_cronologia_versione_1(tmp_path):
    txt = tmp_path / "cronologia.txt"
    txt.write_text(
        "[2026-10-28 13:50] whatsapp · 4 parole · 1.2 s\nCiao, arrivo alle sei\n(detto: ehm ciao arrivo alle sei)\n\n"
        "[2026-10-28 13:55] ? · 3 parole · 0.9 s · tradotto in inglese\nHello, see you\n\n"
        "[2026-10-28 14:00] winword · 6 parole · 2,0 s\nPrimo paragrafo.\n\nSecondo paragrafo qui.\n\n",
        encoding="utf-8")
    jsonl = tmp_path / "cronologia.jsonl"
    assert motore.migra_cronologia_txt(txt, jsonl) == 3
    v = motore.leggi_cronologia(jsonl)
    assert v[0]["app"] == "whatsapp" and v[0]["grezzo"] == "ehm ciao arrivo alle sei" and v[0]["parole"] == 4
    assert v[1]["app"] == "" and v[1]["tradotto"] is True and v[1]["testo"] == "Hello, see you"
    assert v[2]["testo"] == "Primo paragrafo.\n\nSecondo paragrafo qui." and v[2]["t_elaborazione"] == 2.0
    assert not txt.exists() and (tmp_path / "cronologia-vecchia.txt").exists()
    assert motore.migra_cronologia_txt(txt, jsonl) == 0  # una volta sola


def test_uso_giornaliero_e_quota(tmp_path, monkeypatch):
    f = tmp_path / "uso.json"
    u = motore.Uso(f)
    u.registra("openai/gpt-oss-120b", token=900)
    u.registra("openai/gpt-oss-120b", token=1100)
    u.registra("whisper-large-v3-turbo", secondi_audio=10)
    u.salva()
    u2 = motore.Uso(f)
    assert u2.istantanea()["openai/gpt-oss-120b"] == {"richieste": 2, "token": 2000, "secondi_audio": 0.0}
    _json.loads(f.read_text())  # file valido
    f.write_text(_json.dumps({"giorno": "2020-01-01", "modelli": {"x": {"richieste": 9}}}))
    assert motore.Uso(f).istantanea() == {}  # nuovo giorno: si riparte da zero

    cfg = motore.carica_config()
    quote = {"whisper-large-v3-turbo": {"rimaste": 1500, "limite": 2000},
             "openai/gpt-oss-120b": {"bloccato_fino": 10_000_000_000}}
    righe = {r["modello"]: r for r in motore.riepilogo_quota(cfg, quote, u2.istantanea(), ora=1_000)}
    assert righe["whisper-large-v3-turbo"]["usata"] == 0.25
    assert righe["openai/gpt-oss-120b"]["usata"] == 1.0 and righe["openai/gpt-oss-120b"]["bloccato_fino"]
    assert righe["openai/gpt-oss-20b"]["usata"] == 0 and righe["qwen/qwen3.8-27b"]["tipo"] == "ai"
    assert len(righe) == 5


def test_client_legge_quota_dagli_header_e_conta_token(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "k")
    cli.uso = motore.Uso(None)
    h = {"x-ratelimit-remaining-requests": "998", "x-ratelimit-limit-requests": "1000",
         "x-ratelimit-reset-requests": "2m0s"}
    monkeypatch.setattr(cli.s, "post", lambda url, timeout, **kw: RispostaFinta(
        200, {"choices": [{"message": {"content": "Ok."}}], "usage": {"total_tokens": 777}}, h))
    cli.rifinisci("s", "t", cfg)
    q = cli.quote["openai/gpt-oss-120b"]
    assert q["rimaste"] == 998 and q["limite"] == 1000 and q["reset"] > 0
    assert cli.uso.istantanea()["openai/gpt-oss-120b"]["token"] == 777


# ================================================================ versione 1.2: pulsante Copia

def test_pillola_con_pulsante_copia():
    import indicatore
    senza = indicatore.disegna_pillola("fatto", "Inserito: 24 parole", scala=1.5)
    con = indicatore.disegna_pillola("fatto", "Inserito: 24 parole", scala=1.5, pulsante="Copia")
    sopra = indicatore.disegna_pillola("fatto", "Inserito: 24 parole", scala=1.5, pulsante="Copia", evidenzia=True)
    assert "pulsante" not in senza.info and con.width > senza.width
    x0, y0, x1, y1 = con.info["pulsante"]
    assert 0 < x0 < x1 <= con.width and 0 < y0 < y1 <= con.height
    assert x0 > senza.width * 0.6  # il pulsante sta a destra del testo
    centro = ((x0 + x1) // 2 - 22, (y0 + y1) // 2)  # zona di fondo del pulsante
    assert sum(sopra.getpixel(centro)[:3]) > sum(con.getpixel(centro)[:3])  # più chiaro al passaggio del mouse
    sfumata = indicatore.disegna_pillola("fatto", "x", pulsante="Copia", opacita=0.5)
    assert "pulsante" in sfumata.info


def test_impostazione_pulsante_copia(tmp_path):
    cfg = motore.carica_config()
    assert cfg["indicatore"]["pulsante_copia"] is True and cfg["indicatore"]["secondi_copia"] == 5
    motore.salva_impostazioni(tmp_path / "imp.json", {"pulsante_copia": False}, cfg)
    cfg2 = motore.carica_config(motore.CARTELLA / "config.toml", tmp_path / "imp.json")
    assert motore.valori_impostazioni(cfg2)["pulsante_copia"] is False


# ---------------------------------------------------------------- "Grazie." inventato da Whisper

def _voce_poi_silenzio():
    voce = (np.sin(np.arange(FREQ * 2) / 8) * 4000).astype(np.int16)
    return np.concatenate([np.zeros(FREQ, np.int16), voce, np.zeros(FREQ * 2, np.int16)])


def test_taglia_silenzio_prima_e_dopo():
    audio = _voce_poi_silenzio()  # 1 s silenzio, 2 s voce, 2 s silenzio
    t = motore.taglia_silenzio(audio, 200)
    assert 2.0 <= t.size / FREQ <= 2.7
    assert motore.taglia_silenzio(np.zeros(FREQ, np.int16), 200).size == FREQ  # tutto silenzio: invariato


def test_grazie_sul_silenzio_scartato_grazie_vero_tenuto():
    audio = _voce_poi_silenzio()
    falso = {"text": " Grazie.", "start": 3.5, "end": 4.5, "no_speech_prob": 0.1}
    vero = {"text": " Grazie.", "start": 1.5, "end": 2.5, "no_speech_prob": 0.1}
    incerto = {"text": " Grazie mille!", "start": 1.5, "end": 2.5, "no_speech_prob": 0.8}
    frase = {"text": " Ci vediamo domani.", "start": 3.5, "end": 4.5, "no_speech_prob": 0.9}
    assert motore.segmento_inventato(falso, audio, 200)
    assert not motore.segmento_inventato(vero, audio, 200)
    assert motore.segmento_inventato(incerto, audio, 200)
    assert not motore.segmento_inventato(frase, audio, 200)  # solo le chiusure tipiche


def test_trascrivi_toglie_il_grazie_finale(monkeypatch):
    cfg = motore.carica_config()
    cli = motore.ClientAI(cfg, "gsk_test")
    inviati = []

    def post(url, timeout, **kw):
        inviati.append(kw)
        return RispostaFinta(200, {"text": " Ci vediamo domani. Grazie.", "segments": [
            {"text": " Ci vediamo domani.", "start": 0.0, "end": 2.0, "no_speech_prob": 0.01},
            {"text": " Grazie.", "start": 2.2, "end": 2.6, "no_speech_prob": 0.6}]})

    monkeypatch.setattr(cli.s, "post", post)
    assert cli.trascrivi(_voce_poi_silenzio(), cfg) == "Ci vediamo domani."
    assert inviati[0]["data"]["response_format"] == "verbose_json"


def test_prompt_ricuce_le_frasi_spezzate():
    cfg = motore.carica_config()
    for livello in motore.LIVELLI_RISCRITTURA:
        p = motore.costruisci_prompt(cfg, "normale", livello=livello)
        assert "discorso fluido" in p and motore._ESEMPI_SPEZZATO[livello] in p
