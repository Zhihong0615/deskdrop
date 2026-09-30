$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runtimeDir = Join-Path $env:LOCALAPPDATA 'DeskDrop\runtime'
$portableNode = Join-Path $runtimeDir 'node.exe'

function Get-UsableNode {
  $candidate = Get-Command node -ErrorAction SilentlyContinue
  if ($candidate) {
    $versionText = (& $candidate.Source --version 2>$null | Select-Object -First 1)
    if ($versionText -match '^v(\d+)\.' -and [int]$Matches[1] -ge 18) { return $candidate.Source }
  }
  if (Test-Path $portableNode) { return $portableNode }
  return $null
}

try {
  $node = Get-UsableNode
  if (-not $node) {
    Write-Host 'Preparing DeskDrop for first use (downloading the portable Node.js runtime)...' -ForegroundColor Cyan
    $processor = $env:PROCESSOR_ARCHITEW6432
    if (-not $processor) { $processor = $env:PROCESSOR_ARCHITECTURE }
    $arch = if ($processor -match 'ARM64') { 'arm64' } else { 'x64' }
    $releases = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -TimeoutSec 30
    $release = $releases | Where-Object { $_.lts } | Select-Object -First 1
    if (-not $release) { throw 'Could not find a current Node.js LTS release.' }
    $version = $release.version
    $archiveName = "node-$version-win-$arch.zip"
    $archiveUrl = "https://nodejs.org/dist/$version/$archiveName"
    $tempDir = Join-Path $runtimeDir 'download'
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $archivePath = Join-Path $tempDir $archiveName
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -TimeoutSec 180 -UseBasicParsing
    Expand-Archive -Path $archivePath -DestinationPath $tempDir -Force
    $downloadedNode = Get-ChildItem -Path $tempDir -Filter 'node.exe' -Recurse | Select-Object -First 1
    if (-not $downloadedNode) { throw 'The Node.js download did not contain node.exe.' }
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Copy-Item -Path $downloadedNode.FullName -Destination $portableNode -Force
    Remove-Item -Path $tempDir -Recurse -Force
    $node = $portableNode
    Write-Host 'Runtime ready.' -ForegroundColor Green
  }

  Write-Host 'Opening DeskDrop in your browser. Keep this window open while receiving files.' -ForegroundColor Cyan
  $browserJob = Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process 'http://localhost:8787' }
  & $node (Join-Path $root 'server.js')
  Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
} catch {
  Write-Host "`nDeskDrop could not start: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host 'Check your internet connection for first-time setup, or install Node.js 18+ and try again.' -ForegroundColor Yellow
  exit 1
}
