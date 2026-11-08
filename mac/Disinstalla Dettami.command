#!/bin/bash
# Toglie Dettami da questo Mac: app, avvio automatico, permessi, impostazioni, chiave e cronologia.
set -u
APP="$HOME/Applications/Dettami.app"
DATI="$HOME/Library/Application Support/Dettami"
AGENTE="$HOME/Library/LaunchAgents/io.github.albykeg.dettami.plist"

if [ "${1:-}" != "--senza-conferma" ]; then
    osascript -e 'display dialog "Tolgo Dettami da questo Mac, con impostazioni, chiave Groq e cronologia." with title "Disinstalla Dettami" buttons {"Annulla", "Disinstalla"} default button "Annulla" cancel button "Annulla" with icon caution' >/dev/null 2>&1 || exit 0
fi

pkill -f "Dettami.app/Contents/MacOS/Dettami" 2>/dev/null && sleep 1.5
rm -f "$AGENTE"
rm -rf "$APP" "$HOME/Applications/.Dettami-in-installazione.app"
tccutil reset All io.github.albykeg.dettami >/dev/null 2>&1
rm -rf "$DATI"
osascript -e 'display notification "Dettami è stata tolta da questo Mac." with title "Dettami"' >/dev/null 2>&1
echo "Dettami è stata disinstallata."
