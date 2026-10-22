<#
.SYNOPSIS
  Start the chatbot on this laptop. It listens on 127.0.0.1 only. Needs no admin rights.

.DESCRIPTION
  1. Checks that backend\.env exists (creates it from .env.example once).
  2. Installs the locked dependencies, one of two ways:
       uv   : uv sync --locked. Downloads from public PyPI (the URLs recorded in uv.lock).
       pip  : python -m venv + pip install --require-hashes from backend\requirements.lock.txt.
              pip uses YOUR configured index, for example the company Nexus
              (pip config: index-url, or the PIP_INDEX_URL variable). Every file is hash-checked,
              so a mirror cannot change what is installed.
     -Installer auto (the default) uses pip when an index is configured for pip, otherwise uv.
  3. Starts the backend: http://127.0.0.1:8000

.EXAMPLE
  .\scripts\run.cmd
  .\scripts\run.cmd -Installer pip     # force the pip / company-index route
  .\scripts\run.cmd -SkipSync          # start without checking dependencies (offline)
  .\scripts\run.cmd -Background        # check dependencies, then (re)start in the background
#>
[CmdletBinding()]
param(
    [ValidateSet("auto", "uv", "pip")][string]$Installer = "auto",
    [switch]$SkipSync,
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend ".env.example") $envFile
    Write-Host "Created $envFile" -ForegroundColor Yellow
    Write-Host "Open it, set LITELLM_API_KEY (your virtual key), save, then run this script again." -ForegroundColor Yellow
    exit 1
}

# Run a command and return its output. pip prints harmless warnings on stderr (for example
# "features are always enabled: truststore"), and Windows PowerShell 5.1 turns any stderr text from
# a native command into a terminating error when $ErrorActionPreference is "Stop".
function Get-NativeOutput([scriptblock]$Command) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return @(& $Command 2>&1 | ForEach-Object { "$_" }) }
    finally { $ErrorActionPreference = $saved }
}

function Test-PipIndexConfigured {
    if ($env:PIP_INDEX_URL) { return $true }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { return $false }
    $cfg = (Get-NativeOutput { python -m pip config list }) -join "`n"
    return ($cfg -match "index-url")
}

function Show-InstallHelp {
    Write-Host ""
    Write-Host "Dependency install failed." -ForegroundColor Red
    Write-Host "  - 403 / 'Unsuitable material' for files.pythonhosted.org: your web proxy blocks package downloads." -ForegroundColor Yellow
    Write-Host "    This is a company policy; do not work around it. Use the company package index (Nexus):" -ForegroundColor Yellow
    Write-Host "    see 'Using the company Nexus' in the README, then run  .\scripts\run.cmd -Installer pip" -ForegroundColor Yellow
    Write-Host "  - 'certificate ... not trusted' / CERTIFICATE_VERIFY_FAILED: the Nexus certificate comes from a company CA that Windows" -ForegroundColor Yellow
    Write-Host "    does not trust. Get that CA certificate from the Nexus administrators, check its fingerprint with them, then run:" -ForegroundColor Yellow
    Write-Host "      python -m pip config set global.cert ""C:\Users\<you>\certs\company-root-ca.pem""" -ForegroundColor Yellow
    Write-Host "    Never use --trusted-host or turn certificate checking off. See the README section 'If pip says the certificate is not trusted'." -ForegroundColor Yellow
    Write-Host "  - '[X509] PEM lib': the CA file set in pip global.cert is damaged (see the README section on certificates)." -ForegroundColor Yellow
    Write-Host "  - Offline, with dependencies already installed: run  .\scripts\run.cmd -SkipSync" -ForegroundColor Yellow
}

function Install-WithUv {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv was not found on PATH. Install it for your user (no admin needed): pip install --user uv"
    }
    # uv only reads proxy settings from environment variables, not from the Windows settings.
    # Use the system proxy for package downloads when no proxy is set (LiteLLM calls never use it).
    if (-not $env:HTTPS_PROXY) {
        $sys = [System.Net.WebRequest]::DefaultWebProxy.GetProxy([uri]"https://pypi.org")
        if ($sys.AbsoluteUri -ne "https://pypi.org/") {
            $env:HTTPS_PROXY = $sys.AbsoluteUri.TrimEnd("/")
            Write-Host "Using the system proxy for package downloads: $($env:HTTPS_PROXY)"
        }
    }
    # Trust the Windows certificate store (a company proxy usually re-signs HTTPS traffic).
    if (-not $env:UV_NATIVE_TLS)   { $env:UV_NATIVE_TLS = "1" }
    if (-not $env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS = "1" }
    Write-Host "Installing dependencies with uv (uv sync --locked) ..."
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { Show-InstallHelp; throw "uv sync failed (exit code $LASTEXITCODE)." }
}

# If pip is told to trust a CA file (global.cert), make sure Python can read it, so the error is clear.
function Test-PipCertFile {
    # Only a line that looks like a path counts; warnings printed by pip are ignored.
    $cfg = Get-NativeOutput { python -m pip config get global.cert } |
        Where-Object { $_ -notmatch "^(WARNING|ERROR|NOTICE)" -and $_.Trim() } | Select-Object -First 1
    if (-not $cfg) { return }
    $path = "$cfg".Trim()
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "pip is configured to trust a CA file that does not exist: $path" -ForegroundColor Red
        throw "CA certificate file not found."
    }
    $res = (& python -c "import ssl,sys; ssl.create_default_context().load_verify_locations(sys.argv[1]); print('OK')" $path 2>&1 | Out-String).Trim()
    if ($res -ne "OK") {
        Write-Host "The CA file that pip trusts cannot be read as a certificate: $path" -ForegroundColor Red
        Write-Host "  Python says: $res" -ForegroundColor Yellow
        Write-Host "  '[X509] PEM lib' means the file starts with -----BEGIN CERTIFICATE----- but is damaged: a missing or cut-off line," -ForegroundColor Yellow
        Write-Host "  a changed character, or a missing -----END CERTIFICATE----- line. This happens when the text is copied through" -ForegroundColor Yellow
        Write-Host "  email, chat or a web page. Get the certificate file again as a file (attachment or export), not as pasted text." -ForegroundColor Yellow
        Write-Host "  Check it:  python -c ""import ssl,sys; ssl.create_default_context().load_verify_locations(sys.argv[1]); print('OK')"" ""$path""" -ForegroundColor Yellow
        throw "CA certificate file is not valid."
    }
}

function Install-WithPip([string]$VenvDir) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python was not found on PATH." }
    $ok = (& python -c "import sys; print(sys.version_info >= (3, 12))") -eq "True"
    if (-not $ok) { throw "Python 3.12 or newer is required." }
    $vpy = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $vpy)) {
        Write-Host "Creating the virtual environment $VenvDir ..."
        & python -m venv $VenvDir | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed." }
    }
    $req = Join-Path $backend "requirements.lock.txt"
    $stamp = Join-Path $VenvDir "requirements.sha256"
    $hash = (Get-FileHash $req -Algorithm SHA256).Hash
    if ((Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $hash)) {
        Write-Host "Dependencies are up to date."
        return $vpy
    }
    # Use the Windows certificate store (pip 24.2+), because a company index or proxy has its own CA.
    if (-not $env:PIP_USE_FEATURE) {
        $v = (Get-NativeOutput { & $vpy -m pip --version } | Select-Object -First 1) -replace "^pip (\d+)\.(\d+).*", '$1.$2'
        $parts = $v.Split(".")
        if (([int]$parts[0] -gt 24) -or (([int]$parts[0] -eq 24) -and ([int]$parts[1] -ge 2))) { $env:PIP_USE_FEATURE = "truststore" }
    }
    Test-PipCertFile
    $index = if ($env:PIP_INDEX_URL) { "PIP_INDEX_URL" } else { "your pip configuration" }
    Write-Host "Installing dependencies with pip from $index (hash-checked) ..."
    & $vpy -m pip install --require-hashes --no-deps --disable-pip-version-check -r $req | Out-Host
    if ($LASTEXITCODE -ne 0) { Show-InstallHelp; throw "pip install failed (exit code $LASTEXITCODE)." }
    Set-Content -Path $stamp -Value $hash
    return $vpy
}

$useIndexRoute = ($Installer -eq "pip") -or (($Installer -eq "auto") -and (Test-PipIndexConfigured))
$venvPip = Join-Path $backend ".venv-pip"

Push-Location $backend
try {
    $python = $null
    if ($SkipSync) {
        if ($useIndexRoute) { $python = Join-Path $venvPip "Scripts\python.exe" }
    }
    elseif ($useIndexRoute) {
        Write-Host "Installer: pip (company index)" -ForegroundColor Cyan
        $python = Install-WithPip $venvPip
    }
    else {
        Write-Host "Installer: uv (public PyPI)" -ForegroundColor Cyan
        Install-WithUv
    }

    if (-not (Test-Path (Join-Path $repo "frontend\dist"))) {
        Write-Host "Note: the web UI is not built yet; only the API is available. Build it with  .\scripts\build-ui.cmd" -ForegroundColor Yellow
    }
    if ($Background) {
        Write-Host "Starting in the background (stop it with .\scripts\stop.cmd)" -ForegroundColor Cyan
        if ($python) { & $python -m app.daemon start --restart } else { & uv run --locked python -m app.daemon start --restart }
        if ($LASTEXITCODE -ne 0) { throw "The app did not start (exit code $LASTEXITCODE). See .\scripts\logs.cmd" }
    }
    else {
        Write-Host "Starting on http://127.0.0.1:8000  (Ctrl+C to stop)" -ForegroundColor Cyan
        if ($python) { & $python -m app } else { & uv run --locked python -m app }
        if ($LASTEXITCODE -ne 0) { throw "The app exited with code $LASTEXITCODE." }
    }
}
finally {
    Pop-Location
}
