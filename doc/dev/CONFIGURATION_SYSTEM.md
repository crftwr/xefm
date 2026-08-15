# XeFM Configuration System

XeFM includes a comprehensive configuration system that allows users to customize behavior, key bindings, and appearance through a Python configuration file.

## Configuration File Location

**User Config**: `~/.xefm/config.py`
**Template File**: `_config.py` (in XeFM installation directory)

- **Auto-Creation**: If the config file doesn't exist, XeFM automatically creates one from the template on first launch
- **Template-Based**: Default configuration is maintained in a separate `_config.py` template file
- **Python Format**: Configuration is stored as a Python class for flexibility and validation
- **User Directory**: User config located in the user's home directory for per-user customization
- **Clean Separation**: Template and user config are separate for easier maintenance

## Configuration Structure

### Config Class Format

```python
class Config:
    """User configuration for XeFM"""
    
    # Display settings
    SHOW_HIDDEN_FILES = False
    DEFAULT_LEFT_PANE_RATIO = 0.5
    DEFAULT_LOG_HEIGHT_RATIO = 0.25
    
    # Sorting settings
    DEFAULT_SORT_MODE = 'name'
    DEFAULT_SORT_REVERSE = False
    
    # ... more settings
```

## Available Configuration Options

### Display Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `SHOW_HIDDEN_FILES` | bool | `False` | Show hidden files by default (dot-names, plus the Windows hidden attribute) |
| `DEFAULT_LEFT_PANE_RATIO` | float | `0.5` | Left pane width ratio (0.1-0.9) |
| `DEFAULT_LOG_HEIGHT_RATIO` | float | `0.25` | Log pane height ratio (0.1-0.5) |

### Sorting Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `DEFAULT_SORT_MODE` | str | `'name'` | Default sort mode: 'name', 'size', 'date' |
| `DEFAULT_SORT_REVERSE` | bool | `False` | Default reverse sort order |

### Color Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|

### Behavior Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `CONFIRM_DELETE` | bool | `True` | Show confirmation for delete operations |
| `CONFIRM_QUIT` | bool | `True` | Show confirmation when quitting |
| `CONFIRM_COPY` | bool | `True` | Show confirmation for copy operations |
| `CONFIRM_MOVE` | bool | `True` | Show confirmation for move operations |
| `CONFIRM_EXTRACT_ARCHIVE` | bool | `True` | Show confirmation for archive extraction |

### Directory Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `STARTUP_LEFT_PATH` | str/None | `None` | Left pane startup path (None = current dir) |
| `STARTUP_RIGHT_PATH` | str/None | `None` | Right pane startup path (None = home dir) |

### Performance Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `MAX_LOG_MESSAGES` | int | `1000` | Maximum log messages to keep |

### Info Dialog Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `INFO_DIALOG_WIDTH_RATIO` | float | `0.8` | Info dialog width as screen ratio |
| `INFO_DIALOG_HEIGHT_RATIO` | float | `0.8` | Info dialog height as screen ratio |
| `INFO_DIALOG_MIN_WIDTH` | int | `20` | Minimum dialog width |
| `INFO_DIALOG_MIN_HEIGHT` | int | `10` | Minimum dialog height |

## Key Bindings Configuration

### Comprehensive Key Bindings System

XeFM now features a fully configurable key binding system where all keyboard shortcuts can be customized through the configuration file. Each action has a descriptive name and can be assigned multiple keys.

```python
KEY_BINDINGS = {
    # Application Control
    'quit': ['q', 'Q'],                    # Exit XeFM application
    'help': ['?'],                         # Show help dialog with all key bindings
    
    # Display & Navigation
    'toggle_hidden': ['.'],                # Toggle visibility of hidden files (dotfiles, Windows hidden attribute)
    'toggle_color_scheme': ['t'],          # Switch between dark and light color schemes
    
    # Search & Filter
    'search': ['f'],                       # Enter incremental search mode (isearch)
    'search_dialog': ['F'],                # Show filename search dialog
    'search_content': ['G'],               # Show content search dialog (grep)
    'filter': [';'],                       # Enter filter mode to show only matching files
    'clear_filter': [':'],                 # Clear current file filter
    
    # Sorting
    'sort_menu': ['s', 'S'],              # Open the sort dialog (key + order)
    'quick_sort_name': ['1'],              # Quick sort by filename
    'quick_sort_ext': ['2'],               # Quick sort by file extension
    'quick_sort_size': ['3'],              # Quick sort by file size
    'quick_sort_date': ['4'],              # Quick sort by modification date
    
    # File Selection
    'select_file': [' '],                  # Toggle selection of current file (Space)
    'select_all_files': ['a'],             # Toggle selection of all files in current pane
    'select_all_items': ['A'],             # Toggle selection of all items (files + dirs)
    
    # Pane Management
    'sync_current_to_other': ['o'],        # Sync current pane directory to other pane
    'sync_other_to_current': ['O'],        # Sync other pane directory to current pane
    'adjust_pane_left': ['['],            # Make left pane smaller (move boundary left)
    'adjust_pane_right': [']'],           # Make left pane larger (move boundary right)
    'adjust_log_up': ['{'],               # Make log pane larger (Shift+[)
    'adjust_log_down': ['}'],             # Make log pane smaller (Shift+])
    'reset_log_height': ['_'],            # Reset log pane height to default (Shift+-)
    
    # File Operations
    'view_text': ['v', 'V'],              # View text file in built-in viewer
    'edit_file': ['e'],                    # Edit selected file with configured text editor
    'create_file': ['E'],                  # Create new file (prompts for filename)
    'copy_files': ['c', 'C'],             # Copy selected files to other pane
    'move_files': ['m', 'M'],             # Move selected files to other pane
    'delete_files': ['k', 'K'],           # Delete selected files/directories
    'rename_file': ['r', 'R'],            # Rename selected file/directory
    
    # Advanced Features
    'file_details': ['i', 'I'],           # Show detailed file information dialog
    'favorites': ['j', 'J'],              # Show favorite directories dialog
    'subshell': ['X'],                     # Enter subshell (command line) mode
    'programs': ['x'],                     # Show external programs menu
    'create_archive': ['p', 'P'],         # Create archive from selected files
    'extract_archive': ['u', 'U'],        # Extract selected archive file
    'compare_selection': ['w', 'W'],      # Show file and directory comparison options
}
```

### Key Binding Features

- **Multiple Keys**: Each action can have multiple key bindings
- **Case Sensitive**: Separate bindings for uppercase/lowercase
- **Special Keys**: Support for space and other special characters
- **Descriptive Names**: Each action has a clear, descriptive name
- **Full Configurability**: All keyboard shortcuts can be customized
- **Validation**: Invalid key bindings are ignored with warnings
- **Comprehensive Coverage**: Covers all XeFM functionality including pane management

### New Pane Adjustment Keys

XeFM now includes dedicated keys for adjusting pane boundaries:

- **Horizontal Adjustment**: `[` and `]` keys adjust the boundary between left and right panes
- **Vertical Adjustment**: `{` and `}` keys adjust the log pane height
- **Reset Functions**: `-` resets horizontal split to 50/50, `_` resets log height to default
- **Intuitive Design**: Keys visually represent the direction of adjustment

## Architecture and Loading Flow

### Single Source of Truth

All configuration defaults live in the `Config` class in `xefm/_config.py`. There is
**no** second defaults class — the earlier `DefaultConfig` in `xefm/config.py` was
removed, so there are no longer "two configs" to keep in sync. `xefm/_config.py`
serves two roles:

1. **Template** — copied verbatim to `~/.xefm/config.py` on first run.
2. **Default provider** — the source used to fill in any fields a user config is
   missing.

### Automatic Field Copying

When XeFM loads configuration it:

1. Loads the user's `~/.xefm/config.py` (if present).
2. Loads the template `Config` class from `xefm/_config.py`.
3. Copies any missing public fields from the template into the user config.
4. Returns a complete config with every field present.

This means new options appear automatically in existing user configs, corrupted
configs are backfilled with defaults, and users never have to hand-edit their
config to pick up newly added settings.

### Loading Flow

```
1. ConfigManager.load_config() called
2. Load template Config class from xefm/_config.py   (_load_template_config)
3. Does ~/.xefm/config.py exist?
   - No  -> create_default_config() copies xefm/_config.py to ~/.xefm/config.py
   - Yes -> import and instantiate the user's Config
            (on error, fall back to an empty config filled from the template)
4. _copy_missing_fields(user_config, template_class) backfills any missing
   public attributes, logging each field added
5. Return the complete config with all fields present
```

### Key Components (`xefm/config.py`)

- **`ConfigManager`** — loads, caches, and provides access to config. Key methods:
  `load_config()`, `get_config()`, `reload_config()`, `create_default_config()`,
  `validate_config()`, `get_key_bindings()`.
- **`_load_template_config()`** — dynamically imports the `Config` class from
  `xefm/_config.py` and returns the class (not an instance) for field inspection;
  returns `None` on failure.
- **`_copy_missing_fields(user_config, template_config_class)`** — copies public
  (non-`_`) attributes present on the template but missing on the user config,
  logging each addition and the total count.
- **`KeyBindings`** — key-binding lookup and parsing
  (`find_action_for_event`, `get_keys_for_action`, `format_key_for_display`).

> `validate_config()` builds a merged `Config` from `xefm/_config.py` internally to
> check ranges/types — it is a local helper, not a separate defaults class.

### Adding a New Option

1. Add the field to the `Config` class in `xefm/_config.py`.
2. That's it — the field is copied into existing user configs on next launch and
   logged (`Added missing config field: <NAME>`). There is no second class to update.

## Configuration Management

### Automatic Loading

1. **Startup Check**: XeFM checks for `~/.xefm/config.py` on launch
2. **Auto-Creation**: Creates the user config from the `xefm/_config.py` template if the file doesn't exist
3. **Template-Based**: Uses the single `xefm/_config.py` template as the source of defaults
4. **Error Handling**: Fills missing fields from the `xefm/_config.py` template if the config is incomplete or invalid
5. **Validation**: Validates configuration values and reports errors

### Configuration API

```python
from xefm import config

# Get current configuration
config = xefm.config.get_config()

# Reload configuration from file
xefm.config.reload_config()

# Check key bindings
is_bound = xefm.config.is_key_bound_to('q', 'quit')

# Get startup paths
left_path, right_path = xefm.config.get_startup_paths()
```

## Customization Examples

### Example 1: Change Default Directories

```python
class Config:
    # Start left pane in projects directory
    STARTUP_LEFT_PATH = "~/projects"
    
    # Start right pane in downloads
    STARTUP_RIGHT_PATH = "~/Downloads"
```

### Example 2: Customize Key Bindings

```python
class Config:
    KEY_BINDINGS = {
        'quit': ['q'],  # Remove 'Q' binding
        'file_details': ['i', 'I', 'd'],  # Add 'd' for details
        'search': ['/', 'f'],  # Add '/' for search
        'sync_current_to_other': ['o', '>'],  # Add '>' for sync
        'sync_other_to_current': ['O', '<'],  # Add '<' for reverse sync
        'adjust_pane_left': ['[', 'h'],  # Add 'h' for left adjustment
        'adjust_pane_right': [']', 'l'],  # Add 'l' for right adjustment
        'toggle_color_scheme': ['t', 'c'],  # Add 'c' for color toggle
        # ... other bindings
    }
```

### Example 3: Adjust Display Settings

```python
class Config:
    # Show hidden files by default
    SHOW_HIDDEN_FILES = True
    
    # Wider left pane (70/30 split)
    DEFAULT_LEFT_PANE_RATIO = 0.7
    
    # Smaller log pane
    DEFAULT_LOG_HEIGHT_RATIO = 0.15
    
    # Disable quit confirmation
    CONFIRM_QUIT = False
    
    # Disable copy and move confirmations for faster workflow
    CONFIRM_COPY = False
    CONFIRM_MOVE = False
    
    # Keep extract confirmation for safety
    CONFIRM_EXTRACT_ARCHIVE = True
```

### Example 4: Performance Tuning

```python
class Config:
    # Keep more log messages
    MAX_LOG_MESSAGES = 5000
    
    # Larger info dialogs
    INFO_DIALOG_WIDTH_RATIO = 0.9
    INFO_DIALOG_HEIGHT_RATIO = 0.9
```

### Example 5: Confirmation Settings

```python
class Config:
    # Safety-first approach - confirm all operations
    CONFIRM_DELETE = True
    CONFIRM_QUIT = True
    CONFIRM_COPY = True
    CONFIRM_MOVE = True
    CONFIRM_EXTRACT_ARCHIVE = True
```

```python
class Config:
    # Speed-focused approach - minimal confirmations
    CONFIRM_DELETE = True      # Keep for safety
    CONFIRM_QUIT = False       # Quick exit
    CONFIRM_COPY = False       # Fast copying
    CONFIRM_MOVE = False       # Fast moving
    CONFIRM_EXTRACT_ARCHIVE = False  # Quick extraction
```

## Configuration Validation

### Automatic Validation

- **Range Checks**: Ratios must be within valid ranges
- **Type Validation**: Settings must be correct types
- **Value Validation**: Enum values are checked
- **Error Reporting**: Invalid settings are reported with warnings

### Validation Rules

- `DEFAULT_LEFT_PANE_RATIO`: Must be between 0.1 and 0.9
- `DEFAULT_LOG_HEIGHT_RATIO`: Must be between 0.1 and 0.5
- `DEFAULT_SORT_MODE`: Must be 'name', 'size', or 'date'
- `COLOR_SCHEME`: Must be 'default', 'dark', or 'light'

## Error Handling

### Configuration Errors

1. **File Not Found**: Creates the user config from the `xefm/_config.py` template
2. **Syntax Errors**: Loads an empty config and fills all fields from the `xefm/_config.py` template
3. **Missing Config Class**: Fills all fields from the template
4. **Invalid Values**: Uses template defaults for invalid settings
5. **Permission Errors**: Reports warning and falls back to template defaults

### Fallback Behavior

- **Graceful Degradation**: XeFM always starts even with config errors
- **Template Defaults**: Missing or invalid fields are filled from the `xefm/_config.py` template
- **Error Logging**: Configuration errors are logged to the log pane
- **User Notification**: Clear messages about configuration issues

## Template System

### Configuration Template

XeFM uses a template-based configuration system for better maintainability:

- **Template File**: `_config.py` contains the default configuration template
- **Clean Defaults**: Template is maintained separately from user configuration
- **Easy Updates**: Template can be updated without affecting user configs
- **Consistent Creation**: All new user configs are created from the same template

### Template Benefits

1. **Maintainability**: Default configuration is in a separate, version-controlled file
2. **Consistency**: All users get the same default configuration structure
3. **Documentation**: Template includes comprehensive comments and examples
4. **Upgrades**: Template can be updated independently of user configurations

### Template Structure

The `_config.py` template includes:
- Complete configuration class with all available options
- Detailed comments explaining each setting
- Example values and valid ranges
- Organized sections for different setting categories

## Advanced Features

### Dynamic Configuration

- **Runtime Changes**: Some settings can be changed during runtime
- **Configuration Reload**: Reload config without restarting XeFM
- **Validation Feedback**: Real-time validation of configuration changes

### Future Enhancements

- **GUI Configuration Editor**: Visual configuration editor
- **Multiple Profiles**: Support for different configuration profiles
- **Plugin System**: Configuration for custom plugins
- **Theme System**: Advanced color theme configuration

## Troubleshooting

### Common Issues

1. **Config File Not Loading**:
   - Check file permissions
   - Verify Python syntax
   - Ensure Config class exists

2. **Invalid Key Bindings**:
   - Check key binding format
   - Ensure keys are single characters
   - Verify action names are correct

3. **Path Issues**:
   - Use absolute paths or ~ for home directory
   - Ensure directories exist
   - Check path permissions

## Configuration File Example

Here's a complete example configuration file:

```python
#!/usr/bin/env python3
\"\"\"
XeFM User Configuration - Custom Setup
\"\"\"

class Config:
    # Display preferences
    SHOW_HIDDEN_FILES = True
    DEFAULT_LEFT_PANE_RATIO = 0.6
    DEFAULT_LOG_HEIGHT_RATIO = 0.2
    
    # Sorting preferences
    DEFAULT_SORT_MODE = 'date'
    DEFAULT_SORT_REVERSE = True
    
    # Behavior
    CONFIRM_DELETE = True
    CONFIRM_QUIT = False
    CONFIRM_COPY = True
    CONFIRM_MOVE = True
    CONFIRM_EXTRACT_ARCHIVE = False
    
    # Startup directories
    STARTUP_LEFT_PATH = \"~/projects\"
    STARTUP_RIGHT_PATH = \"~/Downloads\"
    
    # Custom key bindings
    KEY_BINDINGS = {
        # Application control
        'quit': ['q'],
        'help': ['?'],
        
        # Navigation and display
        'toggle_hidden': ['.'],
        'toggle_color_scheme': ['t'],
        
        # Search and filter
        'search': ['/', 'f'],  # Add '/' for search
        'search_dialog': ['F'],
        'filter': [';'],
        'clear_filter': [':'],
        
        # File operations
        'file_details': ['i', 'd'],  # Add 'd' for details
        'edit_file': ['e'],
        'view_text': ['v'],
        'copy_files': ['c'],
        'move_files': ['m'],
        'delete_files': ['k'],
        
        # Pane management
        'sync_current_to_other': ['o'],
        'sync_other_to_current': ['O'],
        'adjust_pane_left': ['['],
        'adjust_pane_right': [']'],
        'adjust_log_up': ['{'],
        'adjust_log_down': ['}'],
        'reset_log_height': ['_'],
        
        # Selection
        'select_file': [' '],
        'select_all_files': ['a'],
        'select_all_items': ['A'],
        
        # Sorting
        'sort_menu': ['s'],
        'quick_sort_name': ['1'],
        'quick_sort_size': ['2'],
        'quick_sort_date': ['3'],
    }
    
    # Performance
    MAX_LOG_MESSAGES = 2000
    INFO_DIALOG_WIDTH_RATIO = 0.85
```

The configuration system provides extensive customization while maintaining simplicity and reliability through automatic defaults and comprehensive error handling.