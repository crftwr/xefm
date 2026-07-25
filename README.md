# XeFM — a dual-pane file manager for the desktop and the terminal

XeFM — short for *Xenolith File Manager* — is a powerful file manager that runs as a native desktop application on **Windows and macOS**, and in the terminal on **all platforms — Windows, macOS, and Linux**. Navigate your filesystem with keyboard shortcuts in a clean, intuitive dual-pane interface with comprehensive file operations, rich built-in viewers, themeable visual effects, and professional-grade features.

![title](doc/images/xefm-page-title.jpg)

## Key Features

- **Cross-platform** - Native desktop app on **Windows and macOS**; terminal (TUI) app on **Windows, macOS, and Linux**
- **Dual-pane interface** with independent navigation and cross-pane operations
- **Archive browsing** - Navigate ZIP, TAR, and compressed archives as virtual directories
- **SFTP support** - Browse and manage remote servers via SSH with optimized performance
- **AWS S3 support** for cloud storage operations
- **Advanced search** with real-time filtering and background processing  
- **Multi-selection** with bulk operations and progress tracking
- **Rich built-in viewers** - Syntax-highlighted text, images, Markdown, JSON, and CSV/TSV
- **Themes & visual effects** - A dozen built-in themes; desktop mode adds GPU background animations, CRT/phosphor screen effects, and text-reveal animations
- **External program integration** with configurable launchers
- **Customizable** - Fully configurable key bindings and settings

## Quick Start

### Installation

XeFM is on [PyPI](https://pypi.org/project/xefm/). Install it as a tool and run
it — Windows, macOS, or Linux, no checkout and no virtualenv to manage:

```bash
pipx install xefm     # or:  uv tool install xefm,  or:  pip install xefm
xefm
```

[pipx](https://pipx.pypa.io) and [uv](https://docs.astral.sh/uv/) keep XeFM in
its own environment while putting the `xefm` command on your PATH — the right
shape for an application. Upgrade later with `pipx upgrade xefm` (`uv tool
upgrade xefm`, `pip install --upgrade xefm`), or run `uvx xefm` to try it once
without installing anything.

Python 3.10 or later is the only prerequisite. Desktop mode needs nothing extra:
`xefm --backend gui` opens a native window on Windows 10+ and macOS 10.13+. (A
self-contained app package with Python bundled in is **not yet uploaded to GitHub
Releases**.)

Working on XeFM itself? Use a checkout instead:

```bash
git clone https://github.com/crftwr/xefm.git
cd xefm
make venv        # creates .venv with every dependency
make run         # launch XeFM through it, no activation needed
```

`make help` lists the rest — editable install, PuiKit co-development, and the
macOS / Windows app bundles.

### Essential Controls
- **Navigate:** `↑↓` to move up/down, `←→` to switch panes/navigate directories
- **Enter archives:** Press `Enter` on `.zip`, `.tar`, `.tar.gz` files to browse contents
- **Select:** `Space` to select/deselect files, `A` for all files, `Shift-A` for all items
- **File operations:** `C` (copy), `M` (move), `K` (delete), `R` (rename)
- **Help:** `?` for comprehensive help dialog
- **Quit:** `Q` to exit

### Help System
Press `?` to open the comprehensive help dialog with all key bindings and features organized by category. The help dialog is your quick reference guide - no need to memorize all shortcuts!

## Documentation

For comprehensive information about XeFM's features and usage:

### User Documentation
- **[Complete User Guide](doc/XEFM_USER_GUIDE.md)** - Comprehensive guide covering all features, configuration, and usage
- **[Configuration](doc/CONFIGURATION_FEATURE.md)** - Complete configuration reference and customization guide
- **[Desktop Mode](doc/DESKTOP_MODE_GUIDE.md)** - Native Windows / macOS desktop app setup and options
- **[Color Schemes & Visual Effects](doc/COLOR_SCHEMES_FEATURE.md)** - Themes, themeable GPU background scenes, and screen effects
- **[Image Viewer](doc/IMAGE_VIEWER_FEATURE.md)** - Built-in zoom / pan image viewer
- **[Markdown Viewer](doc/MARKDOWN_VIEWER_FEATURE.md)** & **[JSON / CSV Viewers](doc/JSON_CSV_VIEWERS_FEATURE.md)** - Rendered structured-file views
- **[SFTP Support](doc/SFTP_SUPPORT_FEATURE.md)** - Remote server access via SSH with file operations and search
- **[AWS S3 Support](doc/S3_SUPPORT_FEATURE.md)** - Cloud storage integration and S3 bucket management
- **[Archives](doc/ARCHIVE_FEATURE.md)** - Create, extract, and browse archives as directories
- **[Search Animation](doc/SEARCH_ANIMATION_FEATURE.md)** - Advanced search features and visual feedback

### Developer Documentation
- **[Path Polymorphism System](doc/dev/PATH_POLYMORPHISM_SYSTEM.md)** - Storage-agnostic architecture and extensibility
- **[Navigation System](doc/dev/NAVIGATION_SYSTEM.md)** - Core navigation implementation
- **[External Programs](doc/dev/EXTERNAL_PROGRAMS_SYSTEM.md)** - Program integration system

## Key Features Overview

All key bindings are fully customizable through the configuration system. For complete key binding reference, press `?` in XeFM or see the [User Guide](doc/XEFM_USER_GUIDE.md).

### Core Operations
- **Navigation:** Arrow keys, Tab to switch panes, Enter to open directories/files/archives
- **Archive Browsing:** Press Enter on `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz` files to browse as virtual directories
- **File Operations:** Copy (`C`), Move (`M`), Delete (`K`), Rename (`R`)
- **Selection:** Space to select files, `A` for all files, `Shift-A` for all items
- **Search:** `F` for incremental search, `Shift-F` for filename search, `Shift-G` for content search
- **Archives:** `P` to create archives, `U` to extract, Enter to browse contents
- **File Viewers:** `V` to view the selected file — text (syntax-highlighted), images, Markdown, JSON, and CSV/TSV (works inside archives); `M` toggles rendered/raw in the viewer

### Advanced Features
- **Favorite Directories:** `J` for quick access to bookmarked locations
- **External Programs:** `X` for custom program integration
- **Sub-shell Mode:** `Shift-X` to enter shell with XeFM environment variables
- **Themes:** `T` to cycle themes; more display options under `Z` (view options) and `Shift-Z` (settings)
- **Configuration:** `Shift-Z` for settings menu (`Z` opens view options)
- **SFTP Support:** Navigate remote servers using `ssh://hostname/path` syntax
- **AWS S3 Support:** Navigate S3 buckets using `s3://bucket/path` syntax

For comprehensive SFTP setup and usage, see the **[SFTP Support Feature Guide](doc/SFTP_SUPPORT_FEATURE.md)**.

For comprehensive S3 setup and usage, see the **[AWS S3 Support Feature Guide](doc/S3_SUPPORT_FEATURE.md)**.

## Archive Virtual Directory Browsing

XeFM lets you browse archive files as if they were regular directories - no extraction needed!

**Supported formats:** `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`

**How to use:**
1. Navigate to any archive file
2. Press `Enter` to browse its contents
3. Navigate directories inside the archive with arrow keys
4. Press `Enter` on files to view them
5. Copy files out with `C` (or your copy key)
6. Search within archives with `Alt+F7`
7. Press `Backspace` to exit the archive

**What you can do:**
- Browse nested directories within archives
- View text files with syntax highlighting
- Copy files and directories from archives to local/S3
- Search for files by name or content
- Select multiple files for batch operations
- Sort by name, size, date, or extension

See [Archive Feature](doc/ARCHIVE_FEATURE.md) for complete documentation.

## Built-in File Viewers

Press `V` (or `Enter`) to view the selected file. XeFM picks the right viewer for the file type — all of them work seamlessly on local files, inside archives, and on remote SFTP / S3 paths without extraction or download.

### Text viewer

A powerful text viewer with syntax highlighting for 20+ file formats.

![Text viewer](doc/images/text-viewer.jpg)

- Syntax highlighting for Python, JavaScript, JSON, Markdown, YAML, and more
- Line numbers, horizontal scrolling, line wrapping (`W`), and in-file search
- Multiple encoding support (UTF-8, Latin-1, CP1252)

### Rich viewers — Markdown, JSON, CSV/TSV

For structured files, the viewer offers a *rendered* view in addition to the raw text. Press `M` inside the viewer to toggle between the formatted and raw views.

| Markdown | JSON / JSONL | CSV / TSV |
|:---:|:---:|:---:|
| <img src="doc/images/markdown-viewer.jpg" width="280"> | <img src="doc/images/json-viewer.jpg" width="280"> | <img src="doc/images/csv-viewer.jpg" width="280"> |
| Rendered headings, lists, code, and links | Collapsible, syntax-colored tree (`.json`, `.jsonl`, `.ndjson`) | Column-aligned table grid (`.csv`, `.tsv`) |

### Image viewer

A modal image viewer with zoom, pan, and prev/next navigation through the sibling images in the current pane.

![Image viewer](doc/images/image-viewer.jpg)

- Supports PNG, JPEG, GIF, BMP, WebP, TIFF, ICO, and more (via Pillow)
- Renders inline in graphics-capable terminals (iTerm2, kitty, sixel) and in desktop mode; falls back to a metadata card (format / dimensions / size) elsewhere
- Zoom with `+` / `-`, pan with the arrow keys or a mouse drag, step through images with prev/next

## Themes & Visual Effects

XeFM ships a dozen built-in themes. Press `T` to cycle to the next theme, or pick one from the **View → Theme** menu — your choice is remembered across restarts. Define your own in `~/.xefm/config.py` and they appear in the picker alongside the built-ins.

| | | |
|:---:|:---:|:---:|
| <img src="doc/images/theme-dark.jpg" width="260"><br>**Dark+** | <img src="doc/images/theme-monokai.jpg" width="260"><br>**Monokai** | <img src="doc/images/theme-dracula.jpg" width="260"><br>**Dracula** |
| <img src="doc/images/theme-nord.jpg" width="260"><br>**Nord** | <img src="doc/images/theme-solarized.jpg" width="260"><br>**Solarized** | <img src="doc/images/theme-gruvbox.jpg" width="260"><br>**Gruvbox Dark** |
| <img src="doc/images/theme-light.jpg" width="260"><br>**Light+** | <img src="doc/images/theme-solarized-light.jpg" width="260"><br>**Solarized Light** | <img src="doc/images/theme-sci-fi.jpg" width="260"><br>**Sci-Fi** |
| <img src="doc/images/theme-cyber.jpg" width="260"><br>**Cyber** | <img src="doc/images/theme-segment-lcd.jpg" width="260"><br>**Segment LCD** | <img src="doc/images/theme-shinagawa.jpg" width="260"><br>**Shinagawa** |

The default config also includes a **Phosphor** sample theme — a monochrome phosphor-green CRT terminal — as a starting point for your own.

### Visual effects (desktop mode)

In desktop mode (`--backend gui`), a theme can carry visual effects that the GPU renders behind and over the interface. Terminal mode simply shows the theme's colors and ignores these.

- **Background animations** — a slow, on-palette scene drawn behind the panes, rendered as a GPU fragment shader: `starfield`, `rain`, `hologram`, `wave`, `grid`, `constellation`, and `datastream`.
- **Screen post-effects** — a full-frame CRT / phosphor look composited over the UI: bloom, glow, scanlines, vignette, and drop shadows.
- **Text-reveal animations** — filenames and labels *arrive* rather than appear, decoding or typing into place on a directory change (used by Sci-Fi and Cyber).
- **Translucent surfaces** — panels and chrome can sit at reduced opacity so the animated background reads through.

Effects are pure theme data — each is a combination of parameters attached to a theme, so a custom theme can mix and match them without any application code.

## Sub-shell Mode

Press `Shift-X` to temporarily suspend XeFM and enter a shell with environment variables providing access to current directories and selected files:

- `XEFM_LEFT_DIR`, `XEFM_RIGHT_DIR` - Directory paths for each pane
- `XEFM_THIS_DIR`, `XEFM_OTHER_DIR` - Current and other pane directories  
- `XEFM_LEFT_SELECTED`, `XEFM_RIGHT_SELECTED` - Selected files in each pane
- `XEFM_ACTIVE` - Set to '1' to indicate XeFM sub-shell mode

Type `exit` to return to XeFM.

## Advanced Features

- **Native Desktop App:** Run in a real window on Windows and macOS (`--backend gui`) with GPU rendering, or in any terminal — same keyboard-driven interface
- **Archive Virtual Directories:** Browse ZIP, TAR, and compressed archives as if they were directories - navigate, search, view files, and copy contents without extraction
- **SFTP Support:** Access remote servers via SSH with full file operations, search, and optimized performance through connection multiplexing and bulk operations
- **AWS S3 Support:** Navigate and manage S3 buckets with seamless local/remote operations
- **Rich Viewers:** Built-in viewers for text (syntax-highlighted), images (zoom/pan), Markdown, JSON, and CSV/TSV — plus text and directory diff viewers
- **Themes & Effects:** A dozen built-in themes with GPU background animations, CRT/phosphor screen effects, and text-reveal animations in desktop mode
- **Batch Rename:** Regex-based renaming with capture groups and macros
- **Threaded Search:** Non-blocking filename and content search with progress tracking (works inside archives and on remote servers)
- **Pane Management:** Resizable layout, directory sync, state persistence
- **External Integration:** VSCode, Beyond Compare, and custom program support

For detailed information on all features, see the [User Guide](doc/XEFM_USER_GUIDE.md).

## Command Line Options

```bash
# Run in terminal mode (default)
xefm

# Run in desktop mode (native window on Windows or macOS)
xefm --backend gui

# Specify startup directories
xefm --left /path/to/projects --right /path/to/documents

# Combined usage - desktop mode with custom directories
xefm --backend gui --left ./src --right ./test

# Help and version
xefm --help
xefm --version
```

The full flag set is just `--backend {tui,curses,gui,macos,windows}`, `--left DIR`,
`--right DIR`, `--version`, and `--help`.

Every line above also works as `python3 -m xefm …` when you are running from a
source checkout, where no `xefm` console command is installed.

### Backend Selection

XeFM supports two rendering backends, chosen with `--backend`:

- **Terminal Mode** (`--backend tui`, alias `curses`): traditional terminal interface, works on all platforms (**Windows, macOS, Linux**) — the default
- **Desktop Mode** (`--backend gui`): native desktop window on **Windows** (Direct2D/DirectWrite) or **macOS** (CoreGraphics, via PyObjC). The `gui` alias resolves to the right backend for the current platform; `windows` / `macos` name them explicitly.

Desktop mode provides:
- Native window with resizing and full-screen support
- Customizable fonts (`MONO_FONT_NAME` / `UI_FONT_NAME` / `FONT_SIZE`)
- Window size and position remembered automatically across runs
- Better color accuracy with true RGB colors, plus GPU-rendered theme background animations and screen effects

See the [Desktop Mode Guide](doc/DESKTOP_MODE_GUIDE.md) for detailed desktop mode configuration.

## Configuration

XeFM is highly configurable through `~/.xefm/config.py`. Access configuration via the Settings menu (`Shift-Z` key) or edit manually.

**Key areas:**
- Themes, color schemes, and visual effects (including custom themes)
- Key bindings (fully customizable)
- External programs, file associations, and text editor
- Favorite directories and startup paths
- Performance and behavior settings

For detailed configuration options, see the **[Configuration Feature Guide](doc/CONFIGURATION_FEATURE.md)** and the [User Guide](doc/XEFM_USER_GUIDE.md#configuration).

## Project Structure

```
xefm/
├── xefm/          # The `xefm` package — everything the app ships
│   ├── app.py     # The application (XeFMApp + top-level UI)
│   ├── __main__.py # `python -m xefm` entry point
│   ├── *.py       # Business logic, imported as `xefm.config`, `xefm.path`, …
│   └── tools/     # External programs for end users
├── tools/         # Development tools and utilities
├── test/          # Test files (1000+ passing tests)
└── doc/           # User documentation
    └── dev/       # Developer documentation
```

## Troubleshooting

**Installation Issues:**
- Ensure Python 3.10+ is installed
- `xefm: command not found` after `pip install xefm` — the console script landed in an environment that is not on your PATH; `pipx install xefm` or `uv tool install xefm` handle that for you (or run it as `python3 -m xefm`)
- `error: externally-managed-environment` from pip — [PEP 668](https://peps.python.org/pep-0668/) is protecting a system Python (Homebrew, Debian/Ubuntu); use pipx, uv, or a virtualenv
- Check terminal compatibility with curses library (terminal mode)

**Desktop Mode Issues:**
- Desktop mode runs on Windows and macOS; on other platforms use terminal mode
- On macOS, if PyObjC is missing XeFM automatically falls back to terminal mode
- Check console output for backend initialization messages
- See [Desktop Mode Guide](doc/DESKTOP_MODE_GUIDE.md) for detailed setup

**Performance Issues:**
- Check available memory for large directory operations
- First access to large archives may be slow while structure is cached
- Desktop mode provides better performance with GPU acceleration

**Archive Issues:**
- Verify archive file is not corrupted
- Ensure you have read permissions for the archive
- Check supported formats: `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`
- Archives are read-only - use copy operations to extract files

For detailed troubleshooting, see the [User Guide](doc/XEFM_USER_GUIDE.md#troubleshooting).

## Contact Author

Have questions, suggestions, or found a bug? Get in touch:

- **GitHub Repository**: [https://github.com/crftwr/xefm](https://github.com/crftwr/xefm)
- **GitHub Issues**: [Report bugs or request features](https://github.com/crftwr/xefm/issues)
- **PyPI**: [pypi.org/project/xefm](https://pypi.org/project/xefm/) — released versions (`pipx install xefm`)
- **Author's X (Twitter)**: [@smmrtmnr](https://x.com/smmrtmnr)

We welcome feedback and contributions to make XeFM even better!

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- **Issues:** Create an issue on the project repository
- **Documentation:** Review files in `doc/` and `doc/dev/` directories
- **User Guide:** See [XEFM_USER_GUIDE.md](doc/XEFM_USER_GUIDE.md) for comprehensive information