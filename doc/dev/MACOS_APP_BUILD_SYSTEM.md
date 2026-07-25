# XeFM macOS App Bundle - Build System

## Overview

The XeFM macOS application bundle uses a native Objective-C launcher that embeds Python and launches XeFM with its CoreGraphics backend. The build system is command-line based (no Xcode IDE required) and uses the project's virtual environment as the single source of truth for all Python components.

## Quick Start

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build the app
cd macos_app
./build.sh

# Run the app
open build/XeFM.app
```

## Build Philosophy

**Everything comes from `.venv`:**
- Python interpreter
- Python shared library  
- Python standard libraries
- Third-party packages

This approach eliminates hardcoded system paths and works with any Python installation method (Python.framework, mise, pyenv, homebrew, etc.).

## Build Process

### 1. Python Detection

The build script detects Python configuration from `.venv`:

```bash
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python3"
PYTHON_VERSION=$("${VENV_PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_BASE_PREFIX=$("${VENV_PYTHON}" -c "import sys; print(sys.base_prefix)")
```

### 2. Installation Type Detection

The script detects whether Python is installed as:
- **Python.framework** (python.org installer or Homebrew)
- **Standard Python** (mise, pyenv, system Python)

```bash
if [[ "${PYTHON_BASE_PREFIX}" == *"/Python.framework/Versions/"* ]]; then
    # Framework installation
    USE_FRAMEWORK=true
else
    # Standard installation
    USE_FRAMEWORK=false
fi
```

### 3. Component Collection

All Python components are copied from the venv's base_prefix:

**Python Interpreter:**
- Source: `${PYTHON_BASE_PREFIX}/bin/python3.13`
- Destination: `XeFM.app/Contents/Frameworks/Python.framework/Versions/3.13/bin/python3.13`
- Symlink created: `python3 -> python3.13`

**Python Shared Library:**
- Source: `${PYTHON_BASE_PREFIX}/lib/libpython3.13.dylib`
- Destination: `XeFM.app/Contents/Frameworks/Python.framework/Versions/3.13/lib/libpython3.13.dylib`

**Python Standard Libraries:**
- Source: `${PYTHON_BASE_PREFIX}/lib/python3.13/`
- Destination: `XeFM.app/Contents/Frameworks/Python.framework/Versions/3.13/lib/python3.13/`

**Third-Party Packages:**
- Source: `${PROJECT_ROOT}/.venv/lib/python3.13/site-packages/`
- Destination: `XeFM.app/Contents/Resources/python_packages/`

**XeFM Source:**
- Source: `${PROJECT_ROOT}/src/`
- Destination: `XeFM.app/Contents/Resources/xefm/`

**PuiKit Framework:**
- Source: the installed PuiKit package, located via `import puikit` in the venv (its checkout is typically `../puikit`; honours any `PUIKIT_DIR` override used at install)
- Destination: `XeFM.app/Contents/Resources/puikit/`
- Bundled fonts (`puikit/fonts/`) are fetched into the source tree before copying so Core Text can register them at runtime

### 4. Framework Structure

The build script creates a Python.framework-like structure:

```
XeFM.app/Contents/Frameworks/Python.framework/
  Versions/
    3.13/                    # Version-specific directory (auto-detected)
      Python                 # Shared library (framework style only)
      bin/
        python3.13           # Actual Python executable
        python3 -> python3.13
      lib/
        python3.13/          # Standard library
        libpython3.13.dylib  # Shared library (standard style)
    Current -> 3.13          # Symlink to current version
  bin -> Versions/Current/bin
  lib -> Versions/Current/lib
```

**Version Flexibility:** The Objective-C launcher uses the `Current` symlink instead of hardcoded version numbers, allowing the app to work with any Python version embedded during build time.

### 5. Bundle Optimization

The build script optimizes the bundle size by:

**Removing unnecessary Python files (~400KB savings):**
- Python.app GUI launcher (~172KB)
- Development tools (idle, pip, pydoc, python-config) (~60KB)
- pkg-config files (~8KB)
- Resources directory (~176KB)

**Selective PuiKit copying:**
- Copies the installed `puikit/` package (Python modules, backends, fonts)
- Excludes docs/, examples/, tests/, and development files

**Total bundle size savings: ~400KB+ from Python trimming above**

### 6. Python Pre-compilation

All Python source files are pre-compiled to bytecode for faster startup:

```bash
# Pre-compile XeFM source
python3 -m compileall -q "${XEFM_DEST}"

# Pre-compile PuiKit framework
python3 -m compileall -q "${PUIKIT_DEST}"

# Pre-compile Python standard library
python3 -m compileall -q -f "${STDLIB_PATH}"
```

**Benefits:**
- Faster application startup
- Consistent performance (no first-run compilation)
- Reduced I/O during module imports

**Note:** Source files (.py) are kept alongside bytecode (.pyc) for debugging and introspection.

### 7. Install Name Updates

The build script updates the XeFM executable to use the bundled Python:

```bash
install_name_tool -change \
    "${PYTHON_BASE_PREFIX}/lib/libpython3.13.dylib" \
    "@executable_path/../Frameworks/Python.framework/Versions/3.13/lib/libpython3.13.dylib" \
    "${MACOS_DIR}/XeFM"
```

## System Independence

The app bundle is completely independent of system Python installations:

### User Site-Packages Disabled

A `sitecustomize.py` file disables user site-packages:

```python
import site
import sys

# Disable user site-packages for bundled app
site.ENABLE_USER_SITE = False

# Remove user site-packages from sys.path if already added
user_site = site.USER_SITE
if user_site in sys.path:
    sys.path.remove(user_site)
```

### Relative Library Paths

All dynamic library references use relative paths (`@executable_path`) instead of absolute paths, ensuring the app works on any system without depending on specific Python installations.

### External Dependencies

The bundled Python has one external library dependency:
- **gettext** (`/opt/homebrew/opt/gettext/lib/libintl.8.dylib`)
  - Used for internationalization support
  - Commonly available on macOS systems with Homebrew
  - Does not affect core functionality if missing

## External Program Support

The `xefm_python` variable in `xefm/external_programs.py` automatically detects app bundle execution and uses the bundled Python:

```python
if sys.platform == 'darwin' and '.app/Contents/MacOS' in sys.executable:
    # Running from macOS app bundle - use bundled python3
    bundle_path = sys.executable.rsplit('.app/Contents/MacOS', 1)[0] + '.app'
    xefm_python = os.path.join(bundle_path, 'Contents', 'Frameworks', 
                               'Python.framework', 'bin', 'python3')
else:
    # Normal execution - use current Python interpreter
    xefm_python = sys.executable
```

This ensures external programs (like preview scripts) use the bundled Python when running from the app bundle.

## Build Requirements

1. **macOS 10.13 or later**
2. **Xcode Command Line Tools:**
   ```bash
   xcode-select --install
   ```
3. **Python 3.9 or later**
4. **Virtual environment with dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Makefile Integration

The build system integrates with the project Makefile:

```bash
# Build the app
make macos-app

# Clean build artifacts
make clean-macos

# Create DMG installer
make macos-dmg

# Install to /Applications from that DMG (MACOS_INSTALL_DIR= to install elsewhere)
make install-macos-dmg
```

## Code Signing & Notarization

Distribution builds must be signed with a **Developer ID Application** certificate
and notarized by Apple, or macOS Gatekeeper refuses to open the app on other
machines ("unidentified developer" / "damaged and can't be opened"). Both steps
are optional and **off by default** — an unsigned build is fine for local
development. They require a paid Apple Developer account with a Developer ID
Application certificate installed in the login keychain.

### Environment variables

| Variable | Effect | Used by |
|----------|--------|---------|
| `CODESIGN_IDENTITY` | Signs the `.app` and the DMG. e.g. `"Developer ID Application: Your Name (TEAMID)"` | `build.sh`, `create_dmg.sh` |
| `NOTARY_PROFILE` | Notarizes + staples the `.app` and DMG. Requires `CODESIGN_IDENTITY`. | `build.sh`, `create_dmg.sh` |

With neither set the build is unsigned. `NOTARY_PROFILE` without
`CODESIGN_IDENTITY` is a hard error — you cannot notarize an unsigned app.

Rather than re-exporting these every session, drop them in a local
`macos_app/signing.env`, which `build.sh` and `create_dmg.sh` source
automatically:

```bash
cd macos_app
cp signing.env.example signing.env   # then edit signing.env
./build.sh                           # picks up the values, no export needed
```

`signing.env` is gitignored. Neither value is a secret — `CODESIGN_IDENTITY` is
just the certificate's display name (the private key stays in the keychain) and
`NOTARY_PROFILE` is just a keychain-profile name — but it is per-machine, so it
stays out of the repo. Values exported in the environment still override the
file, so CI can pass them in the usual way.

### One-time setup

```bash
# Find the Developer ID Application identity to use for CODESIGN_IDENTITY
security find-identity -v -p codesigning

# Store notary credentials in the keychain as a reusable profile.
# The password is an app-specific password from https://account.apple.com
# (Sign-In and Security > App-Specific Passwords), NOT your Apple ID password.
xcrun notarytool store-credentials "XeFM-Notary" \
    --apple-id you@example.com \
    --team-id TEAMID \
    --password <app-specific-password>
```

### Building a signed, notarized release

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export NOTARY_PROFILE="XeFM-Notary"

./build.sh        # Step 6 signs the .app; Step 7 notarizes & staples it
./create_dmg.sh   # signs, notarizes & staples the DMG
```

### How signing works (`build.sh`, Step 6)

Signing a `.app` for notarization is not a single `codesign` call. Every Mach-O
binary inside the bundle must be signed with a secure timestamp (`--timestamp`)
and the Hardened Runtime (`--options runtime`), from the **inside out** —
signing an outer container first would invalidate the inner signatures:

1. Nested `.so` / `.dylib` — extension modules, the vendored `.dylibs/` produced
   by delocate, and any dylibs shipped inside pip packages
2. The embedded interpreter executables (`bin/pythonX.Y`)
3. `Python.framework` (framework build path only; the standard-Python path ships
   `libpythonX.Y.dylib`, already signed in step 1)
4. The main executable (`Contents/MacOS/XeFM`)
5. The `.app` bundle last — the outermost seal over everything above

It then verifies strictly with `codesign --verify --deep --strict`.

**Entitlements.** The embedded CPython interpreter needs the Hardened Runtime
relaxations in `resources/entitlements.plist`:

- `com.apple.security.cs.disable-library-validation` — lets the interpreter
  `dlopen()` the bundled C extensions and dylibs, which we sign ourselves rather
  than embedding in the main binary's signature. Without it, importing any C
  extension aborts under the Hardened Runtime.
- `com.apple.security.cs.allow-unsigned-executable-memory` /
  `com.apple.security.cs.allow-jit` — ctypes/libffi allocate executable
  trampolines for callbacks. Safe default for a general-purpose interpreter;
  trim if a build proves it never exercises ctypes callbacks.

**Framework Info.plist.** The Python-embedding step (Step 4) strips the
framework's `Resources/` directory, which removes the `Info.plist` that
`codesign` needs to seal `Python.framework` as a nested bundle. Step 6
synthesizes a minimal one before signing so `codesign --verify --deep` accepts
the framework as valid nested code.

### How notarization works (`build.sh` Step 7, `create_dmg.sh`)

`build.sh` zips the signed `.app` with `ditto -c -k --keepParent` (notarytool
takes a `.zip`/`.dmg`/`.pkg`, not a raw `.app`), submits it with
`xcrun notarytool submit --wait`, then staples the returned ticket with
`xcrun stapler staple`. `create_dmg.sh` signs the finished DMG and, when
`NOTARY_PROFILE` is set, notarizes + staples it too. Stapling both the app and
the DMG means a downloaded installer opens without warnings even offline.

### Verifying

```bash
# Signature is valid under strict (Gatekeeper-style) rules
codesign --verify --deep --strict --verbose=2 build/XeFM.app

# Gatekeeper will accept it (only passes once notarized)
spctl -a -vvv --type exec build/XeFM.app

# Notarization tickets are stapled
xcrun stapler validate build/XeFM.app
xcrun stapler validate build/XeFM-<version>-macos.dmg
```

### Troubleshooting notarization

If `notarytool submit` reports `Invalid`, fetch the per-issue log — it names the
exact binary and reason (unsigned, missing timestamp, missing Hardened Runtime):

```bash
xcrun notarytool log <submission-id> --keychain-profile "XeFM-Notary"
```

Common causes: a Mach-O the inside-out sign loop missed (add it to Step 6), a
signature made without `--options runtime`, or a certificate that is not a
*Developer ID Application* type (Apple Development / Mac Developer certs cannot
be notarized).

## Benefits

### 1. Consistency
Development and bundled app use the same Python version and packages.

### 2. Portability
Works with any Python installation method - no hardcoded paths.

### 3. Self-Contained
App bundle includes everything needed - no system dependencies.

### 4. Version Control
Python version is determined by the venv, not the build script.

### 5. Reproducibility
Same venv always produces the same bundle.

### 6. Performance
Pre-compiled bytecode provides faster startup and consistent performance.

### 7. Size Optimized
Unnecessary files removed, saving ~12.8MB of bundle size.

## Troubleshooting

### Python Not Found
```
[ERROR] Virtual environment not found at /path/to/project/.venv
```
**Solution:** Create virtual environment: `python3 -m venv .venv`

### Missing Dependencies
```
[ERROR] Failed to collect dependencies
```
**Solution:** Install dependencies: `pip install -r requirements.txt`

### Wrong Python Version
The bundled Python version matches the venv's Python version. To change:
1. Delete the venv: `rm -rf .venv`
2. Create new venv with desired Python: `python3.13 -m venv .venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Rebuild: `./macos_app/build.sh`

### Compilation Errors
```
[ERROR] Compilation failed
```
**Solution:** Ensure Xcode Command Line Tools are installed: `xcode-select --install`

## Technical Notes

### Why Framework Structure?

Even for non-framework Python installations, we create a framework-like structure because:
1. Provides consistent paths regardless of source Python type
2. Simplifies install name updates
3. Matches macOS conventions for embedded frameworks
4. Makes the bundle structure predictable

### Symlink Strategy

Framework-level symlinks (`Python.framework/bin`, `Python.framework/lib`) point to version-specific directories. This allows:
- Easy version upgrades (just change `Current` symlink)
- Consistent paths for external programs
- Multiple Python versions in future (if needed)

**Important:** The build script uses `ln -sfn` (with `-n` flag) to prevent following existing symlinks when creating framework-level symlinks. This avoids creating broken symlinks inside the version-specific directory.

### Install Name Tool

The `install_name_tool` command updates dynamic library references in the XeFM executable. This is necessary because:
1. Python shared library path is hardcoded at compile time
2. We need to redirect to bundled Python instead of system Python
3. `@executable_path` makes paths relative to the executable location

## Related Files

- `macos_app/build.sh` - Main build script
- `tools/collect_dependencies.py` - Dependency collection script (shared with the Windows build)
- `macos_app/src/main.m` - Objective-C entry point
- `macos_app/src/XeFMAppDelegate.m` - Application delegate
- `macos_app/create_dmg.sh` - DMG packaging, signing, and notarization
- `macos_app/resources/Info.plist.template` - Bundle metadata template
- `macos_app/resources/entitlements.plist` - Hardened Runtime entitlements for signing
- `macos_app/resources/sitecustomize.py` - Disables user site-packages
- `xefm/external_programs.py` - Defines `xefm_python` variable
- `Makefile` - Build system integration
