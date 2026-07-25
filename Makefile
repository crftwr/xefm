# XeFM Makefile

.PHONY: help run run-gui run-web test test-quick clean install uninstall dev-install lint format demo macos-app macos-app-clean macos-app-install macos-refresh-icon macos-dmg windows-app windows-app-clean windows-app-zip windows-app-install windows-app-msix windows-app-msix-install windows-app-msix-uninstall install-config venv venv-clean check-venv install-puikit

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
	@echo "XeFM - Terminal File Manager"
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
	@echo "  PuiKit installs from PyPI by default. To develop against a local"
	@echo "  editable checkout, set PUIKIT_DIR (Makefile.local / env / CLI),"
	@echo "  e.g. PUIKIT_DIR=../puikit."
	@echo ""
	@echo "macOS App Bundle:"
	@echo "  macos-app         - Build native macOS application bundle"
	@echo "  macos-app-clean   - Clean macOS app build artifacts"
	@echo "  macos-app-install - Install XeFM.app to Applications folder"
	@echo "  macos-refresh-icon - Refresh macOS icon cache (after icon changes)"
	@echo "  macos-dmg         - Create DMG installer for distribution"
	@echo ""
	@echo "Windows App Bundle:"
	@echo "  windows-app         - Build self-contained Windows application bundle"
	@echo "  windows-app-clean   - Clean Windows app build artifacts"
	@echo "  windows-app-zip     - Build the bundle and zip it for distribution"
	@echo "  windows-app-install - Install the built bundle to Program Files (elevates via UAC)"
	@echo "  windows-app-msix          - Package the bundle as a self-signed MSIX (prototype)"
	@echo "  windows-app-msix-install  - Trust cert (elevates) + install the MSIX per-user"
	@echo "  windows-app-msix-uninstall- Remove the MSIX package + throwaway signing cert"
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
	@echo "Running XeFM on PuiKit (terminal)..."
	@$(PYTHON) -m xefm $(PUIKIT_DIRS)

run-gui: check-venv
	@echo "Running XeFM on PuiKit (macOS GUI)..."
	@$(PYTHON) -m xefm --backend gui $(PUIKIT_DIRS)

run-web: check-venv
	@echo "Running XeFM on PuiKit (web backend — opens a browser tab)..."
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

# ============================================================================
# Windows App Bundle Targets
# ============================================================================
# Delegates to windows_app/build.ps1 (PowerShell). These targets are only
# meaningful on Windows; on other platforms PowerShell won't be present.

# The built bundle's launcher; its presence marks a complete bundle. Targets
# that only *consume* the bundle (install, msix) depend on this file target so
# it is built once, on demand, if missing (e.g. after 'make windows-app-clean')
# instead of failing deep inside a packaging script. It is NOT rebuilt when
# already present, so iterating on packaging stays fast; run 'make windows-app'
# to force a fresh bundle.
WINDOWS_APP_BUNDLE := windows_app/build/XeFM/XeFM.exe

$(WINDOWS_APP_BUNDLE):
	@echo "Windows app bundle not found; building it first..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1

windows-app:
	@echo "Building Windows application bundle..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1

windows-app-zip:
	@echo "Building Windows application bundle (+ zip)..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Zip

windows-app-clean:
	@echo "Cleaning Windows app build artifacts..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Clean

# Install the built bundle to Program Files (override dir with INSTALLDIR=...).
# Self-elevates via UAC; builds the bundle first if it is missing.
windows-app-install: $(WINDOWS_APP_BUNDLE)
	@echo "Installing Windows application bundle..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build.ps1 -Install $(if $(INSTALLDIR),-InstallDir "$(INSTALLDIR)")

# --- MSIX (Microsoft Store / winget) packaging, PROTOTYPE ------------------
# The throwaway self-signed cert emitted alongside the signed .msix. It is a
# file target so 'install' can depend on it: a missing cert -- e.g. after
# 'make windows-app-msix-uninstall', which deletes this throwaway cert -- then
# triggers a fresh pack+sign instead of failing. When present (and no newer than
# the bundle) it is not rebuilt, so repeat installs stay fast. Rebuilt if the
# bundle is newer, so a rebuilt bundle is always repackaged before install.
WINDOWS_MSIX_CERT := windows_app/build/XeFM-proto-test.cer

$(WINDOWS_MSIX_CERT): $(WINDOWS_APP_BUNDLE)
	@echo "Signed MSIX package/cert not found (or stale); packaging and signing first..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Sign

# Wraps the built bundle into a self-signed .msix for local testing; builds the
# bundle first if it is missing. Always re-packs (unlike the file target above),
# since invoking this explicitly means "produce a fresh package now".
# See doc/dev/WINDOWS_STORE_MSIX_PLAN.md.
windows-app-msix: $(WINDOWS_APP_BUNDLE)
	@echo "Packaging Windows app as MSIX (self-signed prototype)..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Sign

# Trust the self-signed cert (self-elevates via UAC) then install per-user.
# Packages + signs first if the cert is missing (e.g. after an uninstall).
windows-app-msix-install: $(WINDOWS_MSIX_CERT)
	@echo "Installing MSIX package locally..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Install

# Removes the package (per-user) and the throwaway signing cert; untrusting the
# machine-store cert self-elevates via UAC.
windows-app-msix-uninstall:
	@echo "Removing installed MSIX package and throwaway cert..."
	@powershell -ExecutionPolicy Bypass -File windows_app/build_msix.ps1 -Uninstall
