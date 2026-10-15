<#
.SYNOPSIS
  Read-only environment check for the office laptop. Needs no admin rights and changes nothing.

.DESCRIPTION
  Reports the tooling (Python, uv, Node, Git, Docker, WSL), whether the network can reach
  the package registries, and how the LiteLLM endpoint behaves for the Qwen3 model
  (reasoning shape, thinking toggle, embeddings).
  Paste the full output back into the chat. The API key is never printed.

.EXAMPLE
  # Run from the repo root. "Bypass" applies to this one process only and needs no admin rights.
  $env:LITELLM_API_KEY = "sk-..."
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1

.EXAMPLE
  # Also try running a container (pulls hello-world from Docker Hub)
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1 -DockerRunTest
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://172.17.58.139:4000/v1",
    [string]$Model = "Qwen/Qwen3.8-27B-FP8",
    [switch]$DockerRunTest
)

$ErrorActionPreference = "Continue"
$BaseUrl = $BaseUrl.TrimEnd("/")

function Section([string]$Title) { Write-Host ""; Write-Host "=== $Title ===" -ForegroundColor Cyan }
function Ok([string]$Msg)   { Write-Host "  [OK]   $Msg" -ForegroundColor Green }
function Warn([string]$Msg) { Write-Host "  [WARN] $Msg" -ForegroundColor Yellow }
function Bad([string]$Msg)  { Write-Host "  [FAIL] $Msg" -ForegroundColor Red }
function Info([string]$Msg) { Write-Host "         $Msg" }

# Runs an external command. Returns its first output line, or $null if it isn't installed or fails.
function Get-ToolVersion([string]$Exe, [string[]]$VersionArgs = @("--version")) {
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return $null }
    # The Microsoft Store "python.exe" stub lives in WindowsApps and opens the Store instead of running Python
    if ($cmd.Source -like "*\WindowsApps\*") { return "STORE-STUB ($($cmd.Source))" }
    try {
        $out = & $cmd.Source @VersionArgs 2>&1 | Select-Object -First 1
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) { return $null }
        return "$out  ($($cmd.Source))"
    } catch { return $null }
}

function Report-Tool([string]$Name, [string]$Exe, [string[]]$VersionArgs = @("--version")) {
    $v = Get-ToolVersion $Exe $VersionArgs
    if (-not $v)                    { Warn "$Name not found" }
    elseif ($v -like "STORE-STUB*") { Warn "$Name is only the Microsoft Store alias, not a real install: $v" }
    else                            { Ok "$Name $v" }
}

# ---------------------------------------------------------------------------
Section "System"
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
if ($os) { Ok "$($os.Caption) build $($os.BuildNumber) ($($os.OSArchitecture))" }
Ok "PowerShell $($PSVersionTable.PSVersion)"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
Info "Running elevated: $isAdmin"
Info "Execution policy (per scope):"
Get-ExecutionPolicy -List | ForEach-Object { Info ("  {0,-14} {1}" -f $_.Scope, $_.ExecutionPolicy) }
$freeGB = [math]::Round((Get-PSDrive -Name ($env:USERPROFILE.Substring(0,1))).Free / 1GB, 1)
Info "Free space on user profile drive: $freeGB GB"

# ---------------------------------------------------------------------------
Section "Developer tools"
Report-Tool "python" "python"
Report-Tool "py launcher" "py" @("--version")
Report-Tool "uv" "uv"
Report-Tool "node" "node"
Report-Tool "npm" "npm.cmd"
Report-Tool "git" "git"
if (Get-Command py -ErrorAction SilentlyContinue) {
    Info "Pythons visible to the py launcher:"
    & py -0p 2>&1 | ForEach-Object { Info "  $_" }
}

# ---------------------------------------------------------------------------
Section "Docker"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Warn "docker CLI not on PATH (Docker Desktop is not installed, or its CLI is not on PATH for this user)"
} else {
    Ok "docker CLI: $($docker.Source)"
    $clientVer = & docker version --format "{{.Client.Version}}" 2>&1
    Info "Client version: $clientVer"
    $serverVer = & docker version --format "{{.Server.Version}}" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Ok "Docker engine is RUNNING (server $serverVer)"
        $ctx = & docker context show 2>&1; Info "Context: $ctx"
        $osType = & docker info --format "{{.OSType}}" 2>&1; Info "Engine OS type: $osType"
    } else {
        Bad "Docker engine NOT reachable. Is Docker Desktop started? Output:"
        $serverVer | Select-Object -First 3 | ForEach-Object { Info "  $_" }
    }
}
$groups = (whoami /groups) -join "`n"
if ($groups -match "docker-users") { Ok "User is in the 'docker-users' group" }
else { Warn "User is NOT in 'docker-users'. Docker Desktop usually refuses non-admin users who are not in this group." }
$dockerProc = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if ($dockerProc) { Info "Docker Desktop process is running" } else { Info "Docker Desktop process is not running" }
Info "WSL status:"
$wsl = & wsl.exe --status 2>&1
if ($LASTEXITCODE -eq 0) { $wsl | Where-Object { $_ -and $_.Trim() } | Select-Object -First 4 | ForEach-Object { Info ("  " + ($_ -replace "`0","")) } }
else { Warn "wsl --status failed (WSL may not be installed/enabled)" }

if ($DockerRunTest -and $docker) {
    Info "Running 'docker run --rm hello-world' ..."
    $run = & docker run --rm hello-world 2>&1
    if ($LASTEXITCODE -eq 0 -and ($run -join "`n") -match "Hello from Docker") { Ok "Container ran successfully" }
    else { Bad "Container test failed:"; $run | Select-Object -First 5 | ForEach-Object { Info "  $_" } }
}

# ---------------------------------------------------------------------------
Section "Network: package registries (needed to install dependencies)"
$proxy = [System.Net.WebRequest]::DefaultWebProxy.GetProxy([uri]"https://pypi.org")
if ($proxy.AbsoluteUri -ne "https://pypi.org/") { Info "System proxy for https: $($proxy.AbsoluteUri)" } else { Info "No system proxy detected" }
foreach ($u in @(
        "https://pypi.org/simple/fastapi/",
        "https://registry.npmjs.org/react",
        "https://github.com",
        "https://huggingface.co",
        "https://astral.sh/uv/install.ps1",
        "https://nodejs.org/dist/index.json")) {
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -Method Head -TimeoutSec 10
        Ok "$u -> $($r.StatusCode)"
    } catch {
        Bad "$u -> $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
Section "LiteLLM at $BaseUrl"
$key = $env:LITELLM_API_KEY
if (-not $key) { Warn "LITELLM_API_KEY is not set; authenticated checks will likely fail" }
else { Info ("Using key {0}...{1}" -f $key.Substring(0, [math]::Min(5, $key.Length)), $key.Substring([math]::Max(0, $key.Length - 3))) }
$headers = @{ "Authorization" = "Bearer $key" }

function Invoke-LLM([string]$Path, $Body, [int]$Timeout = 120) {
    $json = $Body | ConvertTo-Json -Depth 10 -Compress
    return Invoke-RestMethod -Uri "$BaseUrl$Path" -Method Post -Headers $headers `
        -ContentType "application/json" -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec $Timeout
}

$root = $BaseUrl -replace "/v1$", ""
try { $null = Invoke-RestMethod -Uri "$root/health/liveliness" -TimeoutSec 10; Ok "LiteLLM is alive ($root/health/liveliness)" }
catch { Warn "Liveliness probe failed: $($_.Exception.Message)" }

try {
    $models = Invoke-RestMethod -Uri "$BaseUrl/models" -Headers $headers -TimeoutSec 15
    Ok "GET /models returned $($models.data.Count) model(s):"
    $models.data | ForEach-Object { Info "  - $($_.id)" }
    if ($models.data.id -notcontains $Model) { Warn "Model '$Model' is not in the list; rerun with -Model <id>" }
} catch { Bad "GET /models failed: $($_.Exception.Message)" }

try {
    $info = Invoke-RestMethod -Uri "$root/model/info" -Headers $headers -TimeoutSec 15
    $info.data | Where-Object { $_.model_name -eq $Model } | ForEach-Object {
        Info "model/info: max_input_tokens=$($_.model_info.max_input_tokens) max_output_tokens=$($_.model_info.max_output_tokens) mode=$($_.model_info.mode)"
    }
} catch { Info "model/info not available to this key (that's fine)" }

function Show-ChatResult($Label, $Resp, $Elapsed) {
    $m = $Resp.choices[0].message
    $hasRc = [bool]($m.PSObject.Properties.Name -contains "reasoning_content" -and $m.reasoning_content)
    $hasThinkTag = [bool]($m.content -match "<think>|</think>")
    Ok ("{0}: {1:N1}s, finish={2}, prompt_tokens={3}, completion_tokens={4}" -f $Label, $Elapsed, $Resp.choices[0].finish_reason, $Resp.usage.prompt_tokens, $Resp.usage.completion_tokens)
    Info "reasoning_content field present: $hasRc | <think> tags inside content: $hasThinkTag"
    $c = "$($m.content)"; if ($c.Length -gt 160) { $c = $c.Substring(0,160) + "..." }
    Info "content: $($c -replace "`r?`n", ' ')"
}

$q = @{ role = "user"; content = "What is 17*23? Answer with just the number." }
try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r1 = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 1024 }
    Show-ChatResult "Chat (thinking default)" $r1 $sw.Elapsed.TotalSeconds
} catch { Bad "Chat completion failed: $($_.Exception.Message)" }

try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r2 = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 256;
                                             chat_template_kwargs = @{ enable_thinking = $false } }
    Show-ChatResult "Chat (enable_thinking=false)" $r2 $sw.Elapsed.TotalSeconds
} catch { Bad "Chat with chat_template_kwargs failed (LiteLLM may reject the param): $($_.Exception.Message)" }

try {
    $null = Invoke-LLM "/embeddings" @{ model = $Model; input = "hello" } 30
    Ok "Embeddings endpoint answered for the chat model (unexpected but usable)"
} catch { Info "Embeddings via LiteLLM: not available (expected; we plan to embed locally)" }

# ---------------------------------------------------------------------------
Section "Local port"
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) { Warn "Port 8000 is already in use by PID $($busy.OwningProcess -join ',')" } else { Ok "Port 8000 is free" }

Write-Host ""
Write-Host "Done. Copy everything above into the chat (the API key is not printed)." -ForegroundColor Cyan
