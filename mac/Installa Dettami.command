#!/bin/bash
# Installa Dettami su questo Mac. Non chiede la password da amministratore:
#   app        ~/Applications/Dettami.app        (con il suo Python: non tocca altro sul Mac)
#   dati       ~/Library/Application Support/Dettami
#   avvio      ~/Library/LaunchAgents/io.github.albykeg.dettami.plist
# Si può rilanciare per aggiornare o riparare: chiave, impostazioni e cronologia restano.
set -u

QUI="$(cd "$(dirname "$0")" && pwd)"
SETUP="$QUI/setup"
APP="$HOME/Applications/Dettami.app"
NUOVA="$HOME/Applications/.Dettami-in-installazione.app"
DATI="$HOME/Library/Application Support/Dettami"
AGENTE="$HOME/Library/LaunchAgents/io.github.albykeg.dettami.plist"

titolo() { printf '\n\033[1;36m  %s\033[0m\n' "$1"; }
info()   { printf '      %s\n' "$1"; }
avviso() { printf '      \033[33m%s\033[0m\n' "$1"; }
fine()   { printf '\n'; read -r -p "  Premi Invio per chiudere questa finestra… " _ || true; exit "${1:-0}"; }
errore() {
    printf '\n  \033[1;31mInstallazione non riuscita:\033[0m %s\n' "$1"
    printf '      Se non si risolve, apri una segnalazione su github.com/albykeg/dettami/issues\n'
    rm -rf "$NUOVA"
    fine 1
}

clear
printf '\n  \033[1m==================================================\033[0m\n'
printf '\033[1m     DETTAMI per Mac — installazione\033[0m\n'
printf '     Dettatura vocale con AI, in qualsiasi programma\n'
printf '  \033[1m==================================================\033[0m\n'

[ -d "$SETUP" ] || errore "manca la cartella «setup» accanto a questo file. Estrai di nuovo lo zip."
VERSIONE="$(cat "$SETUP/app/versione.txt" 2>/dev/null)" || errore "pacchetto incompleto (versione)."
RUNTIME_TGZ="$(ls "$SETUP"/runtime/cpython-*.tar.gz 2>/dev/null | head -n 1)"
[ -n "$RUNTIME_TGZ" ] || errore "pacchetto incompleto: manca Python. Estrai di nuovo lo zip."
RUNTIME_NOME="$(basename "$RUNTIME_TGZ")"
PRIMA_VOLTA=1
[ -f "$DATI/dettami.py" ] && PRIMA_VOLTA=0

# ------------------------------------------------------------------ 1
titolo "[1/5] Controlli"
[ "$(uname -s)" = "Darwin" ] || errore "questo installer è per Mac."
VER_MAC="$(sw_vers -productVersion)"
MAGGIORE="${VER_MAC%%.*}"
RESTO="${VER_MAC#*.}"
MINORE="${RESTO%%.*}"
if [ "$MAGGIORE" -lt 10 ] || { [ "$MAGGIORE" -eq 10 ] && [ "$MINORE" -lt 15 ]; }; then
    errore "serve macOS 10.15 Catalina o più recente (qui c'è $VER_MAC)."
fi
info "macOS $VER_MAC"
if [ "$(uname -m)" = "arm64" ]; then
    if ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
        errore "questo Mac ha il chip Apple e serve Rosetta. Apri il Terminale, scrivi: softwareupdate --install-rosetta  poi rilancia l'installazione."
    fi
    avviso "Mac con chip Apple: uso la versione Intel tramite Rosetta."
fi
if pkill -f "Dettami.app/Contents/MacOS/Dettami" 2>/dev/null; then
    sleep 1.5
    info "Dettami chiusa per aggiornarla"
fi
[ "$PRIMA_VOLTA" -eq 0 ] && info "Aggiornamento alla versione $VERSIONE: chiave, impostazioni e cronologia restano"

# ------------------------------------------------------------------ 2
titolo "[2/5] Dettami.app (Python incluso: non tocca altro sul Mac)"
rm -rf "$NUOVA"
mkdir -p "$NUOVA/Contents/MacOS" "$NUOVA/Contents/Resources" || errore "non riesco a scrivere in ~/Applications."
TEMP="$(mktemp -d)" || errore "non riesco a creare una cartella temporanea."
tar -xzf "$RUNTIME_TGZ" -C "$TEMP" || { rm -rf "$TEMP"; errore "non riesco a estrarre Python."; }
mv "$TEMP/python/lib" "$NUOVA/Contents/lib" || errore "non riesco a preparare Python."
ESEGUIBILE=""
for candidato in "$TEMP"/python/bin/python3.*; do
    case "$candidato" in *-config) ;; *) [ -x "$candidato" ] && ESEGUIBILE="$candidato" ;; esac
done
[ -n "$ESEGUIBILE" ] || errore "Python incompleto nel pacchetto."
cp "$ESEGUIBILE" "$NUOVA/Contents/MacOS/Dettami" && chmod 755 "$NUOVA/Contents/MacOS/Dettami"
rm -rf "$TEMP"
SITO="$(ls -d "$NUOVA"/Contents/lib/python3.*/site-packages 2>/dev/null | head -n 1)"
[ -n "$SITO" ] || errore "Python incompleto nel pacchetto (site-packages)."
cp "$SETUP/mac/avvio_app.py" "$SITO/sitecustomize.py"
cp "$SETUP/mac/Info.plist" "$NUOVA/Contents/Info.plist"
cp "$SETUP/mac/Dettami.icns" "$NUOVA/Contents/Resources/Dettami.icns"
printf 'APPL????' > "$NUOVA/Contents/PkgInfo"
xattr -dr com.apple.quarantine "$NUOVA" 2>/dev/null
info "Python pronto"

# ------------------------------------------------------------------ 3
titolo "[3/5] Librerie (già incluse, niente da scaricare)"
"$NUOVA/Contents/MacOS/Dettami" -m pip install --no-index --find-links "$SETUP/wheels" --require-hashes \
    --no-deps -r "$SETUP/app/requisiti-mac.txt" --disable-pip-version-check --no-warn-script-location -q \
    || errore "installazione delle librerie non riuscita."
"$NUOVA/Contents/MacOS/Dettami" -c "import numpy, sounddevice, PIL, requests, pystray, pyperclip, Quartz, AppKit, ApplicationServices" \
    || errore "le librerie non si caricano su questo Mac."
xattr -dr com.apple.quarantine "$NUOVA" 2>/dev/null
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mv "$NUOVA" "$APP" || errore "non riesco a mettere Dettami.app in ~/Applications."
info "Librerie installate: $APP"

# ------------------------------------------------------------------ 4
titolo "[4/5] File di Dettami e chiave Groq"
mkdir -p "$DATI" || errore "non riesco a creare $DATI"
for f in "$SETUP"/app/*; do
    nome="$(basename "$f")"
    if [ "$nome" = "config.toml" ] && [ -f "$DATI/config.toml" ]; then
        continue  # le tue impostazioni restano
    fi
    cp "$f" "$DATI/$nome" || errore "non riesco a copiare $nome"
done
cp "$SETUP/mac/disinstalla.command" "$DATI/disinstalla.command" && chmod 755 "$DATI/disinstalla.command"
printf '%s\n' "$RUNTIME_NOME" > "$DATI/versione-runtime.txt"
rm -f "$DATI/argomenti-avvio.json" "$DATI/avvio-ok.json"
xattr -dr com.apple.quarantine "$DATI" 2>/dev/null
info "Cartella: $DATI"

CHIAVE=""
if [ -f "$DATI/.env" ]; then
    CHIAVE="$(sed -n 's/^[[:space:]]*GROQ_API_KEY[[:space:]]*=[[:space:]]*//p' "$DATI/.env" | head -n 1 | tr -d '[:space:]"'"'")"
fi
if [ -n "$CHIAVE" ]; then
    info "Chiave Groq già impostata"
else
    info "Ti serve una chiave Groq gratuita: si apre console.groq.com/keys."
    info "Accedi (anche con Google), premi «Create API Key», copiala e incollala nella finestra."
    open "https://console.groq.com/keys" 2>/dev/null
    MESSAGGIO="Incolla qui la tua chiave Groq (inizia con gsk_)."
    for _ in 1 2 3; do
        CHIAVE="$(osascript -e "display dialog \"$MESSAGGIO\" with title \"Chiave Groq per Dettami\" default answer \"\" buttons {\"Più tardi\", \"Verifica e salva\"} default button \"Verifica e salva\" cancel button \"Più tardi\" with icon note" -e 'text returned of result' 2>/dev/null)" || { CHIAVE=""; break; }
        CHIAVE="$(printf '%s' "$CHIAVE" | tr -d '[:space:]"'"'")"
        [ -n "$CHIAVE" ] || { MESSAGGIO="La casella era vuota: incolla la chiave Groq (inizia con gsk_)."; continue; }
        CODICE="$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Authorization: Bearer $CHIAVE" https://api.groq.com/openai/v1/models)"
        if [ "$CODICE" = "200" ]; then
            break
        elif [ "$CODICE" = "401" ]; then
            MESSAGGIO="Groq dice che questa chiave non è valida. Copiala di nuovo tutta e riprova."
            CHIAVE=""
        else
            avviso "Non riesco a verificare la chiave (connessione?): la salvo lo stesso."
            break
        fi
    done
    if [ -n "$CHIAVE" ]; then
        printf 'GROQ_API_KEY=%s\n' "$CHIAVE" > "$DATI/.env"
        chmod 600 "$DATI/.env"
        info "Chiave salvata"
    else
        avviso "Chiave non inserita: la puoi mettere dopo dal menu di Dettami (icona in alto) → Imposta API key."
    fi
fi

# ------------------------------------------------------------------ 5
titolo "[5/5] Avvio"
if [ "$PRIMA_VOLTA" -eq 1 ] || [ -f "$AGENTE" ]; then
    if "$APP/Contents/MacOS/Dettami" -c 'import sys; sys.path.insert(0, sys.argv[1]); import sistema_mac; sistema_mac.imposta_avvio_automatico(True)' "$DATI"; then
        info "Dettami parte da sola all'accensione (si cambia dalla dashboard)"
    else
        avviso "Avvio automatico non impostato: lo attivi dalla dashboard."
    fi
fi

printf '\n  \033[1;32mFatto: Dettami %s è installata.\033[0m\n\n' "$VERSIONE"
printf '  Tra poco macOS ti chiederà alcuni permessi per Dettami:\n'
printf '    • Microfono            → premi «Consenti»\n'
printf '    • Accessibilità         → apri Impostazioni e attiva Dettami\n'
printf '    • Monitoraggio input    → apri Impostazioni e attiva Dettami\n'
printf '  Quando li hai dati, Dettami si riapre da sola.\n\n'
printf '  Come si usa: \033[1mtieni premuto Option destro (⌥)\033[0m, parla, rilascia.\n'
printf '  L'"'"'icona di Dettami è nella barra in alto, accanto all'"'"'orologio.\n'
open "$APP" || avviso "Non riesco ad aprire Dettami: aprila da Applicazioni nella tua cartella Inizio."
fine 0
