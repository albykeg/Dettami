# Disinstalla Dettami per l'utente corrente.
param([string]$Cartella = $PSScriptRoot, [switch]$Silenzioso, [switch]$DaCopia)

# Gira da una copia temporanea, così può cancellare la propria cartella.
if (-not $DaCopia) {
    $copia = Join-Path ([IO.Path]::GetTempPath()) 'dettami-disinstalla.ps1'
    Copy-Item $PSCommandPath $copia -Force
    $argomenti = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$copia`"",
                   '-Cartella', "`"$Cartella`"", '-DaCopia')
    if ($Silenzioso) { $argomenti += '-Silenzioso' }
    Start-Process powershell.exe -ArgumentList $argomenti -WindowStyle Hidden
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
if (-not $Silenzioso) {
    $r = [System.Windows.Forms.MessageBox]::Show(
        "Disinstallare Dettami?`n`nVerranno eliminati anche impostazioni, API key e cronologia.",
        'Dettami', 'YesNo', 'Question')
    if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { exit 1 }
}

$cartellaMin = $Cartella.ToLower()
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($cartellaMin) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'Dettami.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Dettami.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Dettami.lnk') -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dettami' -Recurse -ErrorAction SilentlyContinue

# Sicurezza: cancella solo se è davvero la cartella di Dettami
$nome = Split-Path $Cartella -Leaf
if ($nome -eq 'Dettami' -and (Test-Path (Join-Path $Cartella 'dettami.py')) -and (Test-Path (Join-Path $Cartella 'motore.py'))) {
    Remove-Item $Cartella -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $Silenzioso) {
    [void][System.Windows.Forms.MessageBox]::Show('Dettami è stata disinstallata.', 'Dettami', 'OK', 'Information')
}
