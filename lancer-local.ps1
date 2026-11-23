# Lance Reserva sur ce poste Windows, pour tester avant de déployer.
#
#   .\lancer-local.cmd                 installe ce qui manque, compile le site, démarre
#   .\lancer-local.cmd -Installer      réinstalle les dépendances (après une mise à jour du code)
#   .\lancer-local.cmd -InstallerPdf   installe GTK (MSYS2) pour que le PDF fonctionne
#   .\lancer-local.cmd -Tests          lance d'abord les tests du serveur
#   .\lancer-local.cmd -Port 8080      autre port que 8000
#
# Le site s'ouvre sur http://localhost:8000. Ctrl+C pour arrêter.
# Paiements simulés : aucun débit réel, aucune clé nécessaire.
param(
    [switch]$Installer,
    [switch]$InstallerPdf,
    [switch]$Tests,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Web = Join-Path $Root "web"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nErreur : $text" -ForegroundColor Red; exit 1 }
function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "la commande « $exe $($arguments -join ' ') » a échoué (code $LASTEXITCODE)." }
}

# ---------- outils : uv (qui fournit Python 3.12) et Node.js ----------

Step "Outils"
$env:Path = "$env:USERPROFILE\.local\bin;$env:ProgramFiles\nodejs;$env:Path"
if (-not (Has "uv")) {
    if (-not (Has "winget")) { Fail "uv manque. Installez-le : https://docs.astral.sh/uv/ puis relancez." }
    Write-Host "Installation de uv (gestionnaire Python)…"
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements | Out-Host
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Has "uv")) { Fail "uv installé mais introuvable : fermez cette fenêtre, rouvrez-la et relancez." }
}
$nodeOk = $false
if (Has "node") { $nodeOk = [int]((node -p "process.versions.node.split('.')[0]")) -ge 20 }
if (-not $nodeOk) {
    if (-not (Has "winget")) { Fail "Node.js 20 ou plus récent manque : https://nodejs.org puis relancez." }
    Write-Host "Installation de Node.js…"
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements | Out-Host
    $env:Path = "$env:ProgramFiles\nodejs;$env:Path"
    if (-not (Has "node")) { Fail "Node.js installé mais introuvable : fermez cette fenêtre, rouvrez-la et relancez." }
}
Write-Host "uv $((uv --version) -replace 'uv ', ''), Node $(node --version)"

# ---------- serveur : Python 3.12 et dépendances ----------

Set-Location $Backend
if ($Installer -or -not (Test-Path $Python)) {
    Step "Python 3.12 et dépendances du serveur (quelques minutes la première fois)"
    Run "uv" @("venv", "--python", "3.12", "--allow-existing", ".venv")
    Run "uv" @("pip", "install", "--python", $Python, "-e", ".", "pytest")
}

# ---------- configuration locale ----------

$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) {
    Step "Configuration locale (backend\.env)"
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = ([Convert]::ToBase64String($bytes)) -replace '[/+=]', ''
    $content = @"
# Configuration LOCALE de test. Ne pas copier sur le serveur : il a la sienne.
RESERVA_ENV=dev
RESERVA_SECRET_KEY=$secret
RESERVA_DATA_DIR=data
RESERVA_PUBLIC_BASE_URL=http://localhost:$Port
RESERVA_CORS_ORIGINS=["http://localhost:$Port","http://localhost:5173"]
RESERVA_ADMIN_LOGINS=["695249549"]
# Paiements simulés : tout paiement réussit aussitôt, sans débit.
RESERVA_PAYMENT_SIMULATION=true
RESERVA_AI_PROVIDER=rules
RESERVA_DISPATCH_CHANNEL=console
"@
    # UTF-8 sans BOM : un BOM gênerait la lecture de la première ligne.
    [IO.File]::WriteAllText($EnvFile, $content, (New-Object Text.UTF8Encoding $false))
    Write-Host "Créée. Base et photos de test : backend\data"
}

# ---------- PDF : WeasyPrint a besoin de GTK sous Windows ----------

$GtkBin = "C:\msys64\ucrt64\bin"
if ($InstallerPdf) {
    Step "GTK pour le PDF (MSYS2, une dizaine de minutes)"
    if (-not (Test-Path "C:\msys64\usr\bin\bash.exe")) {
        if (-not (Has "winget")) { Fail "winget manque : installez MSYS2 depuis https://www.msys2.org puis relancez." }
        winget install --id MSYS2.MSYS2 -e --accept-source-agreements --accept-package-agreements | Out-Host
    }
    & "C:\msys64\usr\bin\bash.exe" -lc "pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-pango"
}
if (Test-Path "$GtkBin\libpango-1.0-0.dll") { $env:WEASYPRINT_DLL_DIRECTORIES = $GtkBin }
# Sous Windows PowerShell, rediriger les erreurs d'un programme les rend bloquantes en mode « Stop ».
$ErrorActionPreference = "Continue"
& $Python -c "import weasyprint" 2>$null | Out-Null
$pdfOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"

# ---------- tests ----------

if ($Tests) {
    Step "Tests du serveur"
    if (-not $pdfOk) { Write-Host "(Sans GTK, les tests qui fabriquent un PDF échoueront : lancez d'abord -InstallerPdf.)" -ForegroundColor Yellow }
    Run $Python @("-m", "pytest", "-q")
}

# ---------- site ----------

Set-Location $Web
if ($Installer -or -not (Test-Path (Join-Path $Web "node_modules"))) {
    Step "Dépendances du site"
    Run "npm.cmd" @("ci", "--no-audit", "--no-fund")
}
Step "Compilation du site"
Run "npm.cmd" @("run", "build")

# ---------- démarrage ----------

Set-Location $Backend
Step "Démarrage"
Write-Host ""
Write-Host "  Reserva : http://localhost:$Port" -ForegroundColor Green
Write-Host "  Compte administrateur : inscrivez-vous avec le 695 249 549"
Write-Host "  Paiements simulés : aucun débit réel"
if ($pdfOk) { Write-Host "  PDF : disponible" }
else { Write-Host "  PDF : indisponible (GTK manque). Pour l'activer : .\lancer-local.cmd -InstallerPdf" -ForegroundColor Yellow }
Write-Host "  Codes « mot de passe oublié » : affichés dans cette fenêtre"
Write-Host "  Ctrl+C pour arrêter"
Write-Host ""
Start-Process "cmd.exe" -ArgumentList "/c timeout /t 4 >nul & start http://localhost:$Port" -WindowStyle Hidden
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
