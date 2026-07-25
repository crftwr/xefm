<#
.SYNOPSIS
    Prototype MSIX packager + local installer for XeFM (Store / winget distribution).

.DESCRIPTION
    Wraps the existing windows_app\build\XeFM bundle (produced by build.ps1) into an
    installable .msix, following doc/dev/WINDOWS_STORE_MSIX_PLAN.md:

      (default)   generate assets -> stage payload + AppxManifest -> makeappx pack
      -Sign       also self-sign the package for LOCAL testing
      -Install    trust the self-signed cert (elevates) + Add-AppxPackage (per-user)
      -Uninstall  Remove-AppxPackage + delete the throwaway signing certs (elevates)
      -TrustCert  internal: import the cert into LocalMachine\TrustedPeople (elevated child)
      -CleanCert  internal: remove the cert from LocalMachine\TrustedPeople (elevated child)

    This does NOT submit to the Store. For a real submission the identity values
    come from Partner Center and Microsoft re-signs the (unsigned) package; the
    self-signed path here is purely to exercise the package on the dev box.

.NOTES
    Identity defaults are PLACEHOLDERS — replace -IdentityName / -Publisher /
    -PublisherDisplayName with Partner Center "Product identity" values before any
    real submission (see WINDOWS_STORE_MSIX_PLAN.md 2a).
#>
[CmdletBinding()]
param(
    # PayloadSource / OutDir default to paths under the script dir, but are filled
    # in below — NOT here — because $PSScriptRoot is not reliably populated in a
    # param default when the script is launched via 'powershell -File' (as the
    # Makefile does). Evaluated here it comes back empty, yielding '\build\XeFM'.
    [string]$PayloadSource,
    [string]$OutDir,
    [string]$Version              = "1.0.0.0",           # major != 0, revision = 0 (Store rule)
    [string]$IdentityName         = "XeFM.Prototype",     # Partner Center: Package/Identity/Name
    [string]$Publisher            = "CN=XeFM Prototype Dev", # Partner Center: Publisher (CN=...)
    [string]$PublisherDisplayName = "XeFM Prototype",
    [string]$Arch                 = "x64",
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
if (-not $PayloadSource) { $PayloadSource = Join-Path $ScriptDir 'build\XeFM' }
if (-not $OutDir)        { $OutDir        = Join-Path $ScriptDir 'build' }

# Artifact paths shared by build + install actions.
$msix    = "$OutDir\XeFM-$Version-$Arch.msix"
# Packed/signed here, then renamed to $msix only on full success. Keeps the
# .msix extension (before .building) because signtool refuses to sign a file
# whose extension it doesn't recognize as an app package.
$msixTmp = "$OutDir\XeFM-$Version-$Arch.building.msix"
$pfx     = "$OutDir\XeFM-proto-test.pfx"
$cer     = "$OutDir\XeFM-proto-test.cer"
$pfxPassword = "prototest"

function Find-SdkTool([string]$name) {
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $hit = Get-ChildItem -Path $root -Recurse -Filter $name -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -match "\\x64\\$([regex]::Escape($name))$" } |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
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
            $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -CleanCert -Publisher `"$Publisher`""
            $proc = Start-Process -FilePath $psExe -Verb RunAs -Wait -PassThru -ArgumentList $argLine
            if ($proc.ExitCode -ne 0) { Write-Host "[WARN] Elevated cert cleanup failed or was cancelled (exit $($proc.ExitCode))." }
        }
    }

    # 4. Delete the throwaway cert files (they also go with 'make windows-app-clean').
    foreach ($file in @($pfx, $cer)) {
        if (Test-Path $file) { Remove-Item -Force $file; Write-Host "[OK] Deleted $file" }
    }
    return
}

# ===========================================================================
# Action: -Install — trust the cert (elevates) then install per-user.
# ===========================================================================
if ($Install) {
    if (-not (Test-Path $msix)) { throw "Package not found: $msix. Run 'make windows-app-msix' first." }
    if (-not (Test-Path $cer))  { throw "Signing cert not found: $cer. Run 'make windows-app-msix' first." }

    # Step 1: trust the self-signed cert (machine-wide store => needs admin).
    if (Test-IsAdmin) {
        Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
        Write-Host "[OK] Certificate trusted."
    } else {
        Write-Host "[INFO] Requesting elevation to trust the signing certificate (accept the UAC prompt)..."
        $psExe = (Get-Process -Id $PID).Path
        $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -TrustCert -OutDir `"$OutDir`""
        $proc = Start-Process -FilePath $psExe -Verb RunAs -Wait -PassThru -ArgumentList $argLine
        if ($proc.ExitCode -ne 0) { throw "Elevated cert-trust step failed or was cancelled (exit $($proc.ExitCode))." }
    }

    # Step 2: install per-user (cert is now trusted; Add-AppxPackage needs no admin).
    Write-Host "[INFO] Installing package (Add-AppxPackage)..."
    Add-AppxPackage -Path $msix
    $pkg = Get-AppxPackage -Name $IdentityName -ErrorAction SilentlyContinue
    if (-not $pkg) { throw "Install did not complete (package '$IdentityName' not found afterward)." }
    Write-Host "[OK] Installed $($pkg.PackageFullName)" -ForegroundColor Green
    Write-Host "Launch 'XeFM' from the Start menu. Remove with: make windows-app-msix-uninstall"
    return
}

# ===========================================================================
# Default action: build (and optionally -Sign) the package.
# ===========================================================================
$makeappx = Find-SdkTool "makeappx.exe"
Write-Host "[INFO] makeappx: $makeappx"
if ($Sign) {
    $signtool = Find-SdkTool "signtool.exe"
    Write-Host "[INFO] signtool: $signtool"
}

if (-not (Test-Path $PayloadSource))            { throw "Payload source not found: $PayloadSource. Run 'make windows-app' first." }
if (-not (Test-Path "$PayloadSource\XeFM.exe"))  { throw "XeFM.exe not found in payload source $PayloadSource. Run 'make windows-app' first." }

# ---- 1. Generate Store tile assets ---------------------------------------
$assetsSrc = "$ScriptDir\resources\Assets"
if (-not $SkipAssets) {
    Write-Host "[INFO] Generating Store tile assets..."
    # Use the venv's interpreter (has Pillow) rather than a bare 'python', since
    # 'make' does not activate the venv — same approach as build.ps1.
    $projectRoot = Split-Path -Parent $ScriptDir
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
$manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">

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
        BackgroundColor="transparent">
        <uap:DefaultTile Wide310x150Logo="Assets\Wide310x150Logo.png" />
      </uap:VisualElements>
    </Application>
  </Applications>
</Package>
"@
$manifestPath = "$staging\AppxManifest.xml"
# UTF-8 without BOM (makeappx dislikes a BOM on the manifest).
[System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[INFO] Wrote manifest: $manifestPath"

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
if ($Sign) {
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
    Write-Host "Install locally with:  make windows-app-msix-install" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[DONE] Prototype package: $msix" -ForegroundColor Green
