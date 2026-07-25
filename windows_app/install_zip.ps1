<#
.SYNOPSIS
    Install XeFM on this machine from the portable distribution zip.

.DESCRIPTION
    The Windows counterpart of `make install-macos-dmg`: it installs the exact
    artifact end users download (windows_app\build\XeFM-<version>-win64.zip,
    produced by build.ps1 -Zip) rather than copying windows_app\build\XeFM\
    directly. Expanding the real zip is what catches a truncated or incomplete
    archive here, instead of leaving it for the first person to download it.

    Per-user by default (%LOCALAPPDATA%\Programs\XeFM), so no UAC prompt and no
    elevated shell is needed. Pass -InstallDir 'C:\Program Files\XeFM' for a
    machine-wide install, which does require an elevated shell.

    Invoked by `make install-windows-zip`, which builds the zip first if it is
    missing and passes WINDOWS_INSTALL_DIR through as -InstallDir.

.NOTES
    The zip holds a single XeFM\ folder at its root (build.ps1 compresses the
    bundle directory itself), so it expands into the PARENT of the destination
    to land exactly at the destination.

    Any existing install is REMOVED first rather than expanded over the top of:
    Expand-Archive -Force overwrites files it has replacements for, but leaves
    behind ones a later build stopped shipping, which is how a stale .pyd
    survives an "upgrade" and produces failures no clean install can reproduce.
#>
[CmdletBinding()]
param(
    # Defaults (in the body, not here) to windows_app\build\XeFM-<version>-win64.zip.
    # $PSScriptRoot is not reliably populated in a param default under
    # 'powershell -File' — the form the Makefile uses — so it is resolved below.
    [string]$Zip,
    # Defaults (in the body) to %LOCALAPPDATA%\Programs\XeFM.
    [string]$InstallDir
)

$ErrorActionPreference = "Stop"

function Info    ($m) { Write-Host "[INFO] $m" }
function Success ($m) { Write-Host "[SUCCESS] $m" -ForegroundColor Green }
function Fail    ($m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$projectRoot = Split-Path -Parent $ScriptDir

# Resolve the zip from xefm/__init__.py's __version__ — the same single source of
# truth build.ps1 names the zip after — so the default cannot drift from what the
# build just produced.
if (-not $Zip) {
    $init = Join-Path $projectRoot 'xefm\__init__.py'
    $m = Select-String -Path $init -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $m) { Fail "Could not read __version__ from $init" }
    $version = $m.Matches[0].Groups[1].Value
    $Zip = Join-Path $ScriptDir "build\XeFM-$version-win64.zip"
}

if (-not (Test-Path $Zip)) {
    Fail "Zip not found: $Zip`nBuild it first with 'make windows-zip'."
}

if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\XeFM' }
$parent = Split-Path $InstallDir -Parent

if (Test-Path $InstallDir) {
    Info "Removing existing $InstallDir"
    try {
        Remove-Item -Recurse -Force $InstallDir
    } catch {
        Fail ("Could not remove $InstallDir : $($_.Exception.Message)`n" +
              "Close XeFM if it is running, or re-run from an elevated shell for a machine-wide install.")
    }
}

New-Item -ItemType Directory -Force -Path $parent | Out-Null

Info "Expanding $(Split-Path $Zip -Leaf) into $parent ..."
Expand-Archive -Path $Zip -DestinationPath $parent -Force

# The zip is the deliverable, so verify what came out of it rather than trusting
# that Expand-Archive succeeding means the payload is complete.
$exe = Join-Path $InstallDir 'XeFM.exe'
if (-not (Test-Path $exe)) {
    Fail "XeFM.exe not found at $exe after expanding the zip — the archive looks incomplete."
}

Success "Installed to $InstallDir"
Info "Run it:  & '$exe'"
