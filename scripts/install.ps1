# Floppy guided installer for Windows.
#
# Start with the universal command in docs/install.md. This is its Windows
# branch (Windows PowerShell 5.1 or PowerShell 7). It runs
# Floppy in Docker Desktop: the same image and Compose shape as the Linux/macOS
# installer's Docker path (scripts/install/docker.sh and finish.sh), with two
# deliberate differences:
#
#   - Data lives in named Docker volumes, not folders on C:. SQLite's locking
#     is unreliable on Windows bind mounts, and named volumes keep the database
#     on the Linux filesystem inside Docker Desktop.
#   - No repository checkout. Everything this installer needs is in this file,
#     so it never needs git.
#
# Keep it compatible with Windows PowerShell 5.1: no "&&", "??", ternaries or
# $IsWindows, and write files as UTF-8 without a BOM (5.1's ">" writes UTF-16).

# 'Continue', not 'Stop': Windows PowerShell 5.1 turns a native command's
# redirected stderr into errors, which 'Stop' would make fatal. Every native
# call below checks its exit code instead.
$ErrorActionPreference = 'Continue'

$FloppyImage = if ($env:FLOPPY_IMAGE) { $env:FLOPPY_IMAGE } else { 'ghcr.io/dannyvfilms/floppy:latest' }
$Project = 'floppy'
$ReadyTimeoutSeconds = 300

function Say([string]$Text) { Write-Host $Text }
function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Note([string]$Text) { Write-Host "    $Text" -ForegroundColor DarkGray }
function Warn([string]$Text) { Write-Host "Warning: $Text" -ForegroundColor Yellow }
function Fail([string]$Text) { Write-Host "Error: $Text" -ForegroundColor Red; throw 'Floppy installer stopped.' }

function Ask([string]$Question, [string]$Default) {
    $reply = Read-Host "$Question [$Default]"
    if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
    return $reply.Trim()
}

function AskYesNo([string]$Question, [bool]$Default) {
    $hint = 'y/N'
    if ($Default) { $hint = 'Y/n' }
    while ($true) {
        $reply = Read-Host "$Question [$hint]"
        if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
        switch -Regex ($reply.Trim()) {
            '^(y|yes)$' { return $true }
            '^(n|no)$' { return $false }
        }
        Say 'Please answer y or n.'
    }
}

function Have([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function WriteText([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, ($Text -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
}

function DockerState {
    if (-not (Have 'docker')) { return 'missing' }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { return 'stopped' }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { return 'no-compose' }
    return 'ready'
}

function Compose {
    # Output goes to the console, so callers get only the exit code back.
    & docker compose --project-name $Project -f $script:ComposeFile @args | Out-Host
    return $LASTEXITCODE
}

function TestHealth([int]$Port) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/health/"
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function DetectTimeZone {
    # IANA names are what the container understands. PowerShell 7 can convert
    # the Windows zone; Windows PowerShell 5.1 cannot, so it falls back to UTC.
    try {
        $iana = $null
        $id = [TimeZoneInfo]::Local.Id
        if ([TimeZoneInfo]::TryConvertWindowsIdToIanaId($id, [ref]$iana)) { return $iana }
    } catch { }
    return 'UTC'
}

function StartDockerDesktop {
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $exe)) { return $false }
    Say 'Starting Docker Desktop...'
    Start-Process -FilePath $exe | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 3
        if ((DockerState) -eq 'ready') { return $true }
    }
    return $false
}

function Install {
    if ($env:OS -ne 'Windows_NT' -and -not $env:FLOPPY_INSTALL_ALLOW_NON_WINDOWS) {
        Fail 'This installer is for Windows. On Linux or macOS, use scripts/install.sh (see docs/install.md).'
    }

    Say 'Floppy guided installer for Windows'
    Say 'Floppy runs in Docker Desktop. Nothing is installed without asking first.'

    # --- Docker Desktop ---------------------------------------------------
    Step 'Checking Docker Desktop'
    $state = DockerState
    if ($state -eq 'missing') {
        Say 'Floppy needs Docker Desktop, which is free for personal use.'
        if ((Have 'winget') -and (AskYesNo 'Install Docker Desktop now with winget? (Windows will ask for permission)' $true)) {
            & winget install --exact --id Docker.DockerDesktop --accept-package-agreements
            if ($LASTEXITCODE -ne 0) { Fail 'winget could not install Docker Desktop. Install it from https://www.docker.com/products/docker-desktop/ and run this again.' }
            Say ''
            Say 'Docker Desktop is installed. Windows may need a restart before it works.'
        } else {
            Say 'Install it from https://www.docker.com/products/docker-desktop/'
        }
        Say 'Then open Docker Desktop once, finish its setup, and paste the install command again.'
        return
    }
    if ($state -eq 'stopped') {
        if (-not (StartDockerDesktop)) {
            Fail 'Docker Desktop is installed but not running. Open it, wait until it says it is running, then paste the install command again.'
        }
        $state = DockerState
    }
    if ($state -ne 'ready') {
        Fail 'Docker is missing "docker compose". Update Docker Desktop, then paste the install command again.'
    }
    Say 'Docker Desktop is running.'

    # --- Questions ---------------------------------------------------------
    $root = Join-Path $HOME 'floppy'
    $script:ComposeFile = Join-Path $root 'docker-compose.yml'
    $envFile = Join-Path $root 'floppy.env'
    $existing = Test-Path $script:ComposeFile

    if ($existing) {
        Step "Found an existing installation in $root"
        Note 'Keeping its configuration. This run only starts it again.'
        $portLine = Select-String -Path $script:ComposeFile -Pattern ':(\d+):8000"' | Select-Object -First 1
        $port = 8000
        if ($portLine) { $port = [int]$portLine.Matches[0].Groups[1].Value }
    } else {
        Step 'A few questions'
        $lan = AskYesNo 'Let other devices on your network (phones, TVs) reach Floppy?' $true
        $bind = '127.0.0.1'
        if ($lan) { $bind = '0.0.0.0' }
        while ($true) {
            $answer = Ask 'Port' '8000'
            if ($answer -notmatch '^\d{1,5}$') { Say 'Please enter a number, for example 8000.'; continue }
            $port = [int]$answer
            $busy = $null
            if (Have 'Get-NetTCPConnection') {
                $busy = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
            }
            if (-not $busy) { break }
            Say "Port $port is already in use. Pick another."
        }
        $tz = Ask 'Time zone (IANA name, for example America/Chicago)' (DetectTimeZone)

        Step 'Writing the configuration'
        New-Item -ItemType Directory -Force -Path $root | Out-Null
        WriteText $envFile @"
# Floppy installation settings. Edit, then run:
#   docker compose -f "$($script:ComposeFile)" up -d
TZ=$tz
REDIS_URL=redis://redis:6379
DEBUG=False
ADMIN_ENABLED=False
DEMO_ACCOUNT_ENABLED=False
REGISTRATION=True

"@
        # Same services as scripts/install/templates/docker-compose.install.yml.tmpl,
        # with named volumes instead of host folders (see the header).
        WriteText $script:ComposeFile @"
# Generated by the Floppy Windows installer. Ordinary "docker compose" commands
# are the maintenance interface; the database lives in the floppy_floppy_db volume.
name: $Project

services:
  floppy:
    image: $FloppyImage
    restart: unless-stopped
    # A running celery task gets up to 60 s to finish and the web server 30 s.
    # Docker's default 10 s stop timeout kills the container mid-shutdown.
    stop_grace_period: 150s
    depends_on:
      redis:
        condition: service_healthy
    env_file:
      - "./floppy.env"
    volumes:
      - floppy_db:/floppy/db
      - floppy_backups:/floppy/backups
    ports:
      - "${bind}:${port}:8000"
    networks:
      - floppy-net

  redis:
    image: redis:8-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes --save "" --maxmemory 256mb --maxmemory-policy volatile-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 30
    volumes:
      - redis_data:/data
    networks:
      - floppy-net

volumes:
  floppy_db:
  floppy_backups:
  redis_data:

networks:
  floppy-net:
    driver: bridge
"@
        Say "  $($script:ComposeFile)"
        Say "  $envFile"
    }

    if ((Compose config --quiet) -ne 0) { Fail "The Compose file is not valid. It is at $($script:ComposeFile)." }

    Step "Downloading Floppy's image"
    if ((Compose pull) -ne 0) { Fail 'Could not download the image. Check the network connection and try again.' }

    Step 'Starting Floppy'
    if ((Compose up -d) -ne 0) { Fail "Floppy could not start. Run: docker compose -f `"$($script:ComposeFile)`" logs" }

    # --- Wait for it -------------------------------------------------------
    Step 'Waiting for Floppy to be ready'
    Note 'The first start sets up the database, so it can take a couple of minutes.'
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if (TestHealth $port) { $ready = $true; break }
        Start-Sleep -Seconds 3
    }
    $url = "http://localhost:$port"
    if (-not $ready) {
        Warn "Floppy did not answer within $($ReadyTimeoutSeconds / 60) minutes."
        Say 'Nothing was stopped or removed. Startup may still be in progress. Recent log lines:'
        Compose logs --tail 40 floppy | Out-Null
        Say "Paste the install command again later to finish, or open $url once it is up."
        return
    }

    # --- Owner -------------------------------------------------------------
    if ((-not $existing) -or (AskYesNo 'Make an existing account the owner (admin) now?' $false)) {
        Step 'Create your account'
        Say 'Open this address and create the first account:'
        Say ''
        Say "    $url"
        Say ''
        Say 'The installer never asks for a password. Create the account in the browser.'
        try { Start-Process $url | Out-Null } catch { }
        if (AskYesNo 'Have you created your account?' $true) {
            Step 'Making that account the owner'
            Note 'The owner can change instance-wide settings, such as metadata API keys.'
            while ($true) {
                $username = Ask 'Username of the account you just created' ''
                if ([string]::IsNullOrWhiteSpace($username)) { break }
                if ((Compose exec -T floppy python manage.py promote_superuser $username) -eq 0) {
                    if (AskYesNo 'Close registration so nobody else can sign up?' $true) {
                        WriteText $envFile ((Get-Content -Raw $envFile) -replace 'REGISTRATION=True', 'REGISTRATION=False')
                        Compose up -d floppy | Out-Null
                        Say 'Registration is closed. To reopen it, set REGISTRATION=True in floppy.env and restart Floppy.'
                    }
                    break
                }
                Say 'Accounts on this installation:'
                Compose exec -T floppy python manage.py promote_superuser --list | Out-Null
                if (-not (AskYesNo 'Try a different username?' $true)) { break }
            }
        }
    }

    Step 'Floppy is installed'
    Say ''
    Say "  Address:        $url"
    Say "  Configuration:  $root"
    Say '  Your data:      Docker volumes floppy_floppy_db and floppy_floppy_backups'
    Say ''
    Say 'Floppy starts with Docker Desktop. Turn on "Start Docker Desktop when you sign in"'
    Say 'in Docker Desktop settings to have it running after a restart.'
    Say ''
    Say 'Commands (PowerShell):'
    Say "  Stop:     docker compose -f `"$($script:ComposeFile)`" down"
    Say "  Start:    docker compose -f `"$($script:ComposeFile)`" up -d"
    Say "  Logs:     docker compose -f `"$($script:ComposeFile)`" logs -f"
    Say "  Upgrade:  docker compose -f `"$($script:ComposeFile)`" pull; docker compose -f `"$($script:ComposeFile)`" up -d"
    Say ''
    Say 'Back up before upgrading. Never run "down -v": it deletes the database volume.'
}

try {
    Install
} catch {
    if ($_.Exception.Message -ne 'Floppy installer stopped.') { Write-Host $_ -ForegroundColor Red }
}
