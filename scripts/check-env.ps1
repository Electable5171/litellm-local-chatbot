<#
.SYNOPSIS
  Read-only environment check for the office laptop. Needs no admin rights and changes nothing
  except writing one report file.

.DESCRIPTION
  Reports the tooling (Python, uv, Node, Git, Docker, WSL), whether the network can reach the
  package registries, and how the LiteLLM endpoint behaves for the chat model (reasoning shape in
  normal and streaming responses, thinking toggle, context length, embeddings).

  Everything printed is also saved to a report file (default: diagnostics\env-check-<timestamp>.txt
  in the repo root), so you can commit it and push it for review.
  Redacted before it is shown or saved: the API key (and anything shaped like sk-...), your Windows
  user name, the computer name, and credentials inside proxy URLs.
  NOT redacted: the list of model names on the LiteLLM proxy and the LiteLLM address. Read the report
  once before you push it.

.EXAMPLE
  # Run from the repo root. "Bypass" applies to this one process only and needs no admin rights.
  $env:LITELLM_API_KEY = "sk-..."
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1

.EXAMPLE
  # Different model id, custom report path, and try running a container (pulls hello-world)
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-env.ps1 -Model qwen3.8 -OutFile C:\temp\report.txt -DockerRunTest
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://172.17.58.139:4000/v1",
    [string]$Model = "qwen3.8",
    [string]$OutFile = "",
    [switch]$DockerRunTest
)

$ErrorActionPreference = "Continue"
$BaseUrl = $BaseUrl.TrimEnd("/")
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ---------------------------------------------------------------------------
# Output: every line is redacted, printed, and kept for the report file
# ---------------------------------------------------------------------------
$script:Report = New-Object System.Collections.Generic.List[string]
$script:Key = $env:LITELLM_API_KEY

function Redact([string]$Text) {
    if ($null -eq $Text) { return "" }
    if ($script:Key -and $script:Key.Length -ge 6) { $Text = $Text.Replace($script:Key, "<api-key>") }
    $Text = [regex]::Replace($Text, "sk-[A-Za-z0-9_\-]{8,}", "sk-<redacted>")
    $Text = [regex]::Replace($Text, "(?i)(https?://)[^/\s:@]+:[^/\s@]+@", '$1<creds>@')
    if ($env:USERNAME -and $env:USERNAME.Length -ge 3) { $Text = [regex]::Replace($Text, [regex]::Escape($env:USERNAME), "<user>", "IgnoreCase") }
    if ($env:COMPUTERNAME -and $env:COMPUTERNAME.Length -ge 3) { $Text = [regex]::Replace($Text, [regex]::Escape($env:COMPUTERNAME), "<host>", "IgnoreCase") }
    return $Text
}
function Emit([string]$Text, [string]$Color = "") {
    $clean = Redact $Text
    $script:Report.Add($clean)
    if ($Color) { Write-Host $clean -ForegroundColor $Color } else { Write-Host $clean }
}
function Section([string]$Title) { Emit ""; Emit "=== $Title ===" "Cyan" }
function Ok([string]$Msg)   { Emit "  [OK]   $Msg" "Green" }
function Warn([string]$Msg) { Emit "  [WARN] $Msg" "Yellow" }
function Bad([string]$Msg)  { Emit "  [FAIL] $Msg" "Red" }
function Info([string]$Msg) { Emit "         $Msg" }
function Trunc([string]$Text, [int]$Max = 1200) {
    if ($null -eq $Text) { return "" }
    $t = $Text -replace "`r?`n", " "
    if ($t.Length -gt $Max) { return $t.Substring(0, $Max) + " ...[truncated]" }
    return $t
}

function Get-ErrorDetail($ErrorRecord) {
    $msg = $ErrorRecord.Exception.Message
    try {
        $resp = $ErrorRecord.Exception.Response
        if ($resp) {
            $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
            $body = $reader.ReadToEnd()
            return "$msg | HTTP body: $(Trunc $body 600)"
        }
    } catch { }
    return $msg
}

# Runs an external command and keeps the detail when it fails (exit code, output, or the exception text)
function Try-Run([string]$Path, [string[]]$RunArgs = @("--version")) {
    try {
        $out = (& $Path @RunArgs 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
        return @{ Ok = ($null -eq $code -or $code -eq 0); Exit = $code; Out = $out }
    } catch {
        return @{ Ok = $false; Exit = $null; Out = $_.Exception.Message }
    }
}

# Looks in the usual install folders, to tell "installed but not on PATH" from "not installed"
function Find-InCommonPlaces([string]$Exe) {
    $pf = $env:ProgramFiles; $pf86 = ${env:ProgramFiles(x86)}; $lad = $env:LOCALAPPDATA; $up = $env:USERPROFILE
    $patterns = @{
        "git"     = @("$pf\Git\cmd\git.exe", "$pf86\Git\cmd\git.exe", "$lad\Programs\Git\cmd\git.exe", "$up\PortableGit\cmd\git.exe")
        "node"    = @("$pf\nodejs\node.exe", "$pf86\nodejs\node.exe", "$lad\Programs\nodejs\node.exe", "$env:APPDATA\nvm\*\node.exe", "$up\nodejs*\node.exe")
        "npm.cmd" = @("$pf\nodejs\npm.cmd", "$pf86\nodejs\npm.cmd", "$lad\Programs\nodejs\npm.cmd", "$env:APPDATA\npm\npm.cmd")
        "python"  = @("$lad\Programs\Python\Python3*\python.exe", "$pf\Python3*\python.exe")
        "uv"      = @("$up\.local\bin\uv.exe", "$up\.cargo\bin\uv.exe", "$lad\Programs\uv\uv.exe")
    }
    if (-not $patterns.ContainsKey($Exe)) { return $null }
    foreach ($p in $patterns[$Exe]) {
        $hit = Get-Item -Path $p -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Report-Tool([string]$Name, [string]$Exe, [string[]]$VersionArgs = @("--version")) {
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) {
        # The Microsoft Store "python.exe" stub lives in WindowsApps and opens the Store instead of running Python
        if ($cmd.Source -like "*\WindowsApps\*" -and $Exe -in @("python", "py")) {
            Warn "$Name is only the Microsoft Store alias, not a real install: $($cmd.Source)"
            return
        }
        $r = Try-Run $cmd.Source $VersionArgs
        if ($r.Ok) { Ok "$Name $(Trunc $r.Out 120)  ($($cmd.Source))" }
        else       { Bad "$Name found on PATH at $($cmd.Source) but running it FAILED (exit code $($r.Exit)). Output: $(Trunc $r.Out 400)" }
        return
    }
    $found = Find-InCommonPlaces $Exe
    if ($found) {
        $r = Try-Run $found $VersionArgs
        if ($r.Ok) { Warn "$Name is NOT on PATH, but works when run directly: $(Trunc $r.Out 120)  ($found)" }
        else       { Bad "$Name is NOT on PATH and running $found FAILED (exit code $($r.Exit)). Output: $(Trunc $r.Out 400)" }
    } else {
        Warn "$Name not found on PATH or in the usual install folders (not installed)"
    }
}

function Invoke-LLM([string]$Path, $Body, [int]$Timeout = 180) {
    $json = $Body | ConvertTo-Json -Depth 10 -Compress
    return Invoke-RestMethod -Uri "$BaseUrl$Path" -Method Post -Headers $script:Headers `
        -ContentType "application/json" -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec $Timeout
}

# Summarises where a non-streaming answer put the model's reasoning
function Show-ChatResult([string]$Label, $Resp, [double]$Elapsed) {
    $m = $Resp.choices[0].message
    $names = @($m.PSObject.Properties.Name)
    $rcField = $null
    foreach ($candidate in @("reasoning_content", "reasoning")) {
        if (($names -contains $candidate) -and $m.$candidate) { $rcField = $candidate }
    }
    $hasThinkTag = [bool]("$($m.content)" -match "<think>|</think>")
    Ok ("{0}: {1:N1}s, finish={2}, prompt_tokens={3}, completion_tokens={4}" -f $Label, $Elapsed, $Resp.choices[0].finish_reason, $Resp.usage.prompt_tokens, $Resp.usage.completion_tokens)
    Info "message fields: $($names -join ', ')"
    Info "reasoning field with text: $(if ($rcField) { $rcField } else { 'none' }) | <think> tags inside content: $hasThinkTag"
    Info "content: $(Trunc ([string]$m.content) 300)"
    Info "raw message JSON: $(Trunc ($m | ConvertTo-Json -Depth 6 -Compress) 1200)"
}

# Streams a chat completion with .NET HttpClient and summarises the delta format (what the app will receive)
function Test-Stream([string]$Label, $Body) {
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(240)
    try {
        $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, "$BaseUrl/chat/completions")
        $req.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", [string]$script:Key)
        $json = $Body | ConvertTo-Json -Depth 10 -Compress
        $req.Content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, "application/json")
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if (-not $resp.IsSuccessStatusCode) {
            $err = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            Bad "$Label : HTTP $([int]$resp.StatusCode) $(Trunc $err 600)"
            return
        }
        Info ("{0} : headers after {1:N1}s, Content-Type: {2}" -f $Label, $sw.Elapsed.TotalSeconds, $resp.Content.Headers.ContentType)
        $reader = New-Object System.IO.StreamReader($resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
        $deltaKeys = @{}; $chunks = 0; $rcChunks = 0; $contentChunks = 0
        $tFirst = $null; $tFirstReasoning = $null; $tFirstContent = $null
        $finish = $null; $usage = $null; $thinkInContent = $false; $sample = New-Object System.Collections.Generic.List[string]
        while ($null -ne ($line = $reader.ReadLine())) {
            if (-not $line.StartsWith("data:")) { continue }
            $payload = $line.Substring(5).Trim()
            if ($payload -eq "[DONE]") { break }
            try { $obj = $payload | ConvertFrom-Json } catch { continue }
            $chunks++
            if ($null -eq $tFirst) { $tFirst = $sw.Elapsed.TotalSeconds }
            if ($obj.usage) { $usage = $obj.usage }
            if (-not $obj.choices -or $obj.choices.Count -eq 0) { continue }
            $choice = $obj.choices[0]
            if ($choice.finish_reason) { $finish = $choice.finish_reason }
            $delta = $choice.delta
            if ($null -eq $delta) { continue }
            foreach ($n in $delta.PSObject.Properties.Name) { $deltaKeys[$n] = $true }
            $rc = $null
            if ($delta.PSObject.Properties.Name -contains "reasoning_content") { $rc = $delta.reasoning_content }
            if (-not $rc -and ($delta.PSObject.Properties.Name -contains "reasoning")) { $rc = $delta.reasoning }
            if ($rc) { $rcChunks++; if ($null -eq $tFirstReasoning) { $tFirstReasoning = $sw.Elapsed.TotalSeconds } }
            if ($delta.content) {
                $contentChunks++
                if ($null -eq $tFirstContent) { $tFirstContent = $sw.Elapsed.TotalSeconds }
                if ("$($delta.content)" -match "<think>|</think>") { $thinkInContent = $true }
            }
            if ($sample.Count -lt 4) { $sample.Add((Trunc $payload 300)) }
        }
        $fmt = { param($v) if ($null -eq $v) { "n/a" } else { "{0:N1}s" -f $v } }
        Ok ("{0}: {1} chunks in {2:N1}s, finish={3}" -f $Label, $chunks, $sw.Elapsed.TotalSeconds, $finish)
        Info "delta keys seen: $((@($deltaKeys.Keys) | Sort-Object) -join ', ')"
        Info "chunks with reasoning text: $rcChunks | chunks with content: $contentChunks | <think> tags in content: $thinkInContent"
        Info "time to first chunk: $(& $fmt $tFirst) | first reasoning: $(& $fmt $tFirstReasoning) | first content: $(& $fmt $tFirstContent)"
        if ($usage) { Info "usage in stream: prompt=$($usage.prompt_tokens) completion=$($usage.completion_tokens)" } else { Info "usage in stream: not reported" }
        foreach ($s in $sample) { Info "sample chunk: $s" }
    } catch {
        Bad "$Label failed: $($_.Exception.Message)"
    } finally {
        $client.Dispose()
    }
}

# ---------------------------------------------------------------------------
try {
    Emit "litellm-local-chatbot environment report" "Cyan"
    Emit "generated: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    Emit "script params: BaseUrl=$BaseUrl Model=$Model DockerRunTest=$($DockerRunTest.IsPresent)"

    # -----------------------------------------------------------------------
    Section "System"
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($os) { Ok "$($os.Caption) build $($os.BuildNumber) ($($os.OSArchitecture))" }
    Ok "PowerShell $($PSVersionTable.PSVersion)"
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    Info "Running elevated: $isAdmin"
    Info "Execution policy (per scope):"
    Get-ExecutionPolicy -List | ForEach-Object { Info ("  {0,-14} {1}" -f $_.Scope, $_.ExecutionPolicy) }
    try {
        $freeGB = [math]::Round((Get-PSDrive -Name ($env:USERPROFILE.Substring(0, 1))).Free / 1GB, 1)
        Info "Free space on user profile drive: $freeGB GB"
    } catch { Info "Free space: could not determine" }
    $lang = try { (Get-Culture).Name } catch { "?" }
    Info "Culture: $lang"

    # -----------------------------------------------------------------------
    Section "Developer tools"
    Report-Tool "python" "python"
    Report-Tool "py launcher" "py" @("--version")
    Report-Tool "uv" "uv"
    Report-Tool "node" "node"
    Report-Tool "npm" "npm.cmd"
    Report-Tool "git" "git"
    Info "PATH entries (user + machine, as this process sees them):"
    ($env:PATH -split ";") | Where-Object { $_ } | ForEach-Object { Info "  $_" }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Info "Pythons visible to the py launcher:"
        & py -0p 2>&1 | ForEach-Object { Info "  $_" }
    }
    $pyReal = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyReal -and $pyReal.Source -notlike "*\WindowsApps\*") {
        # sqlite-vec needs a Python whose sqlite3 module can load extensions
        $py = & $pyReal.Source -c "import sqlite3,sys; print(sys.version.split()[0], 'sqlite', sqlite3.sqlite_version, 'extensions', hasattr(sqlite3.Connection, 'enable_load_extension'))" 2>&1
        Info "python sqlite check: $py"
        if (("$py") -notmatch "extensions True") { Warn "This Python cannot load SQLite extensions; sqlite-vec would not work with it (uv-managed Python is fine)" }
    }

    # -----------------------------------------------------------------------
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
    if ($LASTEXITCODE -eq 0) { $wsl | Where-Object { $_ -and $_.Trim() } | Select-Object -First 4 | ForEach-Object { Info ("  " + ($_ -replace "`0", "")) } }
    else { Warn "wsl --status failed (WSL may not be installed/enabled)" }

    if ($DockerRunTest -and $docker) {
        Info "Running 'docker run --rm hello-world' ..."
        $run = & docker run --rm hello-world 2>&1
        if ($LASTEXITCODE -eq 0 -and ($run -join "`n") -match "Hello from Docker") { Ok "Container ran successfully" }
        else { Bad "Container test failed:"; $run | Select-Object -First 5 | ForEach-Object { Info "  $_" } }
    }

    # -----------------------------------------------------------------------
    Section "Network: package registries (needed to install dependencies)"
    $sysProxy = [System.Net.WebRequest]::DefaultWebProxy.GetProxy([uri]"https://pypi.org")
    if ($sysProxy.AbsoluteUri -ne "https://pypi.org/") { Info "System proxy for https: $($sysProxy.AbsoluteUri)" } else { Info "No system proxy detected" }
    foreach ($v in @("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")) {
        $val = [Environment]::GetEnvironmentVariable($v)
        if ($val) { Info "env $v = $val" }
    }
    foreach ($u in @(
            "https://pypi.org/simple/fastapi/",
            "https://files.pythonhosted.org/",
            "https://registry.npmjs.org/react",
            "https://github.com",
            "https://objects.githubusercontent.com",
            "https://huggingface.co",
            "https://astral.sh/uv/install.ps1",
            "https://www.python.org/ftp/python/",
            "https://github.com/astral-sh/python-build-standalone/releases",
            "https://release-assets.githubusercontent.com",
            "https://nodejs.org/dist/index.json")) {
        try {
            $r = Invoke-WebRequest -Uri $u -UseBasicParsing -Method Head -TimeoutSec 10
            Ok "$u -> $($r.StatusCode)"
        } catch {
            $status = ""
            try { if ($_.Exception.Response) { $status = "HTTP $([int]$_.Exception.Response.StatusCode) " } } catch { }
            if ($status) { Warn "$u -> ${status}(reachable, but refuses HEAD or needs a path)" } else { Bad "$u -> $($_.Exception.Message)" }
        }
    }

    # -----------------------------------------------------------------------
    Section "LiteLLM at $BaseUrl"
    # LiteLLM is on the internal network: do not send these calls through a corporate proxy
    [System.Net.WebRequest]::DefaultWebProxy = $null

    if (-not $script:Key) { Warn "LITELLM_API_KEY is not set; authenticated checks will likely fail" }
    else { Info ("API key present, {0} characters (value not shown)" -f $script:Key.Length) }
    $script:Headers = @{ "Authorization" = "Bearer $($script:Key)" }
    $root = $BaseUrl -replace "/v1$", ""

    # TCP reachability first, so a network problem is not mistaken for an API problem
    try {
        $uri = [uri]$BaseUrl
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($uri.Host, $uri.Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(5000) -and $tcp.Connected) { Ok "TCP connect to $($uri.Host):$($uri.Port) works"; $tcp.EndConnect($iar) }
        else { Bad "TCP connect to $($uri.Host):$($uri.Port) timed out after 5s (VPN/firewall?)" }
        $tcp.Close()
    } catch { Bad "TCP connect failed: $($_.Exception.Message)" }

    try {
        $ready = Invoke-RestMethod -Uri "$root/health/readiness" -TimeoutSec 10
        Ok "LiteLLM readiness: status=$($ready.status) version=$($ready.litellm_version)"
    } catch { Warn "Readiness probe failed: $(Get-ErrorDetail $_)" }

    $modelIds = @()
    try {
        $models = Invoke-RestMethod -Uri "$BaseUrl/models" -Headers $script:Headers -TimeoutSec 15
        $modelIds = @($models.data | ForEach-Object { $_.id })
        Ok "GET /models returned $($modelIds.Count) model(s) for this key:"
        $modelIds | ForEach-Object { Info "  - $_" }
        if ($modelIds -notcontains $Model) { Warn "Model '$Model' is not in that list; rerun with -Model <one of the ids above>" }
        $embedLike = @($modelIds | Where-Object { $_ -match "(?i)embed|bge|e5-|gte|minilm" })
        if ($embedLike.Count -gt 0) { Ok "Possible embedding models: $($embedLike -join ', ')" } else { Info "No embedding-looking model ids in the list (local embeddings plan stays)" }
    } catch { Bad "GET /models failed: $(Get-ErrorDetail $_)" }

    # Context length: try the info endpoints; each may be blocked for a non-admin key
    foreach ($path in @("/model_group/info", "/model/info")) {
        try {
            $info = Invoke-RestMethod -Uri "$root$path" -Headers $script:Headers -TimeoutSec 15
            $rows = @($info.data | Where-Object { $_.model_group -eq $Model -or $_.model_name -eq $Model })
            if ($rows.Count -eq 0) { Info "$path : reachable, no entry for '$Model'"; continue }
            foreach ($row in $rows) {
                $mi = if ($row.model_info) { $row.model_info } else { $row }
                Ok "$path : max_input_tokens=$($row.max_input_tokens)$($mi.max_input_tokens) max_output_tokens=$($row.max_output_tokens)$($mi.max_output_tokens) supports_reasoning=$($row.supports_reasoning)$($mi.supports_reasoning) mode=$($row.mode)$($mi.mode)"
            }
        } catch { Info "$path : not available to this key: $(Trunc (Get-ErrorDetail $_) 160)" }
    }

    $q = @{ role = "user"; content = "What is 17*23? Answer with just the number." }

    Info ""
    Info "--- Test 1: normal (non-streaming), default thinking ---"
    try {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $r1 = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 1024 }
        Show-ChatResult "Chat (thinking default)" $r1 $sw.Elapsed.TotalSeconds
    } catch { Bad "Chat completion failed: $(Get-ErrorDetail $_)" }

    Info ""
    Info "--- Test 2: thinking OFF via chat_template_kwargs (top-level body field) ---"
    try {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $r2 = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 512;
                                                 chat_template_kwargs = @{ enable_thinking = $false } }
        Show-ChatResult "Chat (enable_thinking=false)" $r2 $sw.Elapsed.TotalSeconds
        Info "If completion_tokens is much lower than test 1 and no reasoning is present, the toggle works through LiteLLM."
    } catch { Bad "Chat with chat_template_kwargs failed (LiteLLM may reject the field): $(Get-ErrorDetail $_)" }

    Info ""
    Info "--- Test 3: thinking OFF via extra_body wrapper (some LiteLLM setups need this form) ---"
    try {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $r3 = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 512;
                                                 extra_body = @{ chat_template_kwargs = @{ enable_thinking = $false } } }
        Show-ChatResult "Chat (extra_body.chat_template_kwargs)" $r3 $sw.Elapsed.TotalSeconds
    } catch { Bad "Chat with extra_body failed: $(Get-ErrorDetail $_)" }

    Info ""
    Info "--- Test 4: STREAMING, default thinking (the format the app will actually receive) ---"
    Test-Stream "Stream (thinking default)" @{ model = $Model; messages = @($q); max_tokens = 1024; stream = $true;
                                                stream_options = @{ include_usage = $true } }

    Info ""
    Info "--- Test 5: STREAMING, thinking OFF ---"
    Test-Stream "Stream (enable_thinking=false)" @{ model = $Model; messages = @($q); max_tokens = 512; stream = $true;
                                                     chat_template_kwargs = @{ enable_thinking = $false } }

    Info ""
    Info "--- Test 6: STREAMING a longer answer with thinking ON (real token-by-token behaviour and speed) ---"
    $long = @{ role = "user"; content = "Explain in about 250 words how a B-tree index speeds up database lookups. Think it through first." }
    Test-Stream "Stream long (thinking default)" @{ model = $Model; messages = @($long); max_tokens = 1500; stream = $true;
                                                    stream_options = @{ include_usage = $true } }

    Info ""
    Info "--- Test 7: context length probe (asks for an impossible max_tokens; the server's error usually states the limit) ---"
    try {
        $null = Invoke-LLM "/chat/completions" @{ model = $Model; messages = @($q); max_tokens = 100000000 } 60
        Warn "Server accepted max_tokens=100000000; it does not enforce a context limit here (unexpected)"
    } catch {
        $detail = Get-ErrorDetail $_
        Info "Server answer: $(Trunc $detail 700)"
        if ($detail -match "(\d{4,7})\s*tokens") { Ok "Context length hint found in the error: $($Matches[1]) tokens (check the sentence above)" }
    }

    # -----------------------------------------------------------------------
    Section "Local port"
    $busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($busy) { Warn "Port 8000 is already in use by PID $($busy.OwningProcess -join ',')" } else { Ok "Port 8000 is free" }
}
catch {
    Bad "Unexpected script error: $($_.Exception.Message) at line $($_.InvocationInfo.ScriptLineNumber)"
}
finally {
    if (-not $OutFile) {
        $repoRoot = Split-Path -Parent $PSScriptRoot
        if (-not $repoRoot) { $repoRoot = (Get-Location).Path }
        $OutFile = Join-Path (Join-Path $repoRoot "diagnostics") ("env-check-{0}.txt" -f (Get-Date).ToString("yyyyMMdd-HHmmss"))
    }
    try {
        $dir = Split-Path -Parent $OutFile
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        [IO.File]::WriteAllLines($OutFile, $script:Report.ToArray(), (New-Object Text.UTF8Encoding($false)))
        Write-Host ""
        Write-Host "Report saved to: $OutFile" -ForegroundColor Cyan
        Write-Host "Read it once, then commit and push it (see docs/RUNBOOK or the chat instructions)." -ForegroundColor Cyan
    } catch {
        Write-Host "Could not write the report file: $($_.Exception.Message)" -ForegroundColor Red
    }
}
