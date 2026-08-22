# Mouse & Interaction

## Overview

XeFM supports mouse interaction in both Desktop mode (CoreGraphics backend on macOS) and Terminal mode (curses backend in supported terminals). You can click to move the cursor and switch panes, scroll with the wheel, right-click for a context menu, and — in Desktop mode — drag files out to other applications.

## Availability

### Desktop Mode (Full Support)

- **Platform**: macOS with CoreGraphics backend
- **Supported Events**: All mouse events including clicks, movement, scroll wheel, and drag-and-drop
- **Launch Command**: `python -m xefm --backend gui`

### Terminal Mode (Limited Support)

- **Platform**: Terminal emulators that support mouse events
- **Supported Events**: Mouse button clicks (movement, scroll, and drag depend on the terminal)
- **Launch Command**: `python -m xefm` (default terminal mode)
- **Compatibility**: Works in most modern terminal emulators (iTerm2, Terminal.app, xterm, etc.)

### Graceful Degradation

If your terminal doesn't support mouse events, XeFM automatically falls back to keyboard-only operation without errors. You can always use the Tab key to switch between panes.

## Clicking

The mouse moves the cursor and controls which pane is active.

### Click to Focus and Select a Row

1. **Click a file or directory** → the cursor moves to that row and the pane becomes active
2. **Click the other pane** → focus switches to it, exactly like pressing Tab
3. **Visual feedback** → the active pane is highlighted, the inactive pane is dimmed

Clicking a row is the mouse equivalent of arrowing the cursor onto it; press Enter (or double-click, in the contexts noted below) to open or navigate. Multi-selection is still done with Space (or `+`/`*` patterns).

### Right-Click for a Context Menu

Right-clicking a file or directory opens a context menu of common operations for that item.

### Pane Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Left Pane                  │ Right Pane                      │
│ (Click here to focus)      │ (Click here to focus)           │
│                            │                                 │
│ file1.txt                  │ document.pdf                    │
│ file2.txt                  │ image.png                       │
│ directory/                 │ folder/                         │
│                            │                                 │
├─────────────────────────────────────────────────────────────┤
│ Log Pane                                                     │
└─────────────────────────────────────────────────────────────┘
```

Click anywhere within a pane's boundaries to move focus and the cursor there.

## Mouse Wheel Scrolling

You can scroll through file lists using your mouse wheel or trackpad in both left and right panes.

### How It Works

1. **Scroll up / down** → moves the viewport up or down through the file list
2. **Pane under the pointer scrolls** → the pane you hover over scrolls, regardless of which pane has focus
3. **Cursor stays put** → scrolling moves the view, not the cursor
4. **Smooth scrolling** → a trackpad or precise wheel scrolls pixel-by-pixel in Desktop mode; a plain wheel moves one row per notch
5. **Boundary protection** → won't scroll past the top or bottom of the list

### Availability

- **Desktop Mode**: Full support with smooth (sub-row) scrolling
- **Terminal Mode**: Support depends on your terminal emulator's mouse reporting

## Double-Click

XeFM detects double-clicks (two clicks on the same row within the system threshold, roughly 0.5s on macOS) in the **Directory Diff Viewer**:

- **Double-click a directory** → expands it if collapsed, collapses it if expanded (same as Enter)
- **Double-click a file** → opens the file diff viewer to compare contents (same as Enter)
- **Double-click in the inactive side** → focuses that side first, then performs the action

In the main file panes, a single click already moves the cursor and activates the pane, so opening is done with **Enter** (open file / enter directory / enter archive) and **Backspace** (go to the parent directory).

### Terminal Requirements

Double-click detection requires a terminal that reports mouse events (most modern terminals do); mouse reporting is enabled by default. Supported terminals include iTerm2, Terminal.app, GNOME Terminal, Konsole, Windows Terminal, and most other modern emulators.

## Drag-and-Drop

In Desktop mode you can drag files out of XeFM and drop them onto other applications, Finder, or the Dock, using the native operating-system drag-and-drop system.

### How to Use Drag-and-Drop

1. **Navigate to the files** you want to drag
2. **Select files** (optional):
   - `Space` to select individual files
   - `+` to select files matching a pattern
   - `*` to select all files
3. **Click and hold** the mouse button on a file
4. **Move the mouse** past a short threshold to begin the drag
5. **Drag over** the target application or location
6. **Release the mouse button** to drop the files

### What Gets Dragged

- **With a selection**: all selected files are dragged together
- **Without a selection**: only the file under the cursor is dragged
- **Multiple files**: you can drag up to 1,000 files at once

### Visual Feedback

During a drag you'll see:

- **Single file**: the filename in the drag image
- **Multiple files**: a count like "5 files" in the drag image
- **Cursor changes**: the system cursor indicates valid/invalid drop targets and the operation (copy vs. move)

### Modifiers (macOS)

Drag-and-drop uses native macOS drag modifiers, held while dragging:

- **No modifier** or **Option (⌥)**: copy (shows a `+` cursor)
- **Command (⌘)**: move (no `+` cursor)

The cursor updates automatically based on the modifier and the drop target.

### Dropping Files Into XeFM

You can also drop files from another application onto a XeFM pane. Dropping onto a directory row targets that directory; dropping on empty space or past the last row targets the pane's current directory.

### Limitations

- **Terminal mode**: drag-and-drop is not available in terminal mode on any platform — use the copy/move commands instead. On Windows and Linux desktop, drag-out is not yet implemented.
- **Remote files** (S3, SSH, etc.) cannot be dragged; copy them locally first. Error: "Cannot drag remote files".
- **Files inside archives** (.zip, .tar, .gz) cannot be dragged; you can drag the archive file itself, or extract first. Error: "Cannot drag files from inside archives".
- **The parent directory marker** ("..") cannot be dragged; the drag simply doesn't start.
- **More than 1,000 files** cannot be dragged at once. Error: "Too many files selected (limit: 1000)". Drag in smaller batches.
- **Missing files**: if a selected file no longer exists, the drag is cancelled ("File no longer exists: [filename]") and the list reloads automatically.

### Troubleshooting Drag-and-Drop

**Drag doesn't start** — ensure you're in Desktop mode, move the mouse past the threshold before releasing, and check the file isn't a remote file, archive content, or the ".." marker.

**Drop doesn't work** — the target application must accept file drops of that type; try holding Option or Command, and confirm you're dropping on a valid target.

## Keyboard Alternatives

All mouse functionality has keyboard equivalents:

| Mouse Action | Keyboard Alternative |
|--------------|---------------------|
| Click a pane / row | Tab to switch panes; arrow keys to move the cursor |
| Double-click to open | Enter |
| Double-click header (parent dir) | Backspace |
| Wheel scroll | Page Up / Page Down, arrow keys |
| Drag files out | Copy/move commands (`C` / `M`) |

The Tab key cycles between panes, so you can always use it if mouse support is unavailable or if you prefer keyboard navigation.

## Backend Capabilities

### CoreGraphics Backend (Desktop Mode)

Full mouse support with all event types:

| Event Type | Supported | Description |
|------------|-----------|-------------|
| Button Down | ✓ | Mouse button press |
| Button Up | ✓ | Mouse button release |
| Click | ✓ | Press and release on the same row |
| Move | ✓ | Cursor movement |
| Wheel | ✓ | Scroll wheel / trackpad |
| Drag | ✓ | Native file drag-and-drop |

**Coordinate precision**: text grid coordinates (column and row) plus sub-cell positioning (fractional position within a character cell), accurate to pixel level.

### Curses Backend (Terminal Mode)

Basic mouse support, depending on the terminal:

| Event Type | Supported | Description |
|------------|-----------|-------------|
| Button Down | ✓ | Mouse button press |
| Button Up | ✓ | Mouse button release |
| Click | ✓ | Button click |
| Move | terminal-dependent | Reported by some terminals only |
| Wheel | terminal-dependent | Reported by some terminals only |
| Drag | ✗ | Not available in terminal mode |

**Coordinate precision**: text grid coordinates only (column and row), character-level accuracy. Mouse support is automatically disabled — without error messages — if the terminal doesn't report mouse events.

## Input Mode Behavior

### Mouse Events During Text Input

When XeFM is in a text input mode, mouse events are automatically ignored to prevent accidental disruption of your keyboard-based workflow. This ensures that mouse clicks don't interfere while you're typing.

#### Input Modes That Block Mouse Events

1. **Quick Edit Bar**: When renaming files or editing paths
   - Activated by pressing 'r' (rename) or other edit commands
   - Mouse clicks are ignored until you press Enter or Escape
   - Prevents accidental pane switching while typing

2. **Quick Choice Bar**: When confirming operations
   - Activated by copy, move, delete operations requiring confirmation
   - Mouse clicks are ignored until you make a choice
   - Prevents accidental clicks during decision-making

3. **I-search Mode**: When searching in the text viewer
   - Activated by the `isearch` key (default `F`) in the text viewer
   - Mouse clicks are ignored until you exit search mode
   - Prevents accidental scrolling while typing search terms

#### How It Works

- **Automatic Detection**: XeFM automatically detects when you're in an input mode
- **Silent Filtering**: Mouse events are silently ignored (no error messages)
- **Immediate Resume**: Mouse events work normally as soon as you exit the input mode
- **Keyboard Always Works**: Keyboard shortcuts continue to function normally

## Troubleshooting

### Mouse Not Working in Desktop Mode

**Problem**: Clicking doesn't move the cursor or switch focus in Desktop mode

**Solutions**:
1. Verify you're running in Desktop mode: `python -m xefm --backend gui`
2. Check that the window has focus (click on the window first)
3. Ensure you're clicking within the pane boundaries (not on the border)
4. Check the log pane for error messages
5. Try using the Tab key to verify pane switching works

### Mouse Not Working in Terminal Mode

**Problem**: Clicking doesn't move the cursor or switch focus in Terminal mode

**Solutions**:
1. Check if your terminal supports mouse events:
   - iTerm2: Yes (enable in Preferences → Profiles → Terminal → "Report mouse clicks")
   - Terminal.app: Yes (usually enabled by default)
   - xterm: Yes (with `-xrm 'XTerm*VT100.allowMouseOps: true'`)
   - tmux: Requires `set -g mouse on` in `.tmux.conf`
2. Verify mouse reporting is enabled in your terminal settings
3. Try a different terminal emulator
4. Use the Tab key as an alternative (always works)

### Clicks Not Registering

**Problem**: You click but nothing happens

**Solutions**:
1. **Click within pane boundaries**: Don't click on the border between panes
2. **Close dialogs first**: If a dialog is open, close it with Escape
3. **Check window focus**: Click on the window to ensure it has focus

### Wrong Pane Gets Focus

**Problem**: Clicking on one pane switches focus to the other pane

**Solutions**:
1. Check the pane boundary position (adjust with `[` and `]` keys if needed)
2. Click further from the center divider
3. Verify the window size hasn't changed unexpectedly

## Related Features

- **Dual-Pane Interface**: Two file panes for efficient file management
- **Keyboard Navigation**: Complete keyboard control for all operations
- **File Associations**: Configure which programs open which file types
- **Directory Diff Viewer**: Compare directory contents (double-click supported)

## See Also

- [Dual-Pane Feature](DUAL_PANE_FEATURE.md) - Overview of dual-pane interface
- [Desktop Mode Guide](DESKTOP_MODE_GUIDE.md) - Complete desktop mode documentation
- [Diff Viewer Feature](DIFF_VIEWER_FEATURE.md) - File and directory comparison tool
- [Archive Feature](ARCHIVE_FEATURE.md) - Working inside archives
- [S3 Support Feature](S3_SUPPORT_FEATURE.md) - Remote file storage
