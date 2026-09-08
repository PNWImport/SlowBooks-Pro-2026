# ============================================================================
# SlowBooks Pro - Server Edition install (Windows)
#
# Registers a scheduled task that runs the server at machine startup as
# LOCAL SERVICE (no login required), stores books machine-wide under
# C:\ProgramData\SlowBooksPro, and opens the firewall port. Run from an
# elevated PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File serveredition-install.ps1
#
# Undo everything with serveredition-uninstall.ps1.
# ============================================================================
#Requires -RunAsAdministrator
param(
    [ValidateRange(1, 65535)][int]$Port = 3001,
    [string]$ExePath = "",
    [string]$DataDir = "$env:ProgramData\SlowBooksPro"
)

$ErrorActionPreference = "Stop"
$TaskName = "SlowBooksProServer"
$RuleName = "SlowBooks Pro Server Edition"

# The script ships inside the bundle at _internal\scripts\windows\ -
# the exe is three levels up. Explicit -ExePath overrides.
if (-not $ExePath) {
    $ExePath = Join-Path $PSScriptRoot "..\..\..\SlowBooksPro.exe"
}
# Existence check must come first: Resolve-Path throws its own opaque
# error on a missing path under ErrorActionPreference=Stop, which aborted
# the whole install before the firewall/task steps with no guidance (#65).
if (-not (Test-Path $ExePath)) {
    throw ("SlowBooksPro.exe not found at $ExePath - run this script from " +
        "the installed app's _internal\scripts\windows\ folder, or pass -ExePath")
}
$ExePath = (Resolve-Path $ExePath).Path

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

# Bring existing desktop-mode books along (docs promised this; the script
# previously only created an empty folder, #65). Copies company files, the
# manifest, the .env encryption key (without it, stored credentials cannot
# be decrypted), uploads, and backups - not the webview cache or logs.
# Only runs when the server data dir has no company files yet, so it can
# never clobber an active server's books.
$DesktopDir = Join-Path $env:LOCALAPPDATA "SlowBooksPro"
# Company files live in the data home's companies\ subfolder (root-level
# .db checked too, for older layouts).
function Test-HasBooks([string]$dir) {
    if (-not (Test-Path $dir)) { return $false }
    $roots = @(Get-ChildItem -Path $dir -Filter *.db -ErrorAction SilentlyContinue)
    $comps = @(Get-ChildItem -Path (Join-Path $dir "companies") -Filter *.db -ErrorAction SilentlyContinue)
    return ($roots.Count + $comps.Count) -gt 0
}
$serverHasBooks = Test-HasBooks $DataDir
$desktopHasBooks = Test-HasBooks $DesktopDir
if (-not $serverHasBooks -and $desktopHasBooks) {
    # Validate the entire copy set before writing anything. A late collision
    # must not leave a partially copied company that looks ready on retry.
    $DesktopFiles = @(Get-ChildItem -Path $DesktopDir -File -Force |
        Where-Object { $_.Extension -in ".db", ".json" -or $_.Name -like ".env*" })
    foreach ($ItemName in @($DesktopFiles.Name) + @('companies', 'uploads', 'backups')) {
        if ((Test-Path (Join-Path $DesktopDir $ItemName)) -and (Test-Path (Join-Path $DataDir $ItemName))) {
            throw "Destination already exists: $ItemName. Reconcile desktop/server data before installing."
        }
    }
    Write-Host ">> Copying your desktop books from $DesktopDir"
    $DesktopFiles |
        ForEach-Object {
            Copy-Item $_.FullName -Destination $DataDir -Force
            Write-Host ("   " + $_.Name)
        }
    foreach ($sub in "companies", "uploads", "backups") {
        $src = Join-Path $DesktopDir $sub
        if (Test-Path $src) {
            Copy-Item $src -Destination $DataDir -Recurse -Force
            Write-Host ("   " + $sub + "\")
        }
    }
    Write-Host ">> Desktop copies are untouched; the server now uses $DataDir"
} elseif ($serverHasBooks) {
    Write-Host ">> $DataDir already has company files - leaving them as-is"
}

# TLS settings belong in the server data home's .env, not an interactive
# administrator's environment (which the startup account does not inherit).
$ServerEnv = Join-Path $DataDir '.env'
if (-not (Test-Path $ServerEnv)) { throw 'Configure server .env and TLS first; see docs/server-edition.md.' }
foreach ($TlsSetting in 'SLOWBOOKS_TLS_CERTFILE', 'SLOWBOOKS_TLS_KEYFILE') {
    $Entry = Get-Content $ServerEnv | Where-Object { $_ -match "^\s*$TlsSetting=" } | Select-Object -First 1
    if (-not $Entry) { throw "Missing $TlsSetting in server .env" }
    $TlsPath = ($Entry -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if (-not [IO.Path]::IsPathRooted($TlsPath) -or -not (Test-Path $TlsPath -PathType Leaf)) {
        throw "$TlsSetting must name an existing absolute file path"
    }
}

# Give the service access to its data, not administrator privileges. Numeric
# SIDs work on localized Windows installations too. Existing books survive.
icacls $DataDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)M' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not set service data permissions' }

Write-Host ">> Opening firewall port $Port (private/domain local subnet only)"
netsh advfirewall firewall delete rule name="$RuleName" | Out-Null
netsh advfirewall firewall add rule name="$RuleName" dir=in action=allow `
    protocol=TCP localport=$Port profile=private,domain remoteip=localsubnet program="$ExePath" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not create restricted firewall rule' }

Write-Host ">> Registering startup task $TaskName (runs as LOCAL SERVICE)"
# PowerShell 5.1 mangles embedded double quotes when handing arguments to
# native commands: with the app in "C:\Program Files\SlowBooks Pro 2026",
# schtasks saw /TR split at the first space and rejected it (Invalid
# argument/option - 'Files\SlowBooks'), so the task was never created from
# a normal installed location. Backslash-quote is the one form PS passes
# through literally.
$TaskCmd = "\`"$ExePath\`" --serve-lan --port $Port --data-dir \`"$DataDir\`""
schtasks /Create /TN $TaskName /SC ONSTART /RU 'NT AUTHORITY\LOCALSERVICE' /RL LIMITED /F /TR $TaskCmd | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "schtasks could not register the $TaskName task (exit $LASTEXITCODE)"
}

Write-Host ">> Starting the server now"
schtasks /Run /TN $TaskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "schtasks could not start the $TaskName task (exit $LASTEXITCODE)"
}
Start-Sleep -Seconds 8

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress

Write-Host ""
Write-Host "SlowBooks Pro Server Edition is installed." -ForegroundColor Green
Write-Host "Books live in: $DataDir"
Write-Host "Your team connects at:"
Write-Host "    https://$($env:COMPUTERNAME):$Port"
foreach ($ip in $ips) { Write-Host "    https://${ip}:$Port" }
Write-Host ""
Write-Host "It starts automatically with Windows (before anyone logs in)."
Write-Host "HTTPS required - use a certificate-covered hostname trusted by your clients."
