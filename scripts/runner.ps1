<#
.SYNOPSIS
    A job runner Claude can drive through the shared project folder.

.DESCRIPTION
    Claude works in a sandbox whose proxy blocks PyPI and the npm registry, so
    it cannot run pytest, vitest, tsc or mypy itself. It can, however, read and
    write files in this repository, and so can this script. That shared folder
    is the whole channel: no network, no credentials, no remote access.

    Start this, leave it running, and Claude can request a run and read the
    output. Ctrl+C closes the channel.

.NOTES
    WHAT THIS GIVES AWAY -- read once, then decide.

    A request of the form `exec: <command>` runs <command> in PowerShell with
    your full privileges. The named tasks below are shortcuts, not limits.

    So: anything that can write to .runner/request.txt can run anything as
    you. Claude writes that file, and Claude also reads web pages, error
    output and third-party files. Text in any of those could try to steer what
    gets written. That is the actual risk, and it is not hypothetical enough
    to ignore.

    What keeps it manageable:

    - The channel only exists while this window is open. Ctrl+C ends it.
    - Every command is echoed here before its output, and appended to
      .runner/log.txt, so nothing runs invisibly.
    - The repository is under git, so anything done to tracked files can be
      inspected with `git diff` and undone.

    Run it while you are around. Close it when you step away.

.PARAMETER IntervalSeconds
    How often to look for a request. Default 3.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\runner.ps1
#>

[CmdletBinding()]
param(
    [int]$IntervalSeconds = 3
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Channel = Join-Path $RepoRoot '.runner'
$RequestFile = Join-Path $Channel 'request.txt'
$OutputFile = Join-Path $Channel 'output.txt'
$StatusFile = Join-Path $Channel 'status.txt'
$LogFile = Join-Path $Channel 'log.txt'

$PS = 'powershell'
$PSFlags = @('-ExecutionPolicy', 'Bypass', '-Command')

$TASKS = [ordered]@{
    'check'       = @{ Exe = $PS; Args = @('-ExecutionPolicy', 'Bypass', '-File', 'scripts\check.ps1', '-SkipBootstrap'); Desc = 'Full gate' }
    'check-fast'  = @{ Exe = $PS; Args = @('-ExecutionPolicy', 'Bypass', '-File', 'scripts\check.ps1', '-SkipBootstrap', '-SkipFixtures'); Desc = 'Gate without re-capturing fixtures' }
    'test-python' = @{ Exe = 'uv'; Args = @('run', 'pytest', '-q'); Desc = 'Python tests' }
    'test-web'    = @{ Exe = 'pnpm'; Args = @('--filter', 'web', 'test'); Desc = 'Web tests' }
    'lint'        = @{ Exe = $PS; Args = $PSFlags + @('uv run ruff check apps/api scripts services/worker tests; pnpm -r --if-present lint'); Desc = 'Linters' }
    'typecheck'   = @{ Exe = $PS; Args = $PSFlags + @('uv run mypy apps/api/app scripts; pnpm -r --if-present typecheck'); Desc = 'Type checkers' }
    'curriculum'  = @{ Exe = 'uv'; Args = @('run', 'python', 'scripts/validate_curriculum.py'); Desc = 'Validate curriculum' }
    'fixtures'    = @{ Exe = 'uv'; Args = @('run', 'python', 'scripts/capture_api_fixtures.py'); Desc = 'Re-capture API fixtures' }
    'format'      = @{ Exe = $PS; Args = $PSFlags + @('uv run ruff format apps/api scripts services/worker tests; uv run ruff check --fix apps/api scripts services/worker tests; pnpm -r --if-present format:write'); Desc = 'Formatters' }
    'build-web'   = @{ Exe = 'pnpm'; Args = @('--filter', 'web', 'build'); Desc = 'Next.js production build' }
    'e2e'         = @{ Exe = 'pnpm'; Args = @('--filter', 'web', 'e2e'); Desc = 'Playwright suite' }
    'e2e-install' = @{ Exe = 'pnpm'; Args = @('--filter', 'web', 'exec', 'playwright', 'install', '--with-deps', 'chromium'); Desc = 'One-time browser download' }
    'migrate'     = @{ Exe = 'uv'; Args = @('run', 'alembic', 'upgrade', 'head'); Desc = 'Apply migrations' }
    'seed'        = @{ Exe = 'uv'; Args = @('run', 'python', 'scripts/load_curriculum.py', '--publish'); Desc = 'Load and publish curriculum' }
    'status'      = @{ Exe = 'git'; Args = @('status', '--short'); Desc = 'Working tree status' }
    'diff'        = @{ Exe = 'git'; Args = @('diff', '--stat'); Desc = 'Unstaged changes' }
    'commit'      = @{ Exe = $PS; Args = $PSFlags + @('git add -A; git commit -m "checkpoint from runner"'); Desc = 'Stage everything and commit' }
    'push'        = @{ Exe = 'git'; Args = @('push'); Desc = 'Push current branch to origin' }
}

New-Item -ItemType Directory -Force -Path $Channel | Out-Null

$ignore = Join-Path $RepoRoot '.gitignore'
if ((Get-Content $ignore -Raw) -notmatch '(?m)^\.runner/') {
    Add-Content -Path $ignore -Value ".runner/"
}

function Write-Log {
    param([string]$Text)
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Text"
}

function Invoke-Captured {
    <#
        Run a native command and capture stdout+stderr without dying.

        `$ErrorActionPreference = 'Stop'` makes PowerShell treat ANY stderr
        line from a native executable as a terminating error. Plenty of
        healthy tools write warnings to stderr -- FastAPI's deprecation notice
        is one -- so with Stop in force the runner killed itself on a warning
        rather than reporting a result. Preference is relaxed only around the
        call, then restored.
    #>
    param([string]$Exe, [string[]]$Arguments)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $text = & $Exe @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    }
    catch {
        $text = "runner could not start '$Exe': $($_.Exception.Message)"
        $code = 127
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return @{ Output = $text; Exit = $code }
}

Write-Host ''
Write-Host 'FluentForge runner' -ForegroundColor White
Write-Host "Watching: $RequestFile" -ForegroundColor DarkGray
Write-Host ''
Write-Host 'Allowed tasks:' -ForegroundColor Cyan
foreach ($name in $TASKS.Keys) {
    Write-Host ("  {0,-12} {1}" -f $name, $TASKS[$name].Desc) -ForegroundColor DarkGray
}
Write-Host ''
Write-Host 'Full access: "exec: <command>" runs anything as you.' -ForegroundColor Red
Write-Host 'The tasks above are shortcuts, not limits.' -ForegroundColor DarkGray
Write-Host 'Every command is echoed here and logged. Ctrl+C ends the channel.' -ForegroundColor Yellow
Write-Host ''

Set-Content -Path $StatusFile -Value 'idle' -Encoding utf8
Write-Log 'runner started (full access)'

while ($true) {
    if (-not (Test-Path $RequestFile)) {
        Start-Sleep -Seconds $IntervalSeconds
        continue
    }

    # Read then delete: a request is consumed exactly once, so a crash cannot
    # leave the same job repeating.
    try { $request = (Get-Content $RequestFile -Raw).Trim() }
    catch { Start-Sleep -Milliseconds 300; continue }
    Remove-Item $RequestFile -Force -ErrorAction SilentlyContinue

    if (-not $request) { continue }

    $label = $request
    $exe = $null
    $arguments = @()

    if ($request -match '^(?i)exec:\s*(.+)$') {
        $command = $Matches[1]
        $label = "exec: $command"
        $exe = $PS
        $arguments = $PSFlags + @($command)
    }
    elseif ($TASKS.Contains($request)) {
        $exe = $TASKS[$request].Exe
        $arguments = $TASKS[$request].Args
    }
    else {
        # Not a named shortcut, so treat it as a command. With full access
        # there is nothing to refuse, and silently rejecting a typo would be
        # more confusing than running it and showing what happened.
        $label = "exec: $request"
        $exe = $PS
        $arguments = $PSFlags + @($request)
    }

    Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $label) -ForegroundColor Cyan
    Write-Log "running $label"
    Set-Content -Path $StatusFile -Value 'running' -Encoding utf8

    $started = Get-Date
    $result = Invoke-Captured -Exe $exe -Arguments $arguments
    $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)

    Write-Host $result.Output
    $verdict = if ($result.Exit -eq 0) { 'PASSED' } else { "FAILED (exit $($result.Exit))" }
    $colour = if ($result.Exit -eq 0) { 'Green' } else { 'Red' }
    Write-Host ("[{0}] {1} in {2}s" -f (Get-Date -Format 'HH:mm:ss'), $verdict, $seconds) -ForegroundColor $colour
    Write-Log "$label -> $verdict in ${seconds}s"

    $header = "task: $label`nexit: $($result.Exit)`nseconds: $seconds`nfinished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n$('-' * 60)`n"
    Set-Content -Path $OutputFile -Value ($header + $result.Output) -Encoding utf8
    Set-Content -Path $StatusFile -Value "$verdict|$label|$($result.Exit)|$seconds" -Encoding utf8

    Write-Host 'Waiting.' -ForegroundColor DarkGray
    Write-Host ''
}
