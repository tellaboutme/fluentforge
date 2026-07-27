<#
.SYNOPSIS
    Put this repository under version control, ready to push to GitHub.

.DESCRIPTION
    The project ships a .gitignore and a five-job GitHub Actions workflow, but
    has never had a repository for them to run in. This creates one and makes
    the first commit.

    It does not talk to GitHub. Creating the remote needs your account, so the
    script prints the two commands to run once you have made an empty repo.

    Safe to inspect first: it refuses to touch an existing repository, and
    every step is a plain git command you could type yourself.

.PARAMETER Message
    The first commit message. Defaults to a description of the current state.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\git-init.ps1
#>

[CmdletBinding()]
param(
    [string]$Message = "FluentForge: milestones 0-3 complete, full gate passing"
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments)

    Write-Host "   git $($Arguments -join ' ')" -ForegroundColor DarkGray
    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git failed (exit $LASTEXITCODE). Nothing further ran." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host 'Putting FluentForge under version control' -ForegroundColor White
Write-Host "Repository: $RepoRoot" -ForegroundColor DarkGray
Write-Host ''

# --- Preconditions ---------------------------------------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'git is not installed.' -ForegroundColor Red
    Write-Host '  Install from https://git-scm.com/download/win, then reopen this terminal.' -ForegroundColor Yellow
    exit 1
}

if (Test-Path (Join-Path $RepoRoot '.git')) {
    Write-Host 'This is already a git repository. Nothing to do.' -ForegroundColor Yellow
    Write-Host 'Run `git remote -v` to see whether a remote is configured.' -ForegroundColor DarkGray
    exit 0
}

# A commit with no identity fails halfway through, leaving a repository with
# staged files and no history. Better to stop before `git init`.
$userName = (& git config --global user.name) 2>$null
$userEmail = (& git config --global user.email) 2>$null

if (-not $userName -or -not $userEmail) {
    Write-Host 'git has no identity configured, so a commit would fail.' -ForegroundColor Red
    Write-Host '  Set it once, then re-run this script:' -ForegroundColor Yellow
    Write-Host '    git config --global user.name "Your Name"' -ForegroundColor Yellow
    Write-Host '    git config --global user.email "you@example.com"' -ForegroundColor Yellow
    exit 1
}

Write-Host "Committing as: $userName <$userEmail>" -ForegroundColor DarkGray
Write-Host ''

# --- Initialise ------------------------------------------------------------
#
# `main` explicitly: the workflow triggers on it, and git's default branch
# name still varies by version and configuration.

Invoke-Git @('init', '--initial-branch=main')
Invoke-Git @('add', '.')

Write-Host ''
Write-Host 'About to commit these files (first 40):' -ForegroundColor Cyan
& git diff --cached --name-only | Select-Object -First 40
$staged = (& git diff --cached --name-only | Measure-Object).Count
Write-Host "   ... $staged files total" -ForegroundColor DarkGray

# The .gitignore excludes .venv, node_modules, local-data and the caches. If
# any of them slipped through, the first commit would be enormous and the
# mistake is far easier to fix now than after a push.
$leaked = & git diff --cached --name-only |
    Where-Object { $_ -match '(^|/)(\.venv|node_modules|local-data)/' }

if ($leaked) {
    Write-Host ''
    Write-Host 'Refusing to commit: ignored directories were staged anyway.' -ForegroundColor Red
    $leaked | Select-Object -First 10 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host 'Check .gitignore, then run: git rm -r --cached .' -ForegroundColor Yellow
    exit 1
}

Write-Host ''
Invoke-Git @('commit', '-m', $Message)

# --- What to do next -------------------------------------------------------

Write-Host ''
Write-Host 'Done. History starts here.' -ForegroundColor Green
Write-Host ''
Write-Host 'To get GitHub Actions running, create an empty repository on GitHub' -ForegroundColor White
Write-Host '(no README, no .gitignore, no licence), then:' -ForegroundColor White
Write-Host ''
Write-Host '  git remote add origin https://github.com/<you>/fluentforge.git' -ForegroundColor Cyan
Write-Host '  git push -u origin main' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Or, if you have the GitHub CLI, that is one command:' -ForegroundColor White
Write-Host ''
Write-Host '  gh repo create fluentforge --private --source=. --push' -ForegroundColor Cyan
Write-Host ''
Write-Host 'CI runs on that first push: lint, typecheck, tests, PostgreSQL' -ForegroundColor DarkGray
Write-Host 'migrations, fixture drift, and the Playwright suite.' -ForegroundColor DarkGray
