# XeFM User Guide

## Table of Contents

- [Getting Started](#getting-started)
- [Installation](#installation)
- [Desktop Mode (macOS)](#desktop-mode-macos)
- [Basic Usage](#basic-usage)
- [Core Features](#core-features)
- [File Operations](#file-operations)
- [Navigation](#navigation)
- [Search and Filtering](#search-and-filtering)
- [Text Viewing and Editing](#text-viewing-and-editing)
- [AWS S3 Integration](#aws-s3-integration)
- [Advanced Features](#advanced-features)
- [Customization](#customization)
- [Command Line Options](#command-line-options)
- [Troubleshooting](#troubleshooting)
- [Feature Documentation](#feature-documentation)

---

## Getting Started

XeFM (*Xenolith File Manager*) is a powerful dual-pane file manager that runs both as a native desktop app (Windows, macOS) and in the terminal (Windows, macOS, Linux). It provides efficient file management with cloud storage integration, advanced search capabilities, and extensive customization options.

### What Makes XeFM Special

- **Dual-pane interface** for efficient file operations between directories
- **Desktop *and* terminal** - the same app as a native window on Windows/macOS or as a TUI on Windows/macOS/Linux
- **AWS S3 integration** for seamless cloud storage management
- **Advanced search** with content search and filtering
- **Extensible** with external programs and custom key bindings
- **Cross-platform** support for macOS, Linux, and Windows

---

## Installation

### System Requirements

#### Terminal Mode Requirements (All Platforms)
- **Python 3.9+**: Core language requirement (3.11+ recommended, 3.13 supported)
- **Terminal**: Any terminal with curses support
- **Operating System**: macOS, Linux, or Windows
- **Windows**: `windows-curses` package (automatically installed via setup.py)

#### Desktop Mode Requirements (macOS Only)
- **Python 3.9+**: Core language requirement (3.11+ recommended, 3.13 supported)
- **macOS**: 10.13 (High Sierra) or later
- **PyObjC**: Install with `pip install pyobjc-framework-Cocoa`

#### Recommended Setup
- **Python 3.11+**: For best performance and compatibility (3.13 fully supported)
- **Modern Terminal**: Terminal.app (macOS), GNOME Terminal (Linux), Windows Terminal (Windows)
- **UTF-8 Support**: For proper character display

### Installation Methods

#### Method 1: Direct Run (Recommended for Testing)
```bash
# Clone or download XeFM
git clone https://github.com/shimomut/xefm.git
cd xefm

# Run directly in terminal mode
python3 -m xefm

# Run in desktop mode (macOS only)
python3 -m xefm --backend gui
```

#### Method 2: Package Installation
```bash
# Install from source directory
cd xefm
python3 setup.py install

# Run installed version
xefm                # Terminal mode
xefm --backend gui      # Desktop mode (macOS only)
```

#### Method 3: Development Installation
```bash
# Install in editable mode (changes reflected immediately)
cd xefm
pip install -e .

# Run from anywhere
xefm                # Terminal mode
xefm --backend gui      # Desktop mode (macOS only)
```

### Optional Dependencies

#### Enhanced Syntax Highlighting
```bash
pip install pygments
```
**Benefits**: 
- Syntax highlighting for 20+ file formats
- Better code viewing experience
- Automatic file type detection

#### AWS S3 Support
```bash
pip install boto3
```
**Benefits**:
- Navigate S3 buckets with s3:// URIs
- Full file operations on S3 objects
- Seamless local/cloud integration

**Setup AWS Credentials**:
```bash
# Option 1: AWS CLI
aws configure

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-west-2

# Option 3: IAM roles (for EC2 instances)
# No additional setup required
```

#### Desktop Mode (macOS Only)
```bash
pip install pyobjc-framework-Cocoa
```
**Benefits**:
- Native macOS application window
- GPU-accelerated rendering at 60 FPS
- Resizable window with full-screen support
- True RGB colors with better accuracy
- Customizable fonts and window size

### Platform-Specific Setup

#### macOS
```bash
# Ensure Python 3 is installed
python3 --version

# Install optional dependencies
pip3 install pygments boto3

# Run XeFM
python3 -m xefm
```

#### Linux
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-pip

# Install optional dependencies
pip3 install pygments boto3

# Run XeFM
python3 -m xefm
```

#### Windows
```bash
# Install windows-curses (required for Windows)
pip install windows-curses

# Install optional dependencies
pip install pygments boto3

# Run XeFM
python -m xefm
```

**Note**: The `windows-curses` package is automatically installed when using `python setup.py install` on Windows systems.

### Verification

#### Test Basic Functionality
```bash
# Run XeFM
python3 -m xefm

# Test basic navigation
# - Use arrow keys to navigate
# - Press Tab to switch panes
# - Press ? for help
# - Press q to quit
```

---

## Desktop Mode (macOS)

XeFM can run as a native macOS desktop application with GPU acceleration, providing a modern windowed experience while maintaining the same keyboard-driven interface.

### Quick Start

```bash
# Install PyObjC (one-time setup)
pip install pyobjc-framework-Cocoa

# Run in desktop mode (native macOS window)
python3 -m xefm --backend gui
```

### Features

Desktop mode provides several advantages over terminal mode:

- **Native Window**: Resizable macOS window with standard window controls
- **High-Quality Rendering**: Smooth rendering using CoreGraphics
- **Better Colors**: True RGB color support with accurate color reproduction
- **Font Customization**: Choose your preferred monospace font and size
- **Full-Screen Support**: Native macOS full-screen mode
- **Window Persistence**: Window size and position are remembered

### Configuration

Desktop-mode font settings live in `~/.xefm/config.py` (they are ignored in terminal mode):

```python
# GUI fonts and size — the grid is derived from the monospace face
MONO_FONT_NAME = 'Menlo'   # monospaced face for aligned columns (None = bundled default)
UI_FONT_NAME  = None       # proportional face for names/labels (None = bundled/OS default)
FONT_SIZE     = 12         # point size applied to both faces (8–72)
```

The window's size and position are remembered **automatically** across runs (via
the native macOS window autosave) — there are no window-geometry config keys.

#### Available Fonts

Common monospace fonts on macOS:
- `Menlo` (default) - Apple's default monospace font
- `Monaco` - Classic Mac monospace font
- `SF Mono` - San Francisco Mono (if installed)
- `Courier New` - Traditional monospace font
- `Fira Code` - Popular programming font (if installed)
- `JetBrains Mono` - Modern programming font (if installed)

### Backend Selection

The backend is chosen only by the `--backend` flag; there is no configuration-file
preference. The default is terminal mode:

- `--backend tui` (alias `curses`) — terminal / curses, the default
- `--backend gui` (alias `macos`) — native macOS window (requires PyObjC)

If you request `--backend gui` without PyObjC installed, startup fails with an
error — install it (`pip install pyobjc-framework-Cocoa`) or run in terminal mode.

### Keyboard Shortcuts

All keyboard shortcuts work identically in both terminal and desktop modes. The same key bindings apply regardless of which backend you're using.

For a complete list of all keyboard shortcuts, see the [Keyboard Shortcuts Reference](#keyboard-shortcuts-reference) section. You can also press **?** at any time while using XeFM to see the built-in help dialog with all available shortcuts.

### Performance

Desktop mode provides excellent performance:
- **Rendering**: 60 FPS with GPU acceleration
- **Responsiveness**: Immediate input handling
- **Large Directories**: Smooth scrolling even with thousands of files
- **Search Operations**: Non-blocking UI updates

### Troubleshooting Desktop Mode

**Desktop mode doesn't start:**
- Verify you're on macOS (desktop mode is macOS-only)
- Install PyObjC: `pip install pyobjc-framework-Cocoa`
- Check Python version (3.9+ required)

**Window doesn't appear:**
- Check console output for error messages
- Verify PyObjC installation: `python3 -c "import objc; print('OK')"`
- Try terminal mode first to verify XeFM works: `python3 -m xefm`

**Font issues:**
- Verify font name is correct (case-sensitive)
- Use `Font Book.app` to check installed fonts
- Fall back to default: Remove `MONO_FONT_NAME` from config (or set it to `None`)

**Performance issues:**
- Desktop mode should run at 60 FPS
- Check Activity Monitor for CPU/GPU usage
- Try reducing window size in configuration

---

## Basic Usage

### First Launch
When you first run XeFM, you'll see:
- **Left Pane**: Current directory
- **Right Pane**: Home directory
- **Log Pane**: System messages at the bottom
- **Status Bar**: Current path and file information

### Essential Keys
- **Tab**: Switch between left and right panes
- **Arrow Keys**: Navigate files and directories
- **Enter**: Enter directory or view text file
- **Backspace**: Go to parent directory
- **?**: Show help dialog
- **Q**: Quit XeFM

---

## Core Features

### Dual Pane System
- **Left and Right Panes**: Independent file browsing with synchronized operations
- **Active Pane Highlighting**: Visual indication of currently focused pane
- **Tab Switching**: Quick pane switching with Tab key
- **Pane Synchronization**: Sync directories and cursor positions between panes
- **Resizable Layout**: Adjustable pane boundaries with bracket keys

**See detailed documentation**: [Status Bar Feature](STATUS_BAR_FEATURE.md)

### Display and Visualization
- **File Information**: Size, date, permissions display
- **Hidden Files Toggle**: Show/hide hidden files with '.' key
- **Color Schemes**: Dark and Light themes with runtime switching
- **Status Bar**: Current path, file count, operation status
- **Log Pane**: Bottom pane for system messages and output
- **Wide Character Support**: Proper display of international filenames and Unicode characters

**See detailed documentation**: 
- [Color Schemes Feature](COLOR_SCHEMES_FEATURE.md)
- [Wide Character Support Feature](WIDE_CHARACTER_SUPPORT_FEATURE.md)

---

## File Operations

### Basic Operations
```
Space    - Select/deselect file
C        - Copy selected files to the other pane
M        - Move selected files (or create a directory when nothing is selected)
K        - Delete selected files (also the Delete key)
R        - Rename file (or batch-rename multiple)
E        - Edit file with the external editor
Shift-E  - Create a new file
```

**See detailed documentation**: 
- [File Operations Feature](FILE_OPERATIONS_FEATURE.md)

### Multi-Selection
1. Use **Space** to select individual files
2. Use **A** to select/deselect all files
3. Use **Shift-A** to select/deselect all items (files + directories)
4. Perform operations on selected files

**See detailed documentation**: [Key Bindings Feature](KEY_BINDINGS_FEATURE.md)

### Advanced Operations
- **Batch Rename**: Regex-based renaming for multiple files
- **Archive Creation**: Create ZIP, TAR.GZ, TGZ archives (P key)
- **Archive Extraction**: Extract archives to opposite pane (U key)
- **File Comparison**: Compare selected files between panes

**See detailed documentation**: [Batch Rename Feature](BATCH_RENAME_FEATURE.md)

### Safety Features
- **Confirmation Dialogs**: User confirmation for destructive operations
- **Conflict Resolution**: Handle file name conflicts with Overwrite, Skip, Rename, or Cancel options
- **Rename on Conflict**: Specify alternative filenames when conflicts occur during copy/move/extract
- **Permission Checks**: Validate file system permissions
- **Undo Prevention**: Clear warnings about irreversible operations

**See detailed documentation**: [File Operations Feature](FILE_OPERATIONS_FEATURE.md)

---

## Navigation

### Directory Navigation
```
↑↓       - Move up/down in file list
←→       - Switch panes or enter/exit directories
Enter    - Enter directory or view file
Backspace - Go to parent directory
Home/End - Go to first/last file
Page Up/Down - Navigate by page
```

### Quick Navigation
```
J        - Show favorite directories
Shift-J  - Jump to directory dialog
H        - Show directory history
O        - Sync current pane to the other pane
Shift-O  - Sync other pane to the current pane
```

**See detailed documentation**: 
- [Navigation Dialogs Feature](NAVIGATION_DIALOGS_FEATURE.md)

---

## Search and Filtering

### Search Methods
```
F        - Incremental search (filter as you type)
Shift-F  - Threaded filename search dialog
Shift-G  - Content search (grep) dialog
;        - Filter by pattern (*.py, test_*, etc.)
:        - Clear current filter
```

### Sorting
```
S        - Show sort options menu
1        - Quick sort by name
2        - Quick sort by extension
3        - Quick sort by size
4        - Quick sort by date
```

### Search Tips
- **Incremental search**: Start typing to filter files immediately
- **Pattern filtering**: Use wildcards like `*.txt` or `test_*`
- **Filename search (Shift-F)**: The query is an *exact* glob matched against the
  whole filename — `report.txt` matches only that name. Add wildcards for partial
  matches: `report*`, `*.py`, or `*report*` for the old "contains" behaviour.
- **Content search**: Search inside files with progress tracking
- **Quick sort**: Use number keys 1-4 for instant sorting
- **ESC**: Cancel any search operation

**See detailed documentation**: [Search Animation Feature](SEARCH_ANIMATION_FEATURE.md)

---

## Text Viewing and Editing

### Built-in Text Viewer
```
V        - View text file in built-in viewer
Enter    - Open item (views a text file)
```

### Text Viewer Controls
```
q/ESC    - Exit viewer
↑↓       - Scroll up/down
←→       - Scroll left/right
Page Up/Down - Page scrolling
Home/End - Jump to start/end
n        - Toggle line numbers
w        - Toggle line wrapping
s        - Toggle syntax highlighting
/        - Search within file
```

### External Editor
```
e        - Edit existing file
E        - Create new file and edit
```

Configure your preferred editor in `~/.xefm/config.py`:
```python
TEXT_EDITOR = 'vim'  # or 'nano', 'code', etc.
```

**See detailed documentation**: [Text Editor Feature](TEXT_EDITOR_FEATURE.md)

---

## AWS S3 Integration

XeFM provides native AWS S3 integration for seamless cloud storage management. For comprehensive S3 documentation including setup, usage, troubleshooting, and advanced features, see the **[AWS S3 Support Feature Guide](S3_SUPPORT_FEATURE.md)**.

### Quick Start

1. Install boto3: `pip install boto3`
2. Configure AWS credentials (AWS CLI, environment variables, or IAM roles)
3. Navigate to S3 buckets using s3:// URIs

### S3 Navigation
```bash
# Navigate to S3 bucket
s3://my-bucket/

# Navigate to specific path
s3://my-bucket/path/to/files/
```

### S3 Operations
- All standard file operations work with S3 objects
- Copy between local and S3 storage
- Edit S3 text files directly
- Create/extract archives with S3 objects

### S3 Examples
```bash
# Copy local files to S3
# 1. Select files in left pane (local directory)
# 2. Navigate right pane to s3://bucket/path
# 3. Press 'c' to copy

# Edit S3 text file
# 1. Navigate to s3://bucket/file.txt
# 2. Press 'e' to edit or 'v' to view
```

---

## Advanced Features

### Sub-shell Mode
Press **X** (Shift+x) to enter sub-shell mode with environment variables:
- `XEFM_LEFT_DIR`: Left pane directory
- `XEFM_RIGHT_DIR`: Right pane directory
- `XEFM_THIS_DIR`: Current pane directory
- `XEFM_OTHER_DIR`: Other pane directory
- `XEFM_THIS_SELECTED`: Selected files in current pane

### External Programs
Press **x** to show external programs menu. Programs have access to XeFM environment variables.

**See detailed documentation**: [External Programs Feature](EXTERNAL_PROGRAMS_FEATURE.md)

### Pane Layout
```
[        - Make left pane smaller
]        - Make left pane larger
-        - Reset pane split to 50/50
{        - Make log pane larger (Shift+[)
}        - Make log pane smaller (Shift+])
_        - Reset log pane height (Shift+-)
```

### File Comparison
```
=        - View diff between two selected text files (requires 2 files selected)
Shift-=  - Compare the two panes' current directories recursively
W        - Show file and directory comparison options
```

**See detailed documentation**: [Diff Viewer Feature](DIFF_VIEWER_FEATURE.md) (file and directory diff)

### View and Display Options
```
Z        - Show view options menu
Shift-Z  - Show settings and configuration menu
T        - Switch color scheme (cycles dark / light / themes)
Shift-T  - Toggle fallback color mode for terminal compatibility
.        - Toggle visibility of hidden files
```

### Progress Animation
XeFM shows animated progress indicators during long-running operations like searching files.

**See detailed documentation**: [Search Animation Feature](SEARCH_ANIMATION_FEATURE.md)

---

## Customization

### Configuration File
XeFM creates `~/.xefm/config.py` on first run. Access it via:
- Press **Z** → Settings Menu → Edit Configuration
- Or edit `~/.xefm/config.py` directly

**For comprehensive configuration documentation**, see the **[Configuration Feature Guide](CONFIGURATION_FEATURE.md)** which covers all available options, examples, and best practices.

### Key Bindings

XeFM supports powerful key binding customization with modifier keys and multiple keys per action:

```python
KEY_BINDINGS = {
    # An action can have several keys — add your own alongside the defaults
    'quit': ['Q'],
    'help': ['?'],

    # e.g. add vim-style movement next to the arrow keys
    'cursor_up': ['UP', 'k'],
    'cursor_down': ['DOWN', 'j'],

    # Modifier key combinations
    'page_up': ['PAGE_UP', 'Shift-UP'],
    'page_down': ['PAGE_DOWN', 'Shift-DOWN'],

    # Extended form with a selection requirement
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'  # only when files are selected
    },
    'create_directory': {
        'keys': ['M'],
        'selection': 'none'      # only when nothing is selected
    },
}
```

**Key features:**
- **Modifier keys**: Shift, Control, Alt, Command
- **Multiple keys per action**: Assign several keys to the same action
- **Selection requirements**: Control when actions are available
- **Case-insensitive keys**: special key names ('ENTER' = 'enter') and bare letter keys ('q' = 'Q') bind the same physical key; use 'Shift-Q' to bind the shifted variant
- **Order-independent modifiers**: 'Command-Shift-X' = 'Shift-Command-X'

**See detailed documentation**: [Key Bindings Feature](KEY_BINDINGS_FEATURE.md)

### Themes
XeFM ships with several built-in themes (Dark+, Light+, Monokai, Dracula, Nord,
Solarized, Gruvbox Dark, Solarized Light) and remembers the last one you used.
Cycle themes at runtime with the **T** key, or pick one from **View → Theme**.
Define your own with the `THEMES` dict in config.

**See detailed documentation**: [Color Schemes Feature](COLOR_SCHEMES_FEATURE.md)

### Favorite Directories
```python
FAVORITE_DIRECTORIES = [
    {'name': 'Projects', 'path': '~/dev'},
    {'name': 'Documents', 'path': '~/Documents'},
    {'name': 'S3 Bucket', 'path': 's3://my-bucket/'},
]
```

**See detailed documentation**: [Navigation Dialogs Feature](NAVIGATION_DIALOGS_FEATURE.md)

### External Programs
```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Open in VSCode', 'command': ['code', '.'], 
     'options': {'auto_return': True}},
]
```

**See detailed documentation**: [External Programs Feature](EXTERNAL_PROGRAMS_FEATURE.md)

---

## Command Line Options

### Basic Usage
```bash
python3 -m xefm                    # Terminal (curses) mode — the default
python3 -m xefm --backend gui      # Native macOS window (requires PyObjC)
python3 -m xefm --left ~/projects  # Set the left pane's startup directory
python3 -m xefm --right ~/docs     # Set the right pane's startup directory
```

### Backend Selection
`--backend` chooses the rendering backend:

```bash
python3 -m xefm --backend tui      # Terminal / curses (alias: --backend curses) — default
python3 -m xefm --backend gui      # Native macOS window (alias: --backend macos)
```

### All Options
```bash
--backend {tui,curses,gui,macos}  # Rendering backend (default: tui)
--left DIR                        # Left pane startup directory
--right DIR                       # Right pane startup directory
--version                         # Show version and exit
--help                            # Show help and exit
```

### Combined Options
```bash
# macOS GUI with custom startup directories
python3 -m xefm --backend gui --left ~/projects --right ~/docs
```

Startup directories set with `--left`/`--right` override any saved pane history for that session; an invalid path falls back to the saved (or home) directory.

---

## Troubleshooting

### Common Issues

#### Desktop mode not starting (macOS)
- Verify PyObjC is installed: `pip install pyobjc-framework-Cocoa`
- Check Python version: `python3 --version` (3.9+ required)
- Try terminal mode first: `python3 -m xefm`
- Check console output for error messages

#### Desktop mode on non-macOS systems
Desktop mode only works on macOS. On other platforms, XeFM automatically falls back to terminal mode.

#### Colors not working
Check your terminal's color support and TERM environment variable

#### Wide characters display incorrectly
Check terminal Unicode support and locale settings

**See detailed documentation**: [Wide Character Support Feature](WIDE_CHARACTER_SUPPORT_FEATURE.md)

#### Keys not responding
Check terminal key mappings and ESCDELAY setting

#### S3 access denied
Verify AWS credentials and bucket permissions

#### File operations failing
Check file permissions and disk space

#### Performance issues
- Desktop mode provides better performance with GPU acceleration
- Install `pygments` for faster syntax highlighting
- Check available memory for large directory operations

### Getting Help
- Press **?** for built-in help
- Check feature documentation below
- Use `--help` command line option

**See detailed documentation**: [Help Dialog Feature](HELP_DIALOG_FEATURE.md)

---

## Feature Documentation

For detailed information about specific features, see these dedicated guides:

### File Operations
- [File Operations Feature](FILE_OPERATIONS_FEATURE.md) - Copy, move, duplicate, rename-conflict handling, and progress
- [Batch Rename Feature](BATCH_RENAME_FEATURE.md) - Regex-based renaming for multiple files
- [Archive Feature](ARCHIVE_FEATURE.md) - Create, extract, and browse archives (incl. password-protected)
- [File Details Feature](FILE_DETAILS_FEATURE.md) - Viewing detailed file information
- [File Monitoring Feature](FILE_MONITORING_FEATURE.md) - Automatic refresh when directories change on disk

### Remote and Cloud Storage
- [AWS S3 Support Feature](S3_SUPPORT_FEATURE.md) - Cloud storage integration and S3 bucket management
- [SFTP Support Feature](SFTP_SUPPORT_FEATURE.md) - Remote server access over SSH

### Navigation and Search
- [Navigation Dialogs Feature](NAVIGATION_DIALOGS_FEATURE.md) - Favorites, jump, history, and drives pickers
- [Tab Completion Feature](TAB_COMPLETION_FEATURE.md) - Path completion in input dialogs
- [Search Animation Feature](SEARCH_ANIMATION_FEATURE.md) - Progress indicators during search

### Viewers
- [Text Viewer Feature](TEXT_VIEWER_FEATURE.md) - Syntax highlighting, selection, and search in the built-in text viewer
- [Markdown Viewer Feature](MARKDOWN_VIEWER_FEATURE.md) - Rendered Markdown view
- [JSON / CSV Viewers Feature](JSON_CSV_VIEWERS_FEATURE.md) - Rendered structured-file views
- [Image Viewer Feature](IMAGE_VIEWER_FEATURE.md) - Built-in zoom / pan image viewer
- [Diff Viewer Feature](DIFF_VIEWER_FEATURE.md) - File and directory diff viewers
- [Text Editor Feature](TEXT_EDITOR_FEATURE.md) - External editor integration

### Interface and Display
- [Dual Pane Feature](DUAL_PANE_FEATURE.md) - The two-pane layout and pane operations
- [Menu Bar Feature](MENU_BAR_FEATURE.md) - Native / in-window menu bar
- [Status Bar Feature](STATUS_BAR_FEATURE.md) - Viewer status information display
- [Help Dialog Feature](HELP_DIALOG_FEATURE.md) - Built-in help system
- [Mouse & Interaction Feature](MOUSE_EVENT_SUPPORT_FEATURE.md) - Mouse, double-click, and drag-and-drop
- [Color Schemes & Visual Effects](COLOR_SCHEMES_FEATURE.md) - Themes, background animations, and motion
- [Wide Character Support Feature](WIDE_CHARACTER_SUPPORT_FEATURE.md) - International character display
- [Desktop Mode Guide](DESKTOP_MODE_GUIDE.md) - Native desktop app setup and options

### Configuration and Customization
- [Configuration Feature](CONFIGURATION_FEATURE.md) - Complete configuration reference and customization guide
- [Key Bindings Feature](KEY_BINDINGS_FEATURE.md) - Customizable keyboard shortcuts

### Integration and Extensions
- [External Programs Feature](EXTERNAL_PROGRAMS_FEATURE.md) - Custom program integration (incl. Beyond Compare & VSCode recipes)

---

## Keyboard Shortcuts Reference

XeFM provides extensive keyboard shortcuts for efficient file management. All shortcuts work identically in both terminal and desktop modes. Press **?** at any time to see the help dialog with all available shortcuts.

### Navigation

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move cursor up / down |
| ← / → | Switch to the left / right pane |
| Tab | Switch the active pane |
| Enter | Open item (enter directory, open file, or enter archive) |
| Backspace | Go to the parent directory |
| Page Up / Page Down | Scroll by a page |
| Cmd+Enter | Open with the OS default application |
| Alt+Enter | Reveal in the OS file manager |

### Selection

| Key | Action |
|-----|--------|
| Space | Toggle selection and move down |
| Shift+Space | Toggle selection and move up |
| Home | Select all items |
| End | Unselect all |
| A | Toggle all *files* |
| Shift+A | Toggle all *items* (files + directories) |
| W | Compare-and-select against the other pane |

### File Operations

| Key | Action | Selection |
|-----|--------|-----------|
| C | Copy selection to the other pane | required |
| M | Move selection to the other pane | required |
| M | Create a new directory | only when nothing is selected |
| K or Delete | Delete selection | required |
| R | Rename the focused file/directory | any |
| Shift+E | Create a new file | any |
| E | Edit the file (external editor) | any |
| V | View the file (built-in viewer) | any |
| I | Show file details | any |
| = | Diff two selected files | 2 files |
| Shift+= | Diff two directories recursively | 2 dirs |
| Cmd+Shift+C | Copy name(s) to the clipboard | any |
| Cmd+Shift+P | Copy path(s) to the clipboard | any |

### Search, Filter and Sort

| Key | Action |
|-----|--------|
| F | Incremental search (isearch) |
| Shift+F | Filename search dialog |
| Shift+G | Content (grep) search dialog |
| ; | Filter the pane by pattern |
| : | Clear the filter |
| S | Sort menu |
| 1 / 2 / 3 / 4 | Quick sort by name / extension / size / date |

### Archive Operations

| Key | Action | Selection |
|-----|--------|-----------|
| P | Create an archive from the selection | required |
| U | Extract the focused/selected archive | any |

### Panes and Log

| Key | Action |
|-----|--------|
| [ / ] | Make the left pane smaller / larger |
| - | Reset the pane split |
| { / } | Make the log pane larger / smaller |
| _ | Reset the log-pane height |
| Shift+↑ / Shift+↓ | Scroll the log up / down |
| Shift+← / Shift+→ | Page the log up / down |
| O | Sync the current pane's directory to the other pane |
| Shift+O | Sync the other pane's directory to the current pane |

### Places and Dialogs

| Key | Action |
|-----|--------|
| J | Favorite directories |
| Shift+J | Jump to a path |
| H | History for the current pane |
| D | Drives / storage selection dialog |

### Other

| Key | Action |
|-----|--------|
| ? | Show the help dialog |
| Q | Quit XeFM |
| . | Toggle hidden files |
| T | Cycle the color theme |
| Shift+T | Toggle fallback color mode |
| X | External programs menu |
| Shift+X | Enter subshell (command line) mode |
| Z | View options menu |
| Shift+Z | Settings / configuration menu |
| Ctrl+L | Redraw the screen (always available; recovers the display after a terminal-multiplexer switch) |
| F5 | Redraw the screen (rebindable via `redraw` in config) |

> **Letter keys are case-sensitive.** Most file-operation bindings use the
> **uppercase** letter (e.g. `C`, `M`, `K`, `R`), and their variants use `Shift`
> (e.g. `Shift-F`, `Shift-E`). All bindings are customizable — see below.


### Customizing Key Bindings

All key bindings can be customized in your configuration file (`~/.xefm/config.py`). The enhanced key binding system supports:

- **Modifier keys**: Shift, Control, Alt, Command (e.g., 'Shift-UP', 'Command-Q')
- **Multiple keys per action**: Assign several keys to the same action
- **Selection requirements**: Control when actions are available based on file selection
- **Case-insensitive keys**: special key names (`ENTER`) and bare letter keys (`q` = `Q`) bind the same physical key; use `Shift-Q` for the shifted variant

**Examples:**
```python
KEY_BINDINGS = {
    'page_up': ['PAGE_UP', 'Shift-UP'],  # Two ways to page up
    'cursor_up': ['UP', 'k'],            # add a vim-style alternative
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'          # Only when files selected
    },
}
```

See the [Configuration](#customization) section and [Key Bindings Feature](KEY_BINDINGS_FEATURE.md) for complete documentation.

---

## Tips and Tricks

### Efficiency Tips
1. **Use Tab frequently**: Quick pane switching is key to efficiency
2. **Learn multi-selection**: Select multiple files with Space, then operate
3. **Use incremental search**: Press 'f' and start typing to filter files
4. **Customize key bindings**: Adapt XeFM to your workflow
5. **Use favorites**: Set up bookmarks for frequently accessed directories

### Workflow Examples

#### File Organization
1. Navigate to source directory in left pane
2. Navigate to destination in right pane
3. Select files with Space
4. Press 'c' to copy or 'm' to move

#### Development Workflow
1. Set up favorites for project directories
2. Use external programs for git operations
3. Edit files with 'e' key
4. Use content search to find code

#### S3 Data Management
1. Navigate to local directory in left pane
2. Navigate to s3://bucket/path in right pane
3. Copy files between local and cloud storage
4. Edit S3 configuration files directly

---

This comprehensive user guide covers all aspects of using XeFM effectively. For technical implementation details, see the developer documentation in the `doc/dev/` directory.