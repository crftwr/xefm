# Log Clipboard Copy Implementation

## Overview

This document describes the implementation of the log clipboard copy feature, which allows users to copy log pane contents to the system clipboard in desktop mode.

## Architecture

### Components

The feature is implemented across three main components:

1. **MenuManager** (`xefm/app.py`)
   - Defines menu item IDs for clipboard operations
   - Adds menu items to the Edit menu
   - Manages menu item enabled/disabled states

2. **FileManager** (`xefm/app.py`)
   - Implements action handlers for menu items
   - Validates desktop mode and clipboard support
   - Calls LogManager methods to retrieve log text
   - Copies text to clipboard via renderer

3. **LogManager** (`xefm/log_manager.py`)
   - Provides methods to extract log text
   - Handles visible vs. all logs logic
   - Respects scroll position and display height

### Data Flow

```
User clicks menu item
    ↓
MenuManager dispatches action
    ↓
FileManager action handler
    ↓
Validates desktop mode + clipboard support
    ↓
LogManager retrieves log text
    ↓
Renderer copies to clipboard
    ↓
User feedback via logger
```

## Implementation Details

### Menu Items

Two new menu item IDs were added to `MenuManager`:

```python
EDIT_COPY_VISIBLE_LOGS = 'edit.copy_visible_logs'
EDIT_COPY_ALL_LOGS = 'edit.copy_all_logs'
```

Menu items are added to the Edit menu after the existing clipboard operations (Copy Names, Copy Paths), separated by a divider for visual grouping.

Menu items are enabled only when:
- FileManager is the active top layer (no dialogs/viewers open)
- FileManager is not in modal input mode
- Desktop mode is active

### Action Handlers

Two action handlers were added to `FileManager`:

#### `_action_copy_visible_logs()`

1. Validates desktop mode and clipboard support
2. Calculates current log pane height using `_get_log_pane_height()`
3. Calls `log_manager.get_visible_log_text(log_height)`
4. Copies text to clipboard via `renderer.set_clipboard_text()`
5. Logs success/failure message

#### `_action_copy_all_logs()`

1. Validates desktop mode and clipboard support
2. Calls `log_manager.get_all_log_text()`
3. Copies text to clipboard via `renderer.set_clipboard_text()`
4. Logs success/failure message with line count

### LogManager Methods

Two new methods were added to `LogManager`:

#### `get_visible_log_text(display_height)`

Returns log text for currently visible lines based on:
- Current scroll offset (`self.log_scroll_offset`)
- Display height (number of visible lines)
- Total message count

Algorithm:
1. Get all messages from `LogPaneHandler`
2. Calculate max scroll offset based on total messages and display height
3. Cap current scroll offset to max scroll
4. Calculate start/end indices for visible messages
5. Extract formatted text from message tuples
6. Join with newlines and return

#### `get_all_log_text()`

Returns all log messages as text:
1. Get all messages from `LogPaneHandler`
2. Extract formatted text from message tuples
3. Join with newlines and return

### Message Format

Both methods return messages in the same format as displayed in the log pane:
- Formatted messages include timestamp, logger name, level, and message
- Raw stdout/stderr messages are included as-is
- Messages are separated by newlines

The formatting is handled by `LogPaneHandler.get_messages()`, which returns tuples of `(formatted_message, record)`. The clipboard methods extract just the formatted text.

## Design Decisions

### Desktop Mode Only

The feature is restricted to desktop mode because:
- Clipboard operations require desktop backend support
- Terminal mode doesn't have reliable clipboard access
- Consistent with other clipboard features (Copy Names, Copy Paths)

### Separate Visible vs. All

Two separate menu items were provided instead of a single "Copy Logs" command because:
- Users often want just the visible section they're looking at
- Copying all logs can be overwhelming for long sessions
- Provides flexibility for different use cases
- Follows principle of least surprise (visible = what you see)

### No Line Wrapping in Clipboard

The clipboard text does not include line wrapping that may be applied in the display:
- Wrapping is display-specific and depends on terminal width
- Users can wrap text in their target application as needed
- Preserves original message content without artificial breaks
- Simplifies implementation

### No Keyboard Shortcuts

Keyboard shortcuts were not assigned because:
- Limited available key combinations
- Less frequently used than file operations
- Can be added later if user demand exists
- Menu access is sufficient for this use case

## Testing

### Unit Tests

Tests are located in `test/test_copy_log_clipboard.py`:

- `test_get_all_log_text_empty` - Empty log handling
- `test_get_all_log_text_with_messages` - Multiple messages
- `test_get_visible_log_text_all_visible` - All messages fit in display
- `test_get_visible_log_text_partial` - Partial visibility
- `test_get_visible_log_text_with_scroll` - Scroll offset handling
- `test_get_visible_log_text_zero_height` - Edge case: zero height
- `test_log_text_preserves_formatting` - Format verification
- `test_log_text_different_levels` - Multiple log levels


## Future Enhancements

Potential improvements for future versions:

1. **Keyboard Shortcuts**: Add configurable shortcuts for power users
2. **Copy Selection**: Allow selecting specific log lines to copy
3. **Format Options**: Provide options for different output formats (plain text, JSON, CSV)
4. **Filter Before Copy**: Copy only messages matching certain criteria (level, logger name)
5. **Export to File**: Save logs directly to a file instead of clipboard
6. **Rich Text Format**: Preserve colors and formatting in clipboard (platform-dependent)

## Related Code

- `xefm/app.py` - Menu structure and item definitions
- `xefm/app.py` - Action handlers and menu dispatch
- `xefm/log_manager.py` - Log storage and retrieval
- `xefm/logging_handlers.py` - Log message formatting
- `test/test_copy_log_clipboard.py` - Unit tests
