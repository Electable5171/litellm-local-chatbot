<#
.SYNOPSIS
  Upload a document to the running app and watch it being read and embedded.
  The web UI for documents comes later; this checks that reading and embedding work on this laptop.

.EXAMPLE
  .\scripts\upload-doc.cmd C:\Users\me\Documents\report.pdf
  .\scripts\upload-doc.cmd -List
  .\scripts\upload-doc.cmd -Delete <id>
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Path,
    [switch]$List,
    [string]$Delete,
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

function Show-Failure($err) {
    $body = $err.ErrorDetails.Message
    if ($body) { Write-Host "The app answered: $body" -ForegroundColor Red }
    else { Write-Host $err.Exception.Message -ForegroundColor Red }
}

function Show-Docs($docs) {
    foreach ($d in $docs) {
        "{0}  {1,-10} {2,4}/{3,-4} parts  {4}  {5}" -f $d.id, $d.status, $d.embedded_count, $d.chunk_count, $d.filename, $d.error
    }
}

try {
    if ($List) {
        Show-Docs (Invoke-RestMethod -Uri "$BaseUrl/api/documents" -UseBasicParsing).documents
        return
    }
    if ($Delete) {
        Invoke-RestMethod -Method Delete -Uri "$BaseUrl/api/documents/$Delete" -UseBasicParsing | Out-Null
        Write-Host "Deleted $Delete"
        return
    }
    if (-not $Path) { throw "Give the path of a file: .\scripts\upload-doc.cmd C:\path\file.pdf" }
    $file = Get-Item -LiteralPath $Path
    $name = [uri]::EscapeDataString($file.Name)
    Write-Host "Uploading $($file.Name) ($([math]::Round($file.Length / 1KB)) KB) ..."
    $doc = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/documents" -InFile $file.FullName `
        -ContentType "application/octet-stream" -Headers @{ "X-Filename" = $name } -UseBasicParsing
    Write-Host "Read $($doc.chunk_count) parts. Embedding (about 3 seconds per batch of 32) ..."
    $started = Get-Date
    do {
        Start-Sleep -Seconds 2
        $doc = Invoke-RestMethod -Uri "$BaseUrl/api/documents/$($doc.id)" -UseBasicParsing
        Write-Host ("  {0}/{1} parts embedded" -f $doc.embedded_count, $doc.chunk_count)
    } while ($doc.status -eq "processing")
    $secs = [math]::Round(((Get-Date) - $started).TotalSeconds)
    if ($doc.status -eq "ready") { Write-Host "Ready after $secs s. Id: $($doc.id)" -ForegroundColor Green }
    else { Write-Host "Failed: $($doc.error)" -ForegroundColor Red; exit 1 }
}
catch {
    Show-Failure $_
    exit 1
}
