<#
.SYNOPSIS
  Start, stop and check the chatbot in the background (no terminal window stays open).
  Normally used through start.cmd, stop.cmd, status.cmd, open.cmd and logs.cmd.

.EXAMPLE
  .\scripts\start.cmd             # start in the background (nothing happens if it already runs)
  .\scripts\start.cmd -Restart    # stop it first, then start it again
  .\scripts\stop.cmd
  .\scripts\status.cmd
  .\scripts\open.cmd              # start it if needed, then open the browser
  .\scripts\logs.cmd -Lines 100
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("start", "stop", "status", "open", "logs")][string]$Command,
    [switch]$Restart,
    [switch]$Quiet,
    [switch]$Force,
    [int]$Lines = 40
)

$ErrorActionPreference = "Stop"
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"

# The Python of the environment that run.cmd installed (the company-index route first).
$python = $null
foreach ($candidate in @((Join-Path $backend ".venv-pip\Scripts\python.exe"), (Join-Path $backend ".venv\Scripts\python.exe"))) {
    if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
}
if (-not $python) {
    Write-Host "The app is not installed yet. Run  .\scripts\run.cmd  once (it installs the dependencies), stop it with Ctrl+C, then use this command." -ForegroundColor Yellow
    exit 2
}
if (($Command -eq "start") -and (-not (Test-Path -LiteralPath (Join-Path $backend ".env")))) {
    Write-Host "backend\.env is missing. Run  .\scripts\run.cmd  once to create it, set LITELLM_API_KEY in it, then try again." -ForegroundColor Yellow
    exit 2
}

$arguments = @("-m", "app.daemon", $Command)
if ($Command -eq "start") {
    if ($Restart) { $arguments += "--restart" }
    if ($Quiet) { $arguments += "--quiet" }
}
if (($Command -eq "stop") -and $Force) { $arguments += "--force" }
if ($Command -eq "logs") { $arguments += @("-n", "$Lines") }

Push-Location $backend
try {
    & $python @arguments
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
