#!/bin/bash
#
# XeFM macOS App Bundle Build Script
#
# This script compiles the Objective-C launcher and creates a complete
# macOS application bundle for XeFM with embedded Python interpreter.
#

set -e  # Exit on error

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
    echo "[INFO] $1"
}

log_warning() {
    echo "[WARNING] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

log_success() {
    echo "[SUCCESS] $1"
}

# Oldest macOS a Mach-O file declares it can run on, across all its slices.
# Modern binaries say so in LC_BUILD_VERSION ("minos"), older ones in
# LC_VERSION_MIN_MACOSX ("version"); -show-build prints both, alongside a
# "version" line of its own for the linker that produced the file, which is why
# the fields are read per load command rather than grepped for.
macho_min_os() {
    vtool -show-build "$1" 2>/dev/null | awk '
        /cmd LC_BUILD_VERSION/      { build = 1; vmin = 0; next }
        /cmd LC_VERSION_MIN_MACOSX/ { vmin = 1; build = 0; next }
        build && $1 == "minos"      { print $2; build = 0 }
        vmin  && $1 == "version"    { print $2; vmin = 0 }
    ' | sort -V | tail -1
}

# True when macOS version $1 is newer than $2.
version_gt() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

# ============================================================================
# Build Configuration
# ============================================================================

# Determine project root (parent of macos_app directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Build paths
BUILD_DIR="${SCRIPT_DIR}/build"
APP_NAME="XeFM"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"

# Source paths
SRC_DIR="${SCRIPT_DIR}/src"
RESOURCES_DIR="${SCRIPT_DIR}/resources"

# Python configuration - detect from .venv
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python3"
if [ ! -f "${VENV_PYTHON}" ]; then
    log_error "Virtual environment not found at ${PROJECT_ROOT}/.venv"
    log_error "Please create a virtual environment: python3 -m venv .venv"
    exit 1
fi

# Get Python version and paths from venv
PYTHON_VERSION=$("${VENV_PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_BASE_PREFIX=$("${VENV_PYTHON}" -c "import sys; print(sys.base_prefix)")
PYTHON_SITE_PACKAGES="${PROJECT_ROOT}/.venv/lib/python${PYTHON_VERSION}/site-packages"

log_info "Detected Python ${PYTHON_VERSION} from venv"
log_info "Python base: ${PYTHON_BASE_PREFIX}"
log_info "Site packages: ${PYTHON_SITE_PACKAGES}"

# The bundle embeds whichever Python the venv was built on, so that choice is
# the release's floor and its architectures. A Homebrew Python is built for the
# machine that installed it - one architecture, and a minimum OS of the current
# macOS - which is how a 1.5.x DMG came to demand macOS 26 on Apple Silicon only
# (issue #486). The python.org installer ships universal2 with a 10.15/11.0
# floor, so it is what a release is built on; refuse a Homebrew one rather than
# discover the floor afterwards in Step 5. Set ALLOW_HOMEBREW_PYTHON=1 for a
# local throwaway build.
case "${PYTHON_BASE_PREFIX}" in
    /opt/homebrew/*|/usr/local/Cellar/*|/usr/local/opt/*)
        if [ "${ALLOW_HOMEBREW_PYTHON:-0}" != "1" ]; then
            log_error "The venv is built on a Homebrew Python: ${PYTHON_BASE_PREFIX}"
            log_error "A release bundle embeds it as-is, which pins the DMG to this"
            log_error "machine's architecture and macOS version. Install Python from"
            log_error "python.org and rebuild the venv:"
            log_error "  make clean-venv && make venv"
            log_error "(ALLOW_HOMEBREW_PYTHON=1 overrides this for a local build.)"
            exit 1
        fi
        log_warning "Building on a Homebrew Python (ALLOW_HOMEBREW_PYTHON=1)"
        log_warning "The bundle will inherit its architecture and macOS floor"
        ;;
esac

# Check if using Python.framework or standard Python installation
# Python.framework can be in /Library/Frameworks (python.org) or /opt/homebrew (Homebrew)
if [[ "${PYTHON_BASE_PREFIX}" == *"/Python.framework/Versions/"* ]]; then
    # Python.framework installation (python.org or Homebrew)
    # Extract framework root by removing /Versions/X.Y suffix
    PYTHON_FRAMEWORK="${PYTHON_BASE_PREFIX%/Versions/*}"
    USE_FRAMEWORK=true
    log_info "Using Python.framework installation"
    log_info "Framework root: ${PYTHON_FRAMEWORK}"
else
    # Standard Python installation (mise, pyenv, system Python)
    PYTHON_FRAMEWORK="${PYTHON_BASE_PREFIX}"
    USE_FRAMEWORK=false
    log_info "Using standard Python installation"
fi

# Compiler settings
CC="clang"
CFLAGS="-framework Cocoa"

# Oldest macOS the bundle is built to run on. Without this clang targets the
# machine doing the build, so the floor silently followed whoever ran the
# release - a 1.5.0 built on macOS 27 refused to launch on macOS 26 with "You
# can't use this version of the application with this version of macOS"
# (issue #455). Pinning it keeps the floor a decision rather than an accident.
# 11.0 is the oldest macOS any arm64 Mac runs, and every bundled wheel already
# targets it; the embedded Homebrew Python is currently the one component that
# sits higher, so the bundle's real floor is what Step 5 reads back from it.
MACOS_MIN_VERSION="11.0"
CFLAGS="${CFLAGS} -mmacosx-version-min=${MACOS_MIN_VERSION}"

# Configure compiler flags based on Python installation type
if [ "$USE_FRAMEWORK" = true ]; then
    # Python.framework style
    CFLAGS="${CFLAGS} -F${PYTHON_FRAMEWORK}/Versions/${PYTHON_VERSION}"
    CFLAGS="${CFLAGS} -I${PYTHON_FRAMEWORK}/Versions/${PYTHON_VERSION}/include/python${PYTHON_VERSION}"
    CFLAGS="${CFLAGS} -L${PYTHON_FRAMEWORK}/Versions/${PYTHON_VERSION}/lib"
else
    # Standard Python style
    CFLAGS="${CFLAGS} -I${PYTHON_BASE_PREFIX}/include/python${PYTHON_VERSION}"
    CFLAGS="${CFLAGS} -L${PYTHON_BASE_PREFIX}/lib"
fi

CFLAGS="${CFLAGS} -lpython${PYTHON_VERSION}"
LDFLAGS="-rpath @executable_path/../Frameworks"

# Local signing configuration (optional, gitignored). CODESIGN_IDENTITY and
# NOTARY_PROFILE are both non-secret (the certificate's private key and the
# notary app-specific password live in the macOS keychain), so they can be kept
# in macos_app/signing.env to avoid re-exporting them every session. Copy
# signing.env.example to signing.env to start. Values already set in the
# environment take precedence over the file.
SIGNING_ENV_FILE="${SCRIPT_DIR}/signing.env"
if [ -f "${SIGNING_ENV_FILE}" ]; then
    log_info "Loading signing config from ${SIGNING_ENV_FILE}"
    _env_codesign="${CODESIGN_IDENTITY:-}"
    _env_notary="${NOTARY_PROFILE:-}"
    # shellcheck source=/dev/null
    . "${SIGNING_ENV_FILE}"
    [ -n "${_env_codesign}" ] && CODESIGN_IDENTITY="${_env_codesign}"
    [ -n "${_env_notary}" ] && NOTARY_PROFILE="${_env_notary}"
fi

# Code signing (optional). Set to a "Developer ID Application" identity to sign
# the bundle for distribution, e.g.
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
# List the identities in your keychain with: security find-identity -v -p codesigning
CODESIGN_IDENTITY="${CODESIGN_IDENTITY:-}"

# Notarization (optional; requires CODESIGN_IDENTITY). Set to the name of a
# notarytool keychain profile to submit the signed .app to Apple's notary
# service and staple the ticket. Create the profile once with:
#   xcrun notarytool store-credentials "XeFM-Notary" \
#       --apple-id you@example.com --team-id TEAMID --password <app-specific-pw>
# then build with: NOTARY_PROFILE="XeFM-Notary"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"

# Version number (can be overridden by environment variable). Defaults to the
# single source of truth: xefm/__init__.py's __version__ literal (same string
# the Windows build reads), so the bundle version never drifts from --version.
if [ -z "${VERSION:-}" ]; then
    VERSION="$(sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "${PROJECT_ROOT}/xefm/__init__.py" | head -1)"
    VERSION="${VERSION:-0.0.0}"
fi

# ============================================================================
# Build Script Entry Point
# ============================================================================

log_info "Starting XeFM macOS app bundle build..."
log_info "Project root: ${PROJECT_ROOT}"
log_info "Build directory: ${BUILD_DIR}"
log_info "Python version: ${PYTHON_VERSION}"

# ============================================================================
# Step 1: Compile Objective-C Source Files
# ============================================================================

log_info "Step 1: Compiling Objective-C source files..."

# Create build directory if it doesn't exist
mkdir -p "${BUILD_DIR}"

# Compile main.m and XeFMAppDelegate.m
SOURCES="${SRC_DIR}/main.m ${SRC_DIR}/XeFMAppDelegate.m"
OUTPUT_EXECUTABLE="${BUILD_DIR}/${APP_NAME}"

log_info "Compiling: ${SOURCES}"
log_info "Output: ${OUTPUT_EXECUTABLE}"

if ! ${CC} ${CFLAGS} ${LDFLAGS} -o "${OUTPUT_EXECUTABLE}" ${SOURCES}; then
    log_error "Compilation failed"
    exit 1
fi

log_success "Compilation completed successfully"

# ============================================================================
# Step 2: Create Bundle Structure
# ============================================================================

log_info "Step 2: Creating bundle structure..."

# Create bundle directories
CONTENTS_DIR="${APP_BUNDLE}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR_BUNDLE="${CONTENTS_DIR}/Resources"
FRAMEWORKS_DIR="${CONTENTS_DIR}/Frameworks"

# Start from an empty bundle. Every step below copies in what it needs but only
# a few remove anything, so whatever a previous build left behind is signed and
# shipped along with the rest: the switch off Homebrew (issue #486) left four
# Homebrew dylibs in lib-dynload/.dylibs that the python.org build has no use
# for - delocate vendors what the extensions ask for, and nothing deletes what
# they stopped asking for. A release must not depend on what the build tree
# happened to hold.
if [ -d "${APP_BUNDLE}" ]; then
    log_info "Removing the previous bundle at ${APP_BUNDLE}"
    rm -rf "${APP_BUNDLE}"
fi

mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR_BUNDLE}"
mkdir -p "${FRAMEWORKS_DIR}"

log_success "Bundle directories created"

# Copy executable to MacOS directory
log_info "Copying executable to bundle..."
cp "${OUTPUT_EXECUTABLE}" "${MACOS_DIR}/${APP_NAME}"
chmod +x "${MACOS_DIR}/${APP_NAME}"

log_success "Executable copied and permissions set"

# ============================================================================
# Step 3: Copy Resources
# ============================================================================

log_info "Step 3: Copying resources..."

# Copy XeFM Python source.
# XeFM is a single package (xefm/), so the whole directory lands at the
# Resources root and Resources/ goes on sys.path — the launcher then imports
# "xefm.app" directly.
log_info "Copying XeFM Python source"
XEFM_PKG_DEST="${RESOURCES_DIR_BUNDLE}/xefm"
rm -rf "${XEFM_PKG_DEST}"
cp -R "${PROJECT_ROOT}/xefm" "${XEFM_PKG_DEST}"

# Pre-compile XeFM Python files
log_info "Pre-compiling XeFM Python files..."
if "${VENV_PYTHON}" -m compileall -q "${XEFM_PKG_DEST}"; then
    log_info "  Compiled XeFM Python files"
else
    log_info "  Warning: Compilation failed"
fi

# Copy PuiKit library.
# PuiKit is a pure-Python package (its macOS
# GUI backend renders through PyObjC/Quartz - there is no compiled extension to
# bundle) installed editable into the venv from a sibling checkout. Resolve its
# real source directory from the venv interpreter so this works regardless of
# where the checkout lives (honours any PUIKIT_DIR override used at install).
log_info "Copying PuiKit library..."
PUIKIT_DEST="${RESOURCES_DIR_BUNDLE}/puikit"
PUIKIT_SRC=$("${VENV_PYTHON}" -c "import puikit, os; print(os.path.dirname(os.path.abspath(puikit.__file__)))" 2>/dev/null)
# The version of the source actually being copied. PuiKit is normally installed
# editable, and an editable install's .dist-info records the version that was
# current when `pip install -e` ran - it is never rewritten as __version__ moves
# on, so package metadata is not a trustworthy source here. __version__ in the
# copied source is.
PUIKIT_VERSION=$("${VENV_PYTHON}" -c "import puikit; print(puikit.__version__)" 2>/dev/null)

if [ -z "${PUIKIT_SRC}" ] || [ ! -d "${PUIKIT_SRC}" ]; then
    log_error "PuiKit not importable from the venv (resolved source: '${PUIKIT_SRC}')."
    log_error "Install it first: make install-puikit"
    exit 1
fi

if [ -z "${PUIKIT_VERSION}" ]; then
    log_error "Could not read puikit.__version__ from the venv."
    log_error "The bundle's third-party notices must name the version they ship."
    exit 1
fi
log_info "  PuiKit version: ${PUIKIT_VERSION}"

# The GUI backend defaults to a bundled Noto Sans + Noto Sans Mono pair
# (puikit/fonts/), registered with Core Text at runtime so the app renders the
# same on any Mac without the fonts installed. Those files are large,
# OFL-licensed binaries kept out of git and fetched on demand, so an editable
# PuiKit checkout may not have them yet. Fetch them into the source tree before
# copying so the bundle ships them; the fetch is idempotent (skips files already
# present) and stdlib-only. Fall back to the OS fonts is only acceptable as a
# runtime safety net, not for a distributed build, so a missing font is a hard
# error below rather than a silent OS-font substitution in the DMG.
FETCH_FONTS="$(dirname "${PUIKIT_SRC}")/scripts/fetch_fonts.py"
if [ -f "${FETCH_FONTS}" ]; then
    log_info "Ensuring bundled Noto fonts are present..."
    if ! "${VENV_PYTHON}" "${FETCH_FONTS}"; then
        log_warning "Font fetch failed (offline?); relying on any fonts already in the checkout"
    fi
else
    log_info "  PuiKit font-fetch script not found; relying on installed fonts"
fi

# Copy the whole package, then drop caches (compiled fresh below).
rm -rf "${PUIKIT_DEST}"
cp -R "${PUIKIT_SRC}" "${PUIKIT_DEST}"
find "${PUIKIT_DEST}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
log_info "  Copied PuiKit from ${PUIKIT_SRC}"

# Verify the bundled default fonts made it into the app. Shipping a DMG that
# silently falls back to the OS UI font is exactly the regression this guards
# against, so fail the build (loudly, with the fix) rather than ship it.
FONTS_DEST="${PUIKIT_DEST}/fonts"
MISSING_FONTS=""
for f in NotoSans-Regular.ttf NotoSans-Bold.ttf NotoSansMono-Regular.ttf NotoSansMono-Bold.ttf; do
    [ -f "${FONTS_DEST}/${f}" ] || MISSING_FONTS="${MISSING_FONTS} ${f}"
done
if [ -n "${MISSING_FONTS}" ]; then
    log_error "Bundled Noto fonts missing from ${FONTS_DEST}:${MISSING_FONTS}"
    log_error "The app would fall back to OS fonts. Fetch them and rebuild:"
    log_error "  ${VENV_PYTHON} ${FETCH_FONTS}"
    exit 1
fi
log_info "  Bundled Noto fonts present in ${FONTS_DEST}"

# Pre-compile PuiKit Python files
log_info "Pre-compiling PuiKit Python files..."
if "${VENV_PYTHON}" -m compileall -q "${PUIKIT_DEST}"; then
    log_info "  Compiled PuiKit Python files"
else
    log_info "  Warning: Compilation failed"
fi

# Collect Python dependencies
log_info "Collecting Python dependencies..."
PACKAGES_DEST="${RESOURCES_DIR_BUNDLE}/python_packages"
# Start from empty, as the XeFM and PuiKit copies above do. The collector only
# ever adds files, so without this a rebuild over an existing bundle keeps
# distributions that are no longer in the dependency closure - one dropped from
# requirements.txt, one that changed name, or a .dist-info left by an earlier
# install of a different version. Those stale directories are what the notices
# generator scans, so the bundle would keep advertising packages it no longer
# ships. (windows_app/build.ps1 gets this for free: it removes the whole app
# root before building.)
rm -rf "${PACKAGES_DEST}"
mkdir -p "${PACKAGES_DEST}"

REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
# Shared, platform-agnostic collector (also used by windows_app/build.ps1).
COLLECT_SCRIPT="${PROJECT_ROOT}/tools/collect_dependencies.py"

if [ -f "${COLLECT_SCRIPT}" ]; then
    # Use venv's Python to run the collection script
    # --include-deps-of puikit pulls in PuiKit's own runtime deps without copying
    # PuiKit itself (its source is copied into Resources/puikit above). Without
    # it the editable install's stale puikit-*.dist-info ships in the bundle,
    # claiming whatever version was current when `pip install -e` last ran.
    # windows_app/build.ps1 passes the same flag.
    if "${VENV_PYTHON}" "${COLLECT_SCRIPT}" --requirements "${REQUIREMENTS_FILE}" --dest "${PACKAGES_DEST}" --include-deps-of puikit; then
        log_success "Dependencies collected successfully"
    else
        log_error "Failed to collect dependencies"
        log_error "Please ensure all dependencies are installed: pip install -r requirements.txt"
        exit 1
    fi
else
    log_warning "Dependency collection script not found at ${COLLECT_SCRIPT}"
    log_warning "Python packages will need to be added manually"
fi

# Copy application icon if it exists
ICON_SOURCE="${RESOURCES_DIR}/XeFM.icns"
if [ -f "${ICON_SOURCE}" ]; then
    log_info "Copying application icon..."
    cp "${ICON_SOURCE}" "${RESOURCES_DIR_BUNDLE}/"
else
    log_info "Warning: Application icon not found at ${ICON_SOURCE}"
fi

# Copy LICENSE file
LICENSE_SOURCE="${PROJECT_ROOT}/LICENSE"
if [ -f "${LICENSE_SOURCE}" ]; then
    log_info "Copying LICENSE file..."
    cp "${LICENSE_SOURCE}" "${RESOURCES_DIR_BUNDLE}/"
else
    log_warning "LICENSE file not found at ${LICENSE_SOURCE}"
fi

log_success "Resources copied successfully"

# ============================================================================
# Step 4: Embed Python
# ============================================================================

log_info "Step 4: Embedding Python..."

# Clean up old Python versions from previous builds
if [ -d "${FRAMEWORKS_DIR}/Python.framework/Versions" ]; then
    log_info "Cleaning up old Python versions..."
    for old_version in "${FRAMEWORKS_DIR}/Python.framework/Versions"/*; do
        if [ -d "${old_version}" ] && [ "$(basename "${old_version}")" != "Current" ] && [ "$(basename "${old_version}")" != "${PYTHON_VERSION}" ]; then
            log_info "  Removing old version: $(basename "${old_version}")"
            rm -rf "${old_version}"
        fi
    done
fi

# Determine Python source based on installation type
if [ "$USE_FRAMEWORK" = true ]; then
    # Python.framework installation
    PYTHON_SOURCE="${PYTHON_FRAMEWORK}/Versions/${PYTHON_VERSION}"
    if [ ! -d "${PYTHON_SOURCE}" ]; then
        log_error "Python.framework not found at ${PYTHON_SOURCE}"
        exit 1
    fi
    
    # Copy Python.framework to bundle
    log_info "Copying Python.framework from ${PYTHON_SOURCE}..."
    PYTHON_DEST="${FRAMEWORKS_DIR}/Python.framework/Versions/${PYTHON_VERSION}"
    mkdir -p "${PYTHON_DEST}"
    
    # Copy essential framework components
    if command -v rsync > /dev/null 2>&1; then
        rsync -a --no-perms --chmod=u+rw "${PYTHON_SOURCE}/Python" "${PYTHON_DEST}/"
        rsync -a --no-perms --chmod=u+rw "${PYTHON_SOURCE}/Resources" "${PYTHON_DEST}/" 2>/dev/null || true
        rsync -a --no-perms --chmod=u+rw "${PYTHON_SOURCE}/lib" "${PYTHON_DEST}/"
        rsync -a --no-perms --chmod=u+rw "${PYTHON_SOURCE}/bin" "${PYTHON_DEST}/"
    else
        cp -R "${PYTHON_SOURCE}/Python" "${PYTHON_DEST}/" 2>/dev/null || true
        cp -R "${PYTHON_SOURCE}/Resources" "${PYTHON_DEST}/" 2>/dev/null || true
        cp -R "${PYTHON_SOURCE}/lib" "${PYTHON_DEST}/"
        cp -R "${PYTHON_SOURCE}/bin" "${PYTHON_DEST}/"
        chmod -R u+rw "${PYTHON_DEST}" 2>/dev/null || true
    fi
    
    # Create version symlinks
    cd "${FRAMEWORKS_DIR}/Python.framework/Versions"
    ln -sf "${PYTHON_VERSION}" Current
    cd "${FRAMEWORKS_DIR}/Python.framework"
    ln -sf "Versions/Current/Python" Python
    ln -sf "Versions/Current/bin" bin
    
    # Create python3 symlink in bin directory
    log_info "Creating python3 symlink in bin directory..."
    cd "${PYTHON_DEST}/bin"
    if [ -f "python${PYTHON_VERSION}" ]; then
        ln -sf "python${PYTHON_VERSION}" python3
        log_info "  Created python3 -> python${PYTHON_VERSION}"
    fi
    
    # Add sitecustomize.py to disable user site-packages
    log_info "Adding sitecustomize.py to disable user site-packages..."
    SITECUSTOMIZE_SOURCE="${SCRIPT_DIR}/resources/sitecustomize.py"
    SITECUSTOMIZE_DEST="${PYTHON_DEST}/lib/python${PYTHON_VERSION}/sitecustomize.py"
    if [ -f "${SITECUSTOMIZE_SOURCE}" ]; then
        cp "${SITECUSTOMIZE_SOURCE}" "${SITECUSTOMIZE_DEST}"
        log_info "  Installed sitecustomize.py"
    else
        log_error "sitecustomize.py not found at ${SITECUSTOMIZE_SOURCE}"
        exit 1
    fi
    
    log_success "Python.framework embedded successfully"
    
    # Remove unnecessary files from embedded Python
    log_info "Removing unnecessary files from embedded Python..."
    
    # Remove Python.app (GUI launcher)
    if [ -d "${PYTHON_DEST}/Resources/Python.app" ]; then
        rm -rf "${PYTHON_DEST}/Resources/Python.app"
        log_info "  Removed Python.app"
    fi
    
    # Remove Resources directory entirely (Info.plist not needed for embedded use)
    if [ -d "${PYTHON_DEST}/Resources" ]; then
        rm -rf "${PYTHON_DEST}/Resources"
        log_info "  Removed Resources/"
    fi

    # Remove development tools from bin/
    for tool in "idle${PYTHON_VERSION}" pip3 "pip${PYTHON_VERSION}" "pydoc${PYTHON_VERSION}" "python${PYTHON_VERSION}-config"; do
        if [ -f "${PYTHON_DEST}/bin/${tool}" ]; then
            rm -f "${PYTHON_DEST}/bin/${tool}"
            log_info "  Removed bin/${tool}"
        fi
    done

    # The python.org framework also ships an x86_64-only launcher for running
    # the interpreter under Rosetta. XeFM's own executable is built for this
    # machine alone, so the bundle is single-architecture and that launcher can
    # never be the one that runs; it is dead weight that still names the system
    # framework in its load commands, which is exactly what Step 4e refuses.
    for tool in "python${PYTHON_VERSION}-intel64" python3-intel64; do
        if [ -e "${PYTHON_DEST}/bin/${tool}" ]; then
            rm -f "${PYTHON_DEST}/bin/${tool}"
            log_info "  Removed bin/${tool}"
        fi
    done

    # Remove pkg-config files
    if [ -d "${PYTHON_DEST}/lib/pkgconfig" ]; then
        rm -rf "${PYTHON_DEST}/lib/pkgconfig"
        log_info "  Removed lib/pkgconfig/"
    fi

    # config-X.Y-darwin/ is what you link against Python with: a Makefile, the
    # Setup files, install-sh, and python.o - the object file a `make` would
    # link into an interpreter of its own. Nothing here runs, and an app that
    # never compiles an extension never reads it. It also cannot ship: python.o
    # is a Mach-O that Apple's notary service inspects and rejects outright
    # ("The binary is not signed"), and signing an .o is not a thing to do -
    # Step 6 signs the code the app loads, which this is not. Homebrew leaves
    # the directory out, so the rejection only appeared with python.org.
    PYTHON_CONFIG_DIR="${PYTHON_DEST}/lib/python${PYTHON_VERSION}/config-${PYTHON_VERSION}-darwin"
    if [ -d "${PYTHON_CONFIG_DIR}" ]; then
        rm -rf "${PYTHON_CONFIG_DIR}"
        log_info "  Removed lib/python${PYTHON_VERSION}/config-${PYTHON_VERSION}-darwin/"
    fi

    # Remove Python test suite (saves ~68MB)
    if [ -d "${PYTHON_DEST}/lib/python${PYTHON_VERSION}/test" ]; then
        rm -rf "${PYTHON_DEST}/lib/python${PYTHON_VERSION}/test"
        log_info "  Removed lib/python${PYTHON_VERSION}/test/"
    fi

    # Tkinter and the standard library that depends on it (~16MB with Tcl/Tk).
    # XeFM draws through PuiKit's own backends and neither imports tkinter, so
    # the only thing shipping it achieves is two more frameworks to vendor and
    # sign: _tkinter links Tcl and Tk by absolute path, which is why delocate
    # copies 9MB of them into .dylibs. Removing the extension before Step 4b
    # means they are never brought in at all. An external program the user
    # launches through the bundled interpreter loses tkinter with this - the
    # same trade the removed test suite already makes, and a file manager's
    # embedded runtime is not a general-purpose Python install.
    STDLIB_DIR="${PYTHON_DEST}/lib/python${PYTHON_VERSION}"
    for tk_path in "${STDLIB_DIR}/lib-dynload/_tkinter."*.so "${STDLIB_DIR}/tkinter" \
                   "${STDLIB_DIR}/idlelib" "${STDLIB_DIR}/turtledemo" "${STDLIB_DIR}/turtle.py"; do
        if [ -e "${tk_path}" ]; then
            rm -rf "${tk_path}"
            log_info "  Removed lib/python${PYTHON_VERSION}/${tk_path#${STDLIB_DIR}/}"
        fi
    done

    # The framework's lib/ carries the shared libraries CPython was linked
    # against - libssl, libcrypto, libncurses and friends - each naming the
    # others by the absolute path the distribution installs to. Nothing in the
    # bundle loads them: every extension that needs one reaches it through the
    # copy delocate vendors into lib-dynload/.dylibs (Step 4b) and rewrites to
    # @loader_path. What is left is ~18MB of duplicates whose load commands
    # point back at /Library/Frameworks, so a machine without python.org
    # installed is one dlopen away from a failure that the bundle should have
    # made impossible. Drop them and let .dylibs be the only copy. lib/python*/
    # (the standard library) and the libpython symlink to the framework dylib
    # are untouched.
    log_info "Removing duplicate shared libraries from lib/..."
    for lib in "${PYTHON_DEST}"/lib/*.dylib; do
        [ -e "${lib}" ] || continue
        case "$(basename "${lib}")" in
            "libpython${PYTHON_VERSION}.dylib") continue ;;
        esac
        rm -f "${lib}"
        log_info "  Removed lib/$(basename "${lib}")"
    done

    log_success "Unnecessary files removed"

    # Make the bundled interpreter self-contained. bin/pythonX.Y in a framework
    # build is a stub that posix_spawns Resources/Python.app/Contents/MacOS/Python
    # — an app this bundle strips — and both binaries reference the framework by
    # the build machine's absolute path, so external programs launched via
    # xefm_python only ran on machines where that exact path still existed.
    # Replace the stub with the real interpreter binary and point it at the
    # embedded framework dylib. The old load command is read out of the binary
    # rather than assumed — it is the install name the distribution was linked
    # with, which need not be ${PYTHON_BASE_PREFIX} (a Homebrew build records
    # the versioned Cellar path there, not the opt path) — because
    # install_name_tool -change no-ops silently on a mismatch.
    log_info "Making bundled interpreter self-contained..."
    EMBEDDED_PYTHON_BIN="${PYTHON_DEST}/bin/python${PYTHON_VERSION}"
    REAL_PYTHON_BIN="${PYTHON_SOURCE}/Resources/Python.app/Contents/MacOS/Python"
    if [ ! -f "${REAL_PYTHON_BIN}" ]; then
        log_error "Real interpreter not found at ${REAL_PYTHON_BIN}"
        exit 1
    fi
    cp -f "${REAL_PYTHON_BIN}" "${EMBEDDED_PYTHON_BIN}"
    chmod u+wx "${EMBEDDED_PYTHON_BIN}"
    OLD_PYTHON_DYLIB=$(otool -L "${EMBEDDED_PYTHON_BIN}" | awk -v ver="${PYTHON_VERSION}" \
        'index($1, "/Python.framework/Versions/" ver "/Python") && $1 !~ /^@/ {print $1; exit}')
    if [ -n "${OLD_PYTHON_DYLIB}" ]; then
        install_name_tool -change \
            "${OLD_PYTHON_DYLIB}" \
            "@executable_path/../Python" \
            "${EMBEDDED_PYTHON_BIN}"
    fi
    # install_name_tool invalidates the signature the interpreter was shipped
    # with, which is fatal at exec on Apple Silicon. Ad-hoc re-sign so the
    # interpreter runs in unsigned builds and in the pre-compile step below;
    # release signing later replaces this signature (--force).
    codesign --force --sign - "${EMBEDDED_PYTHON_BIN}"
    # The framework dylib needs the same treatment, for a reason that has
    # nothing to do with its own bytes: python.org signs Python.framework as a
    # bundle, and that signature seals Resources/Info.plist — which the strip
    # above deletes. dyld then refuses to load the dylib into the ad-hoc
    # interpreter ("code signature invalid", errno=1) and every use of the
    # bundled Python during the build aborts, the standard-library pre-compile
    # below included. Homebrew's framework is linker-signed with nothing sealed
    # beside it, which is why this only began to matter off Homebrew. Step 6
    # writes a minimal Info.plist and signs the framework for real.
    codesign --force --sign - "${PYTHON_DEST}/Python"
    # Only otool -L's tab-indented lines are load commands. A universal binary
    # prints a "<path> (architecture X):" header per slice, and that path is the
    # file's own — under the build tree — so a filter that reads every line
    # fails a bundle that is in fact self-contained. Skipping just the first
    # line was enough while the embedded Python was a single-architecture
    # Homebrew build; a universal2 python.org one has a header per slice.
    if otool -L "${EMBEDDED_PYTHON_BIN}" | awk '/^\t/ && $1 !~ /^@/ && $1 !~ /^\/usr\/lib\// && $1 !~ /^\/System\//' | grep -q .; then
        log_error "Embedded python${PYTHON_VERSION} still links a build-machine path:"
        otool -L "${EMBEDDED_PYTHON_BIN}"
        exit 1
    fi
    log_success "Bundled interpreter is self-contained"

    # Pre-compile Python standard library
    log_info "Pre-compiling Python standard library..."
    STDLIB_PATH="${PYTHON_DEST}/lib/python${PYTHON_VERSION}"
    if [ -d "${STDLIB_PATH}" ]; then
        # Use the bundled Python to compile the standard library
        # This ensures compatibility and uses the correct Python version
        BUNDLE_PYTHON="${PYTHON_DEST}/bin/python3"
        if [ -f "${BUNDLE_PYTHON}" ]; then
            # Compile all .py files in the standard library
            # -q: quiet mode (only show errors)
            # -f: force recompilation even if .pyc files exist
            if "${BUNDLE_PYTHON}" -m compileall -q -f "${STDLIB_PATH}"; then
                log_info "  Compiled Python standard library"
                
                # Count compiled files for verification
                PYC_COUNT=$(find "${STDLIB_PATH}" -name "*.pyc" | wc -l | tr -d ' ')
                PY_COUNT=$(find "${STDLIB_PATH}" -name "*.py" | wc -l | tr -d ' ')
                log_info "  Created ${PYC_COUNT} .pyc files from ${PY_COUNT} .py files"
            else
                log_warning "Standard library compilation had errors (non-critical)"
            fi
        else
            log_warning "Bundled Python not found, skipping standard library pre-compilation"
        fi
    else
        log_warning "Standard library path not found: ${STDLIB_PATH}"
    fi
    
    # Update install names to use embedded framework
    log_info "Updating install names to use embedded framework..."
    install_name_tool -change \
        "${PYTHON_BASE_PREFIX}/Python" \
        "@executable_path/../Frameworks/Python.framework/Versions/${PYTHON_VERSION}/Python" \
        "${MACOS_DIR}/${APP_NAME}"
else
    # Standard Python installation (mise, pyenv, homebrew, etc.)
    log_info "Copying Python from ${PYTHON_BASE_PREFIX}..."
    PYTHON_DEST="${FRAMEWORKS_DIR}/Python.framework/Versions/${PYTHON_VERSION}"
    mkdir -p "${PYTHON_DEST}"
    
    # Copy Python components (excluding problematic symlinks from source)
    if command -v rsync > /dev/null 2>&1; then
        rsync -a --no-perms --chmod=u+rw "${PYTHON_BASE_PREFIX}/lib" "${PYTHON_DEST}/"
        rsync -a --no-perms --chmod=u+rw "${PYTHON_BASE_PREFIX}/bin" "${PYTHON_DEST}/"
        rsync -a --no-perms --chmod=u+rw "${PYTHON_BASE_PREFIX}/include" "${PYTHON_DEST}/" 2>/dev/null || true
    else
        cp -R "${PYTHON_BASE_PREFIX}/lib" "${PYTHON_DEST}/"
        cp -R "${PYTHON_BASE_PREFIX}/bin" "${PYTHON_DEST}/"
        cp -R "${PYTHON_BASE_PREFIX}/include" "${PYTHON_DEST}/" 2>/dev/null || true
        chmod -R u+rw "${PYTHON_DEST}" 2>/dev/null || true
    fi
    
    # Remove problematic symlinks that were copied from source Python
    # These are framework-level symlinks that don't belong in version-specific directory
    log_info "Removing broken symlinks from copied Python..."
    if [ -L "${PYTHON_DEST}/bin/bin" ]; then
        rm -f "${PYTHON_DEST}/bin/bin"
        log_info "  Removed ${PYTHON_DEST}/bin/bin"
    fi
    if [ -L "${PYTHON_DEST}/lib/lib" ]; then
        rm -f "${PYTHON_DEST}/lib/lib"
        log_info "  Removed ${PYTHON_DEST}/lib/lib"
    fi
    if [ -L "${PYTHON_DEST}/${PYTHON_VERSION}" ]; then
        rm -f "${PYTHON_DEST}/${PYTHON_VERSION}"
        log_info "  Removed ${PYTHON_DEST}/${PYTHON_VERSION}"
    fi
    
    # Add sitecustomize.py to disable user site-packages
    log_info "Adding sitecustomize.py to disable user site-packages..."
    SITECUSTOMIZE_SOURCE="${SCRIPT_DIR}/resources/sitecustomize.py"
    SITECUSTOMIZE_DEST="${PYTHON_DEST}/lib/python${PYTHON_VERSION}/sitecustomize.py"
    if [ -f "${SITECUSTOMIZE_SOURCE}" ]; then
        cp "${SITECUSTOMIZE_SOURCE}" "${SITECUSTOMIZE_DEST}"
        log_info "  Installed sitecustomize.py"
    else
        log_error "sitecustomize.py not found at ${SITECUSTOMIZE_SOURCE}"
        exit 1
    fi
    
    # Create python3 symlink in bin directory
    log_info "Creating python3 symlink in bin directory..."
    if [ -f "${PYTHON_DEST}/bin/python${PYTHON_VERSION}" ]; then
        (cd "${PYTHON_DEST}/bin" && ln -sf "python${PYTHON_VERSION}" python3)
        log_info "  Created python3 -> python${PYTHON_VERSION}"
    fi
    
    # Create version symlinks
    log_info "Creating framework-level symlinks..."
    VERSIONS_DIR="${FRAMEWORKS_DIR}/Python.framework/Versions"
    FRAMEWORK_DIR="${FRAMEWORKS_DIR}/Python.framework"
    
    # Create Current -> 3.12 symlink
    (cd "${VERSIONS_DIR}" && ln -sfn "${PYTHON_VERSION}" Current)
    log_info "  Created ${VERSIONS_DIR}/Current -> ${PYTHON_VERSION}"
    
    # Create framework-level bin and lib symlinks (use -n to avoid following symlinks)
    (cd "${FRAMEWORK_DIR}" && ln -sfn "Versions/Current/bin" bin)
    (cd "${FRAMEWORK_DIR}" && ln -sfn "Versions/Current/lib" lib)
    log_info "  Created ${FRAMEWORK_DIR}/bin -> Versions/Current/bin"
    log_info "  Created ${FRAMEWORK_DIR}/lib -> Versions/Current/lib"
    
    log_success "Python embedded successfully"
    
    # Remove unnecessary files from embedded Python
    log_info "Removing unnecessary files from embedded Python..."
    
    # Remove development tools from bin/
    for tool in "idle${PYTHON_VERSION}" pip3 "pip${PYTHON_VERSION}" "pydoc${PYTHON_VERSION}" "python${PYTHON_VERSION}-config"; do
        if [ -f "${PYTHON_DEST}/bin/${tool}" ]; then
            rm -f "${PYTHON_DEST}/bin/${tool}"
            log_info "  Removed bin/${tool}"
        fi
    done
    
    # Remove pkg-config files
    if [ -d "${PYTHON_DEST}/lib/pkgconfig" ]; then
        rm -rf "${PYTHON_DEST}/lib/pkgconfig"
        log_info "  Removed lib/pkgconfig/"
    fi
    
    # Remove Python test suite (saves ~68MB)
    if [ -d "${PYTHON_DEST}/lib/python${PYTHON_VERSION}/test" ]; then
        rm -rf "${PYTHON_DEST}/lib/python${PYTHON_VERSION}/test"
        log_info "  Removed lib/python${PYTHON_VERSION}/test/"
    fi
    
    log_success "Unnecessary files removed"
    
    # Pre-compile Python standard library
    log_info "Pre-compiling Python standard library..."
    STDLIB_PATH="${PYTHON_DEST}/lib/python${PYTHON_VERSION}"
    if [ -d "${STDLIB_PATH}" ]; then
        # Use the bundled Python to compile the standard library
        # This ensures compatibility and uses the correct Python version
        BUNDLE_PYTHON="${PYTHON_DEST}/bin/python3"
        if [ -f "${BUNDLE_PYTHON}" ]; then
            # Compile all .py files in the standard library
            # -q: quiet mode (only show errors)
            # -f: force recompilation even if .pyc files exist
            if "${BUNDLE_PYTHON}" -m compileall -q -f "${STDLIB_PATH}"; then
                log_info "  Compiled Python standard library"
                
                # Count compiled files for verification
                PYC_COUNT=$(find "${STDLIB_PATH}" -name "*.pyc" | wc -l | tr -d ' ')
                PY_COUNT=$(find "${STDLIB_PATH}" -name "*.py" | wc -l | tr -d ' ')
                log_info "  Created ${PYC_COUNT} .pyc files from ${PY_COUNT} .py files"
            else
                log_warning "Standard library compilation had errors (non-critical)"
            fi
        else
            log_warning "Bundled Python not found, skipping standard library pre-compilation"
        fi
    else
        log_warning "Standard library path not found: ${STDLIB_PATH}"
    fi
    
    # Update install names for Python shared library
    log_info "Updating install names to use embedded Python..."
    # Find the Python shared library
    PYTHON_LIB=$(find "${PYTHON_DEST}/lib" -name "libpython${PYTHON_VERSION}*.dylib" -type f | head -1)
    if [ -n "${PYTHON_LIB}" ]; then
        PYTHON_LIB_NAME=$(basename "${PYTHON_LIB}")
        
        # Update the XeFM executable to use bundled Python library
        install_name_tool -change \
            "${PYTHON_BASE_PREFIX}/lib/${PYTHON_LIB_NAME}" \
            "@executable_path/../Frameworks/Python.framework/Versions/${PYTHON_VERSION}/lib/${PYTHON_LIB_NAME}" \
            "${MACOS_DIR}/${APP_NAME}" 2>/dev/null || true
        
        # Update the Python library's own install name (id)
        install_name_tool -id \
            "@executable_path/../Frameworks/Python.framework/Versions/${PYTHON_VERSION}/lib/${PYTHON_LIB_NAME}" \
            "${PYTHON_LIB}"
        log_info "  Updated Python library install name"
        
        # Check for and update any external library dependencies
        EXTERNAL_LIBS=$(otool -L "${PYTHON_LIB}" | grep -E "/(opt|usr/local|Users)" | grep -v "/usr/lib" | grep -v "/System" | awk '{print $1}')
        if [ -n "${EXTERNAL_LIBS}" ]; then
            log_info "  Warning: Python library has external dependencies:"
            echo "${EXTERNAL_LIBS}" | while read -r lib; do
                log_info "    - ${lib}"
            done
            log_info "  These libraries must be available on the target system"
        fi
    fi
fi

log_success "Install names updated"

# ============================================================================
# Step 4b: Make the bundle self-contained (vendor external dylibs)
# ============================================================================
#
# Python's C-extension modules (_ssl, _hashlib, _sqlite3, _lzma, _zstd,
# _decimal, ...) are dynamically linked against Homebrew libraries that live
# OUTSIDE the bundle, e.g. /opt/homebrew/opt/openssl@3/lib/libssl.3.dylib.
# On a Mac without those exact Homebrew formulae the app fails to launch with
# "Library not loaded: /opt/homebrew/...". delocate copies each such library
# into a .dylibs/ folder next to the extensions and rewrites their load
# commands to @loader_path, so the bundle runs on any Mac.

log_info "Step 4b: Vendoring external dynamic libraries (delocate)..."

# The Homebrew framework copy can leave dangling / self-referential symlinks
# (e.g. Versions/${PYTHON_VERSION}/${PYTHON_VERSION} -> ${PYTHON_VERSION}).
# They are unused by XeFM but trip up delocate's directory walk, so remove any
# broken symlinks first.
BROKEN_LINKS=$(find "${APP_BUNDLE}" -type l ! -exec test -e {} \; -print 2>/dev/null | wc -l | tr -d ' ')
if [ "${BROKEN_LINKS}" != "0" ]; then
    log_info "  Removing ${BROKEN_LINKS} broken symlink(s) from the bundle"
    find "${APP_BUNDLE}" -type l ! -exec test -e {} \; -delete 2>/dev/null || true
fi

# Ensure delocate is available in the build venv.
DELOCATE_PATH="${PROJECT_ROOT}/.venv/bin/delocate-path"
if [ ! -x "${DELOCATE_PATH}" ]; then
    log_info "  delocate not found in venv; installing..."
    if ! "${VENV_PYTHON}" -m pip install --quiet delocate; then
        log_error "Failed to install 'delocate'. Install it and re-run the build:"
        log_error "  ${VENV_PYTHON} -m pip install delocate"
        exit 1
    fi
fi

# Delocate only the lib-dynload tree so the vendored .dylibs/ folder stays
# inside Contents/ and the main executable and Python.framework (already wired
# with @executable_path) are left untouched. This is the only part of the
# bundle with external dependencies; the pip packages under Resources ship
# self-contained wheels.
LIB_DYNLOAD="${FRAMEWORKS_DIR}/Python.framework/Versions/${PYTHON_VERSION}/lib/python${PYTHON_VERSION}/lib-dynload"
if [ -d "${LIB_DYNLOAD}" ]; then
    "${DELOCATE_PATH}" "${LIB_DYNLOAD}"
    log_info "  Vendored external libraries into ${LIB_DYNLOAD}/.dylibs"

    # Verify no C-extension still depends on a library outside the bundle.
    EXTERNAL_DEPS=$(find "${LIB_DYNLOAD}" -name "*.so" -exec otool -L {} \; 2>/dev/null \
        | grep -E "^[[:space:]]+(/opt/homebrew|/usr/local|/opt/local|/Users/)" | sort -u || true)
    if [ -n "${EXTERNAL_DEPS}" ]; then
        log_warning "  Some extensions still reference external libraries:"
        echo "${EXTERNAL_DEPS}"
        log_warning "  The app may fail to launch on machines without these libraries."
    else
        log_success "  All C-extension modules are self-contained"
    fi

    # delocate copies these libraries straight out of Homebrew, and a Homebrew
    # binary carries the minimum OS of whatever machine compiled it: the bottle
    # builder's, or this one when brew had no bottle and built from source.
    # That is how macOS 27 got into 1.5.0 - libcrypto, libssl and liblzma were
    # source builds - and dyld refuses such a library on an older Mac with
    # "built for macOS 27.0 which is newer than running OS", so _ssl, _hashlib
    # and _lzma would fail to import even once the launcher itself is pinned.
    # Only the load command is rewritten: these are portable C libraries that
    # call nothing newer than the floor, and the SDK and linker fields are kept
    # as they were so the file still looks to notarization like what built it.
    # The rewrite invalidates the copied signature, which Step 6 replaces.
    VENDORED_DYLIBS="${LIB_DYNLOAD}/.dylibs"
    if [ -d "${VENDORED_DYLIBS}" ]; then
        for lib in "${VENDORED_DYLIBS}"/*.dylib; do
            [ -f "${lib}" ] || continue
            LIB_MIN=$(macho_min_os "${lib}")
            [ -n "${LIB_MIN}" ] || continue
            version_gt "${LIB_MIN}" "${MACOS_MIN_VERSION}" || continue
            LIB_SDK=$(vtool -show-build "${lib}" 2>/dev/null | awk '$1 == "sdk" { print $2; exit }')
            log_info "  Lowering $(basename "${lib}") from macOS ${LIB_MIN} to ${MACOS_MIN_VERSION}"
            if ! vtool -set-build-version macos "${MACOS_MIN_VERSION}" "${LIB_SDK:-${MACOS_MIN_VERSION}}" \
                    -replace -output "${lib}" "${lib}" > /dev/null 2>&1; then
                log_error "Failed to lower the minimum OS of ${lib}"
                exit 1
            fi
        done
    fi
else
    log_warning "  lib-dynload not found at ${LIB_DYNLOAD}; skipping delocate"
fi

# ============================================================================
# Step 4c: Drop the architectures this bundle cannot run
# ============================================================================
#
# The embedded Python is universal2 because that is how python.org ships it,
# and that is what pins the floor at 10.15/11.0 no matter who builds. It is not
# Intel support: XeFM's own launcher is compiled without -arch, so it is built
# for this machine alone, and a bundle whose executable has no x86_64 slice can
# never run a single byte of the x86_64 code inside it. Pillow settles the
# question anyway - it publishes no universal2 wheel for cp314, so the image
# viewer is this architecture only regardless. Every foreign slice is weight in
# the DMG that no Mac will ever map.
#
# So the slices follow the launcher rather than a hardcoded arm64: a build on
# an Intel Mac thins to x86_64 by the same rule, and if the launcher is ever
# built universal the step stands aside and the bundle stays fat.
#
# lipo rewrites the file, so the signature each binary carries - ad-hoc here,
# whatever the distribution shipped elsewhere - no longer matches. Re-sign
# ad-hoc immediately: an unsigned Mach-O cannot exec on Apple Silicon at all,
# and Step 6 replaces these with the real identity.

LAUNCHER_ARCHS=$(lipo -archs "${MACOS_DIR}/${APP_NAME}" 2>/dev/null)
if [ "$(echo "${LAUNCHER_ARCHS}" | wc -w | tr -d ' ')" != "1" ]; then
    log_info "Step 4c: Launcher is ${LAUNCHER_ARCHS}; keeping every slice"
else
    BUNDLE_ARCH="${LAUNCHER_ARCHS}"
    log_info "Step 4c: Thinning universal binaries to ${BUNDLE_ARCH}..."

    THINNED=0
    BYTES_BEFORE=0
    BYTES_AFTER=0
    while IFS= read -r macho; do
        [ -n "${macho}" ] || continue
        [ -L "${macho}" ] && continue
        file -b "${macho}" | grep -q "Mach-O universal" || continue
        if ! lipo -archs "${macho}" | tr ' ' '\n' | grep -qx "${BUNDLE_ARCH}"; then
            log_error "${macho#${APP_BUNDLE}/} has no ${BUNDLE_ARCH} slice"
            exit 1
        fi
        SIZE_BEFORE=$(stat -f%z "${macho}")
        # Written through the original path so the file keeps its mode: the
        # interpreter and the launcher have to stay executable.
        if ! lipo -thin "${BUNDLE_ARCH}" "${macho}" -output "${macho}.thin"; then
            log_error "Failed to thin ${macho#${APP_BUNDLE}/}"
            exit 1
        fi
        cat "${macho}.thin" > "${macho}"
        rm -f "${macho}.thin"
        codesign --force --sign - "${macho}" 2>/dev/null
        THINNED=$((THINNED + 1))
        BYTES_BEFORE=$((BYTES_BEFORE + SIZE_BEFORE))
        BYTES_AFTER=$((BYTES_AFTER + $(stat -f%z "${macho}")))
    done <<MACHO_LIST
$(find "${APP_BUNDLE}" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \) 2>/dev/null)
MACHO_LIST

    log_success "  Thinned ${THINNED} binaries to ${BUNDLE_ARCH}, \
$(( (BYTES_BEFORE - BYTES_AFTER) / 1024 / 1024 ))MB saved"
fi

# ============================================================================
# Step 4d: Generate third-party license notices
# ============================================================================
#
# Build an aggregated THIRD_PARTY_NOTICES.txt from the license text shipped with
# every bundled Python distribution (python_packages/*.dist-info), plus the
# components that are not Python distributions: the embedded CPython interpreter,
# the copied-in PuiKit source, and the bundled Noto fonts. The generator fails
# the build if any bundled distribution has no discoverable license text, so an
# incomplete notice can never ship. The script is stdlib-only and platform-
# agnostic - the Windows bundle build reuses it the same way.

log_info "Step 4d: Generating third-party license notices..."

NOTICES_SCRIPT="${PROJECT_ROOT}/tools/generate_third_party_notices.py"
NOTICES_OUT="${RESOURCES_DIR_BUNDLE}/THIRD_PARTY_NOTICES.txt"

if [ ! -f "${NOTICES_SCRIPT}" ]; then
    log_error "Notices generator not found at ${NOTICES_SCRIPT}"
    exit 1
fi

NOTICES_EXTRAS=()

# Embedded interpreter's PSF license (under lib/, survives the Resources/
# cleanup performed while embedding Python above).
PYTHON_LICENSE="${PYTHON_DEST}/lib/python${PYTHON_VERSION}/LICENSE.txt"
if [ -f "${PYTHON_LICENSE}" ]; then
    NOTICES_EXTRAS+=(--extra "Python ${PYTHON_VERSION} interpreter and standard library (Python Software Foundation License Agreement)=${PYTHON_LICENSE}")
else
    log_warning "Python LICENSE.txt not found at ${PYTHON_LICENSE}; the interpreter will not be listed in the generated notices"
fi

# PuiKit's LICENSE location depends on how PuiKit is installed:
#   * editable checkout (PUIKIT_DIR / ../puikit): LICENSE sits at the checkout
#     root, one level above the package directory resolved into PUIKIT_SRC.
#   * published wheel: LICENSE ships inside puikit-*.dist-info (.../licenses/LICENSE).
# In the wheel case the package dir's parent IS the venv site-packages, which
# holds that .dist-info; in the editable case the checkout-root LICENSE is found
# first. So a single parent path resolves both layouts.
PUIKIT_PARENT="$(dirname "${PUIKIT_SRC}")"
PUIKIT_LICENSE="${PUIKIT_PARENT}/LICENSE"
if [ ! -f "${PUIKIT_LICENSE}" ]; then
    # …/site-packages/puikit-*.dist-info/licenses/LICENSE is 3 levels down.
    PUIKIT_LICENSE="$(find "${PUIKIT_PARENT}" -maxdepth 3 -ipath '*puikit-*.dist-info*' \
                      -iname 'LICEN[SC]E*' -type f 2>/dev/null | head -n 1)"
fi
if [ -n "${PUIKIT_LICENSE}" ] && [ -f "${PUIKIT_LICENSE}" ]; then
    NOTICES_EXTRAS+=(--extra "PuiKit ${PUIKIT_VERSION} (MIT License)=${PUIKIT_LICENSE}")
else
    log_error "PuiKit LICENSE not found (looked for ${PUIKIT_PARENT}/LICENSE and puikit-*.dist-info under ${PUIKIT_PARENT})"
    exit 1
fi

# Bundled fonts (SIL OFL 1.1); OFL.txt was copied alongside the .ttf files.
FONTS_OFL="${FONTS_DEST}/OFL.txt"
if [ -f "${FONTS_OFL}" ]; then
    NOTICES_EXTRAS+=(--extra "Noto Sans & Noto Sans Mono fonts (SIL Open Font License 1.1)=${FONTS_OFL}")
else
    log_error "Font license OFL.txt not found at ${FONTS_OFL}"
    exit 1
fi

if "${VENV_PYTHON}" "${NOTICES_SCRIPT}" \
        --title "XeFM" \
        --scan "${PACKAGES_DEST}" \
        "${NOTICES_EXTRAS[@]}" \
        --output "${NOTICES_OUT}"; then
    log_success "Third-party notices written to ${NOTICES_OUT}"
else
    log_error "Failed to generate third-party license notices (see errors above)"
    exit 1
fi

# ============================================================================
# Step 4e: Verify the bundle loads nothing from outside itself
# ============================================================================
#
# The steps above each make one part of the bundle self-contained - the
# interpreter's own load command, the extensions' vendored dylibs, the copies
# that had to go. This reads the finished bundle back and answers the question
# they are all serving: on a Mac with no Python installed, does anything here
# reach outside the .app? It runs before signing so a bundle that would fail on
# someone else's machine is never sealed, let alone notarized.

log_info "Step 4e: Verifying the bundle is self-contained..."

SELF_CONTAINED_SCRIPT="${PROJECT_ROOT}/tools/check_bundle_self_contained.py"
if [ ! -f "${SELF_CONTAINED_SCRIPT}" ]; then
    log_error "Self-containment checker not found at ${SELF_CONTAINED_SCRIPT}"
    exit 1
fi

if "${VENV_PYTHON}" "${SELF_CONTAINED_SCRIPT}" "${APP_BUNDLE}"; then
    log_success "Bundle is self-contained"
else
    log_error "The bundle depends on files outside itself (listed above)"
    exit 1
fi

# ============================================================================
# Step 5: Generate Info.plist
# ============================================================================

log_info "Step 5: Generating Info.plist..."

TEMPLATE_FILE="${RESOURCES_DIR}/Info.plist.template"
PLIST_FILE="${CONTENTS_DIR}/Info.plist"

if [ ! -f "${TEMPLATE_FILE}" ]; then
    log_error "Info.plist template not found at ${TEMPLATE_FILE}"
    exit 1
fi

# LSMinimumSystemVersion has to match what the bundle can actually honor, so it
# is read back off the finished bundle rather than written by hand. The value
# used to be a hardcoded 10.13 that no release ever met - every DMG so far has
# in fact required the macOS of the machine that built it - and a plist that
# claims too much turns a clean "you can't use this version" dialog into a dyld
# crash. The floor is the highest minimum any Mach-O in the bundle declares,
# which today is the embedded Homebrew Python; moving off Homebrew is what
# would bring it down to MACOS_MIN_VERSION.
log_info "Reading the bundle's minimum macOS version back off its binaries..."

BUNDLE_MIN_OS="${MACOS_MIN_VERSION}"
BUNDLE_MIN_OS_FILE=""
while IFS= read -r macho; do
    [ -n "${macho}" ] || continue
    file -b "${macho}" | grep -q "Mach-O" || continue
    MACHO_MIN=$(macho_min_os "${macho}")
    [ -n "${MACHO_MIN}" ] || continue
    if version_gt "${MACHO_MIN}" "${BUNDLE_MIN_OS}"; then
        BUNDLE_MIN_OS="${MACHO_MIN}"
        BUNDLE_MIN_OS_FILE="${macho}"
    fi
done <<MACHO_LIST
$(find "${APP_BUNDLE}" -type f \( -perm -u+x -o -name "*.so" -o -name "*.dylib" \) 2>/dev/null)
MACHO_LIST

if [ -n "${BUNDLE_MIN_OS_FILE}" ]; then
    log_warning "  Floor is macOS ${BUNDLE_MIN_OS}, above the ${MACOS_MIN_VERSION} this build targets"
    log_warning "  Raised by: ${BUNDLE_MIN_OS_FILE#${APP_BUNDLE}/}"
else
    log_success "  Every binary runs on macOS ${BUNDLE_MIN_OS}"
fi

# Substitute version number and the minimum OS just measured
log_info "Substituting version: ${VERSION}"
sed -e "s/{{VERSION}}/${VERSION}/g" \
    -e "s/{{MIN_OS}}/${BUNDLE_MIN_OS}/g" \
    "${TEMPLATE_FILE}" > "${PLIST_FILE}"

# Validate Info.plist is valid XML
if ! plutil -lint "${PLIST_FILE}" > /dev/null 2>&1; then
    log_error "Generated Info.plist is not valid XML"
    exit 1
fi

log_success "Info.plist generated and validated"

# ============================================================================
# Step 6: Code Signing (optional; required for notarized distribution)
# ============================================================================
#
# Signing is skipped unless CODESIGN_IDENTITY is set. Signing the .app alone is
# not enough for Gatekeeper / notarization: every Mach-O binary inside it must
# be signed with a secure timestamp and the Hardened Runtime, from the inside
# out (nested libraries first, the .app last). The embedded CPython interpreter
# loads C-extension modules (.so) and vendored dylibs at runtime, so it also
# needs the entitlements in resources/entitlements.plist.

if [ -n "${CODESIGN_IDENTITY}" ]; then
    log_info "Step 6: Code signing bundle (inside-out, Hardened Runtime)..."

    ENTITLEMENTS_FILE="${RESOURCES_DIR}/entitlements.plist"
    if [ ! -f "${ENTITLEMENTS_FILE}" ]; then
        log_error "Entitlements file not found at ${ENTITLEMENTS_FILE}"
        exit 1
    fi

    # Common codesign invocation: replace any existing signature, embed a
    # secure timestamp, opt into the Hardened Runtime, and apply the embedded
    # interpreter entitlements.
    SIGN=(codesign --force --timestamp --options runtime \
          --entitlements "${ENTITLEMENTS_FILE}" --sign "${CODESIGN_IDENTITY}")

    # The Python-embedding step above strips the framework's Resources/ dir,
    # which removes the Info.plist codesign needs to seal Python.framework as a
    # nested bundle. Synthesize a minimal one so the framework signs cleanly and
    # `codesign --verify --deep` accepts it as valid nested code.
    FRAMEWORK_VERSION_DIR="${FRAMEWORKS_DIR}/Python.framework/Versions/${PYTHON_VERSION}"
    if [ -d "${FRAMEWORK_VERSION_DIR}" ] && [ ! -f "${FRAMEWORK_VERSION_DIR}/Resources/Info.plist" ]; then
        log_info "  Writing minimal Python.framework Info.plist for signing..."
        mkdir -p "${FRAMEWORK_VERSION_DIR}/Resources"
        cat > "${FRAMEWORK_VERSION_DIR}/Resources/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>org.python.python</string>
    <key>CFBundleName</key><string>Python</string>
    <key>CFBundleExecutable</key><string>Python</string>
    <key>CFBundlePackageType</key><string>FMWK</string>
    <key>CFBundleShortVersionString</key><string>${PYTHON_VERSION}</string>
    <key>CFBundleVersion</key><string>${PYTHON_VERSION}</string>
</dict>
</plist>
PLIST
    fi

    # 1. Nested Mach-O libraries: extension modules (.so) and dylibs, including
    #    the vendored .dylibs/ from delocate and any shipped inside pip packages.
    log_info "  Signing nested libraries (.so / .dylib)..."
    while IFS= read -r -d '' lib; do
        "${SIGN[@]}" "${lib}" || { log_error "Failed to sign ${lib}"; exit 1; }
    done < <(find "${APP_BUNDLE}" -type f \( -name "*.so" -o -name "*.dylib" \) -print0)

    # 2. Standalone Mach-O executables inside the framework's bin/ (e.g.
    #    pythonX.Y). Skip symlinks and non-Mach-O helper scripts.
    log_info "  Signing embedded interpreter executables..."
    FRAMEWORK_BIN_DIR="${FRAMEWORK_VERSION_DIR}/bin"
    if [ -d "${FRAMEWORK_BIN_DIR}" ]; then
        while IFS= read -r -d '' exe; do
            if file "${exe}" | grep -q "Mach-O"; then
                "${SIGN[@]}" "${exe}" || { log_error "Failed to sign ${exe}"; exit 1; }
            fi
        done < <(find "${FRAMEWORK_BIN_DIR}" -type f -print0)
    fi

    # 3. Python.framework itself (seals its versioned contents as nested code).
    #    Present only in the Python.framework build path; the standard-Python
    #    path ships libpythonX.Y.dylib instead, already signed in step 1.
    if [ -f "${FRAMEWORK_VERSION_DIR}/Python" ]; then
        log_info "  Signing Python.framework..."
        "${SIGN[@]}" "${FRAMEWORKS_DIR}/Python.framework" \
            || { log_error "Failed to sign Python.framework"; exit 1; }
    fi

    # 4. The main executable.
    log_info "  Signing main executable..."
    "${SIGN[@]}" "${MACOS_DIR}/${APP_NAME}" \
        || { log_error "Failed to sign ${APP_NAME}"; exit 1; }

    # 5. The .app bundle last: the outermost seal over everything above.
    log_info "  Signing app bundle..."
    "${SIGN[@]}" "${APP_BUNDLE}" \
        || { log_error "Failed to sign ${APP_BUNDLE}"; exit 1; }

    # Verify the whole static code tree strictly (as Gatekeeper would).
    log_info "  Verifying signature..."
    if codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"; then
        log_success "Code signing completed and verified"
    else
        log_error "Code signing verification failed"
        exit 1
    fi

    # --deep --strict validates the code the bundle declares; the notary
    # service instead opens the archive and inspects every Mach-O it finds,
    # signed or not, and one unsigned file fails the whole submission. The two
    # disagreed over lib/python3.14/config-3.14-darwin/python.o, a link-time
    # object file that is a Mach-O by format and not code by any other measure:
    # codesign never looked at it, Apple did, and the answer came back after
    # the upload and a several-minute wait. Ask the same question here, where
    # it costs a second.
    log_info "  Checking every Mach-O in the bundle carries a signature..."
    # Every file, not just the ones named like code - that is the point. One
    # `file` over the lot, tab-separated so a type string of its own ("Mach-O
    # universal binary with 2 architectures: [x86_64: ...]") cannot be mistaken
    # for the path separator.
    UNSIGNED_MACHOS=""
    while IFS= read -r macho; do
        [ -n "${macho}" ] || continue
        codesign --verify "${macho}" > /dev/null 2>&1 && continue
        UNSIGNED_MACHOS="${UNSIGNED_MACHOS}  ${macho#${APP_BUNDLE}/}
"
    done <<MACHO_LIST
$(find "${APP_BUNDLE}" -type f -print0 2>/dev/null \
    | xargs -0 file -F "$(printf '\t')" 2>/dev/null \
    | awk -F"$(printf '\t')" '$2 ~ /Mach-O/ { print $1 }')
MACHO_LIST
    if [ -n "${UNSIGNED_MACHOS}" ]; then
        log_error "Notarization would reject these unsigned Mach-O files:"
        printf '%s' "${UNSIGNED_MACHOS}"
        log_error "Strip them in Step 4, or sign them, before submitting."
        exit 1
    fi
    log_success "  Every Mach-O is signed"
    log_info "  (After notarization, confirm Gatekeeper acceptance with:"
    log_info "     spctl -a -vvv --type exec \"${APP_BUNDLE}\")"
else
    log_info "Step 6: Skipping code signing (CODESIGN_IDENTITY not set)"
fi

# ============================================================================
# Step 7: Notarization (optional; requires signing)
# ============================================================================
#
# Submits the signed .app to Apple's notary service and staples the resulting
# ticket, so the app launches without Gatekeeper warnings even offline. Skipped
# unless NOTARY_PROFILE names a notarytool keychain profile (see the config
# section above for how to create one). create_dmg.sh notarizes the DMG too.

if [ -n "${NOTARY_PROFILE}" ]; then
    if [ -z "${CODESIGN_IDENTITY}" ]; then
        log_error "NOTARY_PROFILE is set but CODESIGN_IDENTITY is not."
        log_error "A notarized app must be signed first; set CODESIGN_IDENTITY and rebuild."
        exit 1
    fi

    log_info "Step 7: Notarizing app bundle..."

    # notarytool accepts a .zip/.dmg/.pkg, not a raw .app; ditto preserves the
    # bundle's symlinks and signatures inside the zip.
    NOTARIZE_ZIP="${BUILD_DIR}/${APP_NAME}-notarize.zip"
    rm -f "${NOTARIZE_ZIP}"
    log_info "  Packaging app for submission..."
    /usr/bin/ditto -c -k --keepParent "${APP_BUNDLE}" "${NOTARIZE_ZIP}"

    log_info "  Submitting to Apple notary service (this can take a few minutes)..."
    if xcrun notarytool submit "${NOTARIZE_ZIP}" \
            --keychain-profile "${NOTARY_PROFILE}" --wait; then
        log_info "  Stapling notarization ticket to the app..."
        xcrun stapler staple "${APP_BUNDLE}"
        xcrun stapler validate "${APP_BUNDLE}"
        rm -f "${NOTARIZE_ZIP}"
        log_success "Notarization completed and stapled"
    else
        log_error "Notarization failed. Inspect the full log with:"
        log_error "  xcrun notarytool log <submission-id> --keychain-profile \"${NOTARY_PROFILE}\""
        rm -f "${NOTARIZE_ZIP}"
        exit 1
    fi
else
    log_info "Step 7: Skipping notarization (NOTARY_PROFILE not set)"
fi

# ============================================================================
# Build Complete
# ============================================================================

log_success "Build completed successfully!"
log_info "Application bundle: ${APP_BUNDLE}"
log_info ""
log_info "To run the application:"
log_info "  open ${APP_BUNDLE}"
log_info ""
log_info "To install to Applications:"
log_info "  cp -R ${APP_BUNDLE} /Applications/"
