<#
.SYNOPSIS
  Start the chatbot automatically when you log in to Windows, and put a "Local Chat" shortcut on
  the desktop that opens it in the browser. Needs no admin rights; it only creates two shortcuts
  in your own folders, and -Remove deletes them again.

.EXAMPLE
  .\scripts\shortcuts.cmd -Install
  .\scripts\shortcuts.cmd -Status
  .\scripts\shortcuts.cmd -Remove
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$appctl = Join-Path $PSScriptRoot "appctl.ps1"
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Local Chat (background).lnk"
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Local Chat.lnk"

function New-AppShortcut([string]$Path, [string]$Verb, [string]$Description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$appctl`" $Verb"
    $link.WorkingDirectory = $repo
    $link.WindowStyle = 7
    $link.Description = $Description
    $link.Save()
}

if ((-not $Install) -and (-not $Remove) -and (-not $Status)) {
    Write-Host "Use -Install, -Remove or -Status." -ForegroundColor Yellow
    exit 2
}

if ($Install) {
    New-AppShortcut $startup "start -Quiet" "Starts the Local Chat app in the background when you log in"
    New-AppShortcut $desktop "open" "Opens Local Chat in the browser (starts it first if needed)"
    Write-Host "Installed:"
    Write-Host "  starts at login : $startup"
    Write-Host "  desktop shortcut: $desktop"
    Write-Host "The app starts the next time you log in. To start it now:  .\scripts\start.cmd"
}
if ($Remove) {
    foreach ($path in @($startup, $desktop)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path; Write-Host "Removed $path" }
    }
}
if ($Status) {
    Write-Host ("Starts at login : " + $(if (Test-Path -LiteralPath $startup) { "yes ($startup)" } else { "no" }))
    Write-Host ("Desktop shortcut: " + $(if (Test-Path -LiteralPath $desktop) { "yes ($desktop)" } else { "no" }))
}
