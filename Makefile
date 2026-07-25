# XeFM Makefile

.PHONY: help run run-gui run-web test test-quick clean install uninstall dev-install lint format demo build publish-testpypi tag release-github release-whl release-macos-dmg release-windows-zip release-status icons icons-check macos-app macos-app-clean macos-app-install macos-refresh-icon macos-dmg windows-app windows-app-clean windows-zip windows-app-install windows-msix windows-msix-install windows-msix-uninstall install-config venv venv-clean check-venv install-puikit

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
	@echo "  venv-clean     - Remove the .venv directory"
	@echo "  install-puikit - (Re)install PuiKit: editable if PUIKIT_DIR set, else from PyPI"
	@echo "  run            - Run XeFM (terminal); LEFT=/RIGHT= set startup dirs"
	@echo "  run-gui        - Run XeFM in a native macOS GUI window"
	@echo "  run-web        - Run XeFM in a web browser (web backend)"
	@echo "  test           - Run all tests"
	@echo "  test-quick     - Run quick verification tests"
	@echo "  clean          - Clean up temporary files"
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
	@echo "  macos-app          - Build native macOS application bundle"
	@echo "  macos-app-clean    - Clean macOS app build artifacts"
	@echo "  macos-app-install  - Install XeFM.app to Applications folder"
	@echo "  macos-refresh-icon - Refresh macOS icon cache (after icon changes)"
	@echo "  macos-dmg          - Create DMG installer for distribution"
	@echo "                       (publish it with 'make release-macos-dmg')"
	@echo ""
	@echo "Windows App Bundle:"
	@echo "  windows-app            - Build self-contained Windows application bundle"
	@echo "  windows-app-clean      - Clean Windows app build artifacts"
	@echo "  windows-app-install    - Install the built bundle to Program Files (elevates via UAC)"
	@echo "  windows-zip            - Build the bundle and zip it for distribution"
	@echo "                           (publish it with 'make release-windows-zip')"
	@echo "  windows-msix           - Package the bundle as an unsigned MSIX (Store submission;"
	@echo "                           SIGN=1 to self-sign for local testing instead)"
	@echo "  windows-msix-install   - Pack + self-sign, trust cert (elevates), install per-user"
	@echo "  windows-msix-uninstall - Remove the MSIX package + throwaway signing cert"
	@echo ""
	@echo "Examples:"
	@echo "  make run                        # Run XeFM in the terminal"
	@echo "  make run-gui                    # Run XeFM in a macOS GUI window"
	@echo "  make run-web                    # Run XeFM in a web browser"
	@echo "  make run LEFT=./xefm RIGHT=./doc # Run with custom startup directories"
	@echo "  make install-config             # Install/update user config file"
	@echo "  make macos-app                  # Build macOS app bundle"
	@echo "  make macos-app-install          # Install to /Applications"
	@echo "  make macos-dmg                  # Create DMG installer"
	@echo "  make tag VERSION=1.0.1          # Bump the version, commit, tag and push"
	@echo "  make release-github             # Open the GitHub Release for that tag"
	@echo "  make release-whl                # Publish its sdist + wheel to PyPI"
	@echo "  make release-macos-dmg          # Upload the DMG to the GitHub Release"
	@echo "  make release-windows-zip        # Upload the Windows zip to the GitHub Release"

venv:
	@if [ -d .venv ]; then \
		echo ".venv already exists. Run 'make venv-clean' first to recreate it."; \
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
			$(PIP) install --force-reinstall --no-deps "puikit>=1.0"; \
		fi; \
	fi

venv-clean:
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

test-quick: check-venv
	@echo "Running quick verification tests..."
	@cd test && PYTHONPATH=.. $(PYTHON) test_cursor_movement.py
	@cd test && PYTHONPATH=.. $(PYTHON) test_delete_feature.py
	@cd test && PYTHONPATH=.. $(PYTHON) test_integration.py

clean:
	@echo "Cleaning up..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf build/ dist/ 2>/dev/null || true

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

build: check-venv
	@echo "Building sdist + wheel..."
	@$(PIP) install --quiet build twine
	@rm -rf dist build xefm.egg-info
	@$(PYTHON) -m build
	@$(PYTHON) -m twine check dist/*

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

macos-app-clean:
	@echo "Cleaning macOS app build artifacts..."
	@rm -rf macos_app/build/
	@echo "Build artifacts removed"

macos-app-install:
	@echo "Installing XeFM.app to Applications..."
	@if [ ! -d "macos_app/build/XeFM.app" ]; then \
		echo "Error: XeFM.app not found. Run 'make macos-app' first."; \
		exit 1; \
	fi
	@echo "Choose installation location:"
	@echo "  1) /Applications (system-wide, requires sudo)"
	@echo "  2) ~/Applications (user-only)"
	@read -p "Enter choice [1-2]: " choice; \
	case $$choice in \
		1) \
			echo "Installing to /Applications..."; \
			sudo cp -R macos_app/build/XeFM.app /Applications/; \
			echo "XeFM.app installed to /Applications"; \
			;; \
		2) \
			echo "Installing to ~/Applications..."; \
			mkdir -p ~/Applications; \
			cp -R macos_app/build/XeFM.app ~/Applications/; \
			echo "XeFM.app installed to ~/Applications"; \
			;; \
		*) \
			echo "Invalid choice. Installation cancelled."; \
			exit 1; \
			;; \
	esac

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
# (e.g. after 'make macos-app-clean') instead of failing at the upload. An
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

# ============================================================================
# Windows App Bundle Targets
# ============================================================================
# Delegates to windows_app/build.ps1 (PowerShell). These targets are only
# meaningful on Windows; on other platforms PowerShell won't be present.

# The built bundle's launcher; its presence marks a complete bundle. Targets
# that only *consume* the bundle (install, msix) depend on this file target so it
# is built on demand if missing (e.g. after 'make windows-app-clean') instead of
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
# after 'make windows-app-clean') instead of failing at the upload. An existing
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

windows-app-clean:
	@echo "Cleaning Windows app build artifacts..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Clean

# Install the built bundle to Program Files (override dir with INSTALLDIR=...).
# Self-elevates via UAC; builds the bundle first if it is missing.
windows-app-install: $(WINDOWS_APP_BUNDLE)
	@echo "Installing Windows application bundle..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Install $(if $(INSTALLDIR),-InstallDir "$(INSTALLDIR)")

# --- MSIX (Microsoft Store / winget) packaging, PROTOTYPE ------------------
# Wraps the built bundle into an .msix; builds the bundle first if it is missing.
#
# UNSIGNED by default, because that is the form Partner Center wants: Microsoft
# re-signs the package during certification, which is what makes Store signing
# free and warning-free (doc/dev/WINDOWS_STORE_MSIX_PLAN.md 0, 5). Self-signing
# is only useful for sideloading on the dev box, so it is opt-in via SIGN=1 --
# and 'windows-msix-install' below passes it for you.
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
windows-msix-install: $(WINDOWS_APP_BUNDLE)
	@echo "Packaging + self-signing MSIX for local install..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Sign
	@echo "Installing MSIX package locally..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Install

# Removes the package (per-user) and the throwaway signing cert; untrusting the
# machine-store cert self-elevates via UAC.
windows-msix-uninstall:
	@echo "Removing installed MSIX package and throwaway cert..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Uninstall
