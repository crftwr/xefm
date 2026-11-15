<#
.SYNOPSIS
    Install, with WinGet, the minimum MSVC toolchain build.ps1 needs.

.DESCRIPTION
    Build Tools for Visual Studio with only the MSVC compilers for the two
    architectures the app ships, x64 and arm64, and the Windows 11 SDK: cl.exe
    for the launcher, rc.exe for its icon and manifest, and makeappx.exe /
    signtool.exe for the MSIX. Not the whole "Desktop development with C++"
    workload, whose recommended set adds CMake, ATL and test tools that nothing
    here uses.

    Idempotent: skipped when vswhere already finds both MSVC compilers -- the
    checks build.ps1 makes -- so re-running converges instead of reinstalling.
    Invoked by `make windows-toolchain`.

.NOTES
    The Build Tools installer elevates, so expect one UAC prompt. It also takes
    several minutes and shows its own progress window (--passive).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Info    ($m) { Write-Host "[INFO] $m" }
function Success ($m) { Write-Host "[SUCCESS] $m" -ForegroundColor Green }
function Fail    ($m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

$PackageId        = 'Microsoft.VisualStudio.BuildTools'
# The components build.ps1 asks vswhere for (-Arch x64 and -Arch arm64), plus
# the SDK that supplies rc.exe.
$VcToolsComponent = 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64'
$VcArm64Component = 'Microsoft.VisualStudio.Component.VC.Tools.ARM64'
$SdkComponent     = 'Microsoft.VisualStudio.Component.Windows11SDK.26100'

# vswhere always lives under the 32-bit Program Files; see build.ps1 for why
# that root is rebuilt from SystemDrive when the environment lacks it.
function Get-ProgramFilesX86 {
    if (${env:ProgramFiles(x86)}) { return ${env:ProgramFiles(x86)} }
    $drive = if ($env:SystemDrive) { $env:SystemDrive } else { 'C:' }
    return (Join-Path $drive 'Program Files (x86)')
}
$vswhere = Join-Path (Get-ProgramFilesX86) 'Microsoft Visual Studio\Installer\vswhere.exe'

function Find-VcTools {
    if (-not (Test-Path $vswhere)) { return $null }
    return (& $vswhere -latest -products * -requires $VcToolsComponent $VcArm64Component -property installationPath)
}

$existing = Find-VcTools
if ($existing) {
    Info "MSVC already installed at $existing; skipping."
    exit 0
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail ("winget not found. It ships with Windows 11 as 'App Installer'; install or update " +
          "that from the Microsoft Store, then re-run.")
}

winget list --id $PackageId --exact --source winget --accept-source-agreements | Out-Null
if ($LASTEXITCODE -eq 0) {
    # winget install does not modify an existing Visual Studio install, and
    # rather than reinstall over it, leave the choice of components to the user.
    Fail ("Build Tools for Visual Studio is installed but lacks an MSVC compiler build.ps1 uses.`n" +
          "Open the Visual Studio Installer, choose Modify, and add:`n" +
          "  MSVC x64/x86 build tools ($VcToolsComponent)`n" +
          "  MSVC ARM64/ARM64EC build tools ($VcArm64Component)`n" +
          "  Windows 11 SDK ($SdkComponent)")
}

# --override replaces winget's default installer arguments, so --wait has to be
# given here too: without it the bootstrapper returns before the install has
# finished and the check below would run too early.
$vsArgs = "--passive --wait --norestart --add $VcToolsComponent --add $VcArm64Component --add $SdkComponent"
Info "winget install $PackageId ..."
winget install --id $PackageId --exact --source winget `
    --accept-package-agreements --accept-source-agreements --override $vsArgs
if ($LASTEXITCODE -ne 0) { Fail "winget install $PackageId failed (exit code $LASTEXITCODE)." }

$installed = Find-VcTools
if (-not $installed) { Fail 'Build Tools installed, but vswhere still finds no MSVC compiler.' }
Success "MSVC toolchain installed at $installed"
Info "build.ps1 imports its environment by itself; next: 'make windows-app'."
