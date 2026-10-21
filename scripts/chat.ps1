<#
.SYNOPSIS
  Chat with the model from the command line (the web UI comes later). The app must be running.

.EXAMPLE
  .\scripts\chat.cmd "What is 17*23?"
  .\scripts\chat.cmd --no-think "Say hi in three words"
  .\scripts\chat.cmd -i                   # interactive; /new starts over, /quit leaves
#>
$ErrorActionPreference = "Stop"
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"
$venvPython = Join-Path $backend ".venv-pip\Scripts\python.exe"

Push-Location $backend
try {
    if (Test-Path $venvPython) {
        & $venvPython -m app.chat_cli @args
    }
    else {
        & uv run --locked python -m app.chat_cli @args
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
