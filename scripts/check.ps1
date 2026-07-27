<#
.SYNOPSIS
    The `make check` gate, for Windows PowerShell.

.DESCRIPTION
    Windows PowerShell 5.1 has no `&&`, and `make` is not installed by default,
    so `docs/DEVELOPMENT.md`'s "run the underlying commands directly" is
    awkward to do by hand. This runs the same steps in the same order and stops
    at the first failure, so the first error you see is the one that matters.

    Equivalent to: make bootstrap, make format, make capture-fixtures, make check.

.PARAMETER SkipBootstrap
    Skip dependency installation. Use once dependencies are already installed.

.PARAMETER SkipFormat
    Skip the formatters. Use when you want to see whether formatting is
    already clean rather than fixing it in place.

.PARAMETER SkipFixtures
    Skip re-capturing API fixtures. Only safe when no API response shape changed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipBootstrap,
    [switch]$SkipFormat,
    [switch]$SkipFixtures
)

$ErrorActionPreference = 'Stop'

# Run from the repository root regardless of where this was invoked.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$PySources = @('apps/api', 'scripts', 'services/worker', 'tests')

$script:StepNumber = 0

function Invoke-Step {
    <#
        Run one command, echo it, and abort the whole run if it fails.

        Native executables do not throw on a non-zero exit, so $LASTEXITCODE is
        checked explicitly. Without that, a failing test suite would scroll past
        and the run would report success.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $script:StepNumber++
    Write-Host ''
    Write-Host "-- [$script:StepNumber] $Name " -ForegroundColor Cyan -NoNewline
    Write-Host ('-' * [Math]::Max(1, 60 - $Name.Length)) -ForegroundColor DarkGray
    Write-Host "   $Command $($Arguments -join ' ')" -ForegroundColor DarkGray

    & $Command @Arguments
    $exit = $LASTEXITCODE

    if ($exit -ne 0) {
        Write-Host ''
        Write-Host "FAILED at step $script:StepNumber : $Name (exit $exit)" -ForegroundColor Red
        Write-Host 'Nothing after this step ran. Fix the above, then re-run.' -ForegroundColor Red
        exit $exit
    }
}

function Test-Tool {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Hint)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Host "Missing required tool: $Name" -ForegroundColor Red
        Write-Host "  $Hint" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "FluentForge verification gate" -ForegroundColor White
Write-Host "Repository: $RepoRoot" -ForegroundColor DarkGray

Test-Tool -Name 'uv'   -Hint 'Install from https://docs.astral.sh/uv/ then reopen the terminal.'
Test-Tool -Name 'pnpm' -Hint 'Install with: npm install -g pnpm'

# --- Dependencies ----------------------------------------------------------

if (-not $SkipBootstrap) {
    Invoke-Step -Name 'Install Python dependencies' -Command 'uv' -Arguments @('sync', '--extra', 'dev')
    Invoke-Step -Name 'Install web dependencies' -Command 'pnpm' -Arguments @('install')
}

# --- Formatting ------------------------------------------------------------
#
# Runs before the linter deliberately: `ruff format --check` in the lint step
# reports formatting as a failure, and there is no reason to make a human fix
# by hand what the formatter fixes in place.

if (-not $SkipFormat) {
    Invoke-Step -Name 'Format Python' -Command 'uv' -Arguments (@('run', 'ruff', 'format') + $PySources)
    Invoke-Step -Name 'Autofix Python lint' -Command 'uv' -Arguments (@('run', 'ruff', 'check', '--fix') + $PySources)
    Invoke-Step -Name 'Format web' -Command 'pnpm' -Arguments @('-r', '--if-present', 'format:write')
}

# --- API contract fixtures -------------------------------------------------
#
# The web client is hand-written, so its types record an assumption about the
# API. The fixtures are what test that assumption against reality. Any change
# to a response shape makes the committed fixture stale.

if (-not $SkipFixtures) {
    Invoke-Step -Name 'Capture API fixtures' -Command 'uv' -Arguments @('run', 'python', 'scripts/capture_api_fixtures.py')
}

# --- The gate --------------------------------------------------------------

Invoke-Step -Name 'Lint Python' -Command 'uv' -Arguments (@('run', 'ruff', 'format', '--check') + $PySources)
Invoke-Step -Name 'Check Python lint rules' -Command 'uv' -Arguments (@('run', 'ruff', 'check') + $PySources)
Invoke-Step -Name 'Typecheck Python' -Command 'uv' -Arguments @('run', 'mypy', 'apps/api/app', 'scripts')
Invoke-Step -Name 'Validate curriculum' -Command 'uv' -Arguments @('run', 'python', 'scripts/validate_curriculum.py')
Invoke-Step -Name 'Python tests' -Command 'uv' -Arguments @('run', 'pytest')
Invoke-Step -Name 'Lint and typecheck web' -Command 'pnpm' -Arguments @('-r', '--if-present', 'lint')
Invoke-Step -Name 'Typecheck web' -Command 'pnpm' -Arguments @('-r', '--if-present', 'typecheck')
Invoke-Step -Name 'Web tests' -Command 'pnpm' -Arguments @('-r', '--if-present', 'test')

Write-Host ''
Write-Host "All $script:StepNumber steps passed." -ForegroundColor Green
Write-Host 'Not covered here: make e2e (Playwright, needs browsers via make e2e-install).' -ForegroundColor DarkGray
