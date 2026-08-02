# XeFM Desktop Mode Guide

## Overview

XeFM can run as a native desktop application on Windows and macOS with GPU acceleration, providing a modern windowed experience while maintaining the same powerful keyboard-driven interface you know from terminal mode.

## Quick Start

### Getting There

**Install the desktop package.** That is the supported way to run XeFM as a
desktop app: a native `.app` (macOS) or a self-contained `XeFM.exe` folder
(Windows), with Python bundled in — no Python install of your own required. On
Windows, install from the
**[Microsoft Store](https://apps.microsoft.com/detail/9PK2X44W810V)**; the macOS
DMG (and a portable Windows zip) are published on the
**[latest GitHub release](https://github.com/crftwr/xefm/releases/latest)**;
[the next section](#installing-the-desktop-app-package) walks through it.

Then launch it the way you launch any other application — Launchpad, Spotlight
or the Dock on macOS; the Start menu or a pinned taskbar shortcut on Windows.

#### Why not `xefm --backend gui`?

The `--backend gui` flag opens the same window from a terminal. It exists
because it is how XeFM is *developed* — it is a poor way to actually **use**
XeFM, for three reasons:

- **macOS permissions break.** A GUI launched from a terminal is a child of that
  terminal, so macOS attributes every privacy request to it. Access to Desktop,
  Documents, Downloads, iCloud Drive or removable volumes is granted (or denied)
  to *Terminal.app* / *iTerm*, not to XeFM — prompts name the wrong app, and
  file operations can fail with permission errors that no XeFM setting fixes.
  The installed `.app` has its own bundle identity, so it asks for, and keeps,
  its own permissions.
- **The application icon is wrong**, on both platforms. Without an app bundle
  (macOS) or the bundled launcher executable (Windows), the Dock, taskbar and
  Cmd/Alt-Tab switcher show the Python interpreter's generic icon and name
  instead of XeFM's.
- **It is inconvenient.** You need a terminal open for as long as XeFM runs,
  closing that terminal can take the window with it, and there is nothing to
  click in Spotlight, Launchpad or the Start menu.

`--backend gui` stays the right tool when you are working on XeFM itself from a
source checkout, where rebuilding the app bundle on every edit would be far too
slow:

```bash
python3 -m xefm --backend gui   # from a checkout
make run-gui                    # the same thing, through .venv
```

### Installing the desktop app package

| Platform | Install | Signed? |
|---|---|---|
| Windows 10/11 x64 | **[Microsoft Store](https://apps.microsoft.com/detail/9PK2X44W810V)** (recommended) | Yes — signed by Microsoft |
| Windows 10/11 x64 | `XeFM-<version>-win64.zip` (portable alternative) | No — needs [unblocking once](#windows--the-portable-zip) |
| macOS 10.13+ (Intel & Apple Silicon) | `XeFM-<version>-macos.dmg` | Yes — Apple Developer ID |

Every stable release attaches the ready-to-run DMG and zip; the
[latest-release link](https://github.com/crftwr/xefm/releases/latest) always
resolves to the newest stable release. You can also link straight to a specific
release, e.g. `https://github.com/crftwr/xefm/releases/tag/v1.0.1`.

#### Windows — the Microsoft Store package

Install from the
**[Store page](https://apps.microsoft.com/detail/9PK2X44W810V)**, or from a
shell:

```powershell
winget install --id 9PK2X44W810V --source msstore
```

The Store package is signed by Microsoft during certification, so there is no
SmartScreen prompt; it appears in the Start menu, updates automatically through
the Store, and uninstalls from *Settings → Apps*. Settings live in
`%USERPROFILE%\.xefm\`, shared with every other install of XeFM, and survive an
uninstall unless you delete that folder yourself.

#### macOS — the DMG

1. Download `XeFM-<version>-macos.dmg` from the release page.
2. Double-click it and drag **XeFM** onto the *Applications* shortcut.
3. Eject the disk image and launch **XeFM** from Launchpad or Spotlight.

The app is signed with the author's Apple Developer ID, so Gatekeeper opens it
normally. If macOS ever refuses with *"XeFM cannot be opened because the
developer cannot be verified"* — which happens when the quarantine attribute
survives an unusual download path — right-click the app in *Applications* and
choose **Open**, then confirm. That whitelists it permanently.

To remove it: drag `XeFM.app` to the Trash. Settings live in `~/.xefm/` and can
be deleted separately.

#### Windows — the portable zip

The zip is the alternative to the Store install: a **portable folder**, not an
installer. Unzip it and run `XeFM.exe` — there is no MSI, nothing is written to
the registry, and no admin rights are needed. Reach for it on machines without
Store access, or when you want a copy that runs from a USB stick or a network
share.

Unlike the Store package, which Microsoft signs during certification, the zip
on GitHub Releases is unsigned — which is what causes the warning handled
below.

1. **Unblock the zip first.** Right-click the downloaded
   `XeFM-<version>-win64.zip` → **Properties** → tick **Unblock** at the bottom
   of the *General* tab → **OK**.

   Windows tags internet downloads with a *Mark of the Web*, and extracting a
   tagged zip copies that tag onto every file inside. Unblocking the zip *before*
   extracting clears all of them in one step. From PowerShell, the equivalent is:

   ```powershell
   Unblock-File .\XeFM-<version>-win64.zip
   ```

2. **Extract** the `XeFM` folder somewhere convenient:
   - `%LOCALAPPDATA%\Programs\XeFM` — per-user, no elevation required
   - `C:\Program Files\XeFM` — all users, needs administrator rights

3. **Run `XeFM.exe`.** If step 1 was skipped, SmartScreen shows *"Windows
   protected your PC"*. Click **More info**, then **Run anyway**. The prompt
   appears once per downloaded copy, not on every launch.

4. *Optional:* right-click `XeFM.exe` → **Pin to Start** / **Create shortcut** for
   quicker access.

To remove it: delete the extracted folder (and `%USERPROFILE%\.xefm\` if you also
want the settings gone).

**Why not a downloadable `.msix`?** The repository can build one
(`make windows-msix`), but an MSIX must be signed before Windows will install
it, and the unsigned build exists only as a Microsoft Store submission
artifact — Microsoft signs it during certification. So a downloadable `.msix`
would simply refuse to install; outside the Store, the portable zip is the
installable form.

**Prefer not to run an unsigned binary?** Install from the
**[Microsoft Store](https://apps.microsoft.com/detail/9PK2X44W810V)** — Store
packages are signed by Microsoft — or install from PyPI (`pipx install xefm`)
and use XeFM in terminal mode.

### First Launch

When you launch XeFM in desktop mode:
1. A native window appears
2. The interface looks identical to terminal mode
3. All keyboard shortcuts work the same way
4. You can resize the window or go full-screen

## Features

### Native macOS Experience

- **Resizable Window**: Drag window edges to resize
- **Full-Screen Mode**: Click the green button or use macOS full-screen shortcut
- **Window Controls**: Standard macOS minimize, maximize, close buttons
- **Menu Bar Integration**: Native macOS menu bar (when focused)

### Performance Benefits

- **High-Quality Rendering**: Smooth GPU-accelerated rendering
- **Better Responsiveness**: Immediate input handling
- **Smooth Scrolling**: No tearing or lag when navigating large directories
- **Lower CPU Usage**: GPU handles rendering, freeing up CPU

### Visual Improvements

- **True RGB Colors**: Accurate color reproduction
- **Better Fonts**: Crisp font rendering with anti-aliasing
- **Customizable Fonts**: Choose your preferred monospace font
- **Screen Effects & Animated Backgrounds**: Themes can add CRT-style effects and
  moving backdrops (see [Color Schemes](COLOR_SCHEMES_FEATURE.md))


## Configuration

### Choosing the backend

The installed desktop package always starts in desktop mode — its launcher
selects the native backend, so there is nothing to pass and nothing to configure.

The `--backend` flag only matters when you run XeFM from a Python install or a
source checkout. There it defaults to terminal mode, and there is no
configuration-file key to change that; desktop mode is `--backend gui` (aliases
`macos` / `windows`), with the caveats in
[Why not `xefm --backend gui`?](#why-not-xefm---backend-gui) above.

### Customizing Appearance

Font settings live in `~/.xefm/config.py` (they apply to desktop/GUI mode only):

```python
MONO_FONT_NAME = 'Menlo'   # monospaced face for aligned columns (None = bundled default)
UI_FONT_NAME  = None       # proportional face for names/labels (None = bundled/OS default)
FONT_SIZE     = 12         # point size applied to both faces (8–72)
```

The window's size and position are remembered **automatically** across runs (via
the native macOS window autosave); there are no window-geometry config keys.

### Available Fonts

Common monospace fonts on macOS:

**Built-in Fonts**:
- `Menlo` (default) - Apple's default monospace font, excellent readability
- `Monaco` - Classic Mac monospace font, slightly more compact
- `Courier New` - Traditional monospace font, widely compatible

**Optional Fonts** (if installed):
- `SF Mono` - San Francisco Mono, modern Apple font
- `Fira Code` - Popular programming font with ligatures
- `JetBrains Mono` - Modern programming font, excellent for code
- `Source Code Pro` - Adobe's programming font
- `Hack` - Designed specifically for source code

To check installed fonts, open `Font Book.app` and filter by "Fixed Width" (monospace).

### Font Size Guidelines

- **Small** (10-12pt): More content visible, requires good eyesight
- **Medium** (13-15pt): Balanced readability and content density (recommended)
- **Large** (16-20pt): Better for presentations or accessibility
- **Extra Large** (21-24pt): Maximum readability, less content visible

## Usage

### Launching Desktop Mode

Open **XeFM** from Launchpad, Spotlight or the Dock (macOS), or from the Start
menu / a pinned shortcut (Windows). The installed package needs no flags.

From a source checkout, during development, `--backend` picks the renderer:

```bash
# Terminal mode (the default)
python3 -m xefm

# Desktop mode — development only, see "Why not xefm --backend gui?"
python3 -m xefm --backend gui
```

### Switching Between Modes

Terminal mode comes from the PyPI install (`pipx install xefm`) or a source
checkout — the desktop package is a self-contained application and does not put
an `xefm` command on your PATH, so the two installs coexist rather than replace
each other:

```bash
xefm                        # terminal mode
xefm --backend curses       # the same thing, stated explicitly
```

All your settings, favorites, and history live in `~/.xefm/` and are shared
between the desktop app and terminal mode.


### Keyboard Shortcuts

All keyboard shortcuts work identically in desktop mode:

- **Navigation**: Arrow keys, Tab, Enter, Backspace
- **File Operations**: C (copy), M (move), K (delete), R (rename)
- **Selection**: Space, A (all files), Shift-A (all items)
- **Search**: F (incremental), Shift-F (filename), Shift-G (content)
- **Theme**: T (cycle color schemes)
- **Help**: ? (help dialog)
- **Quit**: Q

See the [User Guide](XEFM_USER_GUIDE.md) for the complete keyboard reference.

### Window Management

**Resizing**:
- Drag window edges or corners
- Window content adjusts automatically
- Minimum size enforced for usability

**Full-Screen**:
- Click green button in title bar
- Or use macOS keyboard shortcut (usually Ctrl+Cmd+F)
- Exit full-screen the same way

**Multiple Windows**:
- Currently, XeFM supports one window at a time
- Launch multiple instances for multiple windows

## Troubleshooting

### Desktop Mode Won't Start

**Problem**: Desktop mode doesn't launch or falls back to terminal mode.

**Solutions**:
1. Verify you're on Windows or macOS — Linux has no desktop backend:
   ```bash
   uname -s  # macOS shows "Darwin"
   ```

2. On macOS, check that PyObjC survived the install (it ships with XeFM, so a
   failure here means a broken environment — reinstall XeFM):
   ```bash
   python3 -c "import objc; print('PyObjC OK')"
   ```

3. Check Python version:
   ```bash
   python3 --version  # Should be 3.10 or higher
   ```

### Window Doesn't Appear

**Problem**: Desktop mode starts but no window appears.

**Solutions**:
1. Check console output for error messages
2. Try terminal mode first to verify XeFM works:
   ```bash
   python3 -m xefm --backend curses
   ```
3. Check macOS version (10.13+ required)
4. Restart your Mac and try again

### Font Not Found

**Problem**: Error message about font not being available.

**Solutions**:
1. Check font name spelling (case-sensitive):
   ```python
   MONO_FONT_NAME = 'Menlo'  # Correct
   MONO_FONT_NAME = 'menlo'  # Wrong - case matters
   ```

2. Verify font is installed:
   - Open `Font Book.app`
   - Search for the font name
   - Check "Fixed Width" category for monospace fonts

3. Use a default font:
   ```python
   MONO_FONT_NAME = 'Menlo'  # Always available on macOS
   ```

4. Remove font setting to use default:
   ```python
   # Comment out or remove this line
   # MONO_FONT_NAME = 'CustomFont'
   ```


### Performance Issues

**Problem**: Desktop mode feels slow or laggy.

**Solutions**:
1. Check Activity Monitor:
   - Open Activity Monitor
   - Look for XeFM process
   - Check CPU and GPU usage

2. Make the window smaller by resizing it (the size is remembered for next time).

3. Try a different font:
   ```python
   MONO_FONT_NAME = 'Monaco'  # Simpler font
   ```

4. Close other applications to free resources

5. Desktop mode should run at 60 FPS - if not, check for:
   - Other GPU-intensive applications
   - macOS version (older versions may be slower)
   - Available system memory

### Colors Look Wrong

**Problem**: Colors appear different from terminal mode.

**Explanation**: Desktop mode uses true RGB colors, which may look different from terminal mode's limited color palette. This is expected and provides more accurate colors.

**Solutions**:
1. Adjust color scheme in configuration
2. Cycle through themes with the `T` key
3. Colors should be more accurate in desktop mode, not worse

### Text Rendering Issues

**Problem**: Text appears blurry or misaligned.

**Solutions**:
1. Try a different font size:
   ```python
   FONT_SIZE = 14  # Try different sizes
   ```

2. Use a different font:
   ```python
   MONO_FONT_NAME = 'Monaco'  # Try different fonts
   ```

3. Check display scaling settings in macOS System Preferences

4. Ensure you're using a monospace font (fixed-width)

## Comparison: Terminal vs Desktop Mode

| Feature | Terminal Mode | Desktop Mode |
|---------|--------------|--------------|
| **Platform** | All (macOS, Linux, Windows) | Windows and macOS |
| **Dependencies** | Python + curses | Python (+ PyObjC on macOS, installed for you) |
| **Window** | Terminal window | Native desktop window |
| **Rendering** | Terminal-based | GPU-accelerated |
| **Performance** | Good | Excellent (60 FPS) |
| **Colors** | Terminal palette | True RGB |
| **Fonts** | Terminal font | Customizable |
| **Resizing** | Terminal resize | Native window resize |
| **Full-Screen** | Terminal full-screen | Native full-screen |
| **Keyboard** | Identical | Identical |
| **Features** | All features | All features |

## Best Practices

### When to Use Desktop Mode

**Recommended for**:
- Daily use on Windows and macOS
- Better visual experience
- Smoother performance
- Customized fonts and colors
- Presentations or screen sharing

### When to Use Terminal Mode

**Recommended for**:
- SSH sessions
- Remote servers
- Linux, where there is no desktop backend
- Minimal dependencies
- Integration with terminal workflows

### Switching Strategies

**Flexible Approach**:
- Use desktop mode for local work
- Use terminal mode for remote work
- Keep both options available

**Choosing per run**: open the installed **XeFM** app for desktop mode, and run
`xefm` in a terminal for terminal mode. The two coexist and share `~/.xefm/`, so
there is nothing to switch — pick whichever fits the task.

## Advanced Topics

### Integration with macOS

Installing `XeFM.app` is what makes the desktop integration work — all of it
follows from the app bundle, and none of it needs a launcher script or an
Automator wrapper:

- **Dock**: a proper XeFM icon, right-click options, *Keep in Dock*
- **Cmd+Tab**: XeFM appears under its own name and icon
- **Spotlight / Launchpad**: searchable as "XeFM", launches with one keystroke
- **Privacy permissions**: requests for Desktop / Documents / Downloads and Full
  Disk Access are attributed to XeFM itself, and are granted once in
  *System Settings → Privacy & Security*

Older versions of this guide suggested wrapping `python3 -m xefm --backend gui`
in a shell script or an Automator application to get a Dock and Spotlight entry.
Don't — that is exactly the setup that produces the generic Python icon and
misattributed permission prompts described in
[Why not `xefm --backend gui`?](#why-not-xefm---backend-gui). Install the `.app`
instead.

### Startup directories

The packaged apps take no command-line arguments — their launchers start XeFM
with the native backend and nothing else, so `--left` / `--right` are available
only when running from the command line.

You rarely need them there: each pane's directory is saved to `~/.xefm/state.db`
on exit and restored on the next launch, so the desktop app reopens where you
left off. For jumping elsewhere, use the favorites dialog (`J`).

## Getting Help

If you encounter issues not covered here:

1. Check console output for error messages
2. Try terminal mode to isolate desktop-specific issues
3. Review the [User Guide](XEFM_USER_GUIDE.md)
4. Report issues on GitHub with:
   - macOS version
   - Python version
   - PyObjC version
   - Console output
   - Steps to reproduce

## Summary

Desktop mode provides a modern, native macOS experience while maintaining XeFM's powerful keyboard-driven interface. With GPU acceleration, true RGB colors, and customizable fonts, it offers an enhanced experience for macOS users while remaining fully compatible with terminal mode.

Key benefits:
- ✅ Native macOS window
- ✅ 60 FPS GPU acceleration
- ✅ True RGB colors
- ✅ Customizable fonts
- ✅ Identical functionality
- ✅ Easy switching between modes

Try desktop mode today and experience XeFM in a whole new way!
