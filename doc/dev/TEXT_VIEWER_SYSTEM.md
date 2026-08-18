# Text Viewer System Documentation

## Overview

XeFM includes a comprehensive built-in text file viewer with syntax highlighting, search functionality, and remote file support. The viewer provides a clean, efficient way to view text files from both local and remote storage without leaving the file manager.

## Core Features

### ✅ Syntax Highlighting
- **Automatic detection** of file types via pygments' filename lexer, with an
  extension fallback map (`_EXT_LEXERS`) for common source types
- **Pygments integration** for syntax highlighting (a soft dependency)
- **Graceful fallback** to plain text when pygments is not available

### ✅ Navigation Controls
- **Vertical scrolling**: `↑↓` arrow keys
- **Horizontal scrolling**: `←→` arrow keys
- **Page navigation**: `Page Up/Down` for faster scrolling
- **Jump to start/end**: `Home/End` keys
- **Smooth scrolling** with proper boundary handling

### ✅ Display Options
- **Line numbers**: Toggle with `n` key (on by default)
- **Line wrapping**: Toggle with `w` key (off by default)
- **Syntax highlighting**: Toggle with `s` key (on by default if pygments available)
- **Status bar**: Shows current position, file size, format, and active options
- **Clean interface** with comprehensive information display

### ✅ Search Functionality
- **Incremental search**: Press `f` to search within the current file
- **Real-time highlighting**: Search matches highlighted as you type
- **Case-insensitive**: Finds matches regardless of case
- **Navigation**: Use `↑↓` to move between matches
- **Visual feedback**: Current match highlighted differently from other matches
- **Match counter**: Shows current match position and total matches

### ✅ Remote File Support
- **Unified file access** using xefm.path abstraction layer
- **Transparent handling** of different storage backends (local, S3, etc.)
- **Remote file detection** with scheme display in header
- **Enhanced error handling** for network and permission issues

## File Format Support

Highlighting is driven by pygments, so any language pygments has a lexer for is
supported. Lexer selection is:

1. `pygments.lexers.get_lexer_for_filename(path.name)` — pygments' own filename
   matching (handles `Dockerfile`, `Makefile`, `.rst`, and most extensions).
2. On `ClassNotFound`, a small extension fallback map, `_EXT_LEXERS` in
   `xefm/text_viewer.py` (`.py`, `.js`, `.ts`, `.json`, `.md`, `.yml`/`.yaml`,
   `.xml`, `.html`, `.css`, `.sh`/`.bash`, `.c`/`.cpp`/`.h`/`.hpp`, `.java`,
   `.go`, `.rs`, `.php`, `.rb`, `.sql`, `.ini`/`.cfg`/`.conf`, `.toml`).
3. Otherwise `TextLexer` (plain, uncolored).

Token categories are mapped to a small palette (`DEFAULT_SYNTAX`, VS Code Dark+)
that a theme may override via `extras['syntax']`. Structured formats such as
JSON and CSV also have dedicated *rich* renderers (see
`JSON_CSV_VIEWERS_IMPLEMENTATION.md`) reachable via the view-mode toggle.

## Usage

### Opening Files
1. **Navigate** to a text file in XeFM
2. **Press Enter** to open in text viewer (automatic for text files)
3. **Press `v`** to explicitly open in text viewer
4. **Non-text files** will show file info instead

### Viewer Controls
| Key | Action |
|-----|--------|
| `q` or `ESC` | Exit viewer and return to XeFM |
| `↑↓` | Scroll up/down |
| `←→` | Scroll left/right |
| `Page Up/Down` | Page scrolling |
| `Home/End` | Jump to start/end of file |
| `n` | Toggle line numbers on/off |
| `w` | Toggle line wrapping on/off |
| `s` | Toggle syntax highlighting on/off |
| `f` or `F` | Enter search mode |

### Search Controls
| Key | Action |
|-----|--------|
| `f` or `F` | Enter search mode |
| `ESC` or `Enter` | Exit search mode |
| `Backspace` | Remove last search character |
| `↑` or `k` | Previous match |
| `↓` or `j` | Next match |
| Type characters | Add to search pattern (incremental) |

### Status Information
The viewer interface provides comprehensive status information:

**Header:**
- **File name** and path with storage scheme (e.g., "S3: filename.txt" for remote files)
- **Keyboard controls** for quick reference

**Status Bar (bottom):**
- **Current position**: Line number and scroll percentage
- **File information**: Size and format type
- **Horizontal scroll**: Column position when scrolled
- **Active options**: NUM (line numbers), WRAP (line wrapping), SYNTAX (highlighting)
- **Search status**: Current match position and total matches when searching

## Remote File Support

### Unified File Access
The text viewer uses xefm.path's abstraction layer to support both local and remote files:

- **Transparent handling** of different storage backends
- **Consistent API** regardless of file location
- **Automatic detection** of remote files based on URI scheme

### Supported Remote Storage
Currently supports any storage backend implemented in the xefm.path system:
- **Local files**: Standard filesystem access
- **S3**: AWS S3 buckets (`s3://bucket/key`)
- **Extensible**: New storage backends can be added by implementing `PathImpl`

### Remote File Detection
- Automatically detects remote files based on URI scheme
- Shows remote scheme in the header:
  - Local files: `File: example.txt`
  - S3 files: `S3: example.txt`
  - Other remote: `SCHEME: example.txt`

### Enhanced Error Handling
Specific exception handling for different error types:
- `FileNotFoundError` for missing files
- `PermissionError` for access denied
- `OSError` for general I/O errors
- Network-specific errors for remote files

## Technical Implementation

### File Loading Process

#### 1. Text Reading
Uses `file_path.read_text()` with multiple encoding attempts:
- UTF-8 (primary)
- Latin-1 (fallback)
- CP1252 (Windows fallback)

#### 2. Binary Detection
If text reading fails, attempts `file_path.read_bytes()`:
- Checks for null bytes to identify binary files
- Uses Latin-1 as final fallback for edge cases
- Works with both local and remote files

#### 3. Error Handling
```python
try:
    content = file_path.read_text(encoding='utf-8')
except FileNotFoundError:
    # File doesn't exist
except PermissionError:
    # Access denied
except OSError as e:
    # General I/O error (including network issues)
```

### Syntax Highlighting Implementation
The text viewer uses a **curses-native approach** to syntax highlighting:

1. **Pygments tokenization** - Uses pygments to parse and tokenize source code
2. **Token-to-color mapping** - Maps pygments token types to curses color pairs
3. **Line-by-line rendering** - Renders each line as a sequence of colored text segments
4. **No ANSI escape sequences** - Direct curses color application for proper terminal compatibility

### File Detection
Multi-step approach to identify text files:

1. **Extension matching** against known text file extensions
2. **Filename matching** for common files without extensions (README, Makefile, etc.)
3. **Content analysis** - reads first 1KB to detect binary vs text content
4. **Encoding detection** - tries UTF-8, Latin-1, and CP1252 encodings

### Performance Optimizations

#### Local Files
- **Efficient tokenization** - Pygments tokenization done once per file load
- **Optimized rendering** - Only visible content is rendered to screen
- **Memory conscious** - Handles large files appropriately
- **Fast scrolling** - Smooth navigation with proper color handling

#### Remote Files
- **Caching** - S3 implementation includes built-in caching for metadata and content
- **Network efficiency** - Uses xefm.path's optimized remote operations
- **Minimal data transfer** - Binary detection only reads first 1024 bytes
- **Streaming support** - Through xefm.path abstraction

### Horizontal scrolling

Content is drawn in a fixed-advance face (`MONO`), so a column is a character and
the gutter, horizontal scroll, and highlights all align by column. `self.left`
(and `self.top`) are floats, so a GUI pan is smooth rather than cell-snapped.

Tabs are expanded once at read time by the module function `_expand_tabs()`,
column-aware to `_TAB` (8) stops; `_read_lines()` runs it on every line, so the
rest of the viewer never sees a raw tab.

`_draw_line(ctx, y, line_idx, col0)` renders the visible column window
`[col0, col0 + content_w)`. It walks the line's `(text, fg)` segments tracking a
running character index `col`, clips each to `vis_start = max(col, col0_int)` /
`vis_end = min(seg_end, window_end)`, and slices by index arithmetic. `col0` may
be fractional: the row shifts left by its fractional part (`xfrac`) for smooth
pan, the gutter fill (drawn after) masks the left bleed, and the body's clip
trims the partial right edge.

> **War story — don't locate a character by value.** An earlier version found the
> first visible character with `text.index(char)`. `str.index` returns the
> *first occurrence of that character value*, not the character's position, so
> any line containing a repeated character (e.g. `0123450123...`) rendered from
> the wrong column at horizontal offsets past the repeat. The durable fix is to
> never search for a character by value — track the running character index
> explicitly (the current code's accumulating `col`).

### Text selection

Mouse text selection + clipboard copy in the modal viewer. The feature spans two
repos:

- **PuiKit** owns the reusable pieces — the `clipboard_rich` capability
  (`Panel.set_clipboard_rich`) and `MarkdownView`'s own selection + rich-HTML
  copy (documented in `puikit/docs/widget_catalog.md`).
- **XeFM** owns the raw text viewer's own selection, and forwarding mouse/keys to
  the embedded `MarkdownView` in rich mode.

**Raw text mode.** `_RawTextSelection` holds a `(line, col)` selection over the
source lines (monospace, so a column is a character), using PuiKit's
`MultiClickTracker` + `word_bounds` for the word/line gestures. It is a local
counterpart to PuiKit's `SelectableText` mixin, which can't be reused because
this viewer scrolls vertically **and** horizontally and draws its own line-number
gutter. `_pos_at(ex, ey)` maps a layer-local point through `_body_rect` and the
current `top`/`left` scroll (unwrapping `_row_map` when wrapping) to a
`(line, col)`; `_draw_selection` overlays the selected span of each visible row
over `theme.text_selection_bg` (mirroring the search-match overlay
`_draw_matches`). `handle_event` processes `MOUSE_DOWN`/`UP`/`DRAG` plus
`Cmd`/`Ctrl`+`C` (copy, plain text via `Panel.set_clipboard`) and
`Cmd`/`Ctrl`+`A` (select-all); a press outside the body clears the selection.

**Drag past the edge.** A drag held above or below the body keeps the view
scrolling under it, so a selection can run past the rows the pointer can reach
(issue #320). PuiKit's `EdgeAutoScroll` (`puikit.widgets._input`, also driving
`LogView`) supplies the mechanism: it rides a Panel animation tick and asks for
a **time-based** row delta, so the speed matches on a 60fps GUI and a terminal's
slower tick, and a backend with no ticks degrades to one step per drag event.
The viewer supplies `_edge_scroll_step(rows)`, which moves `top`, re-places the
selection's moving end on the newly revealed edge row, and returns False at the
ends of the file to retire the timer. `_pointer_y` reads the pre-clamp
`pointer_y` hint, since the Panel pins a drag that left the window onto the
nearest edge; `_drag_pos` pulls the endpoint back into the visible band and
takes the edge row *whole* (start of the top row, end of the bottom), which is
what makes dragging out of the view take entire lines.

**Rich mode.** `_forward_mouse_to_rich` translates a mouse event into the
embedded `MarkdownView`'s coordinate space (`event.translated(-bx0, -by0)`) so
its own selection and link clicks work through this modal viewer. KEY events
(including `Cmd`+`C`) are already forwarded in rich mode, so the widget's copy
path needs no extra wiring. `xefm.viewer_registry._build_markdown` builds the
file viewer's `MarkdownView` with `selectable=True`; help / message-box
MarkdownViews build without the flag and stay inert.

Tests: `test/test_viewer_selection.py` (raw-mode drag / multi-line / select-all /
press-outside-clears, and rich-mode mouse + copy forwarding) and
`test/test_viewer_drag_scroll.py` (edge auto-scroll, on a fake clock).
User-facing behavior: `doc/TEXT_VIEWER_FEATURE.md`.

## Installation & Dependencies

### Core Functionality
The text viewer works with **no external dependencies** - it uses Python's built-in libraries and the curses interface.

### Enhanced Syntax Highlighting
For **full syntax highlighting support**, install pygments:

```bash
pip install pygments
```

**Without pygments**: The viewer still works but displays files as plain text without syntax coloring.

**With pygments**: Syntax highlighting for any language pygments can lex, using the theme's syntax palette.

### Remote File Support
Remote file support is provided through the xefm.path system:
- **S3 support**: Requires `boto3` library for AWS S3 access
- **Other backends**: May require additional libraries depending on implementation

## Usage Examples

The viewer is a full-window modal PuiKit `Widget`, pushed over the active panel
with `show_text_viewer`:

### Viewing Local Files
```python
from xefm.path import Path
from xefm.text_viewer import show_text_viewer

# Local file
show_text_viewer(panel, Path('/home/user/document.txt'), state_manager=state_manager)
```

### Viewing Remote Files
```python
# S3 file (same call — xefm.path.Path abstracts the backend)
show_text_viewer(panel, Path('s3://my-bucket/document.txt'))
```

### Text File Detection

There is no `is_text_file()` predicate to call ahead of time, and no list of
text extensions — **the viewer decides from the file's bytes as it reads it**:

```python
from xefm.text_viewer import looks_binary

looks_binary(path)                    # NUL byte in the first 1024 bytes
lines, is_error = _read_lines(path)   # placeholder line when binary
```

`_read_lines()` sniffs with `looks_binary()` **before** attempting any decode,
then tries `utf-8`, `latin-1`, `cp1252` for everything else.

> **The ordering is load-bearing, not stylistic.** `latin-1` maps all 256 byte
> values, so it never raises `UnicodeDecodeError` — any decode loop containing
> it always succeeds. This code originally sniffed only *after* the loop, in an
> "if nothing decoded" branch that could therefore never run: the placeholder
> was unreachable and a PNG rendered as ~45,000 lines of mojibake. If you
> reorder this, `test/test_binary_file_handling.py` will fail.

Content search needs a cheaper, standalone check and has its own:
`XeFMApp._looks_textual(path)` in `xefm/app.py`. It differs deliberately — an empty
file is "nothing to grep" (False) but is perfectly viewable (not binary).

The principle: **detect capability from the bytes, configure preference by
extension.** Extension lists belong in FILE_ASSOCIATIONS (which application the
user prefers), never in text detection — they get files with no extension, an
unknown one, or a misleading one wrong, and sniffing gets all three right.

### Example File Types

#### Python Code
```python
# test_syntax.py - automatically highlighted
def hello_world():
    """A simple function"""
    message = "Hello, World!"
    print(f"Message: {message}")
    return True
```

#### JSON Data
```json
{
  "name": "XeFM Text Viewer",
  "features": ["syntax highlighting", "line numbers", "remote support"],
  "supported": true
}
```

#### Configuration Files
```ini
# config.ini - automatically detected and highlighted
[section]
key = value
debug = true
```

## Error Scenarios

### Local File Errors
```
File not found: /path/to/missing.txt
Permission denied: /path/to/restricted.txt
[Binary file - cannot display as text]
```

### Remote File Errors
```
File not found: s3://bucket/missing.txt
Permission denied: s3://private-bucket/restricted.txt
Error reading file: Connection timeout
Network error: Unable to connect to S3
```

## Integration with XeFM

### Seamless Experience
- **Automatic detection** - Enter key opens text files in viewer, directories navigate normally
- **Consistent interface** - viewer uses same color scheme and key patterns as XeFM
- **State preservation** - returns to exact same XeFM state after viewing
- **Log integration** - viewer actions logged to XeFM's log pane

### Configuration
The text viewer respects XeFM's configuration system:
- **Key bindings** can be customized in `~/.xefm/config.py`
- **Color schemes** integrate with XeFM's color system
- **Behavior settings** follow XeFM's configuration patterns

## Testing

- `test/test_binary_file_handling.py` — the binary-sniff ordering described in
  *Text File Detection* above (a PNG must not render as mojibake).
- `test/test_viewer_selection.py` — raw-mode and rich-mode text selection / copy.

## Future Enhancements

### Planned Features
1. **Regular expression search** for advanced pattern matching
2. **Bookmarks** for large files
3. **Split view** for comparing files
4. **Custom color themes** for syntax highlighting
5. **Plugin system** for additional file format support
6. **Search history** and replace functionality
7. **Streaming support** for very large remote files
8. **Progress indicators** for slow remote file loading

### Extension Points
- New storage backends can be added to xefm.path
- TextViewer automatically supports new backends
- No changes required to TextViewer code for new storage types

## Troubleshooting

### Common Issues

#### Syntax Highlighting
**Q: Syntax highlighting not working**
A: Install pygments with `pip install pygments`

#### File Detection
**Q: File shows as binary when it should be text**
A: Check file encoding - viewer supports UTF-8, Latin-1, and CP1252

#### Performance
**Q: Large files are slow to open**
A: This is expected - the viewer loads content progressively for better performance

#### Display Issues
**Q: Colors look wrong in terminal**
A: Ensure your terminal supports colors and try different XeFM color schemes

#### Remote Files
**Q: S3 files not accessible**
A: Ensure AWS credentials are configured and check network connectivity

**Q: Permission denied on remote files**
A: Verify read access to remote resources and check authentication

### Debug Information
Enable debug logging to see detailed error information:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Getting Help
- Check XeFM's main help with `?` key
- Review configuration in `~/.xefm/config.py`
- Check the log pane for error messages
- Verify file permissions and encoding

## Conclusion

The XeFM Text Viewer System provides a powerful, integrated solution for viewing and examining text files from both local and remote storage without leaving your file management workflow. Whether you're browsing code, checking configuration files, reading documentation, or accessing files from cloud storage, the viewer offers a smooth, efficient experience with professional syntax highlighting and comprehensive search capabilities.

The system's architecture ensures consistent behavior across all storage types while maintaining high performance and reliability. The unified interface means users can work with local and remote files using the same familiar controls and features.