# XeFM on the Microsoft Store (MSIX) — Implementation Plan

**Status:** PARTIALLY IMPLEMENTED. Written 2026-07-20. The local MSIX tooling now
exists — `windows_app/build_msix.ps1` (self-signed prototype), `make_store_assets.py`,
and the `windows-app-msix{,-install,-uninstall}` Makefile targets — and Step 1
(relocating `XeFM-error.log` to `~/.xefm/`) is done in `launcher.c`. What remains is
the manual Partner Center Store submission.

**Goal:** distribute XeFM through the Microsoft Store as an **MSIX package** so that
code signing is **free and automatic** (the Store re-signs the package after
certification — no certificate to buy, no SmartScreen warnings) and the developer
account is now **free** for individuals and companies.

This is the Windows analog of the macOS Developer ID + notarization work already
done in [`MACOS_APP_BUILD_SYSTEM.md`](MACOS_APP_BUILD_SYSTEM.md#code-signing--notarization).
It builds on the existing Windows bundle produced by
[`WINDOWS_APP_BUILD_SYSTEM.md`](WINDOWS_APP_BUILD_SYSTEM.md) /
`windows_app/build.ps1`.

---

## 0. Why MSIX-via-Store (and the one catch)

| Route | Signing cost | SmartScreen | Effort |
|-------|--------------|-------------|--------|
| **Store, MSIX package** | **Free** (Microsoft re-signs) | **No warnings** | Package as MSIX + per-release certification |
| Store, MSI/EXE installer | You Authenticode-sign it | No prompt on Store install | You still need a CA cert |
| Non-Store zip (today) | Unsigned | Strong SmartScreen block | None |
| Non-Store zip + SignPath Foundation | Free (OSS) OV cert | Warns until reputation builds | Apply to SignPath |

The free-signing benefit is **specific to the MSIX package path**. If we ever
submitted a raw MSI/EXE installer instead, Microsoft would *not* re-sign it.

> **Lower-effort fallback if the Store proves too fiddly:** because XeFM is open
> source, [SignPath Foundation](https://signpath.io) offers free OV code signing
> for qualifying OSS projects, which would let us keep shipping the current
> `.zip` signed. Worth keeping in the back pocket. This doc pursues the Store
> route because it gives the best end-user experience (zero warnings).

---

## 1. What MSIX changes about how XeFM runs (read this first)

MSIX is **not** just a different installer format — it changes the app's runtime
environment, and two of those changes directly affect a file manager that shells
out and writes logs. Understand these before touching the manifest:

1. **The install directory is read-only to the app.** MSIX installs under
   `C:\Program Files\WindowsApps\<PackageFullName>\`. The app **cannot write into
   its own install folder.** Writes there are silently redirected to a per-user
   virtualized location (or fail, depending on the API).
   - 🔴 **XeFM impact (confirmed):** the launcher's `BOOTSTRAP` Python writes
     **`XeFM-error.log` to `os.path.dirname(sys.executable)`** — i.e. right next to
     `XeFM.exe` (`windows_app/src/launcher.c`, in the `BOOTSTRAP` string, the
     `base = os.path.dirname(sys.executable)` / `open(os.path.join(base,
     'XeFM-error.log'), ...)` lines). Under MSIX that's the read-only install dir,
     so the write is redirected into a hard-to-find per-package VFS location (or
     silently fails — it's wrapped in `except: pass`), defeating the diagnostic.
     **Relocate it** to a user-profile path — `%LOCALAPPDATA%\XeFM\` or, to match
     XeFM's existing convention, `~/.xefm/` (see below).
   - 🔴 Any `.pyc` written at runtime (`__pycache__` next to bundled `.py`) also
     lands in the read-only tree and gets redirected. The build pre-compiles
     everything, so this should be a no-op — **verify no runtime bytecode writes.**

2. **A packaged app has "package identity."** This is what unlocks Store signing
   and clean install/uninstall, but it also means Windows gives the process a
   *virtualized* view of parts of the registry and file system.

3. **Full trust ≠ sandboxed.** We declare the `runFullTrust` capability, so
   `XeFM.exe` runs **as the user, outside an AppContainer** — normal Win32 file
   access and normal process launching. This is why a file manager is feasible at
   all. `runFullTrust` is a *restricted* capability but is **auto-approved** for
   packaged desktop apps during Store certification (no special request needed).
   The name refers to trust level inside the container — it is **not** UAC
   elevation (MSIX apps install/run per-user, non-elevated).

**Net:** XeFM is a full-trust Win32 desktop app, which is exactly the category MSIX
+ Store supports. The work is packaging + fixing the write-location assumptions.

---

## 2. Decisions to lock down before building

These block the manifest, so resolve them first:

### 2a. Reserve the app name in Partner Center → get the real identity
Create the free account at <https://storedeveloper.microsoft.com>, then in
[Partner Center](https://partner.microsoft.com/dashboard) reserve the app name.
Partner Center then gives you three values that **must be copied verbatim** into
`AppxManifest.xml` (do not invent them):
- **Package/Identity/Name** (e.g. `1234PublisherId.XeFM`)
- **Publisher** (e.g. `CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)
- **Publisher display name**

Find them under the reserved product → *Product management → Product identity*.
Building the manifest before reserving the name means rebuilding it afterward.

### 2b. Version scheme — MAJOR MUST BE ≥ 1
MSIX package versions are 4-part `a.b.c.d` with rules the Store enforces:
- The **first section cannot be 0**, and
- The **last section (revision) must be `0`** — the Store reserves it.

🔴 **XeFM impact:** `xefm/__init__.py`'s `__version__` is currently `0.99`. `0.99.0.0` is
**invalid** for the Store (major = 0). Decide one of:
- **(recommended) Ship the Store package as `1.0.0.0`** and treat "on the Store"
  as the 1.0 milestone, keeping `__version__` as the source string mapped to the
  first three sections once it reaches ≥ 1.0; or
- Decouple the MSIX package version from `__version__` (a separate `-MsixVersion`
  build parameter that always emits `major≥1 … .0`).

Each Store submission needs a **strictly higher** package version than the last.

### 2c. Confirm Store policy fit
Full-trust Win32 apps packaged as MSIX are explicitly Store-eligible ("Recommended
for most new apps" per Microsoft's code-signing-options page). File managers are
allowed (Microsoft's own Files app ships on the Store). No expected policy blocker.

---

## 3. Prerequisites / tooling (on the Windows box)

- Everything already required by `windows_app/build.ps1` (MSVC Build Tools,
  Windows 10/11 SDK, a working `.venv`) — the MSIX wraps that build's output.
- **`makeappx.exe`** and **`signtool.exe`** — ship with the Windows SDK; available
  in the *Developer Command Prompt for VS* (same environment `build.ps1` already
  imports via `vswhere`/`VsDevCmd.bat`).
- **Pillow in the venv** (already used by `make_icon.py`) to generate Store logo
  PNGs from `macos_app/resources/XeFM.icns`.
- Optional: **MSIX Packaging Tool** (Store app) — a GUI alternative to hand-authoring,
  but for a build that already produces a clean self-contained folder, the
  `makeappx pack` route below is more reproducible and CI-friendly.

---

## 4. Implementation steps

### Step 1 — Fix the write-location assumptions (code, do this first)
Independent of packaging, and the highest-risk item:
- Relocate `XeFM-error.log` off `os.path.dirname(sys.executable)` in the
  `BOOTSTRAP` string in `windows_app/src/launcher.c`. Writing under `~/.xefm/`
  keeps it consistent with XeFM's existing user-state convention (and is the same
  logic on both platforms); `%LOCALAPPDATA%\XeFM\` is the Windows-idiomatic
  alternative. Make sure the directory is created before opening the file.
- **Good news / lower risk:** XeFM's own config, tools, and state already live
  under **`~/.xefm/`** (`Path.home() / '.xefm'`, e.g. `xefm/external_programs.py`).
  On Windows that resolves to `%USERPROFILE%\.xefm`, a writable user-profile path
  that **passes through** for full-trust packaged apps — so the main app state is
  MSIX-safe as-is. The error log above is the notable exception.
- Still audit for any *other* write relative to the executable or current working
  directory (temp files, caches), and do **not** assume a particular startup CWD.

### Step 2 — Generate Store logo assets
The Store/manifest needs PNG tile assets (not `.ico`). Minimum set (scale-100):
- `Square44x44Logo.png` (app-list icon)
- `Square150x150Logo.png` (medium tile)
- `StoreLogo.png` (50×50, referenced by `<Properties><Logo>`)
- Optional but nice: `Wide310x150Logo.png`, `SplashScreen` / larger tiles, and
  multiple scale variants (`.scale-200` etc.).

Extend `windows_app/make_icon.py` (already Pillow-based) to emit these from the
shared `XeFM.icns`, into `windows_app/resources/Assets/`.

### Step 3 — Author `AppxManifest.xml`
Place at the **root** of the package payload. Template (fill the `‹…›` identity
values from Step 2a):

```xml
<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap rescap">

  <!-- These three come from Partner Center (Product identity). Do not invent. -->
  <Identity
    Name="‹PublisherId›.XeFM"
    Publisher="CN=‹your-store-publisher-guid›"
    Version="1.0.0.0"
    ProcessorArchitecture="x64" />

  <Properties>
    <DisplayName>XeFM</DisplayName>
    <PublisherDisplayName>‹Publisher display name›</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>

  <Dependencies>
    <!-- 1809 is a safe floor for Desktop Bridge full-trust apps. -->
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
```

Notes:
- `EntryPoint="Windows.FullTrustApplication"` + `rescap:runFullTrust` is the
  classic full-trust marker and works down to 1809. (On 2004+ you may instead use
  `uap10:RuntimeBehavior="packagedClassicApp"` + `uap10:TrustLevel="mediumIL"`;
  the EntryPoint form is simpler and broader — prefer it unless there's a reason.)
- If XeFM registers **file associations / "Open with"** on Windows via the
  registry, that won't work packaged (registry is virtualized). Re-declare any
  such association here via `<uap:Extension Category="windows.fileTypeAssociation">`.
  Check whether the Windows build registers anything; if not, skip.

### Step 4 — Pack with `makeappx`
Assemble a payload directory = the existing `windows_app\build\XeFM\` folder
contents **plus** `AppxManifest.xml` and `Assets\` at its root, then:

```powershell
makeappx pack /d <payload-dir> /p windows_app\build\XeFM-<version>-x64.msix /o
```

`makeappx` validates the manifest during packing; fix any schema errors it reports.

### Step 5 — Local test install (self-signed; Store submission does NOT use this)
To run/test the package on the dev machine before submitting, sign it with a
temporary self-signed cert whose **Subject exactly equals the manifest `Publisher`
string**, trust that cert, then install:

```powershell
# subject MUST match <Identity Publisher="..."> exactly
New-SelfSignedCertificate -Type Custom -CertStoreLocation Cert:\CurrentUser\My `
  -Subject "CN=‹your-store-publisher-guid›" -KeyUsage DigitalSignature `
  -FriendlyName "XeFM MSIX test" `
  -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")
# export to PFX, import the .cer into LocalMachine\TrustedPeople (admin), then:
signtool sign /fd SHA256 /a /f xefm-test.pfx /p <pw> windows_app\build\XeFM-<version>-x64.msix
Add-AppxPackage windows_app\build\XeFM-<version>-x64.msix
```

Then run the **risk-validation checklist in §5**. When done testing:
`Remove-AppxPackage` and delete the test cert.

> For the **actual Store submission you do NOT sign** — you upload the unsigned
> `.msix` (carrying the Partner-Center identity) and Microsoft re-signs it. The
> self-signed step is purely to exercise the package locally.

### Step 6 — Submit via Partner Center
Create a submission for the reserved app, upload the `.msix`, complete the listing
(description, screenshots, category, privacy), and submit for certification.
Microsoft re-signs on success. Certification typically takes hours to a couple of
days; each update needs a higher package version (§2b).

### Step 7 — Wire into the build (after it works manually)
Once the manual flow succeeds end-to-end, fold it into `windows_app/build.ps1` as
a `-Msix` switch (mirroring how macOS's `create_dmg.sh` extends the app build):
generate assets → emit manifest (identity values via parameters / a gitignored
`windows_app\store.env`, same pattern as `macos_app\signing.env`) → `makeappx pack`.
Add a `windows-app-msix` Makefile target. Keep identity values **out of git**.

---

## 5. Risk-validation checklist (the file-manager-specific part)

Run every item from the **locally installed package** (Step 5), because behavior
differs from running the loose `XeFM.exe`. This is where a file manager is most
likely to hit MSIX edges:

- [ ] **Error log / all writes** land under `%LOCALAPPDATA%`, not the install dir.
      Confirm nothing tries (and silently fails) to write into `WindowsApps\`.
- [ ] **Config & state** persist across launches (written to the user profile,
      read back correctly under package identity).
- [ ] **Subshell** (drop-to-shell) launches `cmd`/`powershell` and it sees the
      **real** filesystem and a sane working directory.
- [ ] **External programs** (F-key tools, `xefm/tools/*`) launch and receive correct
      paths/arguments; child processes behave as the user, not sandboxed.
- [ ] **"Open with OS"** hands files to the correct default apps.
- [ ] **Drag & drop** in/out of the XeFM window works.
- [ ] **Archive / S3 / SFTP** features that spawn helpers or write temp files work
      (temp dir should resolve to a writable per-user location).
- [ ] **numpy / native `.pyd`** load correctly from the packaged tree (read-only
      reads are fine; just confirm no load failure).
- [ ] Startup has **no runtime `.pyc` write** churn (all bytecode pre-compiled).

**If a write-location problem can't be fixed in XeFM's own code**, the
[Package Support Framework (PSF)](https://learn.microsoft.com/en-us/windows/msix/psf/package-support-framework-overview)
can redirect writes at runtime — but prefer fixing paths in code over shipping PSF.

---

## 6. Order of operations (summary)

1. Fix write locations in code (Step 1) — this is independent and can land now.
2. Reserve app name in Partner Center → capture identity values (§2a).
3. Decide the version scheme (§2b) — likely bump to `1.0.0.0`.
4. Generate assets (Step 2) + author manifest (Step 3).
5. `makeappx pack` (Step 4) → self-signed local install (Step 5) → run §5 checklist.
6. Fix whatever the checklist surfaces; repeat 4–5.
7. Submit via Partner Center (Step 6).
8. Only then automate in `build.ps1` (Step 7).

---

## 7. Open questions to confirm during implementation

- Does the Windows build register any **file associations / context-menu / "Open
  with XeFM"** entries? If yes, they must move into the manifest as extensions.
- Config/state is already under `~/.xefm/` (MSIX-safe, confirmed). Remaining to
  check: any **temp-file / cache** writes (archive extraction, S3/SFTP staging)
  resolve to a writable per-user temp dir, not the install tree.
- Is a **single-architecture x64** package sufficient, or is an arm64 build wanted
  later? (Manifest `ProcessorArchitecture` / a bundle would change.)
- Individual vs company Store account — the identity/Publisher differs; pick before
  reserving the name.

---

## 8. Command-line installation (the primary consumption path)

XeFM's audience skews to developers — most of them install software from a
shell, not by clicking through the Store GUI. The good news is that a single
Store MSIX submission (§4–6) gives you a **first-class `winget` install line for
free**, and that is arguably the biggest end-user payoff of this whole effort.

### 8a. `winget` via the `msstore` source (recommended)
Once the package is live on the Store, it is installable directly from the
command line — no browser, no GUI:

```powershell
winget install --id 9N‹XXXXXXXXXX› --source msstore
```

- The `9N…` is the **Store product ID** from the Partner Center listing / Store
  URL — **not** the manifest `Identity/Name` (`‹PublisherId›.XeFM`). They are
  different identifiers; don't confuse them.
- First use of the `msstore` source prompts once to accept Microsoft Store terms.
  In CI / unattended installs, pre-agree with:
  ```powershell
  winget install --id 9N‹XXXXXXXXXX› --source msstore `
    --accept-source-agreements --accept-package-agreements
  ```

### 8b. `winget` via the community repo (default `winget` source)
You can *also* submit a manifest to
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) so the shorter,
source-less form works from winget's default repository:

```powershell
winget install crftwr.XeFM
```

That manifest can point at **either** the Store package **or** a directly-signed
installer, so this is the same route SignPath's OV cert would use *without* the
Store at all.

### 8c. Sideloading (`Add-AppxPackage`) — dev/test and enterprise only
```powershell
Add-AppxPackage windows_app\build\XeFM-<version>-x64.msix
```

Direct install of the `.msix`, no winget. Used for the local-test step (§5) and
enterprise/MDM deployment — not a consumer path.

### 🔴 Channel does not equal trust (why 8b/8c do NOT skip the warning)
A future reader will be tempted to reach for the community repo or sideloading to
"avoid the SmartScreen warning." **They don't.** The zero-warning experience comes
from the **signature**, not the delivery channel:

| Path | What it installs | SmartScreen / warning |
|------|------------------|-----------------------|
| `winget --source msstore` (8a) | The Microsoft-re-signed Store MSIX | **None** — Store signature |
| `winget-pkgs` → Store product (8b) | Same Store MSIX, via a pointer | **None** — inherits Store signature |
| `winget-pkgs` → SignPath-signed installer (8b) | Your OV-signed artifact | No hard block; **reputation ramp** |
| `winget-pkgs` → unsigned zip/exe (8b) | Today's unsigned artifact | **Same block as today** |
| `Add-AppxPackage` unsigned/self-signed (8c) | Loose `.msix` | **Won't install** unless the cert is already trusted (admin import) |

- `winget-pkgs` is only a **pointer** — it downloads and runs whatever artifact it
  references and adds no trust of its own.
- `Add-AppxPackage` **cannot install an unsigned MSIX at all**; a self-signed cert
  requires the user to import it into `TrustedPeople` first, which is worse UX than
  the warning, not better.

**Net:** trust = Microsoft re-signature (Store) **or** an OV cert (SignPath). The
CLI paths above are about convenience and discovery; they change *how* users
install, not *whether* they see a warning.

---

## References

- [Code signing options for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) — MSIX-via-Store is free + auto-signed
- [Generating MSIX package components (manual conversion)](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion) — manifest + `makeappx` + `runFullTrust`
- [App package requirements for MSIX](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements) — version rules (revision must be 0, major ≠ 0)
- [Understanding how packaged desktop apps run](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-behind-the-scenes) — full-trust runtime + file/registry virtualization
- [Package Support Framework overview](https://learn.microsoft.com/en-us/windows/msix/psf/package-support-framework-overview) — runtime write-redirection fallback
- [Free developer registration (individuals)](https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer) · [company accounts now free](https://blogs.windows.com/windowsdeveloper/2026/05/07/publish-to-microsoft-store-as-a-company-now-with-free-registration-and-faster-onboarding/)
- Related in this repo: [`WINDOWS_APP_BUILD_SYSTEM.md`](WINDOWS_APP_BUILD_SYSTEM.md), [`MACOS_APP_BUILD_SYSTEM.md`](MACOS_APP_BUILD_SYSTEM.md#code-signing--notarization)
