<#
.SYNOPSIS
  Start the chatbot on this laptop. It listens on 127.0.0.1 only. Needs no admin rights.

.DESCRIPTION
  1. Checks that uv is installed and that backend\.env exists (creates it from .env.example once).
  2. Installs the locked dependencies (uv sync --locked).
  3. Starts the backend: http://127.0.0.1:8000

.EXAMPLE
  .\scripts\run.cmd
  .\scripts\run.cmd -SkipSync     # start without checking dependencies (offline)
#>
[CmdletBinding()]
param([switch]$SkipSync)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found on PATH. Install it for your user (no admin needed): pip install --user uv"
}

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend ".env.example") $envFile
    Write-Host "Created $envFile" -ForegroundColor Yellow
    Write-Host "Open it, set LITELLM_API_KEY (your virtual key), save, then run this script again." -ForegroundColor Yellow
    exit 1
}

Push-Location $backend
try {
    if (-not $SkipSync) {
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

        Write-Host "Installing dependencies (uv sync --locked) ..."
        & uv sync --locked
        if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit code $LASTEXITCODE). If you are offline, use -SkipSync." }
    }

    if (-not (Test-Path (Join-Path $repo "frontend\dist"))) {
        Write-Host "Note: the web UI is not built yet; only the API is available (/api/health)." -ForegroundColor Yellow
    }
    Write-Host "Starting on http://127.0.0.1:8000  (Ctrl+C to stop)" -ForegroundColor Cyan
    & uv run --locked python -m app
    if ($LASTEXITCODE -ne 0) { throw "The app exited with code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
