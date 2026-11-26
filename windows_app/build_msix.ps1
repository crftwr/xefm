<#
.SYNOPSIS
    Prototype MSIX packager + local installer for XeFM (Store / winget distribution).

.DESCRIPTION
    Wraps the existing windows_app\build\XeFM bundle (arm64:
    windows_app\build\arm64\XeFM; both produced by build.ps1) into an installable
    .msix, following doc/dev/WINDOWS_STORE_MSIX_PLAN.md:

      (default)   generate assets -> stage payload + AppxManifest -> makeappx pack
      -Arch       the architecture to pack: x64 (default) or arm64
      -Bundle     combine the x64 and arm64 packages already built into one
                  .msixbundle - what goes to the Store, which delivers the
                  payload that matches the device
      -Sign       also self-sign the package for LOCAL testing
      -Install    trust the self-signed cert (elevates) + Add-AppxPackage (per-user)
      -Uninstall  Remove-AppxPackage + delete the throwaway signing certs (elevates)
      -TrustCert  internal: import the cert into LocalMachine\TrustedPeople (elevated child)
      -CleanCert  internal: remove the cert from LocalMachine\TrustedPeople (elevated child)

    This does NOT submit to the Store. For a real submission the identity values
    come from Partner Center and Microsoft re-signs the (unsigned) package; the
    self-signed path here is purely to exercise the package on the dev box.

.NOTES
    Identity comes from the gitignored windows_app\store.env (copy
    store.env.example and fill in Partner Center's "Product identity" values —
    see WINDOWS_STORE_MSIX_PLAN.md 2a), or from an explicit -IdentityName /
    -Publisher / -PublisherDisplayName, which wins over the file. Without either
    the build falls back to a XeFM.Prototype identity that sideloads fine but
    cannot be submitted, and warns that it did so.

    The package version defaults to xefm/__init__.py's __version__ plus the
    Store-reserved ".0" revision (1.0.1 -> 1.0.1.0); override with -Version. A
    pre-release is cut to its release (1.0.1rc1 -> 1.0.1.0) for local use; the
    unsigned bundle, the Store's form, refuses one.
#>
[CmdletBinding()]
param(
    # PayloadSource / OutDir default to paths under the script dir, but are filled
    # in below — NOT here — because $PSScriptRoot is not reliably populated in a
    # param default when the script is launched via 'powershell -File' (as the
    # Makefile does). Evaluated here it comes back empty, yielding '\build\XeFM'.
    [string]$PayloadSource,
    [string]$OutDir,
    # Defaults (below, in the body) to xefm/__init__.py's __version__ + ".0" --
    # the Store wants major != 0 and revision = 0.
    [string]$Version,
    # Partner Center "Product identity" values. All three default (below, in the
    # body) to windows_app\store.env if present, else to prototype placeholders.
    [string]$IdentityName,                                # Package/Identity/Name
    [string]$Publisher,                                   # Publisher (CN=...)
    [string]$PublisherDisplayName,                        # Package/Properties/PublisherDisplayName
    [ValidateSet("x64", "arm64")]
    [string]$Arch                 = "x64",
    [switch]$Bundle,                                      # x64 + arm64 -> .msixbundle; with -Install, that bundle
    [switch]$Sign,                                        # self-sign for local install test
    [switch]$SkipAssets,                                  # reuse existing resources\Assets
    [switch]$Install,                                     # trust cert + install locally
    [switch]$Uninstall,                                   # remove the package + throwaway certs
    [switch]$TrustCert,                                   # internal: elevated cert-import step
    [switch]$CleanCert                                    # internal: elevated cert-removal step
)

$ErrorActionPreference = "Stop"

# Resolve the script directory reliably (body scope), then fill path defaults.
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$projectRoot = Split-Path -Parent $ScriptDir
if (-not $PayloadSource) {
    $PayloadSource = Join-Path $ScriptDir $(if ($Arch -eq 'x64') { 'build\XeFM' } else { "build\$Arch\XeFM" })
}
if (-not $OutDir)        { $OutDir        = Join-Path $ScriptDir 'build' }

# Resolve the package version from xefm/__init__.py's __version__ -- the single
# source of truth build.ps1 already reads -- plus the Store-reserved ".0"
# revision, so a source version of 1.0.1 packages as 1.0.1.0. Deriving it (rather
# than hardcoding) keeps the package version from drifting behind the app version
# it contains, which matters because every submission needs a strictly higher
# package version than the last (WINDOWS_STORE_MSIX_PLAN.md 2b).
#
# Deterministic, so the separate -Install / -Uninstall invocations that follow a
# pack all compute the same $msix path.
#
# A pre-release (1.18.0rc1, 1.18.0b2, 1.18.0.dev1) has no place in MSIX's four
# numbers, so it is cut to its release (1.18.0.0), as the DMG's CFBundleVersion
# is. That serves everything done on this machine: a pack, a self-signed install,
# an uninstall. It never reaches the Store: the form submitted, an unsigned
# bundle, refuses it below, since the Store would take 1.18.0.0 for good and the
# real 1.18.0 could not follow it (RELEASE_SYSTEM.md: a release candidate is not
# submitted).
$preRelease = $null
if (-not $Version) {
    $xefmInit = Join-Path $projectRoot 'xefm/__init__.py'
    $m = Select-String -Path $xefmInit -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $m) { throw "Could not read __version__ from $xefmInit; pass -Version explicitly." }
    $source = $m.Matches[0].Groups[1].Value
    if ($source -match '^([0-9]+\.[0-9]+\.[0-9]+)(?:(?:a|b|rc)[0-9]+)?(?:\.dev[0-9]+)?$' -and
            $source -ne $Matches[1]) {
        $preRelease = $source
        $Version = "$($Matches[1]).0"
    } else {
        $Version = "$source.0"
    }
}
if ($preRelease) {
    if ($Bundle -and -not $Sign -and -not $Install -and -not $Uninstall) {
        throw ("XeFM $preRelease is a pre-release, and an unsigned bundle is what goes " +
               "to the Store, which never takes one (doc/dev/RELEASE_SYSTEM.md). " +
               "Pass -Sign to try the bundle here.")
    }
    Write-Host "[INFO] XeFM $preRelease is a pre-release: packaged as $Version, for this machine only."
}
# Validated here because makeappx reports a malformed version as an opaque
# manifest schema error.
if ($Version -notmatch '^[1-9][0-9]*\.[0-9]+\.[0-9]+\.0$') {
    throw ("Invalid MSIX package version '$Version': the Store requires " +
           "major.minor.build.revision with major >= 1 and revision = 0 " +
           "(see doc/dev/WINDOWS_STORE_MSIX_PLAN.md 2b).")
}

# Local Store identity configuration (optional, gitignored) -- same pattern as
# macos_app/signing.env, and non-secret for the same reason: all three values are
# readable from any shipped package. They are kept out of git because they are
# per-Partner-Center-account, so a fork/clone must supply its own.
#
# Precedence, highest first: an explicit -IdentityName/-Publisher/... argument,
# then store.env, then the prototype placeholder (which cannot be submitted).
$storeEnv = Join-Path $ScriptDir 'store.env'
$storeCfg = @{}
if (Test-Path $storeEnv) {
    Write-Host "[INFO] Loading Store identity from $storeEnv"
    foreach ($line in Get-Content $storeEnv) {
        # KEY=VALUE; '#' comments and blank lines do not match, quotes are trimmed.
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$') {
            $storeCfg[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
        }
    }
}
foreach ($d in @(
    @{ Param = 'IdentityName';         Key = 'XEFM_MSIX_IDENTITY_NAME';          Fallback = 'XeFM.Prototype' },
    @{ Param = 'Publisher';            Key = 'XEFM_MSIX_PUBLISHER';              Fallback = 'CN=XeFM Prototype Dev' },
    @{ Param = 'PublisherDisplayName'; Key = 'XEFM_MSIX_PUBLISHER_DISPLAY_NAME'; Fallback = 'XeFM Prototype' }
)) {
    if ($PSBoundParameters.ContainsKey($d.Param)) { continue }   # explicit argument wins
    $value = if ($storeCfg.ContainsKey($d.Key)) { $storeCfg[$d.Key] } else { $d.Fallback }
    Set-Variable -Name $d.Param -Value $value
}
# Loud, because a prototype-identity package packs and installs locally just fine
# and is only rejected once uploaded -- after the slow pack and a Partner Center
# round trip.
if ($IdentityName -eq 'XeFM.Prototype') {
    Write-Host ("[WARNING] Using the PROTOTYPE identity '$IdentityName' -- fine for local " +
                "testing, but Partner Center will reject it. Copy store.env.example to " +
                "store.env and fill in your Product identity values.") -ForegroundColor Yellow
}
Write-Host "[INFO] Package identity: $IdentityName  ($Publisher)"

# Artifact paths shared by build + install actions.
$msix    = "$OutDir\XeFM-$Version-$Arch.msix"
# Packed/signed here, then renamed to $msix only on full success. Keeps the
# .msix extension (before .building) because signtool refuses to sign a file
# whose extension it doesn't recognize as an app package.
$msixTmp = "$OutDir\XeFM-$Version-$Arch.building.msix"
$bundleFile = "$OutDir\XeFM-$Version.msixbundle"
$bundleTmp  = "$OutDir\XeFM-$Version.building.msixbundle"
$pfx     = "$OutDir\XeFM-proto-test.pfx"
$cer     = "$OutDir\XeFM-proto-test.cer"
$pfxPassword = "prototest"

# The two "Program Files" roots, derived rather than read from the environment.
# ProgramFiles / ProgramFiles(x86) are set in any normal Windows session, but a
# process launched from a shell whose MSYS runtime differs from the one its
# parent was built against inherits only a handful of variables, and neither of
# these survives -- on this project's Windows box that handoff is Git Bash (Git
# for Windows' own msys) invoking C:\msys64's make, which leaves a recipe with
# eight variables. An empty root turned the search paths below into a bare
# "\Windows Kits\10\bin", so the SDK read as missing and the error blamed an
# uninstalled Windows SDK that was in fact sitting right there. Both directory
# names are fixed under the system drive, so construct them when asking fails.
function Get-ProgramFilesRoot([switch]$X86) {
    $fromEnv = if ($X86) { ${env:ProgramFiles(x86)} } else { ${env:ProgramFiles} }
    if ($fromEnv) { return $fromEnv }
    $drive = if ($env:SystemDrive) { $env:SystemDrive } else { 'C:' }
    return (Join-Path $drive $(if ($X86) { 'Program Files (x86)' } else { 'Program Files' }))
}

function Find-SdkTool([string]$name) {
    $roots = @(
        "$(Get-ProgramFilesRoot -X86)\Windows Kits\10\bin",
        "$(Get-ProgramFilesRoot)\Windows Kits\10\bin"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        # The architecture here is the tool's, not the package's: x64 tools pack
        # either, and run on any machine this builds on. An SDK on Windows on
        # Arm may have only its arm64 ones.
        $all = @(Get-ChildItem -Path $root -Recurse -Filter $name -ErrorAction SilentlyContinue)
        $hostDir = 'x64'
        $hits = @($all | Where-Object { $_.FullName -match "\\x64\\$([regex]::Escape($name))$" })
        if (-not $hits.Count) {
            $hostDir = 'arm64'
            $hits = @($all | Where-Object { $_.FullName -match "\\arm64\\$([regex]::Escape($name))$" })
        }
        if (-not $hits.Count) { continue }
        # Prefer the newest bin\10.0.xxxxx.0\<host> copy: the top-level bin\x64
        # dir (pre-1703 SDK layout) can hold an ancient signtool that does not
        # recognize the MSIX format, and a plain descending name sort would
        # pick it ('x64' sorts after '10.0.26100.0').
        $versioned = @($hits | Where-Object { $_.FullName -match "\\10\.[0-9.]+\\$hostDir\\" } |
                       Sort-Object { [version]([regex]::Match($_.FullName, '\\(10\.[0-9.]+)\\').Groups[1].Value) } -Descending)
        if ($versioned.Count) { return $versioned[0].FullName }
        return ($hits | Sort-Object FullName -Descending | Select-Object -First 1).FullName
    }
    throw "$name not found under any Windows Kits\10\bin. Install the Windows 10/11 SDK."
}

function Test-IsAdmin {
    ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

# ===========================================================================
# Action: -TrustCert (internal, runs elevated) — trust the self-signed cert.
# ===========================================================================
if ($TrustCert) {
    if (-not (Test-Path $cer)) { throw "Certificate not found: $cer (build with -Sign first)" }
    Write-Host "[INFO] Trusting $cer in LocalMachine\TrustedPeople ..."
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
    Write-Host "[OK] Certificate trusted."
    return
}

# ===========================================================================
# Action: -CleanCert (internal, runs elevated) — untrust the self-signed cert.
# ===========================================================================
if ($CleanCert) {
    $trusted = @(Get-ChildItem Cert:\LocalMachine\TrustedPeople -ErrorAction SilentlyContinue |
                 Where-Object { $_.Subject -eq $Publisher })
    if ($trusted.Count) {
        $trusted | Remove-Item -Force
        Write-Host "[OK] Removed $($trusted.Count) cert(s) from LocalMachine\TrustedPeople."
    } else {
        Write-Host "[INFO] No trusted cert with subject '$Publisher' found."
    }
    return
}

# ===========================================================================
# Action: -Uninstall — remove the package and the throwaway signing certs.
# ===========================================================================
if ($Uninstall) {
    # 1. Remove the installed package (per-user, no admin).
    $pkg = Get-AppxPackage -Name $IdentityName -ErrorAction SilentlyContinue
    if ($pkg) {
        $pkg | Remove-AppxPackage
        Write-Host "[OK] Removed $($pkg.PackageFullName)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Package '$IdentityName' is not installed."
    }

    # 2. Remove the signing cert (private key) from the user store (no admin).
    $mine = @(Get-ChildItem Cert:\CurrentUser\My -ErrorAction SilentlyContinue |
              Where-Object { $_.Subject -eq $Publisher })
    if ($mine.Count) {
        $mine | Remove-Item -Force
        Write-Host "[OK] Removed $($mine.Count) signing cert(s) from CurrentUser\My."
    }

    # 3. Untrust the public cert in the machine store (needs admin -> elevate).
    $trusted = @(Get-ChildItem Cert:\LocalMachine\TrustedPeople -ErrorAction SilentlyContinue |
                 Where-Object { $_.Subject -eq $Publisher })
    if ($trusted.Count) {
        if (Test-IsAdmin) {
            $trusted | Remove-Item -Force
            Write-Host "[OK] Removed $($trusted.Count) cert(s) from LocalMachine\TrustedPeople."
        } else {
            Write-Host "[INFO] Requesting elevation to untrust the certificate (accept the UAC prompt)..."
            $psExe = (Get-Process -Id $PID).Path
            $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -CleanCert -Publisher `"$Publisher`" -Version $Version"
            $proc = Start-Process -FilePath $psExe -Verb RunAs -Wait -PassThru -ArgumentList $argLine
            if ($proc.ExitCode -ne 0) { Write-Host "[WARN] Elevated cert cleanup failed or was cancelled (exit $($proc.ExitCode))." }
        }
    }

    # 4. Delete the throwaway cert files (they also go with 'make clean-windows').
    foreach ($file in @($pfx, $cer)) {
        if (Test-Path $file) { Remove-Item -Force $file; Write-Host "[OK] Deleted $file" }
    }
    return
}

# ===========================================================================
# Action: -Install — trust the cert (elevates) then install per-user. With
# -Bundle, the bundle rather than this architecture's package.
# ===========================================================================
if ($Install) {
    if ($Bundle) { $msix = $bundleFile }
    if (-not (Test-Path $msix)) { throw "Package not found: $msix. Run 'make windows-msix' first." }
    if (-not (Test-Path $cer))  { throw "Signing cert not found: $cer. Run 'make windows-msix' first." }

    # Step 1: trust the self-signed cert (machine-wide store => needs admin).
    if (Test-IsAdmin) {
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
        Write-Host "[OK] Certificate trusted."
    } else {
        Write-Host "[INFO] Requesting elevation to trust the signing certificate (accept the UAC prompt)..."
        $psExe = (Get-Process -Id $PID).Path
        $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -TrustCert -OutDir `"$OutDir`" -Version $Version"
        $proc = Start-Process -FilePath $psExe -Verb RunAs -Wait -PassThru -ArgumentList $argLine
        if ($proc.ExitCode -ne 0) { throw "Elevated cert-trust step failed or was cancelled (exit $($proc.ExitCode))." }
    }

    # Step 2: install per-user (cert is now trusted; Add-AppxPackage needs no admin).
    Write-Host "[INFO] Installing package (Add-AppxPackage)..."
    Add-AppxPackage -Path $msix
    $pkg = Get-AppxPackage -Name $IdentityName -ErrorAction SilentlyContinue
    if (-not $pkg) { throw "Install did not complete (package '$IdentityName' not found afterward)." }
    Write-Host "[OK] Installed $($pkg.PackageFullName)" -ForegroundColor Green
    Write-Host "Launch 'XeFM' from the Start menu. Remove with: make uninstall-windows-msix"
    return
}

function New-ThrowawayCert {
    Write-Host "[INFO] Creating self-signed cert (Subject must equal Publisher)..."
    # Drop any prior private-key certs with the same subject so CurrentUser\My
    # does not accumulate a duplicate on every rebuild (trust lives in the
    # machine store via the .cer, so removing these here is safe).
    Get-ChildItem Cert:\CurrentUser\My -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $Publisher } | Remove-Item -Force -ErrorAction SilentlyContinue
    $cert = New-SelfSignedCertificate -Type Custom -CertStoreLocation Cert:\CurrentUser\My `
        -Subject $Publisher -KeyUsage DigitalSignature -FriendlyName "XeFM MSIX prototype" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")
    $securePw = ConvertTo-SecureString -String $pfxPassword -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $securePw | Out-Null
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
}

# ===========================================================================
# Default action: build (and optionally -Sign) the package, or with -Bundle
# combine two that are built.
# ===========================================================================
$makeappx = Find-SdkTool "makeappx.exe"
Write-Host "[INFO] makeappx: $makeappx"
if ($Sign) {
    $signtool = Find-SdkTool "signtool.exe"
    Write-Host "[INFO] signtool: $signtool"
}

if ($Bundle) {
    # The two packages share an identity and a version, and differ only in
    # ProcessorArchitecture. Atomic like the pack below. Packages inside a signed
    # bundle need no signature of their own; the Store takes it all unsigned.
    $bundleInputs = "$OutDir\msixbundle-inputs"
    foreach ($stale in @($bundleFile, $bundleTmp, $bundleInputs, $pfx, $cer)) {
        if (Test-Path $stale) { Remove-Item -Recurse -Force $stale }
    }
    New-Item -ItemType Directory -Force -Path $bundleInputs | Out-Null
    foreach ($a in @('x64', 'arm64')) {
        $one = "$OutDir\XeFM-$Version-$a.msix"
        if (-not (Test-Path $one)) { throw "Package not found: $one. Run 'make windows-msix ARCH=$a' first." }
        Copy-Item -Force $one $bundleInputs
    }
    if ($Sign) { New-ThrowawayCert }
    Write-Host "[INFO] Bundling -> $bundleTmp"
    & $makeappx bundle /d $bundleInputs /p $bundleTmp /bv $Version /o
    if ($LASTEXITCODE -ne 0) { throw "makeappx bundle failed ($LASTEXITCODE)" }
    if ($Sign) {
        Write-Host "[INFO] Signing bundle..."
        & $signtool sign /fd SHA256 /f $pfx /p $pfxPassword $bundleTmp
        if ($LASTEXITCODE -ne 0) { throw "signtool sign failed ($LASTEXITCODE)" }
    }
    Remove-Item -Recurse -Force $bundleInputs
    Move-Item -Force $bundleTmp $bundleFile
    Write-Host ""
    Write-Host "[DONE] Bundle: $bundleFile" -ForegroundColor Green
    return
}

$makepri = Find-SdkTool "makepri.exe"
Write-Host "[INFO] makepri: $makepri"

if (-not (Test-Path $PayloadSource))            { throw "Payload source not found: $PayloadSource. Run 'make windows-app ARCH=$Arch' first." }
if (-not (Test-Path "$PayloadSource\XeFM.exe"))  { throw "XeFM.exe not found in payload source $PayloadSource. Run 'make windows-app ARCH=$Arch' first." }
# The manifest declares an app execution alias on this file, and a missing
# alias target is only found when a user's xefmctl fails.
if (-not (Test-Path "$PayloadSource\xefmctl.exe")) { throw "xefmctl.exe not found in payload source $PayloadSource (bundle predates the xefmctl alias, #983). Run 'make windows-app ARCH=$Arch' first." }

# ---- 1. Generate Store tile assets ---------------------------------------
$assetsSrc = "$ScriptDir\resources\Assets"
if (-not $SkipAssets) {
    Write-Host "[INFO] Generating Store tile assets..."
    # Use the venv's interpreter (has Pillow) rather than a bare 'python', since
    # 'make' does not activate the venv — same approach as build.ps1.
    $venvPy = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) { throw ".venv not found at $venvPy. Run 'make venv' first." }
    $env:PYTHONPATH = "$ScriptDir;$projectRoot\src"
    & $venvPy "$ScriptDir\make_store_assets.py"
    if ($LASTEXITCODE -ne 0) { throw "make_store_assets.py failed ($LASTEXITCODE)" }
}
if (-not (Test-Path "$assetsSrc\StoreLogo.png")) { throw "Assets missing in $assetsSrc; run without -SkipAssets." }

# ---- 2. Stage the payload -------------------------------------------------
$staging = "$OutDir\msix-staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Write-Host "[INFO] Staging payload from $PayloadSource ..."
robocopy $PayloadSource $staging /E /NFL /NDL /NJH /NJS /NP | Out-Null   # 0-7 = success
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

Copy-Item -Recurse -Force $assetsSrc "$staging\Assets"

# ---- 3. Generate AppxManifest.xml at the payload root ---------------------
# windows.appExecutionAlias: the ONLY way anything in this package can be
# started by a process that is not part of it. Everything under
# C:\Program Files\WindowsApps refuses CreateProcess from such a process with
# "Access is denied" - and every shell XeFM starts is such a process: Windows
# starts a child whose program lies outside the package (cmd, PowerShell,
# bash) without the identity, so the xefmctl.cmd shim's runtime\python.exe
# was refused from all of them (#983). The alias puts a stub in
# %LOCALAPPDATA%\Microsoft\WindowsApps (on PATH) that starts xefmctl.exe with
# this package's identity, which may then run the bundled interpreter; the
# packaged XeFM's shim calls that stub (xefm/remote_server.py). The alias name
# must match the file name, and the target must be an .exe - which is why
# xefmctl is one (src/xefmctl.c).
$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap3 desktop rescap">

  <!-- PROTOTYPE identity. For a real submission replace with Partner Center values. -->
  <Identity
    Name="$IdentityName"
    Publisher="$Publisher"
    Version="$Version"
    ProcessorArchitecture="$Arch" />

  <Properties>
    <DisplayName>XeFM</DisplayName>
    <PublisherDisplayName>$PublisherDisplayName</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>

  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop"
                        MinVersion="10.0.17763.0"
                        MaxVersionTested="10.0.26100.0" />
  </Dependencies>

  <Resources>
    <Resource Language="en-us" />
  </Resources>

  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>

  <Applications>
    <Application Id="XeFM"
                 Executable="XeFM.exe"
                 EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements
        DisplayName="XeFM"
        Description="Dual-pane terminal-style file manager"
        Square150x150Logo="Assets\Square150x150Logo.png"
        Square44x44Logo="Assets\Square44x44Logo.png"
        BackgroundColor="#1B2429">
        <uap:DefaultTile Wide310x150Logo="Assets\Wide310x150Logo.png" />
      </uap:VisualElements>
      <Extensions>
        <uap3:Extension
          Category="windows.appExecutionAlias"
          Executable="xefmctl.exe"
          EntryPoint="Windows.FullTrustApplication">
          <uap3:AppExecutionAlias>
            <desktop:ExecutionAlias Alias="xefmctl.exe" />
          </uap3:AppExecutionAlias>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>
</Package>
"@
$manifestPath = "$staging\AppxManifest.xml"
# UTF-8 without BOM (makeappx dislikes a BOM on the manifest).
[System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[INFO] Wrote manifest: $manifestPath"

# ---- 3b. Index the qualified assets into resources.pri --------------------
# MRT only finds Square44x44Logo's targetsize-* / _altform-unplated variants
# through the package's resources.pri. With no PRI the shell sees just the one
# path the manifest names, and *plates* the taskbar icon -- XeFM's rounded tile
# composited into a solid accent-colored square (issue #322). So the unplated
# PNGs make_store_assets.py emits are inert until they are indexed here.
#
# makepri indexes a throwaway root holding only the manifest and Assets\, not
# $staging: pointed at the full payload it would walk every file under
# Lib\site-packages to no purpose. The layout under it mirrors the package's, so
# the indexed Assets\... paths resolve identically once the PRI is copied in.
$priRoot   = "$OutDir\msix-pri"
$priConfig = "$OutDir\priconfig.xml"
$priFile   = "$OutDir\resources.pri"
if (Test-Path $priRoot) { Remove-Item -Recurse -Force $priRoot }
New-Item -ItemType Directory -Force -Path $priRoot | Out-Null
Copy-Item -Force $manifestPath "$priRoot\AppxManifest.xml"
Copy-Item -Recurse -Force $assetsSrc "$priRoot\Assets"

& $makepri createconfig /cf $priConfig /dq en-US /o | Out-Null
if ($LASTEXITCODE -ne 0) { throw "makepri createconfig failed ($LASTEXITCODE)" }

# Drop <packaging>: its autoResourcePackage entries split the scale-200 tiles out
# into a separate resources.scale-200.pri -- a resource *package* that this
# .msix never carries (the .msixbundle holds only the two architecture packages),
# leaving those tiles unresolvable. Without the element every candidate lands in
# the one resources.pri we ship.
$priXml = [xml](Get-Content $priConfig)
$packaging = $priXml.resources.packaging
if ($packaging) { $priXml.resources.RemoveChild($packaging) | Out-Null }
$priXml.Save($priConfig)

# Clear stale PRIs so the split-check below cannot pass on a leftover file.
Get-ChildItem $OutDir -Filter "resources*.pri" -ErrorAction SilentlyContinue | Remove-Item -Force
& $makepri new /pr $priRoot /cf $priConfig /of $priFile /o | Out-Null
if ($LASTEXITCODE -ne 0) { throw "makepri new failed ($LASTEXITCODE)" }
$split = @(Get-ChildItem $OutDir -Filter "resources.*.pri" -ErrorAction SilentlyContinue)
if ($split.Count) { throw "makepri split out $($split[0].Name); the <packaging> strip did not take." }
Copy-Item -Force $priFile "$staging\resources.pri"
Write-Host "[INFO] Wrote resources.pri -> $staging"

# ---- 4. Pack + optional sign (atomic) -------------------------------------
# The final $msix must only ever exist as a fully-built (and, if requested,
# fully-signed) artifact. So we pack to a temp path and promote it with a
# rename only after every step below succeeds. Any stale artifacts from a
# previously-aborted run are cleared first, so a failure here leaves NO $msix
# rather than an unsigned one masquerading as complete -- which is what the
# -Install step would otherwise trust.
foreach ($stale in @($msix, $msixTmp, $pfx, $cer)) {
    if (Test-Path $stale) { Remove-Item -Force $stale }
}

# When signing, mint the cert FIRST: it is the cheap, most-likely-to-fail step
# (cert policy, missing signtool), so failing before the slow pack is cheaper
# and never leaves a packed-but-unsigned artifact behind.
if ($Sign) { New-ThrowawayCert }

Write-Host "[INFO] Packing -> $msixTmp"
& $makeappx pack /d $staging /p $msixTmp /o
if ($LASTEXITCODE -ne 0) { throw "makeappx pack failed ($LASTEXITCODE)" }

if ($Sign) {
    Write-Host "[INFO] Signing package..."
    & $signtool sign /fd SHA256 /f $pfx /p $pfxPassword $msixTmp
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed ($LASTEXITCODE)" }
}

# Commit point: promote the temp package to its final name. From here on the
# artifact is guaranteed complete, so -Install can trust its presence.
Move-Item -Force $msixTmp $msix
Write-Host "[OK] Built $msix"
if ($Sign) {
    Write-Host "[OK] Signed $msix"
    Write-Host "Install locally with:  make install-windows-msix" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[DONE] Prototype package: $msix" -ForegroundColor Green
