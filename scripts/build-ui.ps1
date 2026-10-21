<#
.SYNOPSIS
  Build the web UI (frontend\dist). The backend serves it at http://127.0.0.1:8000/. Needs Node 22+.

.DESCRIPTION
  Runs "npm ci" (exact versions from package-lock.json) and "npm run build" in the frontend folder.
  npm reads your own npm configuration, so a company registry set with  npm config set registry <url>
  is used automatically.

.EXAMPLE
  .\scripts\build-ui.cmd
#>
$ErrorActionPreference = "Stop"
$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) "frontend"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node was not found on PATH. Install Node 22 or newer." }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "npm was not found on PATH." }
$version = (& node --version).TrimStart("v")
if ([version]($version -replace "^(\d+\.\d+\.\d+).*", '$1') -lt [version]"22.12.0") {
    throw "Node $version is too old: the build needs 22.12.0 or newer."
}

function Show-NpmHelp {
    Write-Host ""
    Write-Host "The UI build failed." -ForegroundColor Red
    Write-Host "  - 403 / 'Unsuitable material' / a web page instead of a package: your web proxy blocks npm downloads." -ForegroundColor Yellow
    Write-Host "    This is a company policy; do not work around it. Ask the Nexus administrators for the npm repository URL, then:" -ForegroundColor Yellow
    Write-Host "      npm config set registry https://<nexus>/repository/<npm-group>/" -ForegroundColor Yellow
    Write-Host "  - 'self-signed certificate' / 'unable to verify the first certificate': the registry uses a company CA. Use the" -ForegroundColor Yellow
    Write-Host "    same PEM file as for pip (see the README):  npm config set cafile ""C:\Users\<you>\certs\company-root-ca.pem""" -ForegroundColor Yellow
    Write-Host "    Never use  npm config set strict-ssl false." -ForegroundColor Yellow
}

Push-Location $frontend
try {
    Write-Host "Installing packages (npm ci) ..."
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Show-NpmHelp; throw "npm ci failed (exit code $LASTEXITCODE)." }
    Write-Host "Building (npm run build) ..."
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { Show-NpmHelp; throw "npm run build failed (exit code $LASTEXITCODE)." }
    Write-Host "Done. Start the app with .\scripts\run.cmd and open http://127.0.0.1:8000/" -ForegroundColor Green
}
finally {
    Pop-Location
}
