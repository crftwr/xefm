# File Extension Associations Implementation

## Overview

The file extension associations system provides a flexible mechanism for mapping file extensions to programs for different actions (open, view, edit). This document describes the implementation details for developers.

## Architecture

### Configuration Storage

File associations are stored in the configuration system as a list of dictionaries (compact format):

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': '*.pdf' or ['*.jpg', '*.png'],
        'open|view': ['command'],  # Combined actions
        'edit': ['command']
    }
]
```

Where:
- `extensions`: Single pattern string or list of patterns (e.g., `'*.pdf'` or `['*.jpg', '*.png']`)
- Action keys: `'open'`, `'view'`, `'edit'`, or combined like `'open|view'`
- `command`: Command list, command string, or `None`

### Compact Format Benefits

1. **Reduced duplication**: Group related extensions together
2. **Clearer intent**: Combined actions show when programs are shared
3. **More maintainable**: Fewer entries to update
4. **Backward compatible**: Old format can be converted if needed

### Location

File associations are defined in two places:

1. **DefaultConfig** (`xefm/config.py`): Default associations
2. **User Config** (`~/.xefm/config.py`): User-customized associations

User config takes precedence over default config.

## Implementation Details

### Core Functions

#### `get_file_associations()`

Returns the file associations list from configuration.

```python
def get_file_associations():
    """Get the file extension associations from configuration"""
    config = get_config()
    
    if hasattr(config, 'FILE_ASSOCIATIONS') and config.FILE_ASSOCIATIONS:
        return config.FILE_ASSOCIATIONS
    elif hasattr(DefaultConfig, 'FILE_ASSOCIATIONS'):
        return DefaultConfig.FILE_ASSOCIATIONS
    
    return []
```

**Returns**: List of file association entries or empty list if none configured.

#### `_lookup_action(filename, action)`

The single walk over `FILE_ASSOCIATIONS` that every public accessor delegates
to. Extracted because the walk was previously duplicated across
`get_program_for_file` and `has_explicit_association`, which had to be kept in
step by hand.

```python
def _lookup_action(filename, action):
    """
    Returns:
        (found, value, entry)
    """
```

**Algorithm**:
1. Iterate entries top to bottom
2. Skip entries whose pattern(s) do not match (`_entry_matches`)
3. Within a matching entry, split combined keys (`'open|view'`) and look for
   the requested action, skipping the reserved keys (`pattern`, and `terminal`
   for backward compatibility)
4. Return on the first entry that *defines* the action — a matching entry that
   does not mention it falls through to later entries

**Why it returns a triple**: `found` separates "explicitly configured as
`None`" from "not configured at all". Those are indistinguishable by `value`
alone and mean opposite things at the call site — one selects the built-in
viewer, the other means "apply the default". `entry` is returned so
a caller can read entry-level settings without walking the list a second time.

#### `get_builtin_handler_for_file(filename, action='enter')`

Resolves the *casual* (Enter) tier, whose values name built-in handlers rather
than external commands.

```python
def get_builtin_handler_for_file(filename, action='enter'):
    """
    Returns:
        (configured, handler)   handler in BUILTIN_HANDLERS, or None
    """
```

**Kept separate from `get_program_for_file` deliberately.** That function
coerces a bare string into a command list, so routing the `enter` tier through
it would silently turn the handler name `'viewer'` into the command
`['viewer']`. Different value spaces need different accessors.

An unrecognised handler name is logged as a warning and reported as
*unconfigured*, so a typo falls back to XeFM's default dispatch rather than
silently disabling the Enter key.

#### Display handover is not a config concern

There is deliberately no `needs_terminal()` accessor and no `'terminal'` key.
Whether to suspend follows from the **backend**, resolved in
`_launch_associated()` via `is_desktop_mode()` — the same signal `_config.py`
already uses to pick `code` vs `vim` for `TEXT_EDITOR`.

An earlier draft did have a per-entry `'terminal': True` flag. Three reasons it
was removed, worth recording so it does not come back:

1. **It duplicated a decision PuiKit already makes.** `backend.suspended()` is
   polymorphic — a real curses shell-out dance on the terminal backend, a no-op
   on GUI backends, which is exactly the distinction the flag encoded.
2. **It could not express a mixed entry.** `'view': ['less']` with
   `'edit': ['code']` is a realistic pairing, and an entry-level flag forced
   both, requiring a duplicated pattern list to work around.
3. **It failed unsafely.** Omitting it on `less` corrupted the terminal — and
   omission was the default. The backend rule cannot be forgotten.

`'terminal'` remains in `_RESERVED_KEYS` so a leftover key in a hand-written
config stays inert rather than being matched as an action name.

#### `get_program_for_file(filename, action='open')`

Retrieves the program command for a specific file and action.

```python
def get_program_for_file(filename, action='open'):
    """
    Get the program command for a specific file and action.
    
    Args:
        filename: The filename to check (e.g., 'document.pdf')
        action: The action to perform ('open', 'view', or 'edit')
    
    Returns:
        Command list if found, None otherwise
    """
```

**Algorithm**:
1. Delegate the walk to `_lookup_action(filename, action)`
2. Convert a string command to list format (`'open -e'` → `['open', '-e']`)
3. Return the value if it is a list, otherwise `None`

**Returns**: Command list `['program', 'arg1', 'arg2']` or `None`

Note that `None` here is ambiguous by design — it covers both "explicitly
configured as `None`" and "no rule matched". Call `has_explicit_association()`
when the caller needs to tell them apart.

#### `has_action_for_file(filename, action='open')`

Checks if a specific action is available for a file.

```python
def has_action_for_file(filename, action='open'):
    """
    Check if a specific action is available for a file.
    
    Args:
        filename: The filename to check
        action: The action to check ('open', 'view', or 'edit')
    
    Returns:
        True if the action is available, False otherwise
    """
```

**Returns**: Boolean indicating if action is available

### Pattern Matching

Pattern matching uses Python's `fnmatch` module:

```python
import fnmatch

if fnmatch.fnmatch(filename_lower, pattern.lower()):
    # Pattern matches
```

**Features**:
- Case-insensitive matching
- Wildcard support (`*`, `?`, `[seq]`, `[!seq]`)
- Standard Unix shell-style wildcards

**Examples**:
- `*.pdf` matches `document.pdf`, `file.PDF`
- `*.tar.gz` matches `archive.tar.gz`
- `image_*.jpg` matches `image_001.jpg`, `image_photo.jpg`

### Command Format Handling

Commands can be specified in multiple formats:

1. **List format** (preferred):
   ```python
   ['open', '-a', 'Preview']
   ```

2. **String format** (converted to list):
   ```python
   'open -a Preview'  # Converted to ['open', '-a', 'Preview']
   ```

3. **None** (action not available):
   ```python
   None  # Action not configured
   ```

The `get_program_for_file()` function normalizes all formats to list format or `None`.

## Integration Points

### Configuration System

File associations integrate with the existing configuration system:

1. **DefaultConfig class**: Provides default associations
2. **User Config class**: Allows user customization
3. **ConfigManager**: Handles loading and merging

### Usage in XeFM

Four handlers in `xefm/app.py` consult associations, one per action:

| Handler | Action | Fallback when unconfigured |
|---|---|---|
| `_enter_file()` (via `_open`) | `enter` | Built-in viewer |
| `open_with_os()` | `open` | OS default app (`open`/`xdg-open`/`start`) |
| `view_file()` | `view` | Built-in viewer |
| `edit_file()` | `edit` | `TEXT_EDITOR` |

> **History**: these call sites were wired in the pre-PuiKit `xefm_main.py`
> (commit `f2f60c51`), lost when that file was removed during the port, and
> restored here. In between, the engine below was complete and correct but had
> no production callers, so editing `FILE_ASSOCIATIONS` had no observable
> effect. If association behavior ever appears to "do nothing" again, check
> that these four handlers still call into `xefm.config` before debugging the
> matching logic.

All three external actions launch through one helper:

```python
def _launch_associated(self, entry, command, action) -> bool:
    """Returns False (having logged why) if the program could not be run,
    so the caller can fall back to its built-in behavior."""
```

Two rules it enforces:

1. **Local paths only.** An external program needs a real path on disk, so
   remote (`s3://`, `ssh://`) and in-archive entries always take the fallback
   — which for `view` means the built-in viewer, the one thing that *can* read
   them.
2. **Handover follows the backend.** `is_desktop_mode()` selects
   `_run_in_terminal()` (suspend, run, wait, restore, refresh) in terminal mode
   and a detached `subprocess.Popen` in desktop mode, where blocking would
   freeze the window and there is no tty to release.

Example integration:

```python
from xefm.config import get_program_for_file, has_explicit_association

command = get_program_for_file('document.pdf', 'view')
if command:
    launch(command)
elif has_explicit_association('document.pdf', 'view'):
    open_builtin_viewer()      # explicitly None -> built-in
else:
    apply_default_behavior()   # no rule at all
```

## OS-default fallback (`open_with_os`)

`open_with_os()` in `xefm/app.py` is the deliberate "hand this file to another
program" action (bound to Cmd/Ctrl-Enter), as opposed to Enter's
open-inside-XeFM. It is **not** association-blind: it consults `FILE_ASSOCIATIONS`
first, exactly like the other three handlers, and only reaches the OS default
when no rule applies.

> **Reconciliation note.** An earlier standalone doc described this action as a
> pure `platform.system()` dispatch to `open` / `xdg-open` / `start` with no
> mention of associations, and used older method names (`_action_open_with_os`,
> `_action_reveal_in_file_manager`). That is stale. The real dispatch order,
> confirmed against `open_with_os()`, is: association first, OS default second.

The dispatch, on the **focused entry** (not the whole selection):

1. `get_program_for_file(entry.name, 'open')` — a matching `open` command wins
   and is launched through `_launch_associated()`. On success, done.
2. `has_explicit_association(entry.name, 'open')` — an entry set explicitly to
   `None` **suppresses the launch entirely** and returns; this is how a file
   type is stopped from being handed to the OS at all.
3. Otherwise, fall back to the OS default application by platform:
   - macOS (`Darwin`): `open <file>`
   - Windows: `start "" <file>` (via `shell=True`)
   - Linux / other: `xdg-open <file>`

The fallback runs `subprocess.run(..., check=True)` directly and does **not**
suspend the renderer — these launchers open their target in a separate
application and return immediately, so there is no terminal handover to manage
(unlike `_launch_associated()`, which suspends in terminal mode). Errors are
logged, never raised. Platform detection uses `platform.system()`
(`'Darwin'` / `'Linux'` / `'Windows'`).

### Reveal in file manager (`reveal_in_os`)

`reveal_in_os()` is the companion action: it opens the OS file manager with the
focused entry selected. It ignores `FILE_ASSOCIATIONS` entirely (there is no
program to associate — the target is always the platform's file manager) and
operates only on the focused entry:

- macOS: `open -R <item>` — reveals/selects the item in Finder (files and
  directories alike).
- Windows: `explorer /select, <item>` — selects the item in Explorer.
- Linux / other: `xdg-open <parent>` — opens the containing directory (no
  portable "select this item" verb).

Default binding is `Alt-Enter` (`Ctrl-Shift-E` on Windows), configured under
`KEY_BINDINGS` in `xefm/_config.py`. As with `open_with_os`, the launcher
returns immediately, so the renderer is not suspended; errors are logged.

## Data Structures

### FILE_ASSOCIATIONS List (Compact Format)

```python
[
    {
        'pattern': '*.pdf',
        'open|view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Adobe Acrobat']
    },
    {
        'pattern': ['*.jpg', '*.jpeg', '*.png'],
        'open|view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Photoshop']
    }
]
```

**Structure**:
- Top-level: List of association entries
- Each entry: Dictionary with 'extensions' key and action keys
- 'pattern': String or list of extension patterns
- Action keys: 'open', 'view', 'edit', or combined like 'open|view'
- Values: Command lists, command strings, or None

**Expansion Example**:
```python
{
    'pattern': ['*.jpg', '*.png'],
    'open|view': ['preview']
}
```
Expands to:
- `('*.jpg', 'open', ['preview'])`
- `('*.jpg', 'view', ['preview'])`
- `('*.png', 'open', ['preview'])`
- `('*.png', 'view', ['preview'])`

## Performance Considerations

### Pattern Matching Performance

- Pattern matching is O(n*m) where n is number of entries and m is average extensions per entry
- First match wins (no priority system)
- Case conversion happens once per lookup
- Entry expansion happens on each lookup

**Optimization opportunities**:
- Cache expanded entries (pre-expand on config load)
- Cache pattern matching results
- Pre-compile patterns for faster matching
- Use more specific patterns first

### Memory Usage

- Associations stored in memory once at config load
- No significant memory overhead
- Command lists are small (typically 2-5 elements)

## Error Handling

### Missing Configuration

If `FILE_ASSOCIATIONS` is not defined:
- `get_file_associations()` returns empty dict
- `get_program_for_file()` returns `None`
- `has_action_for_file()` returns `False`

### Invalid Configuration

Invalid configurations are handled gracefully:

1. **Invalid pattern**: Skipped during matching
2. **Invalid action**: Returns `None` for that action
3. **Invalid command**: Returned as-is (will fail at execution)

### No Match Found

If no pattern matches:
- `get_program_for_file()` returns `None`
- `has_action_for_file()` returns `False`
- Caller should handle fallback behavior

## Testing

### Unit Tests

Test cases should cover:

1. **Pattern matching**:
   - Case-insensitive matching
   - Wildcard patterns
   - Multiple extensions

2. **Command format handling**:
   - List format
   - String format
   - None values

3. **Action availability**:
   - Available actions
   - Unavailable actions
   - Missing patterns

4. **Configuration loading**:
   - Default config
   - User config
   - Missing config

### Example Test

```python
def test_get_program_for_file():
    # Test PDF file
    command = get_program_for_file('document.pdf', 'view')
    assert command == ['open', '-a', 'Preview']
    
    # Test case-insensitive
    command = get_program_for_file('DOCUMENT.PDF', 'view')
    assert command == ['open', '-a', 'Preview']
    
    # Test unavailable action
    command = get_program_for_file('file.xyz', 'edit')
    assert command is None
```

## Future Enhancements

### Priority System

Add priority to patterns for more specific matching:

```python
'*.tar.gz': {'priority': 10, 'open': ['tar', '-xzf']},
'*.gz': {'priority': 5, 'open': ['gunzip']}
```

### MIME Type Support

Support MIME type matching in addition to extensions:

```python
'image/jpeg': {'open': ['open', '-a', 'Preview']},
'application/pdf': {'view': ['open', '-a', 'Preview']}
```

### Action Chaining

Support multiple programs for a single action:

```python
'*.pdf': {
    'open': [
        ['open', '-a', 'Preview'],
        ['open', '-a', 'Adobe Acrobat']
    ]
}
```

### Environment Variables

Support environment variable expansion in commands:

```python
'*.txt': {
    'edit': ['$EDITOR']  # Expands to user's preferred editor
}
```

## Dependencies

- **fnmatch**: Standard library module for pattern matching
- **xefm.config**: Configuration system
- **xefm.path**: Path handling utilities

## API Reference

### Public Functions

```python
def get_file_associations() -> dict
def get_program_for_file(filename: str, action: str = 'open') -> list | None
def has_action_for_file(filename: str, action: str = 'open') -> bool
```

### Configuration Attributes

```python
class DefaultConfig:
    FILE_ASSOCIATIONS: dict  # File extension associations

class Config:
    FILE_ASSOCIATIONS: dict  # User-customized associations
```
