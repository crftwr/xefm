"""
Color definitions and initialization for XeFM
"""
from typing import Tuple, Optional

try:
    from puikit import TextAttribute
except ImportError:
    # Fallback for when PuiKit is not available (during testing). Mirrors
    # puikit.TextAttribute (an IntFlag) for the attributes XeFM uses.
    from enum import IntFlag
    class TextAttribute(IntFlag):
        NORMAL = 0
        BOLD = 1
        UNDERLINE = 2
        REVERSE = 4

# Color pair constants
# Note: Color pair 1 is reserved for terminal background in curses backend

# File type colors (normal)
COLOR_REGULAR_FILE = 28      # Regular files (changed from 1 to avoid conflict with terminal background)
COLOR_DIRECTORIES = 2        # Directories
COLOR_EXECUTABLES = 3        # Executable files

# File type colors (focused)
COLOR_REGULAR_FILE_FOCUSED = 4    # Focused regular files
COLOR_DIRECTORIES_FOCUSED = 5     # Focused directories
COLOR_EXECUTABLES_FOCUSED = 6     # Focused executables

# File type colors (focused inactive)
COLOR_REGULAR_FILE_FOCUSED_INACTIVE = 24    # Focused regular files in inactive pane
COLOR_DIRECTORIES_FOCUSED_INACTIVE = 25     # Focused directories in inactive pane
COLOR_EXECUTABLES_FOCUSED_INACTIVE = 26     # Focused executables in inactive pane

# Interface colors
COLOR_HEADER = 7        # File list headers (directory paths)
COLOR_FOOTER = 8        # File list footers (file counts)
COLOR_STATUS = 9        # Status bar
COLOR_BOUNDARY = 10     # Pane boundaries
COLOR_ERROR = 11        # Error messages

# Log colors
COLOR_LOG_STDOUT = 12   # Stdout log messages
COLOR_LOG_SYSTEM = 13   # System log messages
COLOR_LOG_WARNING = 31  # Warning log messages
COLOR_LINE_NUMBERS = 14 # Line numbers in text viewer

# Syntax highlighting colors
COLOR_SYNTAX_KEYWORD = 15    # Keywords (def, class, if, etc.)
COLOR_SYNTAX_STRING = 16     # String literals
COLOR_SYNTAX_COMMENT = 17    # Comments
COLOR_SYNTAX_NUMBER = 18     # Numbers
COLOR_SYNTAX_OPERATOR = 19   # Operators (+, -, =, etc.)
COLOR_SYNTAX_BUILTIN = 20    # Built-in functions/types
COLOR_SYNTAX_NAME = 21       # Variable/function names

# Search highlighting colors
COLOR_SEARCH_MATCH = 22      # Search match highlighting
COLOR_SEARCH_CURRENT = 23    # Current search match highlighting

# Background color pair
COLOR_BACKGROUND = 27        # Background color for filling areas

# Scroll bar colors
COLOR_SCROLLBAR = 29         # Scroll bar (uses different characters for track and thumb)

# Diff viewer colors
COLOR_DIFF_ONLY_ONE_SIDE = 30  # Lines only in one side (delete/insert)
COLOR_DIFF_CHANGE = 32         # Changed lines in diff viewer (yellow background)
COLOR_DIFF_BLANK = 33          # Blank lines in diff viewer (for alignment)
COLOR_DIFF_CHAR_CHANGE = 34    # Character-level changes within lines (bright highlight)
COLOR_DIFF_FOCUSED = 35        # Focused difference (highlighted background)
COLOR_DIFF_SEPARATOR_RED = 36  # Red separator for differences (red fg, status bg)
COLOR_TREE_LINES = 37          # Gray color for tree lines (├─ └─ │)

# Matrix animation colors (for About dialog)
COLOR_MATRIX_BRIGHT = 38       # Bright green for Matrix head (brightest)
COLOR_MATRIX_MEDIUM = 39       # Medium green for Matrix middle
COLOR_MATRIX_DIM = 40          # Dim green for Matrix tail (dimmest)

# Current color scheme
current_color_scheme = 'dark'

# Default background and foreground colors for the current scheme
default_background_color = None
default_foreground_color = None

# Color scheme definitions (RGB values 0-255)
COLOR_SCHEMES = {
    'dark': {
        'HEADER_BG': {
            'color_num': 100,
            'rgb': (51, 63, 76)     # Dark blue-gray for file list headers
        },
        'FOOTER_BG': {
            'color_num': 104,
            'rgb': (51, 63, 76)     # Dark blue-gray for file list footers
        },
        'STATUS_BG': {
            'color_num': 105,
            'rgb': (51, 63, 76)     # Dark blue-gray for status bar
        },
        'BOUNDARY_BG': {
            'color_num': 106,
            'rgb': (51, 63, 76)     # Dark blue-gray for boundaries
        },
        'DIRECTORY_FG': {
            'color_num': 101,
            'rgb': (204, 204, 120)  # Yellow for directories
        },
        'EXECUTABLE_FG': {
            'color_num': 102,
            'rgb': (51, 229, 51)    # Bright green for executables
        },
        'FOCUSED_BG': {
            'color_num': 103,
            'rgb': (40, 80, 160)    # Dark blue-purple background for focused items
        },
        'FOCUSED_INACTIVE_BG': {
            'color_num': 150,
            'rgb': (80, 80, 80)    # Darker blue background for focused items in inactive pane
        },
        'REGULAR_FILE_FG': {
            'color_num': 107,
            'rgb': (220, 220, 220)  # Light gray for regular files
        },
        'LOG_STDOUT_FG': {
            'color_num': 108,
            'rgb': (220, 220, 220)  # Light gray for stdout logs
        },
        'LOG_SYSTEM_FG': {
            'color_num': 109,
            'rgb': (100, 200, 255)  # Light blue for system logs
        },
        'LOG_WARNING_FG': {
            'color_num': 158,
            'rgb': (255, 165, 0)    # Orange for warning logs
        },
        'LINE_NUMBERS_FG': {
            'color_num': 110,
            'rgb': (128, 128, 128)  # Gray for line numbers
        },
        # Syntax highlighting colors
        'SYNTAX_KEYWORD_FG': {
            'color_num': 111,
            'rgb': (255, 119, 0)    # Orange for keywords
        },
        'SYNTAX_STRING_FG': {
            'color_num': 112,
            'rgb': (0, 255, 0)      # Green for strings
        },
        'SYNTAX_COMMENT_FG': {
            'color_num': 113,
            'rgb': (128, 128, 128)  # Gray for comments
        },
        'SYNTAX_NUMBER_FG': {
            'color_num': 114,
            'rgb': (255, 255, 0)    # Yellow for numbers
        },
        'SYNTAX_OPERATOR_FG': {
            'color_num': 115,
            'rgb': (255, 0, 255)    # Magenta for operators
        },
        'SYNTAX_BUILTIN_FG': {
            'color_num': 116,
            'rgb': (0, 255, 255)    # Cyan for built-ins
        },
        'SYNTAX_NAME_FG': {
            'color_num': 117,
            'rgb': (220, 220, 220)  # Light gray for names
        },
        # Search highlighting colors
        'SEARCH_MATCH_BG': {
            'color_num': 118,
            'rgb': (30, 60, 120)    # Dark blue background for search matches
        },
        'SEARCH_CURRENT_BG': {
            'color_num': 119,
            'rgb': (40, 80, 160)    # Medium blue background for current search match
        },
        # Scroll bar colors
        'SCROLLBAR_FG': {
            'color_num': 148,
            'rgb': (150, 150, 150)  # Light gray for scroll bar (thumb uses █, track uses │)
        },
        'SCROLLBAR_BG': {
            'color_num': 149,
            'rgb': (60, 60, 60)     # Dark gray for scroll bar
        },
        'DEFAULT_FG': {
            'color_num': 146,
            'rgb': (220, 220, 220)  # Light gray for default foreground
        },
        'DEFAULT_BG': {
            'color_num': 147,
            'rgb': (0, 0, 0)        # Black for default background
        },
        # Diff viewer colors
        'DIFF_ONLY_ONE_SIDE_BG': {
            'color_num': 152,
            'rgb': (30, 80, 50)     # Green-based background for lines only in one side (delete/insert)
        },
        'DIFF_CHANGE_BG': {
            'color_num': 154,
            'rgb': (70, 40, 40)     # Red-based background for different lines (less prominent than CHAR_CHANGE)
        },
        'DIFF_BLANK_BG': {
            'color_num': 155,
            'rgb': (50, 50, 50)     # Gray background for dummy lines (alignment)
        },
        'DIFF_CHAR_CHANGE_BG': {
            'color_num': 156,
            'rgb': (140, 40, 40)    # Red-based background for different characters (more prominent)
        },
        'DIFF_FOCUSED_BG': {
            'color_num': 157,
            'rgb': (60, 70, 140)    # Blue-based background for focused lines (more prominent than CHANGE)
        },
        # Matrix animation colors (bright white to black gradient)
        'MATRIX_BRIGHT_FG': {
            'color_num': 161,
            'rgb': (220, 255, 220)  # Almost white with slight green tint for Matrix head (1 char)
        },
        'MATRIX_MEDIUM_FG': {
            'color_num': 162,
            'rgb': (0, 200, 0)      # Bright green for Matrix middle (main trail)
        },
        'MATRIX_DIM_FG': {
            'color_num': 163,
            'rgb': (0, 100, 0)      # Dim green for Matrix tail (2 chars)
        }
    },
    'light': {
        'HEADER_BG': {
            'color_num': 120,
            'rgb': (220, 220, 220)     # Light gray for file list headers
        },
        'FOOTER_BG': {
            'color_num': 124,
            'rgb': (220, 220, 220)     # Light gray for file list footers
        },
        'STATUS_BG': {
            'color_num': 125,
            'rgb': (220, 220, 220)     # Light gray for status bar
        },
        'BOUNDARY_BG': {
            'color_num': 126,
            'rgb': (220, 220, 220)     # Light gray for boundaries
        },
        'DIRECTORY_FG': {
            'color_num': 121,
            'rgb': (160, 120, 0)  # Dark yellow/brown for directories
        },
        'EXECUTABLE_FG': {
            'color_num': 122,
            'rgb': (0, 160, 0)    # Dark green for executables
        },
        'FOCUSED_BG': {
            'color_num': 123,
            'rgb': (120, 160, 255)    # Light blue background for focused items
        },
        'FOCUSED_INACTIVE_BG': {
            'color_num': 151,
            'rgb': (160, 160, 160)    # Lighter blue background for focused items in inactive pane
        },
        'REGULAR_FILE_FG': {
            'color_num': 127,
            'rgb': (60, 60, 60)     # Dark gray for regular files
        },
        'LOG_STDOUT_FG': {
            'color_num': 128,
            'rgb': (60, 60, 60)     # Dark gray for stdout logs
        },
        'LOG_SYSTEM_FG': {
            'color_num': 129,
            'rgb': (50, 100, 160)  # Dark blue for system logs
        },
        'LOG_WARNING_FG': {
            'color_num': 159,
            'rgb': (255, 140, 0)    # Dark orange for warning logs
        },
        'LINE_NUMBERS_FG': {
            'color_num': 130,
            'rgb': (128, 128, 128)  # Gray for line numbers
        },
        # Syntax highlighting colors
        'SYNTAX_KEYWORD_FG': {
            'color_num': 131,
            'rgb': (128, 0, 128)    # Purple for keywords
        },
        'SYNTAX_STRING_FG': {
            'color_num': 132,
            'rgb': (0, 128, 0)      # Dark green for strings
        },
        'SYNTAX_COMMENT_FG': {
            'color_num': 133,
            'rgb': (128, 128, 128)  # Gray for comments
        },
        'SYNTAX_NUMBER_FG': {
            'color_num': 134,
            'rgb': (0, 0, 200)      # Blue for numbers
        },
        'SYNTAX_OPERATOR_FG': {
            'color_num': 135,
            'rgb': (200, 0, 0)      # Red for operators
        },
        'SYNTAX_BUILTIN_FG': {
            'color_num': 136,
            'rgb': (0, 128, 128)    # Teal for built-ins
        },
        'SYNTAX_NAME_FG': {
            'color_num': 137,
            'rgb': (64, 64, 64)     # Dark gray for names
        },
        # Search highlighting colors
        'SEARCH_MATCH_BG': {
            'color_num': 138,
            'rgb': (180, 240, 255)    # Very light blue background for search matches
        },
        'SEARCH_CURRENT_BG': {
            'color_num': 139,
            'rgb': (140, 200, 255)    # Light blue background for current search match
        },
        # Scroll bar colors
        'SCROLLBAR_FG': {
            'color_num': 150,
            'rgb': (60, 60, 60)     # Dark gray for scroll bar (thumb uses █, track uses │)
        },
        'SCROLLBAR_BG': {
            'color_num': 151,
            'rgb': (150, 150, 150)  # Light gray background for scroll bar
        },
        'DEFAULT_FG': {
            'color_num': 148,
            'rgb': (0, 0, 0)        # Black for default foreground
        },
        'DEFAULT_BG': {
            'color_num': 149,
            'rgb': (255, 255, 255)  # White for default background
        },
        # Diff viewer colors
        'DIFF_ONLY_ONE_SIDE_BG': {
            'color_num': 152,
            'rgb': (200, 240, 220)  # Light green-based background for lines only in one side (delete/insert)
        },
        'DIFF_CHANGE_BG': {
            'color_num': 154,
            'rgb': (240, 220, 220)  # Light red-based background for different lines (less prominent than CHAR_CHANGE)
        },
        'DIFF_BLANK_BG': {
            'color_num': 155,
            'rgb': (230, 230, 230)  # Light gray background for blank lines (alignment)
        },
        'DIFF_CHAR_CHANGE_BG': {
            'color_num': 156,
            'rgb': (255, 180, 180)  # Light red-based background for different characters (more prominent)
        },
        'DIFF_FOCUSED_BG': {
            'color_num': 157,
            'rgb': (200, 210, 255)  # Light blue-based background for focused lines (more prominent than CHANGE)
        },
        # Matrix animation colors (inverted for light theme: black to white gradient)
        'MATRIX_BRIGHT_FG': {
            'color_num': 161,
            'rgb': (0, 0, 0)        # Black for Matrix head (1 char) - inverted from dark theme
        },
        'MATRIX_MEDIUM_FG': {
            'color_num': 162,
            'rgb': (0, 120, 0)      # Dark green for Matrix middle (main trail)
        },
        'MATRIX_DIM_FG': {
            'color_num': 163,
            'rgb': (180, 220, 180)  # Light green (close to white) for Matrix tail (2 chars)
        }
    }
}

# Backward compatibility - use current scheme's colors
def get_current_rgb_colors():
    """Get RGB colors for the current color scheme"""
    return COLOR_SCHEMES.get(current_color_scheme, COLOR_SCHEMES['dark'])

def init_colors(renderer, color_scheme=None):
    """
    Initialize all color pairs for the application.
    
    Args:
        renderer: Renderer instance
        color_scheme: Optional color scheme name ('dark' or 'light')
    """
    global current_color_scheme, default_background_color, default_foreground_color
    
    # Set color scheme from parameter or use current
    if color_scheme:
        current_color_scheme = color_scheme
    
    # Full RGB throughout; the renderer approximates on 8/16-color terminals.
    if hasattr(renderer, 'set_fullcolor_mode'):
        renderer.set_fullcolor_mode(True)
    
    # Clear color cache to allow reinitialization with new colors
    # This is essential for color scheme switching to work properly
    if hasattr(renderer, 'clear_color_cache'):
        renderer.clear_color_cache()
    
    # Get RGB colors for current scheme
    rgb_colors = get_current_rgb_colors()
    
    # Extract default background color first
    default_bg = rgb_colors['DEFAULT_BG']['rgb']
    
    # Update terminal background color to match the color scheme
    # This ensures all areas (including where no characters are drawn) have the correct background
    if hasattr(renderer, 'update_background'):
        renderer.update_background(default_bg)
    
    # Extract RGB tuples from color definitions
    header_bg = rgb_colors['HEADER_BG']['rgb']
    footer_bg = rgb_colors['FOOTER_BG']['rgb']
    status_bg = rgb_colors['STATUS_BG']['rgb']
    boundary_bg = rgb_colors['BOUNDARY_BG']['rgb']
    directory_fg = rgb_colors['DIRECTORY_FG']['rgb']
    executable_fg = rgb_colors['EXECUTABLE_FG']['rgb']
    focused_bg = rgb_colors['FOCUSED_BG']['rgb']
    focused_inactive_bg = rgb_colors['FOCUSED_INACTIVE_BG']['rgb']
    regular_file_fg = rgb_colors['REGULAR_FILE_FG']['rgb']
    log_stdout_fg = rgb_colors['LOG_STDOUT_FG']['rgb']
    log_system_fg = rgb_colors['LOG_SYSTEM_FG']['rgb']
    log_warning_fg = rgb_colors['LOG_WARNING_FG']['rgb']
    line_numbers_fg = rgb_colors['LINE_NUMBERS_FG']['rgb']
    # Syntax highlighting colors
    syntax_keyword_fg = rgb_colors['SYNTAX_KEYWORD_FG']['rgb']
    syntax_string_fg = rgb_colors['SYNTAX_STRING_FG']['rgb']
    syntax_comment_fg = rgb_colors['SYNTAX_COMMENT_FG']['rgb']
    syntax_number_fg = rgb_colors['SYNTAX_NUMBER_FG']['rgb']
    syntax_operator_fg = rgb_colors['SYNTAX_OPERATOR_FG']['rgb']
    syntax_builtin_fg = rgb_colors['SYNTAX_BUILTIN_FG']['rgb']
    syntax_name_fg = rgb_colors['SYNTAX_NAME_FG']['rgb']
    # Search highlighting colors
    search_match_bg = rgb_colors['SEARCH_MATCH_BG']['rgb']
    search_current_bg = rgb_colors['SEARCH_CURRENT_BG']['rgb']
    # Default colors
    default_fg = rgb_colors['DEFAULT_FG']['rgb']
    default_bg = rgb_colors['DEFAULT_BG']['rgb']
    
    # Store default colors for later use
    default_background_color = default_bg
    default_foreground_color = default_fg
    
    # Initialize color pairs
    # Note: Color pair 0 is reserved for default colors
    
    # File type colors (normal)
    renderer.init_color_pair(COLOR_REGULAR_FILE, regular_file_fg, default_bg)
    renderer.init_color_pair(COLOR_DIRECTORIES, directory_fg, default_bg)
    renderer.init_color_pair(COLOR_EXECUTABLES, executable_fg, default_bg)
    
    # File type colors (focused)
    renderer.init_color_pair(COLOR_REGULAR_FILE_FOCUSED, regular_file_fg, focused_bg)
    renderer.init_color_pair(COLOR_DIRECTORIES_FOCUSED, directory_fg, focused_bg)
    renderer.init_color_pair(COLOR_EXECUTABLES_FOCUSED, executable_fg, focused_bg)
    
    # File type colors (focused inactive)
    renderer.init_color_pair(COLOR_REGULAR_FILE_FOCUSED_INACTIVE, regular_file_fg, focused_inactive_bg)
    renderer.init_color_pair(COLOR_DIRECTORIES_FOCUSED_INACTIVE, directory_fg, focused_inactive_bg)
    renderer.init_color_pair(COLOR_EXECUTABLES_FOCUSED_INACTIVE, executable_fg, focused_inactive_bg)
    
    # Interface colors
    renderer.init_color_pair(COLOR_HEADER, default_fg, header_bg)
    renderer.init_color_pair(COLOR_FOOTER, default_fg, footer_bg)
    renderer.init_color_pair(COLOR_STATUS, default_fg, status_bg)
    renderer.init_color_pair(COLOR_BOUNDARY, default_fg, boundary_bg)
    renderer.init_color_pair(COLOR_ERROR, (255, 0, 0), default_bg)  # Red for errors
    
    # Log colors
    renderer.init_color_pair(COLOR_LOG_STDOUT, log_stdout_fg, default_bg)
    renderer.init_color_pair(COLOR_LOG_SYSTEM, log_system_fg, default_bg)
    renderer.init_color_pair(COLOR_LOG_WARNING, log_warning_fg, default_bg)
    renderer.init_color_pair(COLOR_LINE_NUMBERS, line_numbers_fg, default_bg)
    
    # Syntax highlighting color pairs
    renderer.init_color_pair(COLOR_SYNTAX_KEYWORD, syntax_keyword_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_STRING, syntax_string_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_COMMENT, syntax_comment_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_NUMBER, syntax_number_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_OPERATOR, syntax_operator_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_BUILTIN, syntax_builtin_fg, default_bg)
    renderer.init_color_pair(COLOR_SYNTAX_NAME, syntax_name_fg, default_bg)
    
    # Search highlighting color pairs
    renderer.init_color_pair(COLOR_SEARCH_MATCH, default_fg, search_match_bg)
    renderer.init_color_pair(COLOR_SEARCH_CURRENT, default_fg, search_current_bg)
    
    # Scroll bar colors
    scrollbar_fg = rgb_colors['SCROLLBAR_FG']['rgb']
    scrollbar_bg = rgb_colors['SCROLLBAR_BG']['rgb']
    renderer.init_color_pair(COLOR_SCROLLBAR, scrollbar_fg, scrollbar_bg)
    
    # Background color pair for filling areas
    renderer.init_color_pair(COLOR_BACKGROUND, default_fg, default_bg)
    
    # Diff viewer colors
    diff_only_one_side_bg = rgb_colors['DIFF_ONLY_ONE_SIDE_BG']['rgb']
    diff_change_bg = rgb_colors['DIFF_CHANGE_BG']['rgb']
    diff_blank_bg = rgb_colors['DIFF_BLANK_BG']['rgb']
    diff_char_change_bg = rgb_colors['DIFF_CHAR_CHANGE_BG']['rgb']
    diff_focused_bg = rgb_colors['DIFF_FOCUSED_BG']['rgb']
    renderer.init_color_pair(COLOR_DIFF_ONLY_ONE_SIDE, default_fg, diff_only_one_side_bg)
    renderer.init_color_pair(COLOR_DIFF_CHANGE, default_fg, diff_change_bg)
    renderer.init_color_pair(COLOR_DIFF_BLANK, default_fg, diff_blank_bg)
    renderer.init_color_pair(COLOR_DIFF_CHAR_CHANGE, default_fg, diff_char_change_bg)
    renderer.init_color_pair(COLOR_DIFF_FOCUSED, default_fg, diff_focused_bg)
    # Red separator for differences (red foreground, status background)
    renderer.init_color_pair(COLOR_DIFF_SEPARATOR_RED, (255, 0, 0), status_bg)
    # Gray color for tree lines
    renderer.init_color_pair(COLOR_TREE_LINES, (128, 128, 128), default_bg)
    
    # Matrix animation colors (for About dialog)
    matrix_bright_fg = rgb_colors['MATRIX_BRIGHT_FG']['rgb']
    matrix_medium_fg = rgb_colors['MATRIX_MEDIUM_FG']['rgb']
    matrix_dim_fg = rgb_colors['MATRIX_DIM_FG']['rgb']
    renderer.init_color_pair(COLOR_MATRIX_BRIGHT, matrix_bright_fg, default_bg)
    renderer.init_color_pair(COLOR_MATRIX_MEDIUM, matrix_medium_fg, default_bg)
    renderer.init_color_pair(COLOR_MATRIX_DIM, matrix_dim_fg, default_bg)

def get_file_color(is_dir, is_executable, is_focused, is_active):
    """
    Get the appropriate color pair and attributes for a file based on its properties.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    # Handle focused files with common background color
    if is_focused and is_active:
        if is_dir:
            return COLOR_DIRECTORIES_FOCUSED, TextAttribute.NORMAL
        elif is_executable:
            return COLOR_EXECUTABLES_FOCUSED, TextAttribute.NORMAL
        else:
            return COLOR_REGULAR_FILE_FOCUSED, TextAttribute.NORMAL
    
    # Handle inactive focus with dedicated colors
    if is_focused:
        if is_dir:
            return COLOR_DIRECTORIES_FOCUSED_INACTIVE, TextAttribute.NORMAL
        elif is_executable:
            return COLOR_EXECUTABLES_FOCUSED_INACTIVE, TextAttribute.NORMAL
        else:
            return COLOR_REGULAR_FILE_FOCUSED_INACTIVE, TextAttribute.NORMAL
    
    # Normal (unfocused) files
    if is_dir:
        return COLOR_DIRECTORIES, TextAttribute.NORMAL
    elif is_executable:
        return COLOR_EXECUTABLES, TextAttribute.NORMAL
    else:
        return COLOR_REGULAR_FILE, TextAttribute.NORMAL



def get_header_color(is_active=False):
    """
    Get header color pair and attributes with optional bold for active panes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    if is_active:
        return COLOR_HEADER, TextAttribute.BOLD
    else:
        return COLOR_HEADER, TextAttribute.NORMAL

def get_footer_color(is_active=False):
    """
    Get footer color pair and attributes with optional bold for active panes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    if is_active:
        return COLOR_FOOTER, TextAttribute.BOLD
    else:
        return COLOR_FOOTER, TextAttribute.NORMAL

def get_status_color():
    """
    Get status line color pair and attributes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_STATUS, TextAttribute.NORMAL

def get_error_color():
    """
    Get error message color pair and attributes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_ERROR, TextAttribute.NORMAL

def get_boundary_color():
    """
    Get boundary color pair and attributes for pane separators.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_BOUNDARY, TextAttribute.NORMAL

def get_available_color_schemes():
    """Get list of available color schemes"""
    return list(COLOR_SCHEMES.keys())

def get_current_color_scheme():
    """Get the current color scheme name"""
    return current_color_scheme

def set_color_scheme(scheme_name):
    """Set the color scheme (init_colors should be called separately)"""
    global current_color_scheme
    
    if scheme_name not in COLOR_SCHEMES:
        raise ValueError(f"Unknown color scheme: {scheme_name}. Available schemes: {list(COLOR_SCHEMES.keys())}")
    
    current_color_scheme = scheme_name
    return True

def toggle_color_scheme():
    """Toggle between dark and light color schemes"""
    global current_color_scheme
    new_scheme = 'light' if current_color_scheme == 'dark' else 'dark'
    current_color_scheme = new_scheme
    # Note: init_colors() should be called separately in the application
    return new_scheme

def get_background_color_pair():
    """
    Get a color pair that can be used for background areas.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_BACKGROUND, TextAttribute.NORMAL

def get_log_color(source):
    """
    Get appropriate color pair and attributes for log messages based on source.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    if source == "STDERR":
        return COLOR_ERROR, TextAttribute.NORMAL  # Red for stderr
    elif source == "SYSTEM":
        return COLOR_LOG_SYSTEM, TextAttribute.NORMAL  # Light blue for system messages
    elif source == "STDOUT":
        return COLOR_LOG_STDOUT, TextAttribute.NORMAL  # Medium gray for stdout
    else:
        return COLOR_LOG_STDOUT, TextAttribute.NORMAL  # Default to stdout color

def get_line_number_color():
    """
    Get line number color pair and attributes for text viewer.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_LINE_NUMBERS, TextAttribute.NORMAL

def get_syntax_color(token_type):
    """
    Get syntax highlighting color pair for a token type.
    
    Returns:
        int: color_pair constant
    """
    # Map pygments token types to our color pairs
    token_str = str(token_type)
    
    if 'Keyword' in token_str:
        return COLOR_SYNTAX_KEYWORD
    elif 'String' in token_str or 'Literal.String' in token_str:
        return COLOR_SYNTAX_STRING
    elif 'Comment' in token_str:
        return COLOR_SYNTAX_COMMENT
    elif 'Number' in token_str or 'Literal.Number' in token_str:
        return COLOR_SYNTAX_NUMBER
    elif 'Operator' in token_str or 'Punctuation' in token_str:
        return COLOR_SYNTAX_OPERATOR
    elif 'Builtin' in token_str or 'Name.Builtin' in token_str:
        return COLOR_SYNTAX_BUILTIN
    elif 'Name' in token_str:
        return COLOR_SYNTAX_NAME
    else:
        # Default to regular text color
        return COLOR_REGULAR_FILE

def get_search_color():
    """
    Get search interface color pair and attributes (same as status color).
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_STATUS, TextAttribute.NORMAL

def get_search_match_color():
    """
    Get search match highlighting color pair and attributes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_SEARCH_MATCH, TextAttribute.NORMAL

def get_search_current_color():
    """
    Get current search match highlighting color pair and attributes.
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_SEARCH_CURRENT, TextAttribute.NORMAL

def get_color_with_attrs(color_pair):
    """
    Convert a color pair constant to (color_pair, attributes) tuple.
    
    This is a helper function for components that store color pair constants
    and need to convert them to the renderer API format.
    
    Args:
        color_pair: Color pair constant (e.g., COLOR_REGULAR_FILE)
        
    Returns:
        Tuple[int, int]: (color_pair, TextAttribute.NORMAL)
    """
    return color_pair, TextAttribute.NORMAL

def get_scrollbar_color():
    """
    Get scroll bar color pair and attributes.
    
    The scrollbar uses a single color pair with different characters:
    - Track: space character (background color shows through)
    - Thumb: █ (solid block)
    
    Returns:
        Tuple[int, int]: (color_pair, attributes)
    """
    return COLOR_SCROLLBAR, TextAttribute.NORMAL