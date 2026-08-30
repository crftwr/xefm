# XeFM Navigation System

## Overview

The XeFM Navigation System handles directory traversal, cursor positioning, and navigation state management. This document covers the implementation details of navigation behaviors and optimizations.

## Core Navigation Components

### Directory Navigation
- **Enter Key**: Navigate into directories
- **Backspace Key**: Navigate to parent directory with intelligent cursor positioning
- **Path Resolution**: Cross-platform path handling with XeFMPath abstraction

### Cursor Management
- **Position Memory**: Maintains cursor positions across directory changes
- **Scroll Adjustment**: Ensures selected items remain visible
- **History Integration**: Fallback to saved cursor positions

## Parent Directory Cursor Positioning

### Implementation Details

When navigating from a child directory to its parent directory using the Backspace key, the system implements intelligent cursor positioning to improve user experience.

#### Key Changes in `xefm/app.py`

```python
elif key == curses.KEY_BACKSPACE or key == KEY_BACKSPACE_2 or key == KEY_BACKSPACE_1:  # Backspace - go to parent directory
    if current_pane['path'] != current_pane['path'].parent:
        try:
            # Save current cursor position before changing directory
            self.save_cursor_position(current_pane)
            
            # Remember the child directory name we're leaving
            child_directory_name = current_pane['path'].name
            
            current_pane['path'] = current_pane['path'].parent
            current_pane['selected_index'] = 0
            current_pane['scroll_offset'] = 0
            current_pane['selected_files'].clear()  # Clear selections when changing directory
            self.refresh_files(current_pane)
            
            # Try to set cursor to the child directory we just came from
            cursor_set = False
            for i, file_path in enumerate(current_pane['files']):
                if file_path.name == child_directory_name and file_path.is_dir():
                    current_pane['selected_index'] = i
                    # Adjust scroll offset to keep selection visible
                    self.adjust_scroll_for_selection(current_pane)
                    cursor_set = True
                    break
            
            # If we couldn't find the child directory, try to restore cursor position from history
            if not cursor_set and not self.restore_cursor_position(current_pane):
                # If no history found, default to first item
                current_pane['selected_index'] = 0
                current_pane['scroll_offset'] = 0
            
            self.needs_full_redraw = True
        except PermissionError:
            self.show_error("Permission denied")
            self.needs_full_redraw = True
```

#### Behavior Flow

1. **User presses Backspace** while in a child directory
2. **System remembers** the current directory name (`child_directory_name`)
3. **Navigation occurs** to the parent directory
4. **Files are refreshed** in the parent directory
5. **Cursor positioning logic**:
   - First, try to find the child directory we came from
   - If found, position cursor on that directory
   - If not found (e.g., directory was deleted), fall back to cursor history
   - If no history available, default to first item
6. **Scroll adjustment** ensures the selected directory is visible

#### Fallback Mechanisms

The implementation includes robust fallback mechanisms:

1. **Primary**: Position cursor on child directory we came from
2. **Secondary**: Restore cursor position from saved history
3. **Tertiary**: Default to first item (index 0)

### Edge Cases Handled

#### 1. Child Directory No Longer Exists
If the child directory is deleted while the user is in it, the fallback mechanisms ensure graceful handling:
- Attempts to find the child directory (fails)
- Falls back to cursor history restoration
- If no history, defaults to first item

#### 2. Root Directory Navigation
When already at the root directory, the condition `current_pane['path'] != current_pane['path'].parent` prevents unnecessary processing.

#### 3. Permission Errors
Permission errors during navigation are caught and displayed to the user with appropriate error messages.

#### 4. Scroll Adjustment
The `adjust_scroll_for_selection()` method ensures that when the cursor is positioned on the child directory, it remains visible even if it's outside the current scroll view.

## Root Navigation (`go_root`)

`go_root` (default `\`) takes the active pane to the top of whatever it is
showing. Issue #353 asked for it as a *Windows* feature and assumed the TUI
would need a per-OS branch, because "root" means something different on each
platform. It does not: every `PathImpl` already answers `anchor`, so one
implementation is correct everywhere.

| Pane is showing | `anchor` |
|-----------------|----------|
| `C:\Users\foo\src` | `C:\` |
| `/home/foo/src` | `/` |
| `s3://bucket/logs/2026/` | `s3://bucket/` |
| `ssh://host/var/log` | `ssh://host/` |
| Inside an archive | the root of the filesystem holding the archive |

`XeFMApp._go_root` reads `pane["path"].anchor`, bails with an "Already at …"
log line when the pane is there already (unless the pane is virtual, where the
jump still has to leave the result set), and otherwise hands the jump to
`_go_to_dir`, which exits virtual mode and re-lists on a worker.

### Cursor landing

`_top_level_name` mirrors what `_go_parent` does with the child it came from:
it walks `parent` upward until the next step *is* the root and returns that
branch's name, so jumping from `/home/foo/src` to `/` lands the cursor on
`home`. The walk is bounded (256 steps) rather than trusting every backend's
chain to terminate — it runs on the UI thread, and a path implementation whose
parents never reach a fixed point would otherwise hang the app. A path whose
chain never meets the root simply lands at the top of the listing.

### Two path fixes this needed

- **`S3PathImpl.anchor`** returned the bare `s3://`, which names no listable
  location — XeFM has no bucket enumeration — while `parent`/`parents` already
  stopped at the bucket root. The bucket is S3's drive, the way the host is
  SFTP's, so the anchor is `s3://{bucket}/`.
- **`SSHPathImpl.parents`** looped forever. It walked upward while comparing
  each step against the *starting* path, which never matches again once the walk
  moves off it, so at the host root (its own parent) it appended without end.
  It now stops at the fixed point, and all four backends agree: `parents` ends
  at the anchor and is empty at the root.

## Navigation State Management

### Cursor History System
- **Position Saving**: `save_cursor_position(current_pane)` stores cursor state before navigation
- **Position Restoration**: `restore_cursor_position(current_pane)` retrieves saved positions
- **History Limits**: Uses `MAX_HISTORY_ENTRIES` configuration for memory management

### Scroll Management
- **Automatic Adjustment**: `adjust_scroll_for_selection(current_pane)` keeps selections visible
- **Offset Calculation**: Maintains proper scroll offset during navigation
- **Viewport Management**: Ensures selected items remain within visible area

## Performance Considerations

### Minimal Overhead
- Single directory name string storage (minimal memory impact)
- Linear search through parent directory files (typically small lists)
- No additional file system operations beyond normal navigation

### Optimization
- Early termination when child directory is found
- Efficient fallback chain prevents unnecessary operations
- Reuses existing scroll adjustment and cursor positioning logic

## Cross-Platform Compatibility

### Storage Support
- Works with all supported storage types (local filesystem, S3, etc.)
- Uses XeFMPath abstraction for cross-platform compatibility
- Handles different path separators and naming conventions

### Path Handling
- **Name Extraction**: Uses `current_pane['path'].name` for cross-platform directory name extraction
- **Parent Navigation**: Uses `current_pane['path'].parent` for reliable parent directory access
- **Type Checking**: Uses `file_path.is_dir()` for consistent directory identification

## Testing

### Unit Tests
The navigation system includes comprehensive unit tests in `test/test_parent_directory_navigation.py`:

- **Basic cursor positioning**: Verifies cursor is set to child directory
- **Nonexistent child handling**: Tests fallback when child directory doesn't exist
- **Root directory navigation**: Ensures proper handling at filesystem root

## Configuration Integration

### History Settings
- Uses `MAX_HISTORY_ENTRIES` for fallback cursor history
- Integrates with existing scroll adjustment logic
- Works with both left and right panes independently

### Backward Compatibility
- Fully backward compatible with existing XeFM installations
- No configuration changes required
- Existing cursor history functionality remains intact

## Future Enhancements

### Potential Improvements
1. **Multi-level navigation memory**: Remember cursor positions for multiple directory levels
2. **Smart positioning**: Consider file modification times or access patterns
3. **Visual indicators**: Highlight the directory we came from temporarily
4. **Configuration options**: Allow users to disable this behavior if desired

### Integration Opportunities
- **Breadcrumb navigation**: Could integrate with breadcrumb-style navigation
- **Quick navigation**: Could support quick jump-back functionality
- **History visualization**: Could show navigation history in status bar

## Related Systems

- **State Manager**: Integrates with state persistence for cursor history
- **Path System**: Uses XeFMPath for cross-platform path operations
- **Pane Management**: Works with dual-pane interface system
- **File Operations**: Coordinates with file refresh and display systems