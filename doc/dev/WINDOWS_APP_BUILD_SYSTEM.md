# Windows Application Bundle — Build System

This document describes the `windows_app/` build system that packages XeFM into a
self-contained Windows application folder (`XeFM.exe` + embedded CPython + all
dependencies), the direct counterpart of the macOS `macos_app/` bundle.

It is the design-and-implementation reference; the source of truth is the code
under `windows_app/`.

---

## Goals

- A double-clickable `XeFM.exe` that launches XeFM in the native **Windows GUI
  backend** (PuiKit's Direct2D/DirectWrite renderer), with no console window.
- **Self-contained**: no dependency on a system Python, on the developer's
  `.venv`, or on any pip-installed package on the target machine.
- **Hand-rolled and transparent**, mirroring the macOS approach — no PyInstaller
  / cx_Freeze magic. Every file that lands in the bundle is put there by an
  explicit, readable step.

## Why this mirrors macOS so closely

The macOS bundle embeds a `Python.framework` and drives it from a small Obj-C
launcher (`macos_app/src/{main.m,XeFMAppDelegate.m}`) that:

1. initializes CPython with `PyConfig` (Python home = the embedded runtime),
2. points `sys.path` at the bundled XeFM source, PuiKit, and third-party packages,
3. sets `sys.argv = ["XeFM", "--backend", "gui"]`, and
4. imports the `xefm` module and calls `xefm.app.main()`.

The Windows launcher (`windows_app/src/launcher.c`) does the **same four things**
against the CPython **embeddable** distribution. Crucially, there is **nothing to
compile in XeFM or PuiKit**: PuiKit's Windows backend
(`puikit/backends/windows_backend.py`, `_win32_native.py`) is pure Python built
on `ctypes` + `numpy`, exactly as the macOS backend is pure PyObjC. The only
native code we build is the ~200-line launcher stub itself.

---

## Bundle layout

The build produces `windows_app/build/XeFM/`, a self-contained folder (this whole
folder is what gets zipped for distribution):

```
XeFM/                              <- bundle root = the .exe's directory (5 entries)
├── XeFM.exe                       compiled C launcher (this repo); static CRT, no DLL deps
├── LICENSE                       XeFM's own license
├── THIRD_PARTY_NOTICES.txt       aggregated license text for bundled components
├── runtime/                      the entire embedded CPython, kept out of the root
│   ├── python3XX.dll             CPython (delay-loaded by XeFM.exe)
│   ├── python3.dll               stable-ABI forwarder
│   ├── python3XX.zip             zipped standard library
│   ├── vcruntime140.dll, vcruntime140_1.dll   the CRT python3XX.dll needs
│   ├── _ctypes.pyd, _ssl.pyd, ...             stdlib C extensions
│   ├── libffi-8.dll, libssl-3.dll, ...        their support DLLs
│   ├── python.exe, pythonw.exe                (usable standalone for debugging)
│   └── LICENSE.txt               embedded CPython's PSF license
├── app/                          XeFM's own code (mirror of macOS Resources/)
│   ├── xefm/app.py                    entry script (imported as the `xefm` module)
│   ├── src/                      xefm_* business-logic modules
│   └── puikit/                   PuiKit toolkit (copied from the sibling repo)
└── Lib/
    └── site-packages/            third-party deps: numpy, pygments, boto3, watchdog, ...
```

The app icon is compiled **into** `XeFM.exe` as a resource (`XeFM.rc`) and the
window icon loads from there, so no loose `XeFM.ico` ships in the bundle.

### Path resolution at runtime

The launcher computes `<root>` from `GetModuleFileNameW` (the directory
containing `XeFM.exe`) and configures CPython **explicitly** — it does *not* rely
on a `python3XX._pth` file — so the layout is unambiguous:

- `PyConfig.home = <root>`
- `PyConfig.module_search_paths` (with `module_search_paths_set = 1`):
  1. `<root>\runtime\python3XX.zip`  — standard library
  2. `<root>\runtime`                — stdlib C extensions (`*.pyd`) and their DLLs
  3. `<root>\Lib\site-packages`      — third-party deps
  4. `<root>\app`                    — the `xefm` package and `puikit`
- `PyConfig.site_import = 0`, `user_site_directory = 0` — fully deterministic
  path; no `site.py` global-path guessing, no user site-packages leaking in
  (the equivalent of the macOS bundle's `sitecustomize.py`).
- `PyConfig.write_bytecode = 0` — the install dir may be read-only
  (e.g. `Program Files`); the standard library and app code are pre-compiled at
  build time instead.

`sys.argv` is set to `["XeFM", "--backend", "gui"]` (via `PyConfig.argv` with
`parse_argv = 0`) so `xefm.app.main()`'s argparse selects the Windows GUI backend —
`create_backend("gui")` maps to `WindowsBackend` on `sys.platform == "win32"`.

---

## The launcher (`src/launcher.c`)

- **GUI subsystem** (`/SUBSYSTEM:WINDOWS`, `wWinMain` entry): no console window.
  Because there is no terminal, any failure *before* the UI is up is surfaced via
  `MessageBoxW`, not stderr:
  - CPython init failures are reported from the `PyStatus` error message in C.
  - Failures *after* init (import errors, exceptions from `xefm.app.main()`) are caught
    by a small Python bootstrap that formats the traceback and shows it in a
    message box (and writes `XeFM-error.log` next to the exe).
- **No import library shipped**: `Python.h` auto-links `python3XX.lib` via
  `#pragma comment(lib, ...)`; the build only has to supply `/I<include>` and
  `/LIBPATH:<libs>` from the developer's full CPython install (`sys.base_prefix`).
- **Static CRT + delay-loaded interpreter** so the whole runtime can live in
  `runtime\` (see layout) with nothing beside the exe. `XeFM.exe` is built `/MT`
  (its only load-time deps are `kernel32`/`user32`), and `python3XX.dll` is
  delay-loaded (`/DELAYLOAD:python3XX.dll` + `delayimp.lib`). At startup, before
  the first Python call, the launcher `SetDefaultDllDirectories` +
  `AddDllDirectory(<root>\runtime)` and pre-loads `python3XX.dll` by full path
  (turning a missing runtime into a clear message box instead of a delay-load
  crash); CPython's extension loader then resolves each `.pyd`'s sibling DLLs
  from `runtime\` via `LOAD_WITH_ALTERED_SEARCH_PATH`.
- **Manifest** (`resources/XeFM.manifest`): mirrors CPython 3.14's own
  `python.exe` manifest — `asInvoker`, the Vista→Win11 `supportedOS` GUIDs,
  `longPathAware`, and Common-Controls v6, plus **Per-Monitor-V2 `dpiAware`/
  `dpiAwareness`**. The WindowsBackend has a real DPI-scaling path (font sizes
  and the base unit scale by the monitor's `GetDpiForWindow`; `WM_DPICHANGED`
  rescales live), so declaring awareness lets text render at the display's true
  pixel density instead of being bitmap-stretched. The backend also calls
  `SetProcessDpiAwarenessContext` at startup, so plain `python -m xefm --backend
  gui` is DPI-aware too and the two still render **identically**; the manifest
  just fixes it at process start for the bundle.

---

## The embedded runtime — CPython "embeddable" package

`build.ps1` downloads the official `python-<X.Y.Z>-embed-amd64.zip` from
python.org **matching the exact version of the developer's `.venv`** and extracts
it into the bundle root. This is the minimal, redistributable CPython: the DLL,
the zipped stdlib, and the stdlib C-extension `.pyd`s + their support DLLs
(`libffi`, `libssl`/`libcrypto`, etc.). `ctypes` (which the whole Windows backend
rides on) and its `libffi-8.dll` are included.

**Version lock:** compiled wheels in `.venv\Lib\site-packages` (notably `numpy`)
are built for the venv's Python ABI (`cp3XX`). The embeddable must be the same
`X.Y`, so `build.ps1` derives the download version from the venv interpreter and
refuses to mix ABIs.

**Coverage note:** the 3.14 embeddable ships a broad stdlib C-extension set —
including `_ctypes.pyd` + `libffi-8.dll` (which the whole Windows backend rides
on), `_ssl`/`_hashlib` + `libssl`/`libcrypto`, and `_sqlite3.pyd` + `sqlite3.dll`.
It omits `_tkinter` (and Tcl/Tk); XeFM/PuiKit don't use it, so that's fine. If a
future dependency needs a module the embeddable leaves out, copy its `.pyd`
(+ any support DLL) from a full CPython install of the same version into the
bundle root.

---

## Dependency collection + license notices (shared with macOS)

The Windows build reuses the **shared, platform-agnostic** scripts rather than
maintaining Windows-specific copies:

- **`tools/collect_dependencies.py`** (platform-agnostic — its one PyObjC check
  self-skips off `darwin`; shared with `macos_app/build.sh`). It resolves the
  *runtime dependency closure* of `requirements.txt` from installed package
  metadata (not a blanket `site-packages` copy), honouring environment markers
  so `windows-curses; sys_platform=="win32"` is collected and `pyobjc; darwin`
  is not. `build.ps1` passes **`--include-deps-of puikit`** so PuiKit's own
  runtime deps — notably **`numpy`**, which the win32 Direct2D backend imports —
  are collected *without* copying PuiKit itself (its source is copied into
  `app\puikit` separately). Each distribution is copied file-for-file from its
  `RECORD`, so its `.dist-info` (and bundled license text) travels along; `numpy`
  brings its own `numpy.libs\` DLLs, registered via `os.add_dll_directory`.
- **`tools/generate_third_party_notices.py`** then aggregates a
  `THIRD_PARTY_NOTICES.txt` at the bundle root from every bundled distribution's
  `.dist-info` license text, plus three `--extra` non-distribution components:
  the embedded CPython (its `LICENSE.txt`), PuiKit (`MIT`), and the bundled Noto
  fonts (`SIL OFL 1.1`). It runs in strict mode — the build **fails** if any
  bundled distribution has no discoverable license, so an incomplete notice can
  never ship. This mirrors `macos_app/build.sh` exactly.

---

## The build script (`build.ps1`)

PowerShell orchestrator (invoked from the `Makefile` `windows-app` target or
directly). Steps:

1. **Locate the venv** (`.venv\Scripts\python.exe`); derive Python version,
   `base_prefix` (for `include/` + `libs/`), and the `python3XX` DLL/lib names.
2. **Locate the toolchain** — `cl.exe` + `rc.exe`. If not already on `PATH`, find
   Visual Studio via `vswhere` and import `VsDevCmd.bat`'s environment. If neither
   MSVC nor the Windows SDK is present, fail with install instructions (this is
   the Windows analog of the macOS build's Xcode Command Line Tools requirement).
3. **Fetch + extract** the matching embeddable CPython into `<root>\runtime`
   (cached under `windows_app/.cache/`).
4. **Assemble app code**: copy `xefm/` (as `app/xefm/`), the resolved `puikit/` package,
   and `LICENSE` into `app/`; `compileall` them.
5. **Collect dependencies** into `Lib\site-packages` via the shared
   `tools/collect_dependencies.py` (`--include-deps-of puikit`), then
   **generate `THIRD_PARTY_NOTICES.txt`** at the bundle root via
   `tools/generate_third_party_notices.py`. See the section above.
6. **Generate resources**: `version_generated.h` (from `$VERSION` / xefm/__init__.py's
   `__version__`) and `XeFM.ico` (via `make_icon.py`); compile `XeFM.rc` → `XeFM.res`.
7. **Compile** `launcher.c` + `XeFM.res` → `XeFM.exe` (GUI subsystem).
8. **(optional)** `-Zip` → `build\XeFM-<version>-win64.zip` for distribution.

### Usage

```powershell
# from the project root (or windows_app/)
powershell -ExecutionPolicy Bypass -File windows_app\build.ps1
powershell -ExecutionPolicy Bypass -File windows_app\build.ps1 -Version 1.0.0 -Zip
powershell -ExecutionPolicy Bypass -File windows_app\build.ps1 -Clean

# or via make (Git-Bash):
make windows-app
make windows-app-zip
make windows-app-clean
```

---

## Build requirements

- **Windows 10/11 x64**, PowerShell 5.1+.
- A **full CPython** install backing the `.venv` (provides `Python.h` and
  `python3XX.lib` under `sys.base_prefix`). `make venv` already sets this up.
- **MSVC Build Tools** (or Visual Studio) with the **Windows 10/11 SDK** —
  supplies `cl.exe`, `rc.exe`, and `vcruntime`. Install the *"Desktop development
  with C++"* workload, or the standalone *Build Tools for Visual Studio*.
- Network access on first build (to download the embeddable package; cached
  afterward).

---

## Open items / future work

- **Code signing** — `signtool` pass over `XeFM.exe` (and the zip), gated on a
  cert like the macOS build's optional `CODESIGN_IDENTITY`.
- **Installer** — an Inno Setup / MSIX wrapper around the folder for a Start-menu
  entry and uninstaller (the folder itself is already xcopy-deployable).

## Build gotchas (found live standing this up)

- **`user32.lib`** — the launcher calls `MessageBoxW`; with `WIN32_LEAN_AND_MEAN`
  it isn't auto-linked, so `launcher.c` carries `#pragma comment(lib,"user32.lib")`.
  (`python3XX.lib` and `kernel32` link automatically.)
- **No `--` in the manifest's XML comments.** XML forbids a double-hyphen inside
  a comment, and Windows' SxS manifest parser enforces it strictly (a lenient XML
  parser does not): an offending comment makes the loader report *"side-by-side
  configuration is incorrect / Invalid Xml syntax on line 1"* and the app won't
  start. Validate a manifest without launching the GUI via `CreateActCtx`
  (`ACTCTX_FLAG_RESOURCE_NAME_VALID` + resource id 1 to check the embedded copy).
- **`/MANIFEST:NO`** on the link line so the linker doesn't embed a second
  `RT_MANIFEST` alongside the one from `XeFM.rc`.
- **A real app icon** — `make_icon.py` converts `macos_app/resources/XeFM.icns`
  when Pillow is available, else emits a placeholder; a hand-authored multi-size
  `XeFM.ico` can be dropped into `windows_app/resources/` to override.
