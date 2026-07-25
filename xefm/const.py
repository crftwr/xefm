#!/usr/bin/env python3
"""
XeFM - Constants and Configuration

Note: standard keys (ENTER, TAB, ESCAPE, arrows, function keys, ...) come from
PuiKit's keyboard contract as canonical key names. Only values that contract does
not cover are defined here.
"""

from xefm import __version__ as VERSION  # noqa: F401  (re-exported as a constant)

# Application metadata
APP_NAME = "XeFM"
APP_DESCRIPTION = "A terminal-based file manager"
GITHUB_URL = "https://github.com/shimomut/xefm"

# Display constants
DEFAULT_LOG_HEIGHT_RATIO = 0.25  # Log pane takes 1/4 of screen
MIN_LOG_HEIGHT = 5
MAX_LOG_MESSAGES = 1000

# Date/time formats
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
LOG_TIME_FORMAT = "%H:%M:%S"

# File list date format options
DATE_FORMAT_FULL = 'full'        # YYYY-MM-DD HH:mm:ss
DATE_FORMAT_SHORT = 'short'      # YY-MM-DD HH:mm (default)

# Pane layout constants
MIN_PANE_RATIO = 0.1  # Minimum left pane width (10%)
MAX_PANE_RATIO = 0.9  # Maximum left pane width (90%)
PANE_ADJUST_STEP = 0.05  # 5% adjustment per key press

# Vertical pane layout constants
MIN_LOG_HEIGHT_RATIO = 0.0   # Minimum log pane height (0% - can be hidden)
MAX_LOG_HEIGHT_RATIO = 0.9   # Maximum log pane height (60%)
LOG_HEIGHT_ADJUST_STEP = 0.05  # 5% adjustment per key press

# Dialog dimension constants
LIST_DIALOG_WIDTH_RATIO = 0.6   # Width ratio for list dialogs (0.1 to 1.0)
LIST_DIALOG_HEIGHT_RATIO = 0.7  # Height ratio for list dialogs (0.1 to 1.0)
LIST_DIALOG_MIN_WIDTH = 40      # Minimum width for list dialogs
LIST_DIALOG_MIN_HEIGHT = 15     # Minimum height for list dialogs
INFO_DIALOG_WIDTH_RATIO = 0.8   # Width ratio for info dialogs (0.1 to 1.0)
INFO_DIALOG_HEIGHT_RATIO = 0.8  # Height ratio for info dialogs (0.1 to 1.0)
INFO_DIALOG_MIN_WIDTH = 20      # Minimum width for info dialogs
INFO_DIALOG_MIN_HEIGHT = 10     # Minimum height for info dialogs
