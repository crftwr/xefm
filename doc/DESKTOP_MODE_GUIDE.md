# XeFM Desktop Mode Guide

## Overview

XeFM can run as a native macOS desktop application with GPU acceleration, providing a modern windowed experience while maintaining the same powerful keyboard-driven interface you know from terminal mode.

## Quick Start

### Installation

**Option 1: Direct installation**
```bash
# Install PyObjC (one-time setup)
pip install pyobjc

# Run in desktop mode
python3 -m xefm --backend gui
```

**Option 2: Install with extras**
```bash
# Install XeFM with macOS desktop mode support
pip install -e .[macos]

# Run in desktop mode
python3 -m xefm --backend gui
```

**Option 3: From PyPI (when published)**
```bash
# Install with macOS support
pip install xefm[macos]

# Run in desktop mode
xefm --backend gui
```

### First Launch

When you launch XeFM in desktop mode:
1. A native macOS window appears
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

There is no configuration-file default for the backend — it is selected only by
the `--backend` flag, and terminal mode is the default. To launch in desktop
mode, pass `--backend gui` (alias `macos`) each time, or wrap it in a shell alias.

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

```bash
# Terminal mode (the default)
python3 -m xefm

# Desktop mode — chosen with --backend
python3 -m xefm --backend gui
```

### Switching Between Modes

You can easily switch between terminal and desktop modes:

```bash
# Terminal mode
python3 -m xefm --backend curses

# Desktop mode
python3 -m xefm --backend gui
```

All your settings, favorites, and history are shared between modes.


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
1. Verify you're on macOS:
   ```bash
   uname -s  # Should show "Darwin"
   ```

2. Install PyObjC:
   ```bash
   # Option 1: Direct installation
   pip install pyobjc
   
   # Option 2: Install with extras
   pip install -e .[macos]
   ```

3. Verify installation:
   ```bash
   python3 -c "import objc; print('PyObjC installed successfully')"
   ```

4. Check Python version:
   ```bash
   python3 --version  # Should be 3.9 or higher
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
| **Platform** | All (macOS, Linux, Windows) | macOS only |
| **Dependencies** | Python + curses | Python + PyObjC |
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
- Daily use on macOS
- Better visual experience
- Smoother performance
- Customized fonts and colors
- Presentations or screen sharing

### When to Use Terminal Mode

**Recommended for**:
- SSH sessions
- Remote servers
- Non-macOS systems
- Minimal dependencies
- Integration with terminal workflows

### Switching Strategies

**Flexible Approach**:
- Use desktop mode for local work
- Use terminal mode for remote work
- Keep both options available

**Choosing per run**:
```bash
python3 -m xefm                 # terminal mode (default)
python3 -m xefm --backend gui   # desktop mode
```
Tip: wrap the desktop command in a shell alias if you use it often (there is no
config-file default for the backend).

## Advanced Topics

### Custom Launch Scripts

Create a launcher script for easy access:

```bash
#!/bin/bash
# ~/bin/xefm-desktop

PYTHONPATH=/path/to/xefm python3 -m xefm --backend gui "$@"
```

Make it executable:
```bash
chmod +x ~/bin/xefm-desktop
```

Now you can run:
```bash
xefm-desktop --left ~/projects --right ~/documents
```

### Integration with macOS

**Dock Integration**:
- Desktop mode appears in Dock when running
- Can right-click for options
- Shows in Cmd+Tab app switcher

**Spotlight Integration**:
- Create an Automator application
- Add "Run Shell Script" action
- Use: `PYTHONPATH=/path/to/xefm python3 -m xefm --backend gui`
- Save as "XeFM" in Applications folder

## Getting Help

If you encounter issues not covered here:

1. Check console output for error messages
2. Try terminal mode to isolate desktop-specific issues
3. Review the [User Guide](XEFM_USER_GUIDE.md)
4. Check the [PuiKit framework](https://github.com/crftwr/puikit) for technical details on the UI framework
5. Report issues on GitHub with:
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
