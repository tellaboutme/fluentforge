<#
.SYNOPSIS
    Start FluentForge locally, for Windows PowerShell.

.DESCRIPTION
    Prepares the local SQLite database and curriculum, then launches the API
    and the web app in two new terminal windows.

    Both servers run in the foreground of their own window on purpose: you can
    read their logs, and closing a window stops that server. Nothing is left
    running in the background for you to hunt down later.

    Equivalent to: make migrate, make load-curriculum, then make api and
    make web in two terminals.

.PARAMETER SkipSetup
    Skip migration and curriculum loading. Use on repeat runs.

.PARAMETER Reset
    Delete the local database first and start from an empty one. Useful for
    walking through the new-learner experience again.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Reset
#>

[CmdletBinding()]
param(
    [switch]$SkipSetup,
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    Write-Host ''
    Write-Host "-- $Name" -ForegroundColor Cyan

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host 'FluentForge local development' -ForegroundColor White

if ($Reset) {
    $data = Join-Path $RepoRoot 'local-data'
    if (Test-Path $data) {
        Write-Host "Removing $data" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $data
    }
    # A reset database needs seeding again whatever the caller asked for.
    $SkipSetup = $false
}

if (-not $SkipSetup) {
    Invoke-Step -Name 'Apply migrations' -Command 'uv' -Arguments @('run', 'alembic', 'upgrade', 'head')
    Invoke-Step -Name 'Load curriculum' -Command 'uv' -Arguments @('run', 'python', 'scripts/load_curriculum.py', '--publish')
}

# Each server gets its own window. `-NoExit` keeps it open if the server dies
# on startup, so the traceback is still readable.
$apiCommand = "Set-Location '$RepoRoot'; Write-Host 'API - http://localhost:8000/docs' -ForegroundColor Green; uv run uvicorn apps.api.app.main:app --reload --port 8000"
$webCommand = "Set-Location '$RepoRoot'; Write-Host 'Web - http://localhost:3000' -ForegroundColor Green; pnpm --filter web dev"

Write-Host ''
Write-Host 'Starting the API in a new window...' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit', '-Command', $apiCommand

# The web app calls the API on first paint. Giving uvicorn a moment avoids a
# connection error on the very first page load.
Start-Sleep -Seconds 3

Write-Host 'Starting the web app in a new window...' -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit', '-Command', $webCommand

Write-Host ''
Write-Host 'Two windows are starting.' -ForegroundColor Green
Write-Host '  API   http://localhost:8000/docs'
Write-Host '  Web   http://localhost:3000'
Write-Host ''
Write-Host 'Give Next.js 10-20 seconds to compile on the first run.' -ForegroundColor DarkGray
Write-Host 'Close either window to stop that server.' -ForegroundColor DarkGray
