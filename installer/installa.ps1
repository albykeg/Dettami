# Installa o aggiorna Dettami per l'utente corrente.
# Non servono permessi di amministratore, non serve Python installato, non tocca altri programmi.
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
try { $Host.UI.RawUI.WindowTitle = 'Installazione Dettami' } catch {}
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$setup    = $PSScriptRoot
$sorg     = Join-Path $setup 'app'
$runtime  = Join-Path $setup 'runtime'
$dest     = Join-Path $env:LOCALAPPDATA 'Programs\Dettami'
$versione = (Get-Content (Join-Path $sorg 'versione.txt') -Raw).Trim()
# Dettami fino alla 1.2 si chiamava Dettatura: se c'è la vecchia installazione, ne prende i dati
$vecchia     = Join-Path $env:LOCALAPPDATA 'Programs\Dettatura'
$regVecchia  = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dettatura'
$daDettatura = Test-Path (Join-Path $vecchia 'motore.py')
$eraInAvvio  = $false
# è un aggiornamento solo se un'installazione precedente è arrivata fino in fondo
$aggiornamento = (Test-Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dettami') -or $daDettatura

function Titolo($t) { Write-Host ''; Write-Host "  $t" -ForegroundColor Cyan }
function Info($t)   { Write-Host "      $t" -ForegroundColor Gray }
function Avviso($t) { Write-Host "      $t" -ForegroundColor Yellow }
function Chiudi($codice) {
    Write-Host ''
    Read-Host '  Premi Invio per chiudere' | Out-Null
    exit $codice
}

# Esegue un programma senza che i suoi avvisi su stderr fermino lo script (PowerShell 5.1).
function Esegui([string]$exe, [string[]]$argomenti) {
    $prima = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $uscita = & $exe @argomenti 2>&1 | Out-String }
    finally { $ErrorActionPreference = $prima }
    return [pscustomobject]@{ Codice = $LASTEXITCODE; Uscita = $uscita }
}

function Processi-Dettami {
    $cartella = $dest.ToLower()
    $cartellaVecchia = $vecchia.ToLower()
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            if ($_.ProcessId -eq $PID -or -not $_.CommandLine) { return $false }
            $riga = $_.CommandLine.ToLower()
            $riga.Contains($cartella) -or $riga.Contains($cartellaVecchia)
        }
}

# Chiede la chiave nella finestra dell'installer (ripiego se la finestra grafica non si apre).
function Chiave-Da-Console($fileChiave) {
    for ($i = 0; $i -lt 3; $i++) {
        $k = ((Read-Host '      Incolla qui la chiave (tasto destro o Ctrl+V) e premi Invio') -replace '\s', '').Trim('"')
        if (-not $k) { return $false }
        try {
            Invoke-RestMethod -Uri 'https://api.groq.com/openai/v1/models' -Headers @{ Authorization = "Bearer $k" } -TimeoutSec 15 | Out-Null
        } catch {
            $codice = $null
            try { $codice = [int]$_.Exception.Response.StatusCode } catch {}
            if ($codice -eq 401) { Avviso 'Chiave non valida: controlla di averla copiata tutta e riprova.'; continue }
            Avviso 'Non riesco a verificarla (rete): la salvo comunque.'
        }
        [IO.File]::WriteAllText($fileChiave, "GROQ_API_KEY=$k`r`n", (New-Object Text.UTF8Encoding($false)))
        return $true
    }
    return $false
}

trap {
    Write-Host ''
    Write-Host "  ERRORE: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '  Fai una foto di questa schermata e mandala a chi ti ha passato Dettami,' -ForegroundColor Red
    Write-Host '  oppure apri una segnalazione su github.com/albykeg/dettami/issues' -ForegroundColor Red
    Chiudi 1
}

Write-Host ''
Write-Host '  ==================================================' -ForegroundColor White
if ($daDettatura) {
    Write-Host "     Dettatura diventa DETTAMI $versione" -ForegroundColor White
} elseif ($aggiornamento) {
    Write-Host "     Aggiornamento di DETTAMI alla versione $versione" -ForegroundColor White
} else {
    Write-Host "     Installazione di DETTAMI $versione" -ForegroundColor White
}
Write-Host '     Dettatura vocale con AI, in qualsiasi programma' -ForegroundColor Gray
Write-Host '  ==================================================' -ForegroundColor White

# ------------------------------------------------------------------ 1
Titolo '[1/6] Preparazione'
$aperti = @(Processi-Dettami)
foreach ($p in $aperti) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
if ($aperti.Count -gt 0) { Start-Sleep -Milliseconds 800; Info 'Dettami chiusa per aggiornarla' }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Info "Cartella: $dest"

if ($daDettatura) {
    Info 'Trovata la vecchia Dettatura: porto in Dettami chiave, impostazioni, dizionario e cronologia'
    $daPortare = '.env', 'config.toml', 'impostazioni.json', 'cronologia.jsonl', 'cronologia.txt',
                 'cronologia-vecchia.txt', 'uso.json', 'stato.json', 'prompt.txt'
    foreach ($f in $daPortare) {
        $da = Join-Path $vecchia $f
        $a  = Join-Path $dest $f
        if ((Test-Path $da) -and -not (Test-Path $a)) { Copy-Item $da $a -Force }
    }
    $audio = Join-Path $vecchia 'audio_non_elaborati'
    if ((Test-Path $audio) -and -not (Test-Path (Join-Path $dest 'audio_non_elaborati'))) {
        Copy-Item $audio $dest -Recurse -Force
    }
    $eraInAvvio = Test-Path (Join-Path ([Environment]::GetFolderPath('Startup')) 'Dettatura.lnk')
    Info 'fatto: la vecchia versione la tolgo alla fine, quando Dettami è installata'
}

# ------------------------------------------------------------------ 2
Titolo '[2/6] Python (incluso: non tocca altre installazioni)'
$pyZip = Get-ChildItem $runtime -Filter 'python-*-win64.zip' | Select-Object -First 1
if (-not $pyZip) { throw 'Pacchetto incompleto: manca Python. Estrai di nuovo lo zip.' }
$pyDir  = Join-Path $dest 'python'
$pyExe  = Join-Path $pyDir 'python.exe'
$pywExe = Join-Path $pyDir 'pythonw.exe'
$marcatore = Join-Path $pyDir 'versione-runtime.txt'
$attuale = ''
if (Test-Path $marcatore) { $attuale = (Get-Content $marcatore -Raw).Trim() }
if ((Test-Path $pyExe) -and ($attuale -eq $pyZip.Name)) {
    Info 'già presente'
} else {
    if (Test-Path $pyDir) { Remove-Item $pyDir -Recurse -Force }
    $estratto = $false
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path $tar) {
        $r = Esegui $tar @('-xf', $pyZip.FullName, '-C', $dest)
        $estratto = ($r.Codice -eq 0) -and (Test-Path $pyExe)
    }
    if (-not $estratto) {
        Info 'estrazione in corso (può richiedere un minuto)...'
        Expand-Archive -Path $pyZip.FullName -DestinationPath $dest -Force
    }
    if (-not (Test-Path $pyExe)) { throw 'Estrazione di Python non riuscita.' }
    Set-Content -Path $marcatore -Value $pyZip.Name -Encoding ASCII
    Info 'pronto'
}

# ------------------------------------------------------------------ 3
Titolo '[3/6] Componenti'
$r = Esegui $pyExe @('-m', 'pip', 'install', '--no-index',
    '--find-links', (Join-Path $runtime 'wheels'),
    '-r', (Join-Path $sorg 'requisiti-windows.txt'),
    '--disable-pip-version-check', '--no-warn-script-location', '-q')
if ($r.Codice -ne 0) { Write-Host $r.Uscita; throw 'Installazione dei componenti non riuscita.' }
Info 'installati'

# ------------------------------------------------------------------ 4
Titolo '[4/6] Programma'
$file = 'dettami.py', 'motore.py', 'indicatore.py', 'dashboard.py', 'dashboard.html',
        'aggiornamenti.py', 'aggiorna.py', 'chiave.ps1', 'disinstalla.ps1', 'icona.ico',
        'LEGGIMI.md', 'versione.txt', 'requisiti-windows.txt'
foreach ($f in $file) { Copy-Item (Join-Path $sorg $f) (Join-Path $dest $f) -Force }
Copy-Item (Join-Path $sorg 'config.toml') (Join-Path $dest 'config.esempio.toml') -Force
Remove-Item (Join-Path $dest '__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
$config = Join-Path $dest 'config.toml'
if (Test-Path $config) {
    Info 'le tue impostazioni sono state mantenute'
} else {
    Copy-Item (Join-Path $sorg 'config.toml') $config
    Info 'impostazioni predefinite create'
}
Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# ------------------------------------------------------------------ 5
Titolo '[5/6] Chiave Groq (gratuita)'
$fileChiave = Join-Path $dest '.env'
$haChiave = (Test-Path $fileChiave) -and ((Get-Content $fileChiave -Raw) -match 'GROQ_API_KEY\s*=\s*\S{20,}')
if ($haChiave) {
    Info 'già impostata'
} else {
    Info 'Ti apro la pagina di Groq nel browser: registrati gratis e premi "Create API Key".'
    Info 'Poi copia la chiave e incollala nella finestrella di Dettami (in basso a destra).'
    try { Start-Process 'https://console.groq.com/keys' }
    catch { Avviso 'Apri tu il browser su:  https://console.groq.com/keys' }
    $salvata = $false
    try {
        $global:LASTEXITCODE = 1
        & (Join-Path $dest 'chiave.ps1') -Cartella $dest
        $salvata = ($LASTEXITCODE -eq 0)
    } catch {
        Avviso "La finestra non si è aperta: incolla la chiave qui sotto."
        $salvata = Chiave-Da-Console $fileChiave
    }
    if ($salvata) {
        Info 'salvata e verificata'
    } else {
        Avviso 'Saltata: potrai inserirla dopo da icona di Dettami > Imposta API key.'
    }
}

# ------------------------------------------------------------------ 6
Titolo '[6/6] Collegamenti'
$shell = New-Object -ComObject WScript.Shell
function Crea-Collegamento($percorso, $extra = '') {
    $c = $shell.CreateShortcut($percorso)
    $c.TargetPath = $pywExe
    $c.Arguments = ("`"$(Join-Path $dest 'dettami.py')`" $extra").Trim()
    $c.WorkingDirectory = $dest
    $c.Description = 'Dettatura vocale con AI'
    $c.IconLocation = Join-Path $dest 'icona.ico'
    $c.Save()
}
Crea-Collegamento (Join-Path ([Environment]::GetFolderPath('Programs')) 'Dettami.lnk')
Crea-Collegamento (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Dettami.lnk')
Info 'icona "Dettami" sul Desktop e nel menu Start (apre la dashboard)'

$avvio = Join-Path ([Environment]::GetFolderPath('Startup')) 'Dettami.lnk'
if ($aggiornamento) {
    if ((Test-Path $avvio) -or $eraInAvvio) { Crea-Collegamento $avvio '--avvio'; Info 'avvio automatico: mantenuto' }
} else {
    $risposta = Read-Host '      Vuoi che parta da sola all''accensione del PC? [S/n]'
    if ($risposta -notmatch '^\s*[nN]') { Crea-Collegamento $avvio '--avvio'; Info 'avvio automatico: attivo' }
}

# Voce in Impostazioni > App installate (per disinstallare come un programma normale)
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dettami'
New-Item -Path $reg -Force | Out-Null
$disinstalla = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $dest 'disinstalla.ps1')`""
$dimensioneKB = [int]((Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object -Property Length -Sum).Sum / 1KB)
$stringhe = @{
    DisplayName = 'Dettami'; DisplayVersion = $versione; Publisher = 'Dettami'
    DisplayIcon = (Join-Path $dest 'icona.ico'); InstallLocation = $dest
    UninstallString = $disinstalla; QuietUninstallString = "$disinstalla -Silenzioso"
}
foreach ($k in $stringhe.Keys) { New-ItemProperty -Path $reg -Name $k -Value $stringhe[$k] -PropertyType String -Force | Out-Null }
foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty -Path $reg -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
New-ItemProperty -Path $reg -Name 'EstimatedSize' -Value $dimensioneKB -PropertyType DWord -Force | Out-Null
Info 'registrata in Impostazioni > App installate'

# Tolta la vecchia Dettatura solo ora che Dettami è installata (se qualcosa si fosse fermato prima, la vecchia funziona ancora)
if ($daDettatura) {
    foreach ($posto in 'Programs', 'Desktop', 'Startup') {
        Remove-Item (Join-Path ([Environment]::GetFolderPath($posto)) 'Dettatura.lnk') -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $regVecchia -Recurse -Force -ErrorAction SilentlyContinue
    # la vecchia cartella sparisce solo se tutti i tuoi file sono arrivati nella nuova
    $mancanti = @($daPortare | Where-Object { (Test-Path (Join-Path $vecchia $_)) -and -not (Test-Path (Join-Path $dest $_)) })
    if ($mancanti.Count -eq 0) {
        Remove-Item $vecchia -Recurse -Force -ErrorAction SilentlyContinue
        Info 'vecchia Dettatura tolta: da ora si chiama Dettami'
    } else {
        Avviso "Non ho potuto copiare: $($mancanti -join ', '). La vecchia cartella resta in $vecchia"
    }
}

# ------------------------------------------------------------------ fine
Start-Process -FilePath $pywExe -ArgumentList "`"$(Join-Path $dest 'dettami.py')`"" -WorkingDirectory $dest

Write-Host ''
Write-Host '  ==================================================' -ForegroundColor Green
Write-Host '     FATTO! Dettami è avviata e si apre la dashboard.' -ForegroundColor Green
Write-Host '     Per riaprirla: icona "Dettami" sul Desktop.' -ForegroundColor Green
Write-Host ''
Write-Host '     Tieni premuto CTRL DESTRO, parla e rilascia.' -ForegroundColor White
Write-Host '     Doppio tocco = mani libere   |   SHIFT = traduci' -ForegroundColor Gray
Write-Host '  ==================================================' -ForegroundColor Green

if (-not $aggiornamento) {
    Write-Host ''
    $prova = Read-Host '  Vuoi fare subito una prova del microfono? [S/n]'
    if ($prova -notmatch '^\s*[nN]') {
        $prima = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $pyExe (Join-Path $dest 'dettami.py') --prova
        $ErrorActionPreference = $prima
    }
}
Chiudi 0
