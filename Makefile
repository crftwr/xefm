# XeFM Makefile

.PHONY: help run run-gui run-web test test-quick test-linux test-linux-musl clean clean-python install uninstall dev-install lint format demo build publish-testpypi tag release-github release-whl release-macos-dmg release-windows-zip release-status icons icons-check macos-app clean-macos macos-refresh-icon macos-dmg install-macos-dmg uninstall-macos-dmg windows-app clean-windows clean-windows-cache windows-zip install-windows-zip uninstall-windows-zip windows-msix install-windows-msix uninstall-windows-msix install-config venv clean-venv check-venv install-puikit

# Python interpreter selection
# All Python is run through the project virtual environment (.venv). There is no
# fallback to a system python3 - run 'make venv' first to create the environment.
# An absolute path is used so targets that change directories still resolve the
# same interpreter.
# venv layout differs by platform: POSIX uses .venv/bin/, Windows uses .venv/Scripts/.
# Detected via `uname -s` rather than $(OS) - MSYS2/Git-Bash make does not
# reliably inherit the Windows OS environment variable.
UNAME_S := $(shell uname -s 2>/dev/null)
ifneq (,$(findstring MINGW,$(UNAME_S))$(findstring MSYS,$(UNAME_S))$(findstring CYGWIN,$(UNAME_S)))
VENV_BINDIR := Scripts
PYTHON := $(abspath .venv/$(VENV_BINDIR)/python.exe)
else
VENV_BINDIR := bin
PYTHON := $(abspath .venv/$(VENV_BINDIR)/python)
endif
PIP := $(PYTHON) -m pip

# --- PuiKit source: PyPI by default, local editable checkout on opt-in ---------
# PuiKit is released on PyPI, so `make venv` installs it from there by default.
# To develop against a local PuiKit checkout, set PUIKIT_DIR to its path — PuiKit
# is then installed *editable* from there (live edits, no reinstall). Declare it
# once, persistently, without editing this file, in either way:
#   * Makefile.local (gitignored):   PUIKIT_DIR = ../puikit
#   * or your environment:           export PUIKIT_DIR=../puikit
# venv / install / dev-install then honour it. On demand, `make install-puikit`
# (re)installs PuiKit into an existing .venv from whichever source PUIKIT_DIR
# selects right now — set it for editable, unset for the released PyPI build.
-include Makefile.local
PUIKIT_DIR ?=

help:
	@echo "XeFM - a dual-pane file manager for the desktop and the terminal"
	@echo ""
	@echo "Using Python: $(PYTHON)"
	@echo "(run 'make venv' first if .venv does not exist)"
	@echo ""
	@echo "Available commands:"
	@echo "  venv           - Create .venv using the latest python3 in PATH and install deps"
	@echo "  clean-venv     - Remove the .venv directory"
	@echo "  install-puikit - (Re)install PuiKit: editable if PUIKIT_DIR set, else from PyPI"
	@echo "  run            - Run XeFM (terminal); LEFT=/RIGHT= set startup dirs"
	@echo "  run-gui        - Run XeFM in a native macOS GUI window"
	@echo "  run-web        - Run XeFM in a web browser (web backend)"
	@echo "  test           - Run all tests"
	@echo "  test-quick     - Run quick verification tests"
	@echo "  test-linux     - Run all tests on Linux in Docker (glibc/Debian)"
	@echo "  test-linux-musl- Check libarchive is found on musl (Alpine), and that"
	@echo "                   its absence degrades cleanly"
	@echo "  clean          - Remove every rebuildable artifact (keeps .venv + the"
	@echo "                   Windows download cache; it names both when it finishes)"
	@echo "  clean-python   - Just the source tree: build/, dist/, egg-info, pyc, pytest"
	@echo "  install        - Install XeFM"
	@echo "  uninstall      - Uninstall XeFM"
	@echo "  dev-install    - Install in development mode"
	@echo "  install-config - Copy default config to ~/.xefm/config.py (overwrites existing)"
	@echo "  lint           - Run code linting"
	@echo "  format         - Format code"
	@echo ""
	@echo "Release (one target per artifact; run in this order):"
	@echo "  tag VERSION=x.y.z  - Bump __version__, commit, tag, push (no publishing)"
	@echo "  release-github     - Open the GitHub Release at that tag"
	@echo "  release-whl        - Upload sdist + wheel to PyPI, and to the Release"
	@echo "  release-macos-dmg  - (on macOS)   attach XeFM-<ver>-macos.dmg to the Release"
	@echo "  release-windows-zip- (on Windows) attach XeFM-<ver>-win64.zip to the Release"
	@echo "  release-windows-msix - (on Windows) submit the MSIX to the Microsoft Store"
	@echo "  release-status     - Show which artifacts have landed so far"
	@echo ""
	@echo "  The three release-<artifact> targets are independent and re-runnable,"
	@echo "  in any order, on their own machine. Supporting targets:"
	@echo "  build            - Build the sdist + wheel into dist/ (installs build/twine as needed)"
	@echo "  publish-testpypi - Rehearsal: upload dist/* to TestPyPI ([testpypi] token in ~/.pypirc)"
	@echo ""
	@echo "  PuiKit installs from PyPI by default. To develop against a local"
	@echo "  editable checkout, set PUIKIT_DIR (Makefile.local / env / CLI),"
	@echo "  e.g. PUIKIT_DIR=../puikit."
	@echo ""
	@echo "App Icons (macOS-only; the generated assets are committed):"
	@echo "  icons             - Regenerate icon assets from tools/icon/*.svg"
	@echo "  icons-check       - Verify the committed icon assets match the SVG masters"
	@echo ""
	@echo "macOS App Bundle:"
	@echo "  macos-app           - Build native macOS application bundle"
	@echo "  clean-macos         - Remove macos_app/build/ (the .app AND the DMG)"
	@echo "  macos-refresh-icon  - Refresh macOS icon cache (after icon changes)"
	@echo "  macos-dmg           - Create DMG installer for distribution"
	@echo "  install-macos-dmg   - Install XeFM.app from that DMG to /Applications"
	@echo "                        (MACOS_INSTALL_DIR=~/Applications to install per-user)"
	@echo "  uninstall-macos-dmg - Remove that installed XeFM.app"
	@echo ""
	@echo "Windows App Bundle:"
	@echo "  windows-app            - Build self-contained Windows application bundle"
	@echo "  clean-windows          - Remove windows_app/build/ (bundle, zip, .msix) + tiles"
	@echo "  clean-windows-cache    - Remove the downloaded CPython embeddable zips"
	@echo "  windows-zip            - Build the bundle and zip it for distribution"
	@echo "  install-windows-zip    - Install from that zip to %LOCALAPPDATA%\\\\Programs\\\\XeFM"
	@echo "                           (WINDOWS_INSTALL_DIR=... to install elsewhere)"
	@echo "  uninstall-windows-zip  - Remove that installed bundle"
	@echo "  windows-msix           - Package the bundle as an unsigned MSIX (Store submission;"
	@echo "                           SIGN=1 to self-sign for local testing instead)"
	@echo "  install-windows-msix   - Pack + self-sign, trust cert (elevates), install per-user"
	@echo "  uninstall-windows-msix - Remove the MSIX package + throwaway signing cert"
	@echo ""
	@echo "Examples:"
	@echo "  make run                        # Run XeFM in the terminal"
	@echo "  make run-gui                    # Run XeFM in a macOS GUI window"
	@echo "  make run-web                    # Run XeFM in a web browser"
	@echo "  make run LEFT=./xefm RIGHT=./doc # Run with custom startup directories"
	@echo "  make install-config             # Install/update user config file"
	@echo "  make macos-app                  # Build macOS app bundle"
	@echo "  make macos-dmg                  # Create DMG installer"
	@echo "  make tag VERSION=1.0.1          # Bump the version, commit, tag and push"
	@echo "  make release-github             # Open the GitHub Release for that tag"
	@echo "  make release-whl                # Publish its sdist + wheel to PyPI"
	@echo "  make release-macos-dmg          # Upload the DMG to the GitHub Release"
	@echo "  make release-windows-zip        # Upload the Windows zip to the GitHub Release"
	@echo "  make release-windows-msix       # Submit the MSIX to the Microsoft Store"

venv:
	@if [ -d .venv ]; then \
		echo ".venv already exists. Run 'make clean-venv' first to recreate it."; \
		exit 1; \
	fi
ifneq (,$(findstring MINGW,$(UNAME_S))$(findstring MSYS,$(UNAME_S))$(findstring CYGWIN,$(UNAME_S)))
	@echo "Windows detected; using the 'py' launcher to create .venv..."
	@if ! command -v py >/dev/null 2>&1; then \
		echo "Error: 'py' launcher not found in PATH. Install Python from python.org first."; \
		exit 1; \
	fi
	@echo "Using $$(py --version 2>&1) to create .venv..."
	@py -m venv .venv
else
	@echo "Searching for the latest python3 in PATH..."
	@best=""; best_key=0; \
	for dir in $$(echo "$$PATH" | tr ':' '\n'); do \
		for py in "$$dir"/python3.[0-9] "$$dir"/python3.[0-9][0-9]; do \
			[ -x "$$py" ] || continue; \
			key=$$("$$py" -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null) || continue; \
			if [ -n "$$key" ] && [ "$$key" -gt "$$best_key" ]; then \
				best_key=$$key; best="$$py"; \
			fi; \
		done; \
	done; \
	if [ -z "$$best" ]; then \
		if command -v python3 >/dev/null 2>&1; then \
			best=$$(command -v python3); \
			echo "No versioned python3.x found; falling back to python3"; \
		else \
			echo "Error: no python3 interpreter found in PATH"; \
			exit 1; \
		fi; \
	fi; \
	echo "Using $$best ($$($$best --version 2>&1)) to create .venv..."; \
	"$$best" -m venv .venv
endif
	@echo "Upgrading pip..."
	@.venv/$(VENV_BINDIR)/python -m pip install --upgrade pip
	@echo "Installing dependencies from requirements.txt..."
	@.venv/$(VENV_BINDIR)/python -m pip install -r requirements.txt
	@$(MAKE) install-puikit
	@echo ""
	@echo ".venv created successfully with $$(.venv/$(VENV_BINDIR)/python --version 2>&1)"
	@echo "Run 'make run' to launch XeFM using the new environment."

# Install PuiKit into .venv from the source chosen by PUIKIT_DIR: a local editable
# checkout when PUIKIT_DIR is set (live edits, no reinstall), otherwise the
# released build from PyPI. Idempotent — skips the install when PuiKit is already
# present from the selected source. Run standalone to switch an existing .venv
# between the two; also run automatically by venv / install / dev-install.
install-puikit: check-venv
	@info=$$($(PIP) show puikit 2>/dev/null); \
	editloc=$$(echo "$$info" | sed -n 's/^Editable project location: //p'); \
	if [ -n "$(PUIKIT_DIR)" ]; then \
		if [ ! -d "$(PUIKIT_DIR)" ]; then \
			echo "Error: PuiKit not found at '$(PUIKIT_DIR)'. Set PUIKIT_DIR to your checkout."; \
			exit 1; \
		fi; \
		want=$$(cd "$(PUIKIT_DIR)" && pwd -P); \
		have=""; \
		[ -n "$$editloc" ] && [ -d "$$editloc" ] && have=$$(cd "$$editloc" && pwd -P); \
		if [ -n "$$have" ] && [ "$$have" = "$$want" ]; then \
			echo "PuiKit already editable from $$want; skipping."; \
		else \
			echo "Installing PuiKit (editable) from $(PUIKIT_DIR)..."; \
			$(PIP) install -e "$(PUIKIT_DIR)"; \
		fi; \
	else \
		if [ -n "$$info" ] && [ -z "$$editloc" ]; then \
			echo "PuiKit already installed from PyPI; skipping."; \
		else \
			echo "Installing PuiKit from PyPI..."; \
			$(PIP) install --force-reinstall --no-deps "$$(grep -o '^puikit[^ #]*' requirements.txt)"; \
		fi; \
	fi

clean-venv:
	@echo "Removing .venv..."
	@rm -rf .venv
	@echo ".venv removed"

# Guard target: ensure the virtual environment exists before running any
# Python-based target. Fails with a clear message instead of falling back to
# system python.
check-venv:
	@if [ ! -x .venv/$(VENV_BINDIR)/python ]; then \
		echo "Error: .venv not found. Run 'make venv' to create it first."; \
		exit 1; \
	fi

# Run XeFM (PuiKit). Optional startup directories: make run LEFT=./xefm RIGHT=./doc
# ``python -m`` puts the working directory on sys.path, so the repo-root ``xefm``
# package resolves straight from the checkout — no install, no PYTHONPATH.
PUIKIT_DIRS := $(if $(LEFT),--left $(LEFT)) $(if $(RIGHT),--right $(RIGHT))

run: check-venv
	@echo "Running XeFM (terminal)..."
	@$(PYTHON) -m xefm $(PUIKIT_DIRS)

run-gui: check-venv
	@echo "Running XeFM (macOS GUI)..."
	@$(PYTHON) -m xefm --backend gui $(PUIKIT_DIRS)

run-web: check-venv
	@echo "Running XeFM (web backend — opens a browser tab)..."
	@$(PYTHON) -m xefm --backend web $(PUIKIT_DIRS)

# Run from the repo root so ``python -m pytest`` puts it on sys.path and the
# ``xefm`` package resolves. The per-file fallback runs scripts directly (which
# puts test/ on the path instead), so that one still needs PYTHONPATH.
test: check-venv
	@echo "Running XeFM tests..."
	@$(PYTHON) -m pytest test -v || echo "pytest not available, running individual tests..."
	@cd test && for test in test_*.py; do echo "Running $$test..."; PYTHONPATH=.. $(PYTHON) "$$test" || exit 1; done

# --- Linux, in Docker --------------------------------------------------------
#
# XeFM is developed on macOS and shipped for Windows too, so Linux is the
# platform nobody runs the suite on by hand. These targets are that hand.
#
# The images hold the dependencies and the source is mounted read-only, so a run
# needs no rebuild after an edit and cannot write into the working tree. Two
# images, because they answer different questions: glibc runs the whole suite,
# musl exists solely to ask whether libarchive can be *found* — the one thing
# only it gets wrong. See doc/dev/LINUX_TESTING_SYSTEM.md.
DOCKER ?= docker
LINUX_PYTHON ?= 3.13
LINUX_IMAGE ?= xefm-test-linux
LINUX_MUSL_IMAGE ?= xefm-test-linux-musl
DOCKER_RUN = $(DOCKER) run --rm -v "$(CURDIR):/src:ro"

test-linux:
	@echo "Building the Linux test image (Python $(LINUX_PYTHON), glibc)..."
	@$(DOCKER) build -q -f tools/docker/Dockerfile \
		--build-arg PYTHON_VERSION=$(LINUX_PYTHON) -t $(LINUX_IMAGE) . > /dev/null
	@echo "Running the test suite on Linux..."
	@$(DOCKER_RUN) $(LINUX_IMAGE)

test-linux-musl:
	@echo "Building the musl test image..."
	@$(DOCKER) build -q -f tools/docker/Dockerfile.musl -t $(LINUX_MUSL_IMAGE) . > /dev/null
	@echo "With libarchive installed:"
	@$(DOCKER_RUN) $(LINUX_MUSL_IMAGE)
	@echo ""
	@echo "With libarchive removed:"
	@$(DOCKER_RUN) $(LINUX_MUSL_IMAGE) sh -c \
		"apk del libarchive > /dev/null 2>&1; \
		 python tools/docker/probe_libarchive.py --expect-absent"

test-quick: check-venv
	@echo "Running quick verification tests..."
	@cd test && PYTHONPATH=.. $(PYTHON) test_cursor_movement.py
	@cd test && PYTHONPATH=.. $(PYTHON) test_delete_feature.py
	@cd test && PYTHONPATH=.. $(PYTHON) test_integration.py

# --- Cleaning -----------------------------------------------------------------
# One clean target per AREA of the tree, plus `clean` to sweep the disposable
# ones together:
#
#   clean-python        the source tree      build/, dist/, *.egg-info,
#                                            __pycache__/*.pyc, .pytest_cache/,
#                                            .coverage
#   clean-macos         macos_app/build/     the .app AND the DMG
#   clean-windows       windows_app/         build/ (bundle, zip, .msix, certs)
#                                            + the generated MSIX tiles
#   clean-venv          .venv/               EXCLUDED from `clean`
#   clean-windows-cache windows_app/.cache/  EXCLUDED from `clean`
#
# `clean` runs the first three: everything they remove is rebuilt from the
# checkout by a plain `make`. The last two are excluded because restoring them
# needs the NETWORK — a venv install and a ~10MB CPython download — so losing
# them to a routine clean would be a nasty surprise. `clean` prints both, so
# "everything" is one command away and never a silent omission.
#
# Grouping is by area rather than one-cleaner-per-producing-target: splitting
# out .pytest_cache or the MSIX tiles as their own targets was more precision
# than anyone needs, and made the target list harder to read than the tree it
# describes.
#
# Hence clean-macos / clean-windows rather than clean-macos-app /
# clean-windows-app: they are NOT the inverse of macos-app / windows-app. Each
# platform's build/ holds the output of every target for that platform, so
# clean-macos also takes the DMG that macos-dmg wrote, and clean-windows also
# takes the zip and the .msix. Naming them after the app bundle claimed a
# symmetry that does not exist.
#
# Never cleaned by anything: Makefile.local, macos_app/signing.env and
# windows_app/store.env are gitignored *configuration*, not artifacts — losing
# them to a stray clean would cost real setup work.
clean: clean-python clean-macos clean-windows
	@echo ""
	@echo "Cleaned. Kept (each needs the network to restore — remove explicitly):"
	@echo "  .venv/                -> make clean-venv"
	@echo "  windows_app/.cache/   -> make clean-windows-cache"

# Everything the Python toolchain leaves in the source tree: the sdist/wheel
# outputs `make build` writes, bytecode caches, and what pytest leaves behind.
# (.coverage is gitignored but nothing here writes it — it appears when you run
# pytest-cov by hand, so it is removed if present rather than assumed.)
#
# The prunes are the point of the find calls: .venv's caches belong to
# clean-venv, and the built bundles ship *deliberately* pre-compiled bytecode
# (macos_app/build.sh and build.ps1 both compile ahead of time, and the Windows
# launcher runs with write_bytecode = 0), so sweeping those would quietly
# degrade a finished artifact rather than clean anything.
clean-python:
	@echo "Cleaning Python build, bytecode and test artifacts..."
	@rm -rf build/ dist/ .pytest_cache .coverage
	@rm -f README.pypi.md
	@find . -path ./.venv -prune -o -type d -name "*.egg-info" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . \( -path ./.venv -o -path ./macos_app/build -o -path ./windows_app/build \) -prune -o \
		-type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
	@find . \( -path ./.venv -o -path ./macos_app/build -o -path ./windows_app/build \) -prune -o \
		-type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
	@echo "Python artifacts removed"

install: check-venv install-puikit
	@echo "Installing XeFM..."
	@$(PIP) install .

uninstall: check-venv
	@echo "Uninstalling XeFM..."
	@$(PIP) uninstall -y xefm
	@echo "Uninstalling PuiKit..."
	@$(PIP) uninstall -y puikit

dev-install: check-venv install-puikit
	@echo "Installing XeFM in development mode..."
	@$(PIP) install -e .

install-config:
	@echo "Installing default configuration to ~/.xefm/config.py..."
	@mkdir -p ~/.xefm
	@if [ -f ~/.xefm/config.py ]; then \
		echo "Warning: ~/.xefm/config.py already exists"; \
		echo "This will overwrite your existing configuration!"; \
		read -p "Continue? [y/N] " confirm; \
		if [ "$${confirm}" = "y" ] || [ "$${confirm}" = "Y" ]; then \
			cp xefm/_config.py ~/.xefm/config.py; \
			echo "Configuration installed successfully"; \
			echo "Your old config has been overwritten"; \
		else \
			echo "Installation cancelled"; \
			exit 1; \
		fi; \
	else \
		cp xefm/_config.py ~/.xefm/config.py; \
		echo "Configuration installed successfully"; \
	fi

lint: check-venv
	@echo "Running linting..."
	@$(PYTHON) -m flake8 xefm/ --max-line-length=120 --ignore=E501,W503 || echo "flake8 not available"
	@$(PYTHON) -m pylint xefm/ || echo "pylint not available"

format: check-venv
	@echo "Formatting code..."
	@$(PYTHON) -m black xefm/ --line-length=120 || echo "black not available"
	@$(PYTHON) -m isort xefm/ || echo "isort not available"

demo: check-venv
	@echo "Running XeFM demo..."
	@cd test && $(PYTHON) demo_delete_feature.py

# ============================================================================
# Packaging / Release Targets
# ============================================================================
# Releasing is one target per artifact, each independently runnable:
#
#   make tag VERSION=x.y.z     any machine  bump __version__, commit, tag, push
#   make release-github        any machine  open the GitHub Release at that tag
#   make release-whl           any machine  sdist + wheel -> PyPI (+ the Release)
#   make release-macos-dmg     macOS        XeFM-<ver>-macos.dmg  -> the Release
#   make release-windows-zip   Windows      XeFM-<ver>-win64.zip  -> the Release
#   make release-windows-msix  Windows      XeFM-<ver>.0-x64.msix -> the Microsoft Store
#   make release-status        any machine  what has landed so far
#
# Order matters only twice: `tag` first (everything else names the tag it
# creates), then `release-github` (the three release-<artifact> targets upload
# into the Release it opens). Those three are peers — they run in any order, on
# their own machine, minutes or days later, because the artifacts build on
# three different platforms and no one machine can produce them all. Each one
# builds its artifact if it is missing, re-checks the preconditions, and
# uploads with --clobber, so re-running any of them is safe.
#
# release-windows-msix is the odd one out: it publishes to the Microsoft Store,
# not the GitHub Release, so it needs no `release-github` — and it always
# repacks rather than reusing an existing .msix, since the Store rejects a
# resubmitted package version anyway (each submission must be strictly higher).
#
# The version's single source of truth is xefm/__init__.py's __version__;
# pyproject.toml derives it (dynamic version = attr), `xefm --version`
# re-exports it, and the macOS/Windows bundle builders extract that same
# literal. XEFM_VERSION below reads it the same way, so every release-* target
# acts on the release the checkout is actually on — only `tag` takes a
# VERSION=. Override it on the others to target a different release (e.g.
# re-uploading an asset for an older tag).
XEFM_VERSION := $(if $(VERSION),$(VERSION),$(shell sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' xefm/__init__.py 2>/dev/null | head -1))

# Guards shared by the release-* targets, kept in one place so they cannot
# drift into checking different things. Used as $(call ...) inside a recipe;
# each expands to a single multi-line shell test.
#
# check_gh:             a resolvable version and a usable `gh`.
# check_release_exists: the above, plus the GitHub Release to upload into.
define check_gh
test -n "$(XEFM_VERSION)" || { echo "ERROR: could not determine version; pass VERSION=x.y.z"; exit 1; }; \
command -v gh >/dev/null 2>&1 || { echo "ERROR: 'gh' not found. Install the GitHub CLI first."; exit 1; }; \
gh auth status >/dev/null 2>&1 || { echo "ERROR: 'gh' is not authenticated. Run 'gh auth login'."; exit 1; }
endef

define check_release_exists
$(check_gh); \
gh release view v$(XEFM_VERSION) >/dev/null 2>&1 || { \
	echo "ERROR: GitHub Release v$(XEFM_VERSION) does not exist."; \
	echo "       Open it first with 'make release-github'."; \
	exit 1; \
}
endef

# --- tag: the one target that changes the version ---------------------------
# Usage: make tag VERSION=1.0.1
#
# Pure version + git work: bump __version__, commit, tag, push. It publishes
# nothing and needs no `gh` and no PyPI token — the release-* targets do the
# publishing, each with its own toolchain and credentials.
#
# bump_version.py rewrites the single __version__ line, which is why the commit
# stages __init__.py rather than pyproject.toml.
#
# release_preflight.py runs FIRST and aborts before any mutation if the tree is
# dirty, the version is stale, or the tag exists — so a failed precondition
# never leaves a half-cut release. The test suite must pass before anything is
# built.
#
# `make build` runs before the pushes purely as a gate: it proves the sdist and
# wheel build and pass `twine check` while the tag is still local and
# retractable. It also leaves dist/ ready for `make release-whl`.
tag: check-venv
	@test -n "$(VERSION)" || { echo "ERROR: set VERSION, e.g. make tag VERSION=1.0.1"; exit 1; }
	$(PYTHON) tools/release_preflight.py "$(VERSION)"
	@# Gates on pytest directly rather than on `make test`: that target tolerates a
	@# missing pytest (`|| echo ...`) and would let an unrun suite pass silently.
	$(PYTHON) -m pytest test
	$(PYTHON) tools/bump_version.py "$(VERSION)"
	git add xefm/__init__.py
	git commit -m "Releasing $(VERSION)"
	git tag -a v$(VERSION) -m "$(VERSION)"
	$(MAKE) build
	git push
	git push origin v$(VERSION)
	@echo ""
	@echo "Tagged $(VERSION): commit + tag v$(VERSION), both pushed ✓"
	@echo "Next:"
	@echo "  make release-github          # open the GitHub Release at v$(VERSION)"
	@echo "  make release-whl             # here:       sdist + wheel -> PyPI"
	@echo "  make release-macos-dmg       # on macOS:   XeFM-$(VERSION)-macos.dmg"
	@echo "  make release-windows-zip     # on Windows: XeFM-$(VERSION)-win64.zip"
	@echo "  make release-windows-msix    # on Windows: submit the MSIX to the Microsoft Store"

# --- release-github: open the Release the artifacts upload into -------------
# Reads the version from the checkout, so the usual path is `make tag` then
# `make release-github` with no arguments. --verify-tag refuses to invent a tag
# GitHub does not already have, which is why `tag` pushes it first.
#
# Idempotent on purpose: an existing Release is reported and left alone rather
# than erroring, so re-running the pipeline from the top costs nothing.
release-github:
	@$(call check_gh)
	@git ls-remote --exit-code --tags origin "v$(XEFM_VERSION)" >/dev/null 2>&1 || { \
		echo "ERROR: tag v$(XEFM_VERSION) is not on origin."; \
		echo "       Push it with 'make tag VERSION=$(XEFM_VERSION)' (or 'git push origin v$(XEFM_VERSION)')."; \
		exit 1; \
	}
	@if gh release view v$(XEFM_VERSION) >/dev/null 2>&1; then \
		echo "GitHub Release v$(XEFM_VERSION) already exists; leaving it as is."; \
	else \
		gh release create v$(XEFM_VERSION) --title "v$(XEFM_VERSION)" --generate-notes --verify-tag && \
		echo "Opened GitHub Release v$(XEFM_VERSION) ✓"; \
	fi

# --- The Python distributions -----------------------------------------------
# `build` and `twine` are release-time tooling, not needed to run or develop
# XeFM, so they are installed on demand here rather than sitting in
# requirements.txt. Invoked as `python -m ...` (not the venv's console scripts)
# so the same recipe works on Windows, where those scripts live in Scripts/ and
# end in .exe.
# The PyPI long description (README.pypi.md) is generated here on the fly and
# never committed: README.md keeps repo-relative image/link targets for GitHub,
# and gen_pypi_readme.py rewrites them to version-tagged GitHub URLs so they
# render on the PyPI page. `twine check --strict` promotes twine's
# "description missing" warning to a failure, so a build that somehow skipped
# generation can never upload an empty description.

build: check-venv
	@echo "Building sdist + wheel..."
	@$(PIP) install --quiet build twine
	@rm -rf dist build xefm.egg-info
	@$(PYTHON) tools/gen_pypi_readme.py
	@$(PYTHON) -m build
	@$(PYTHON) -m twine check --strict dist/*

# The safe rehearsal for release-whl: same build and upload path, but a bad
# TestPyPI version costs nothing. Deliberately NOT named release-* — it needs
# neither a tag nor a GitHub Release and publishes nothing permanent, so it is
# a pre-release smoke test rather than a step of the pipeline. Depends on
# `build` (not on the file target below) so it always builds fresh.
publish-testpypi: build
	@$(PYTHON) -m twine upload -r testpypi dist/*

# The filenames setuptools gives the sdist + wheel, derived from the same
# version literal as XEFM_VERSION. Naming them explicitly (rather than globbing
# dist/*) means a stale artifact left from an earlier version can never be
# swept into an upload.
PYPI_SDIST := dist/xefm-$(XEFM_VERSION).tar.gz
PYPI_WHEEL := dist/xefm-$(XEFM_VERSION)-py3-none-any.whl

# File target so release-whl builds the distributions on demand when they are
# missing (e.g. after `make clean`), the same way release-macos-dmg and
# release-windows-zip build their artifacts. `make build` wipes dist/ and
# writes both files, so the sdist alone is enough of a prerequisite to trigger
# it; the recipe below then asserts the wheel landed too. Existing artifacts are
# NOT rebuilt — publishing the exact bytes that were verified is the point.
$(PYPI_SDIST):
	@echo "Python distributions for $(XEFM_VERSION) not found; building them first..."
	@$(MAKE) build

# --- release-whl: publish the Python distributions --------------------------
# Uploads BOTH the sdist and the wheel — the target is named for the headline
# artifact, not the whole payload.
#
# A PyPI version can never be re-uploaded, so this refuses to publish a build
# that is not the tagged one: HEAD must sit exactly on vX.Y.Z. `make tag`
# leaves the checkout there, so the usual path is `make tag` then
# `make release-whl`; publishing an older release means checking out its tag
# first. When tagging and publishing were one recipe that held by construction
# — this check is what keeps it true now that they are separate targets.
#
# Also attaches both files to the GitHub Release, so the release page lists
# every artifact. --clobber replaces same-named assets on a re-run.
# Prereqs: a [pypi] token in ~/.pypirc and an authenticated `gh`.
release-whl: $(PYPI_SDIST)
	@$(call check_release_exists)
	@git rev-parse -q --verify "v$(XEFM_VERSION)^{commit}" >/dev/null || { \
		echo "ERROR: tag v$(XEFM_VERSION) not found locally. Cut it with 'make tag VERSION=$(XEFM_VERSION)' or fetch it."; \
		exit 1; \
	}
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse "v$(XEFM_VERSION)^{commit}")" || { \
		echo "ERROR: HEAD is not at tag v$(XEFM_VERSION); the upload would not match the tag."; \
		echo "       Check the tag out first: git checkout v$(XEFM_VERSION)"; \
		exit 1; \
	}
	@# Both files, not just the sdist that triggered the build: a VERSION= override
	@# that disagrees with __version__ builds different filenames entirely, and
	@# this is where that shows up as a clear error instead of a twine traceback.
	@for f in "$(PYPI_SDIST)" "$(PYPI_WHEEL)"; do \
		test -f "$$f" || { echo "ERROR: $$f missing; run 'make build' from a checkout at v$(XEFM_VERSION)."; exit 1; }; \
	done
	@echo "Uploading $(notdir $(PYPI_SDIST)) + $(notdir $(PYPI_WHEEL)) to PyPI..."
	$(PYTHON) -m twine upload "$(PYPI_SDIST)" "$(PYPI_WHEEL)"
	gh release upload v$(XEFM_VERSION) "$(PYPI_SDIST)" "$(PYPI_WHEEL)" --clobber
	@echo "Published $(XEFM_VERSION) to PyPI and attached both distributions to release v$(XEFM_VERSION) ✓"

# --- release-status: read-only progress check -------------------------------
# The pipeline spans three machines, so this is the one place to see which
# artifacts have landed for the version the checkout is on.
release-status:
	@test -n "$(XEFM_VERSION)" || { echo "ERROR: could not determine version; pass VERSION=x.y.z"; exit 1; }
	@echo "Release v$(XEFM_VERSION):"
	@# Asset names only: gh renders JSON numbers in Go's default float format, so
	@# {{.size}} would print sizes as 8.8917854e+07.
	@gh release view v$(XEFM_VERSION) --json assets \
		--template '{{range .assets}}  GitHub asset: {{.name}}{{"\n"}}{{end}}' \
		2>/dev/null || echo "  (no GitHub Release yet — run 'make release-github')"
	@$(PYTHON) -c "import json,urllib.request as u; \
		v='$(XEFM_VERSION)'; \
		d=json.load(u.urlopen('https://pypi.org/pypi/xefm/json')); \
		print('  PyPI: ' + ('published' if v in d['releases'] else 'NOT published'))" \
		2>/dev/null || echo "  PyPI: unknown (needs .venv and network access)"

# ============================================================================
# macOS App Bundle Targets
# ============================================================================

macos-app:
	@echo "Building macOS application bundle..."
	@cd macos_app && ./build.sh

# Everything macos_app/build/ holds, which is more than `macos-app` wrote: the
# .app and its compiled executable, plus the DMG from macos-dmg and any mount
# point install-macos-dmg left. Hence clean-macos, not clean-macos-app.
clean-macos:
	@echo "Cleaning macOS build artifacts (.app, executable, DMG)..."
	@rm -rf macos_app/build/
	@echo "macOS build artifacts removed"

# --- App icons --------------------------------------------------------------
# The SVG masters in tools/icon/ are the single source of truth. Rendering needs
# AppKit's SVG support, so these targets are macOS-only - the resulting .icns/.ico/
# .png assets are committed, and the Windows build consumes them as-is.

icons: check-venv
	@echo "Regenerating icon assets from tools/icon/*.svg..."
	@$(PYTHON) tools/make_icons.py
	@echo "Done. Run 'make macos-refresh-icon' to see the new icon in Finder/Dock."

icons-check: check-venv
	@$(PYTHON) tools/make_icons.py --check

macos-refresh-icon:
	@echo "Refreshing macOS icon cache..."
	@if [ ! -d "macos_app/build/XeFM.app" ]; then \
		echo "Warning: XeFM.app not found at macos_app/build/XeFM.app"; \
	else \
		touch macos_app/build/XeFM.app; \
		echo "Touched app bundle to invalidate cache"; \
	fi
	@echo "Clearing system icon cache (may require password)..."
	@sudo rm -rf /Library/Caches/com.apple.iconservices.store 2>/dev/null || echo "Skipped system cache (no sudo access)"
	@rm -rf ~/Library/Caches/com.apple.iconservices 2>/dev/null || true
	@echo "Restarting Dock and Finder..."
	@killall Dock 2>/dev/null || true
	@killall Finder 2>/dev/null || true
	@echo "Icon cache cleared successfully"
	@echo "The new icon should appear now. If the app is running, quit and relaunch it."

macos-dmg: macos-app
	@echo "Creating DMG installer..."
	@cd macos_app && ./create_dmg.sh
	@echo "DMG installer created successfully"

# --- release-macos-dmg: publish the macOS DMG -------------------------------
# create_dmg.sh derives the DMG's filename from the same xefm/__init__.py
# literal XEFM_VERSION reads (defined in the Packaging / Release section), so
# the two always agree without a second place to bump.
#
# Filename mirrors create_dmg.sh's own naming (XeFM-<version>-macos.dmg), the
# same platform-suffixed shape as WINDOWS_ZIP below.
MACOS_DMG := macos_app/build/XeFM-$(XEFM_VERSION)-macos.dmg

# File target so `release-macos-dmg` builds the DMG on demand when it is missing
# (e.g. after 'make clean-macos') instead of failing at the upload. An
# existing DMG is NOT rebuilt, so re-uploading stays fast and never re-runs
# notarization; run 'make macos-dmg' to force a fresh one.
$(MACOS_DMG):
	@echo "DMG not found at $@; building it first..."
	@$(MAKE) macos-dmg

# Attach the signed/notarized DMG to the GitHub Release for this version. Kept
# separate from `macos-dmg` on purpose: building a DMG is a local operation you
# may do many times, uploading publishes it. The Release must already exist
# ('make release-github') — this only adds the macOS asset, which no other
# machine can build. --clobber replaces an asset of the same name, so
# re-uploading a rebuilt DMG supersedes the previous one rather than erroring.
# Prereq: an authenticated `gh` (gh auth login).
release-macos-dmg: $(MACOS_DMG)
	@$(call check_release_exists)
	@echo "Uploading $(MACOS_DMG) to GitHub Release v$(XEFM_VERSION)..."
	gh release upload v$(XEFM_VERSION) "$(MACOS_DMG)" --clobber
	@echo "Uploaded $(notdir $(MACOS_DMG)) to release v$(XEFM_VERSION) ✓"

# --- install-macos-dmg: install what we actually ship ------------------------
# Installs from the DMG rather than from macos_app/build/XeFM.app on purpose:
# the DMG is the exact bytes a user downloads, signed and stapled as a
# container, so a packaging, signing or notarization mistake surfaces here
# instead of after the release. Builds the DMG first if it is missing.
#
# /Applications is group-writable by admin users, so no sudo is needed; the
# writability check below says so plainly when it is not.
# Override the destination with MACOS_INSTALL_DIR=~/Applications.
MACOS_INSTALL_DIR ?= /Applications

# zsh does not expand the tilde in `make MACOS_INSTALL_DIR=~/Applications`
# (that needs magic_equal_subst, off by default), so it arrives here intact and
# would fail the existence check below with a confusing message. `override` is
# required: a command-line assignment otherwise wins over this one.
override MACOS_INSTALL_DIR := $(patsubst ~/%,$(HOME)/%,$(MACOS_INSTALL_DIR))

# Mounted inside macos_app/build/ (gitignored, and where create_dmg.sh already
# stages) rather than /Volumes, so a stale mount point can never collide with a
# DMG the user opened in Finder.
MACOS_DMG_MOUNT := macos_app/build/dmg_mount

install-macos-dmg: $(MACOS_DMG)
	@test -d "$(MACOS_INSTALL_DIR)" || { echo "ERROR: $(MACOS_INSTALL_DIR) does not exist."; exit 1; }
	@test -w "$(MACOS_INSTALL_DIR)" || { \
		echo "ERROR: $(MACOS_INSTALL_DIR) is not writable."; \
		echo "       Re-run under sudo, or install per-user with MACOS_INSTALL_DIR=~/Applications."; \
		exit 1; \
	}
	@rm -rf "$(MACOS_DMG_MOUNT)"
	@mkdir -p "$(MACOS_DMG_MOUNT)"
	@echo "Mounting $(notdir $(MACOS_DMG))..."
	@# One shell line so the trap that unmounts survives to the end, however the
	@# copy turns out — an orphaned mount would break every later run.
	@hdiutil attach "$(MACOS_DMG)" -nobrowse -readonly -quiet -mountpoint "$(MACOS_DMG_MOUNT)" || { \
		echo "ERROR: could not mount $(MACOS_DMG)"; rmdir "$(MACOS_DMG_MOUNT)" 2>/dev/null; exit 1; \
	}; \
	trap 'hdiutil detach "$(MACOS_DMG_MOUNT)" -quiet >/dev/null 2>&1' EXIT; \
	test -d "$(MACOS_DMG_MOUNT)/XeFM.app" || { echo "ERROR: XeFM.app not found inside the DMG"; exit 1; }; \
	echo "Installing XeFM.app to $(MACOS_INSTALL_DIR)..."; \
	rm -rf "$(MACOS_INSTALL_DIR)/XeFM.app"; \
	cp -R "$(MACOS_DMG_MOUNT)/XeFM.app" "$(MACOS_INSTALL_DIR)/"
	@rmdir "$(MACOS_DMG_MOUNT)" 2>/dev/null || true
	@echo "Installed $(MACOS_INSTALL_DIR)/XeFM.app ✓"

# Removes what install-macos-dmg put there — the app bundle only, never the
# containing directory. No DMG prerequisite on purpose: uninstalling must work
# after 'make clean-macos', when building a DMG just to delete an app would
# be absurd. Set the same MACOS_INSTALL_DIR you installed with.
#
# An absent install is reported, not an error: re-running an uninstall should
# converge on "not installed" rather than fail the second time.
uninstall-macos-dmg:
	@if [ ! -e "$(MACOS_INSTALL_DIR)/XeFM.app" ]; then \
		echo "Not installed: $(MACOS_INSTALL_DIR)/XeFM.app"; \
	elif [ ! -w "$(MACOS_INSTALL_DIR)" ]; then \
		echo "ERROR: $(MACOS_INSTALL_DIR) is not writable."; \
		echo "       Re-run under sudo, or pass the MACOS_INSTALL_DIR you installed with."; \
		exit 1; \
	else \
		rm -rf "$(MACOS_INSTALL_DIR)/XeFM.app"; \
		echo "Removed $(MACOS_INSTALL_DIR)/XeFM.app ✓"; \
	fi

# ============================================================================
# Windows App Bundle Targets
# ============================================================================
# Delegates to windows_app/build.ps1 (PowerShell). These targets are only
# meaningful on Windows; on other platforms PowerShell won't be present.

# The built bundle's launcher; its presence marks a complete bundle. Targets
# that only *consume* the bundle (install, msix) depend on this file target so it
# is built on demand if missing (e.g. after 'make clean-windows') instead of
# failing deep inside a packaging script.
#
# It also rebuilds when any bundled input is newer, which is what stops a
# packaging target from silently shipping a stale .exe -- the failure mode that
# once put a pre-icon-update launcher inside an .msix whose tiles were current.
# 'make windows-app' still forces an unconditional rebuild.
WINDOWS_APP_BUNDLE := windows_app/build/XeFM/XeFM.exe

# Inputs compiled or copied into the bundle. XeFM.ico is here because it is
# compiled into XeFM.exe as a resource, so an icon change has to reach the .exe.
#
# All wildcarded so a missing optional input (XeFM.ico is generated by
# tools/make_icons.py and need not exist -- build.ps1 falls back to make_icon.py)
# expands to nothing rather than a "no rule to make target" error.
#
# PuiKit is deliberately absent: it ships in the bundle but comes from an
# editable install outside this tree (../puikit), so changes there still need an
# explicit 'make windows-app'.
WINDOWS_APP_SOURCES := $(wildcard windows_app/src/*.c) \
                       $(wildcard windows_app/resources/XeFM.rc) \
                       $(wildcard windows_app/resources/XeFM.manifest) \
                       $(wildcard windows_app/resources/XeFM.ico) \
                       $(wildcard xefm/*.py) \
                       $(wildcard xefm/tools/*.py)

$(WINDOWS_APP_BUNDLE): $(WINDOWS_APP_SOURCES)
	@echo "Windows app bundle missing or stale; building it first..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1

windows-app:
	@echo "Building Windows application bundle..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1

# Named for the artifact it produces, matching macos-dmg on the macOS side.
windows-zip:
	@echo "Building Windows application bundle (+ zip)..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Zip

# --- release-windows-zip: publish the Windows portable zip ------------------
# The portable zip is the artifact end users can actually install today: it is
# unsigned, but a zip carries no signature requirement, so Windows only shows
# the Mark-of-the-Web / SmartScreen prompt documented in
# doc/DESKTOP_MODE_GUIDE.md. The .msix is deliberately NOT published here --
# Add-AppxPackage refuses an unsigned package, so the unsigned .msix is only
# useful as a Partner Center submission (Microsoft re-signs it during
# certification), never as a download.
#
# Filename mirrors build.ps1's own naming (XeFM-<version>-win64.zip), derived
# from the same version literal as XEFM_VERSION above, so the two cannot drift.
WINDOWS_ZIP := windows_app/build/XeFM-$(XEFM_VERSION)-win64.zip

# File target so the upload builds the zip on demand when it is missing (e.g.
# after 'make clean-windows') instead of failing at the upload. An existing
# zip is NOT rebuilt; run 'make windows-zip' to force a fresh one.
$(WINDOWS_ZIP):
	@echo "Windows zip not found at $@; building it first..."
	@$(MAKE) windows-zip

# Attach the portable zip to the GitHub Release for this version. Kept separate
# from 'windows-zip' on purpose: building is local, uploading publishes. The
# Release must already exist ('make release-github'). --clobber replaces an
# asset of the same name, so re-uploading a rebuilt zip supersedes the previous
# one rather than erroring.
# Prereq: an authenticated `gh` (gh auth login).
release-windows-zip: $(WINDOWS_ZIP)
	@$(call check_release_exists)
	@echo "Uploading $(WINDOWS_ZIP) to GitHub Release v$(XEFM_VERSION)..."
	gh release upload v$(XEFM_VERSION) "$(WINDOWS_ZIP)" --clobber
	@echo "Uploaded $(notdir $(WINDOWS_ZIP)) to release v$(XEFM_VERSION) ✓"

# --- install-windows-zip: install what we actually ship ---------------------
# The counterpart of install-macos-dmg: expands the portable zip a user would
# download, rather than copying windows_app/build/XeFM/, so a truncated or
# incomplete zip is caught here instead of by the first person to download it.
# Builds the zip first if it is missing.
#
# Per-user by default (%LOCALAPPDATA%\Programs\XeFM), so no UAC prompt and no
# elevated shell — the same "no password needed" story /Applications gives on
# macOS. Override with WINDOWS_INSTALL_DIR='C:\Program Files\XeFM', which does
# need an elevated shell.
#
# The expand/replace/verify logic lives in install_zip.ps1 rather than inline
# here: an inline -Command would have to survive both make's and sh's expansion
# before PowerShell sees it, and every bare $var in it would be eaten by the
# shell. Same reason every other Windows target delegates to a .ps1.
WINDOWS_INSTALL_DIR ?=

install-windows-zip: $(WINDOWS_ZIP)
	@echo "Installing XeFM from $(notdir $(WINDOWS_ZIP))..."
	@powershell -ExecutionPolicy Bypass -File windows_app/install_zip.ps1 \
		-Zip "$(WINDOWS_ZIP)" $(if $(WINDOWS_INSTALL_DIR),-InstallDir "$(WINDOWS_INSTALL_DIR)")

# Removes what install-windows-zip put there. No zip prerequisite on purpose —
# same reason as uninstall-macos-dmg: deleting an install must not depend on
# being able to rebuild the artifact it came from. install_zip.ps1 -Uninstall
# resolves the default location the same way the install did, so the two cannot
# disagree about what to remove. Set the same WINDOWS_INSTALL_DIR you used.
uninstall-windows-zip:
	@powershell -ExecutionPolicy Bypass -File windows_app/install_zip.ps1 \
		-Uninstall $(if $(WINDOWS_INSTALL_DIR),-InstallDir "$(WINDOWS_INSTALL_DIR)")

# Everything the Windows build machinery generates: build/ (the bundle, the zip,
# the .msix, its staging dir and the throwaway .pfx/.cer) plus resources/Assets/,
# the Store tiles make_store_assets.py renders from the committed PNG masters —
# the one thing the MSIX build writes outside build/. Removing the tiles is also
# how you force regeneration, since build_msix.ps1 -SkipAssets reuses them.
#
# Plain rm rather than `build.ps1 -Clean`, which does exactly `Remove-Item
# -Recurse -Force build`: identical effect, but no PowerShell, so this works on
# any OS and `make clean` does not fail on macOS or Linux.
clean-windows:
	@echo "Cleaning Windows build artifacts (bundle, zip, .msix, certs, tiles)..."
	@rm -rf windows_app/build windows_app/resources/Assets
	@echo "Windows build artifacts removed"

# The CPython embeddable zips build.ps1 downloads on the first build, kept so
# later builds do not re-download ~10MB. Excluded from `clean` for that reason:
# cleaning a build should never cost you a download.
clean-windows-cache:
	@echo "Removing windows_app/.cache/ (downloaded CPython embeddable zips)..."
	@rm -rf windows_app/.cache
	@echo "Download cache removed; the next Windows build will re-download"

# --- MSIX (Microsoft Store / winget) packaging, PROTOTYPE ------------------
# Wraps the built bundle into an .msix; builds the bundle first if it is missing.
#
# UNSIGNED by default, because that is the form Partner Center wants: Microsoft
# re-signs the package during certification, which is what makes Store signing
# free and warning-free (doc/dev/WINDOWS_STORE_MSIX_PLAN.md 0, 5). Self-signing
# is only useful for sideloading on the dev box, so it is opt-in via SIGN=1 --
# and 'install-windows-msix' below passes it for you.
#
# Note the identity values are still Partner Center placeholders; a real
# submission also needs -IdentityName / -Publisher / -PublisherDisplayName
# (see WINDOWS_STORE_MSIX_PLAN.md 2a).
windows-msix: $(WINDOWS_APP_BUNDLE)
	@echo "Packaging Windows app as MSIX$(if $(SIGN), (self-signed, local testing), (unsigned, Store submission))..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 $(if $(SIGN),-Sign)

# Trust the self-signed cert (self-elevates via UAC) then install per-user.
#
# Always re-packs with -Sign first rather than reusing whatever .msix is on
# disk: both this and 'windows-msix' write the same
# build\XeFM-<version>-x64.msix, so an unsigned pack may have overwritten a
# signed one. Add-AppxPackage cannot install an unsigned package, so packing
# here is what guarantees the artifact it installs is actually signed.
install-windows-msix: $(WINDOWS_APP_BUNDLE)
	@echo "Packaging + self-signing MSIX for local install..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Sign
	@echo "Installing MSIX package locally..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Install

# Removes the package (per-user) and the throwaway signing cert; untrusting the
# machine-store cert self-elevates via UAC.
uninstall-windows-msix:
	@echo "Removing installed MSIX package and throwaway cert..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Uninstall

# --- release-windows-msix: submit the MSIX to the Microsoft Store -----------
# Packs first via the 'windows-msix' target, not the file: signed and unsigned
# packs write the same path, and Partner Center takes only the UNSIGNED form,
# so repacking is what guarantees the upload is not a leftover self-signed
# .msix from 'install-windows-msix'. The msstore CLI then uploads the package,
# creates a new submission carrying the listing metadata of the previous one,
# and commits it -- certification proceeds exactly as for a browser submission.
#
# One-time setup, both outside this Makefile (doc/dev/WINDOWS_STORE_MSIX_PLAN.md):
#   - the msstore CLI, configured once with the Partner Center API credentials
#     ('msstore reconfigure'; they persist in Windows Credential Manager)
#   - XEFM_STORE_PRODUCT_ID in windows_app/store.env: the listing's 9N...
#     Store product ID (see store.env.example)
#
# Poll certification afterwards with: msstore submission status <product id>
#
# Mirrors WINDOWS_ZIP: build_msix.ps1 derives its version from the same
# __version__ literal as XEFM_VERSION, plus the Store-required ".0" revision,
# so this is the path the pack above just wrote.
WINDOWS_MSIX := windows_app/build/XeFM-$(XEFM_VERSION).0-x64.msix

release-windows-msix: windows-msix
	@command -v msstore >/dev/null 2>&1 || { \
		echo "ERROR: msstore CLI not found on PATH."; \
		echo "       Install: winget install \"Microsoft Store Developer CLI\", then run 'msstore reconfigure'."; \
		exit 1; }
	@test -f windows_app/store.env || { \
		echo "ERROR: windows_app/store.env not found."; \
		echo "       Copy windows_app/store.env.example to store.env and fill it in."; \
		exit 1; }
	@. ./windows_app/store.env; \
	test -n "$$XEFM_STORE_PRODUCT_ID" || { \
		echo "ERROR: XEFM_STORE_PRODUCT_ID is not set in windows_app/store.env."; \
		echo "       Add the listing's 9N... product ID (see store.env.example)."; \
		exit 1; }; \
	test -f "$(WINDOWS_MSIX)" || { \
		echo "ERROR: $(WINDOWS_MSIX) missing after packing."; \
		exit 1; }; \
	echo "Submitting $(WINDOWS_MSIX) to the Microsoft Store ($$XEFM_STORE_PRODUCT_ID)..."; \
	msstore publish "$(WINDOWS_MSIX)" -id "$$XEFM_STORE_PRODUCT_ID"

