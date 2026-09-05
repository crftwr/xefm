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

**Desktop app (Windows, macOS).** Install from the
[Microsoft Store](https://apps.microsoft.com/detail/9PK2X44W810V) on Windows, or
download the `-macos.dmg` from the
[latest release](https://github.com/crftwr/xefm/releases/latest) on macOS —
Python is bundled in. This is the recommended way to run XeFM on the desktop;
see the [Desktop Mode Guide](DESKTOP_MODE_GUIDE.md#installing-the-desktop-app-package).

**Terminal app (Windows, macOS, Linux).** From PyPI:

```bash
pipx install xefm     # or:  uv tool install xefm,  or:  pip install xefm
xefm
```

[pipx](https://pipx.pypa.io) and [uv](https://docs.astral.sh/uv/) keep XeFM in
its own environment while putting the `xefm` command on your PATH — the right
shape for an application. Or run `uvx xefm` to try it once without installing
anything. Python 3.10 or later is all you need; every dependency, including the
platform-specific ones, comes with it.

The two installs coexist and share `~/.xefm/`; installing both is a perfectly
normal setup. The **[README](../README.md#from-source)** covers working from a
source checkout.

### Upgrading and uninstalling

**Use the tool you installed with**, so pick the row you started from:

| Installed with | Upgrade | Uninstall |
|----------------|---------|-----------|
| `pipx install xefm` | `pipx upgrade xefm` | `pipx uninstall xefm` |
| `uv tool install xefm` | `uv tool upgrade xefm` | `uv tool uninstall xefm` |
| `pip install xefm` | `pip install --upgrade xefm` | `pip uninstall xefm` |

These are not interchangeable: each tool only knows about what it installed
itself. `uv tool upgrade xefm` on a pipx- or pip-installed copy fails with
`` `xefm` is not installed ``, and `uvx xefm` installs nothing at all, so there
is never anything for it to upgrade.

The desktop packages upgrade through their own channel: the Microsoft Store
updates automatically, and on macOS you install the new DMG over the old app.

### Installation troubleshooting

- `xefm: command not found` after `pip install xefm` — the console script landed
  in an environment that is not on your PATH; `pipx install xefm` or
  `uv tool install xefm` handle that for you (or run it as `python3 -m xefm`)
- `error: externally-managed-environment` from pip —
  [PEP 668](https://peps.python.org/pep-0668/) is protecting a system Python
  (Homebrew, Debian/Ubuntu); use pipx, uv, or a virtualenv
- `` `xefm` is not installed `` from `uv tool upgrade xefm` — uv only manages
  what `uv tool install` put there, so this means pipx or pip owns your copy
  (or `uvx` ran it without installing). Upgrade with the tool you installed
  with — see the table above

**First run:** arrow keys navigate, `Tab` switches panes, `?` opens help, `Q`
quits.

---

## Desktop Mode (Windows, macOS)

XeFM can run as a native desktop application with GPU acceleration, providing a modern windowed experience while maintaining the same keyboard-driven interface.

### Quick Start

Install the desktop package (see [Installation](#installation)) and open **XeFM**
from Launchpad / Spotlight on macOS, or the Start menu on Windows.

Running `xefm --backend gui` from a terminal opens the same window, but that is
the *development* path — it gives the wrong app icon and, on macOS, attributes
file permissions to your terminal rather than to XeFM. See
[Why not `xefm --backend gui`?](DESKTOP_MODE_GUIDE.md#why-not-xefm---backend-gui).

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

- `--backend tui` — terminal, the default (`--backend curses` selects the
  classic curses renderer instead, as a fallback for unusual terminals)
- `--backend gui` — native window on Windows (alias `windows`) or macOS (alias `macos`)

On Linux there is no desktop backend; use terminal mode.

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
- Verify you're on Windows or macOS (Linux is terminal-mode only)
- Check Python version (3.10+ required)

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
- **\\**: Go to the root of the current drive or location
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
- **Hidden Files Toggle**: Show/hide hidden files with '.' key — dot-names on
  every platform, plus files and folders carrying the hidden attribute on Windows
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
E        - Edit the selected files (or the focused file) with the external editor
Shift-E  - Create a new file
```

**See detailed documentation**: 
- [File Operations Feature](FILE_OPERATIONS_FEATURE.md)

### Multi-Selection
1. Use **Space** to select individual files
2. Use **A** to select/deselect all files
3. Use **Shift-A** to select/deselect all items (files + directories)
4. Use **Ctrl-Down** / **Ctrl-Up** to jump the cursor to the next / previous selected item
5. Perform operations on selected files

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
\        - Go to the root of the current drive or location
Home/End - Go to first/last file
Page Up/Down - Navigate by page
Ctrl-Home/End - Move the cursor to the first / last item
```

### Quick Navigation
```
J        - Show favorite directories
Shift-J  - Jump to a path (a file path lands the cursor on the file)
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
S        - Open the sort dialog (key + order)
1        - Quick sort by name
2        - Quick sort by extension
3        - Quick sort by size
4        - Quick sort by date
```

See [Sort Dialog Feature](SORT_DIALOG_FEATURE.md) for the dialog's controls
(F/E/S/T choose a key directly; Left/Right choose ascending/descending).

### Incremental search keys

Press `F`, then type. While the search bar is open:

| Key | Action |
|-----|--------|
| ↑ / ↓ | Previous / next match |
| Shift+↑ / Shift+↓ | Select the file, then move to the previous / next match |
| Ctrl+A | Select every match at once — press again to clear them |
| Enter | Stop at the current match |
| Esc | Cancel and go back to where the cursor was |

The search stops where its matches do: a character that would leave nothing
matching is refused, so the pattern stays on the last file it found instead of
running on into an empty list. Backspace always takes you back out. (Typing
romaji for Japanese keeps a couple of characters of leeway, since `ni` finds
Japanese only once it is `nih` — see [Migemo Search](MIGEMO_SEARCH_FEATURE.md).)

Space types a space — it separates the pattern's words (`re 24` finds
`report_2024.txt`), so selecting a file uses Shift+↓ rather than the file list's
Space. Ctrl+A marks the whole set the counter on the right is showing: type
`.log`, press Ctrl+A, and every log file is selected. Files selected outside the
search are left alone, so a second search adds to them. Every one of these keys can be rebound; see
[Customization](CUSTOMIZATION_FEATURE.md#the-incremental-search-bar).

### Search Tips
- **Incremental search**: Start typing to filter files immediately
- **Japanese by romaji (Migemo)**: In incremental search, typing `kensaku`
  also finds `検索` — no IME needed. See [Migemo Search](MIGEMO_SEARCH_FEATURE.md).
- **Pattern filtering**: Use wildcards like `*.txt` or `test_*`
- **Filename search (Shift-F)**: The query is an *exact* glob matched against the
  whole filename — `report.txt` matches only that name. Add wildcards for partial
  matches: `report*`, `*.py`, or `*report*` for the old "contains" behaviour.
- **Content search**: Search inside files with progress tracking. An active
  pane filter (`;`) narrows the search to the files it matches — filter to
  `*.txt` and only `.txt` files are grepped (subdirectories are still walked).
  The dialog title shows the pattern while it applies. Unicode files with a
  BOM (UTF-8, UTF-16, UTF-32) are searched as text, not skipped as binary.
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
E        - Edit the selected files (or the focused file)
Shift-E  - Create a new file
```

With several files selected, `E` opens them all — files sharing an editor are
passed to it in one launch (`vim a.txt b.txt`).

Configure your preferred editor in `~/.xefm/config.py`:
```python
TEXT_EDITOR = 'vim'  # or 'nano', 'code', etc.
```

**See detailed documentation**: [Text Editor Feature](TEXT_EDITOR_FEATURE.md)

### Subshell
```
Shift-X  - Open a shell in the current directory (terminal mode only)
```

Exit the shell to return to XeFM. The shell sees the `XEFM_*` environment
variables (pane directories and selections) and a `[XeFM]` prompt prefix.

The prefix is passed via the `PS1`/`PROMPT` environment variables, so a shell
whose startup files set their own prompt overwrites it. zsh always does — on
macOS, `/etc/zshrc` resets the prompt for every interactive shell, even if you
have no `~/.zshrc` — so key off `XEFM_ACTIVE` at the **end** of your
`~/.zshrc` instead:

```zsh
if [[ -n $XEFM_ACTIVE ]]; then
  PROMPT="[XeFM] $PROMPT"
fi
```

A framework that rebuilds the prompt before every command (powerlevel10k,
starship) overwrites even this; put the marker in its own config instead —
e.g. starship's `env_var` module, or a custom powerlevel10k segment.

Which variable carries the prefix follows the shell being launched: `cmd.exe`
reads `PROMPT` in its own `$`-code syntax, so it gets `[XeFM] $P$G` (or your
existing `PROMPT`, prefixed). PowerShell builds its prompt from a `prompt`
function that no environment variable can reach, so it gets no prefix — define
one in your profile keyed off `XEFM_ACTIVE`:

```powershell
if ($env:XEFM_ACTIVE) {
  function prompt { "[XeFM] $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
}
```

By default XeFM launches `$SHELL`, falling back to the platform default
(`cmd.exe` on Windows, `/bin/sh` elsewhere). Override it in
`~/.xefm/config.py`:
```python
SUBSHELL = 'zsh'                     # a single command...
SUBSHELL = ['powershell', '-NoLogo'] # ...or a command with arguments
```

---

## AWS S3 Integration

XeFM provides native AWS S3 integration for seamless cloud storage management. For comprehensive S3 documentation including setup, usage, troubleshooting, and advanced features, see the **[AWS S3 Support Feature Guide](S3_SUPPORT_FEATURE.md)**.

### Quick Start

1. Configure AWS credentials — `aws configure`, the `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` environment variables, or an
   IAM role (nothing to set up on EC2)
2. Navigate to S3 buckets using s3:// URIs

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
- View S3 text files and images directly (editing is local-only — copy the
  file to a local pane, edit it there, and copy it back)
- Create/extract archives with S3 objects

### S3 Examples
```bash
# Copy local files to S3
# 1. Select files in left pane (local directory)
# 2. Navigate right pane to s3://bucket/path
# 3. Press 'c' to copy

# View S3 text file
# 1. Navigate to s3://bucket/file.txt
# 2. Press 'v' to view (editing needs a local copy)
```

---

## Advanced Features

### Sub-shell Mode
Press **Shift+X** to enter sub-shell mode (terminal mode only — the desktop
app has no terminal to hand over) with environment variables:
- `XEFM_LEFT_DIR`: Left pane directory
- `XEFM_RIGHT_DIR`: Right pane directory
- `XEFM_THIS_DIR`: Current pane directory
- `XEFM_OTHER_DIR`: Other pane directory
- `XEFM_THIS_SELECTED`: Files selected with Space in the current pane — empty
  when nothing is selected
- `XEFM_THIS_FOCUSED`: The item under the cursor in the current pane, whatever
  is selected (`*_FOCUSED` exists for the other three panes too)

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
.        - Toggle visibility of hidden files
```

Other display settings — sorting, hidden files, themes — are also in the
menu bar under **View**.

Color themes are switched from the menu bar (**View → Theme**); assign a key to
`toggle_color_scheme` in `~/.xefm/config.py` to cycle them from the keyboard.

### Progress Animation
XeFM shows animated progress indicators during long-running operations like searching files.

**See detailed documentation**: [Search Animation Feature](SEARCH_ANIMATION_FEATURE.md)

---

## Customization

### Configuration File
XeFM creates `~/.xefm/config.py` on first run. Access it via:
- **Tools → Edit Configuration…** in the menu bar
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
    {'name': 'Open in VSCode', 'command': ['code', '.']},
    {'name': 'View with less', 'command': ['less'],
     'options': {'terminal': True}},
]
```

**See detailed documentation**: [External Programs Feature](EXTERNAL_PROGRAMS_FEATURE.md)

---

## Command Line Options

These apply to the terminal install and to source checkouts. The desktop
packages take no command-line arguments — their launcher starts the native
backend directly.

### Basic Usage
```bash
python3 -m xefm                    # Terminal (curses) mode — the default
python3 -m xefm --left ~/projects  # Set the left pane's startup directory
python3 -m xefm --right ~/docs     # Set the right pane's startup directory
```

### Backend Selection
`--backend` chooses the rendering backend:

```bash
python3 -m xefm --backend tui      # Terminal — default (--backend curses: classic curses fallback)
python3 -m xefm --backend gui      # Native window (aliases: --backend macos / windows)
```

`--backend gui` is the development path for desktop mode; for everyday use
install the desktop package instead
([why](DESKTOP_MODE_GUIDE.md#why-not-xefm---backend-gui)).

### All Options
```bash
--backend {tui,curses,gui,macos,windows}  # Rendering backend (default: tui)
--left DIR                        # Left pane startup directory
--right DIR                       # Right pane startup directory
--version                         # Show version and exit
--help                            # Show help and exit
```

### Combined Options
```bash
# Desktop window with custom startup directories (from a checkout)
python3 -m xefm --backend gui --left ~/projects --right ~/docs
```

Startup directories set with `--left`/`--right` override any saved pane history for that session; an invalid path falls back to the saved (or home) directory.

---

## Troubleshooting

### Common Issues

#### Desktop mode not starting (Windows / macOS)
- Check Python version: `python3 --version` (3.10+ required)
- Try terminal mode first: `xefm`
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
- [Migemo Search Feature](MIGEMO_SEARCH_FEATURE.md) - Japanese matching from typed romaji in incremental search
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
- [Customization (Preview)](CUSTOMIZATION_FEATURE.md) - Rebind viewer keys, bind keys to your own Python functions, run functions on events

### Integration and Extensions
- [External Programs Feature](EXTERNAL_PROGRAMS_FEATURE.md) - Custom program integration (incl. the VSCode recipe)

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
| \\ | Go to the root of the current drive or location |
| Page Up / Page Down | Scroll by a page |
| Ctrl+Home / Ctrl+End | Move the cursor to the first / last item |
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
| Ctrl+↓ / Ctrl+↑ | Jump the cursor to the next / previous selected item |
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
| E | Edit the selected file(s) (external editor) | any |
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
| ; | Filter the pane by pattern (Shift+Delete forgets a saved pattern) |
| : | Clear the filter |
| S | Sort dialog (key + order) |
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
| Shift+J | Jump to a path — a file path goes to its directory and focuses it |
| H | History for the current pane (Shift+Delete forgets an entry) |
| D | Drives / storage selection dialog |

### Other

| Key | Action |
|-----|--------|
| ? | Show the help dialog |
| Q | Quit XeFM |
| . | Toggle hidden files |
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