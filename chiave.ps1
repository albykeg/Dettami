# Dettami - finestra per inserire e verificare la API key di Groq.
# Esce con codice 0 se la chiave è stata salvata, 1 se annullato.
param([string]$Cartella = $PSScriptRoot)

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$fileChiave = Join-Path $Cartella '.env'
$chiaveAttuale = ''
if (Test-Path $fileChiave) {
    $riga = Get-Content $fileChiave | Where-Object { $_ -match '^\s*GROQ_API_KEY\s*=' } | Select-Object -First 1
    if ($riga) { $chiaveAttuale = ($riga -split '=', 2)[1].Trim().Trim('"') }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Dettami - API key Groq'
$form.ClientSize = New-Object System.Drawing.Size(500, 250)
$form.StartPosition = 'Manual'
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$form.Location = New-Object System.Drawing.Point(($area.Right - 540), ($area.Bottom - 320))
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$icona = Join-Path $Cartella 'icona.ico'
if (Test-Path $icona) { $form.Icon = New-Object System.Drawing.Icon($icona) }

$testo = New-Object System.Windows.Forms.Label
$testo.Text = "Dettami usa Groq per trascrivere la voce. È gratuito: crea la tua chiave (basta registrarsi, nessuna carta), copiala e incollala qui sotto."
$testo.Location = New-Object System.Drawing.Point(18, 14)
$testo.Size = New-Object System.Drawing.Size(465, 48)

$link = New-Object System.Windows.Forms.LinkLabel
$link.Text = '1. Apri la pagina per creare la chiave  (console.groq.com/keys)'
$link.Location = New-Object System.Drawing.Point(18, 70)
$link.Size = New-Object System.Drawing.Size(465, 24)
$link.Add_LinkClicked({ Start-Process 'https://console.groq.com/keys' })

$etichetta = New-Object System.Windows.Forms.Label
$etichetta.Text = '2. Incolla qui la chiave (inizia con gsk_):'
$etichetta.Location = New-Object System.Drawing.Point(18, 100)
$etichetta.Size = New-Object System.Drawing.Size(465, 22)

$campo = New-Object System.Windows.Forms.TextBox
$campo.Location = New-Object System.Drawing.Point(18, 124)
$campo.Size = New-Object System.Drawing.Size(464, 28)
$campo.Text = $chiaveAttuale

$stato = New-Object System.Windows.Forms.Label
$stato.Location = New-Object System.Drawing.Point(18, 158)
$stato.Size = New-Object System.Drawing.Size(465, 40)

$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'Verifica e salva'
$ok.Location = New-Object System.Drawing.Point(242, 204)
$ok.Size = New-Object System.Drawing.Size(140, 34)

$annulla = New-Object System.Windows.Forms.Button
$annulla.Text = 'Annulla'
$annulla.Location = New-Object System.Drawing.Point(392, 204)
$annulla.Size = New-Object System.Drawing.Size(90, 34)
$annulla.DialogResult = [System.Windows.Forms.DialogResult]::Cancel

$form.AcceptButton = $ok
$form.CancelButton = $annulla

$ok.Add_Click({
    $k = ($campo.Text -replace '\s', '').Trim('"')
    if ($k.Length -lt 20) {
        $stato.ForeColor = [System.Drawing.Color]::Firebrick
        $stato.Text = 'Sembra incompleta: copia e incolla la chiave intera.'
        return
    }
    $stato.ForeColor = [System.Drawing.Color]::DimGray
    $stato.Text = 'Verifico la chiave...'
    $form.Refresh()
    $salva = $false
    try {
        Invoke-RestMethod -Uri 'https://api.groq.com/openai/v1/models' -Headers @{ Authorization = "Bearer $k" } -TimeoutSec 15 | Out-Null
        $salva = $true
    } catch {
        $codice = $null
        try { $codice = [int]$_.Exception.Response.StatusCode } catch {}
        if ($codice -eq 401) {
            $stato.ForeColor = [System.Drawing.Color]::Firebrick
            $stato.Text = 'Chiave non valida: controlla di averla copiata tutta.'
            return
        }
        $r = [System.Windows.Forms.MessageBox]::Show(
            "Non riesco a verificare la chiave (connessione o rete aziendale).`nLa salvo comunque?",
            'Dettami', 'YesNo', 'Warning')
        if ($r -eq [System.Windows.Forms.DialogResult]::Yes) { $salva = $true } else { return }
    }
    if ($salva) {
        [IO.File]::WriteAllText($fileChiave, "GROQ_API_KEY=$k`r`n", (New-Object Text.UTF8Encoding($false)))
        $form.Tag = 'ok'
        $form.Close()
    }
})

$form.Controls.AddRange(@($testo, $link, $etichetta, $campo, $stato, $ok, $annulla))
$form.Add_Shown({ $form.WindowState = 'Normal'; $form.Activate(); $campo.Focus() })
[void]$form.ShowDialog()
if ($form.Tag -eq 'ok') { exit 0 } else { exit 1 }
