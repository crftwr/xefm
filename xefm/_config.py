#!/usr/bin/env python3
"""
XeFM User Configuration

This file contains your personal XeFM configuration.
You can modify any of these settings to customize XeFM behavior.
"""

import platform
import sys

# Import xefm_tool function and xefm_python variable for external program configuration
from xefm.external_programs import xefm_tool, xefm_python

# Import backend detector for runtime backend detection
from xefm.backend_detector import is_desktop_mode

class Config:
    """User configuration for XeFM"""

    # --- Desktop (GUI) mode fonts (ignored in TUI mode) ----------------------
    # UI_FONT_NAME   : proportional default face (file names, labels,
    #                  dialogs, markdown prose).
    # MONO_FONT_NAME : monospaced face for aligned content (size/date
    #                  columns, viewer, diffs); also grounds the layout
    #                  grid, so it must be monospaced.
    # FONT_SIZE      : point size applied to BOTH faces.
    # Missing glyphs use the OS's native font substitution.
    #
    # None = the OS system default face -- already a matched pair per platform:
    #   macOS   -> San Francisco + SF Mono
    #   Windows -> Segoe UI + Consolas
    #
    # To use named fonts, uncomment ONE block below (it runs after the defaults
    # and overrides them). `sys` is already imported at the top of this file.

    # Default: the system pair on every platform (recommended).
    UI_FONT_NAME = None
    MONO_FONT_NAME = None

    # Example -- a sans-serif pairing:
    # if sys.platform == 'darwin':        # macOS
    #     UI_FONT_NAME = 'Helvetica Neue'
    #     MONO_FONT_NAME = 'Menlo'
    # elif sys.platform == 'win32':       # Windows
    #     UI_FONT_NAME = 'Segoe UI'
    #     MONO_FONT_NAME = 'Consolas'
    # else:                               # other
    #     UI_FONT_NAME = None
    #     MONO_FONT_NAME = None

    # Example -- a serif pairing (serif UI + serif/slab monospace):
    # if sys.platform == 'darwin':        # macOS
    #     UI_FONT_NAME = 'Georgia'
    #     MONO_FONT_NAME = 'PT Mono'
    # elif sys.platform == 'win32':       # Windows
    #     UI_FONT_NAME = 'Georgia'
    #     MONO_FONT_NAME = 'Courier New'
    # else:                               # other
    #     UI_FONT_NAME = None
    #     MONO_FONT_NAME = None

    FONT_SIZE = 12  # point size for both faces (8-72)

    # Text viewer: the encodings offered by the viewer's encoding picker (the
    # 'change_encoding' action, Shift-E). Automatic detection — UTF-8 with or without
    # BOM, UTF-16/32 by BOM, Shift-JIS, EUC-JP, ISO-2022-JP, CP1252 — is built
    # in and always the default; this list only feeds the manual picker, for
    # when detection gets a file wrong. Any Python codec name works here
    # (e.g. 'koi8-r', 'gb2312', 'utf-16-le'):
    # https://docs.python.org/3/library/codecs.html#standard-encodings
    TEXT_ENCODINGS = ['utf-8', 'cp932', 'euc-jp', 'iso-2022-jp', 'latin-1']

    # Display settings
    SHOW_HIDDEN_FILES = False  # dot-names anywhere, plus the hidden attribute on Windows
    DEFAULT_LEFT_PANE_RATIO = 0.5  # 0.1 to 0.9
    DEFAULT_LOG_HEIGHT_RATIO = 0.25  # 0.1 to 0.5
    DATE_FORMAT = 'short'  # 'short' (YY-MM-DD HH:mm) or 'full' (YYYY-MM-DD HH:mm:ss)
    
    # Sorting settings
    DEFAULT_SORT_MODE = 'name'  # 'name', 'size', 'date'
    DEFAULT_SORT_REVERSE = False
    
    # -----------------------------------------------------------------------
    # Custom themes (optional)
    # -----------------------------------------------------------------------
    # Register your own named themes here. Each one is added to the theme picker
    # (View > Theme) and the T-key cycle alongside the built-ins — Dark+, Monokai,
    # Dracula, Nord, Solarized, Gruvbox Dark, Light+, Solarized Light — so you can
    # switch between them at run time. XeFM starts on Dark+ and remembers whichever
    # theme you last switched to across restarts.
    #
    # THEMES maps a display name to a dict of color overrides. A theme inherits a
    # base and overrides only what differs: set 'base' to any built-in (or another
    # theme you defined above) to inherit it; with no 'base' it builds on the theme
    # of the same name if one exists (so {'Dark+': {...}} tweaks the built-in), else
    # on 'Dark+'. A name matching an existing theme replaces it in place.
    #
    # Every available key (all optional). Colors are (R, G, B) tuples, 0-255:
    #
    #   'base':          'Dark+'          # theme to inherit (see above for default)
    #   # --- base palette ---
    #   'background':    (30, 30, 30)     # content surface / editor background
    #   'foreground':    (212, 212, 212)  # primary text
    #   'muted':         (157, 157, 157)  # secondary text, dividers
    #   'accent':        (0, 122, 204)    # focus ring, selection fill, default bars
    #   'accent2':       (78, 201, 176)   # secondary accent (i-search base, recipes)
    #   'surface':       (48, 48, 52)     # raised panels (pane header / popup)
    #   'selection':     (10, 105, 178)   # active selection fill
    #   # --- chrome bars (a solid color for the whole bar) ---
    #   'status':        (0, 122, 204)    # bottom status bar (also the viewers')
    #   'footer':        (0, 122, 204)    # per-pane info bar
    #   # --- file panes: per-type name colors (a sub-dict, like 'syntax';
    #   #     override only the types you name) ---
    #   'file_types': {'directory': (204, 204, 120),  # dirs  (default: soft yellow)
    #                  'file':      (212, 212, 212),  # files (default: foreground)
    #                  'link':      (86, 194, 214)}   # symlinks (default: cyan)
    #   #   ('directory' may also be given as a flat top-level key — shorthand for
    #   #    file_types['directory']. A symlink is colored as a link even when it
    #   #    points at a directory.)
    #   # --- file pane cursor cue (a sub-dict; the row outline / [ ] bracket,
    #   #     distinct from the selection fill) ---
    #   'cursor': {'active':   (231, 76, 76),  # focused pane (default: red)
    #              'inactive': (140, 92, 94)}  # blurred pane (default: muted red)
    #   # --- incremental search ---
    #   'isearch_match': (78, 201, 176)   # match-highlight base (default: accent2)
    #   # --- text / diff viewer syntax colors (override only the tokens you name) ---
    #   'syntax': {'keyword': (86, 156, 214), 'string': (206, 145, 120),
    #              'comment': (106, 153, 85), 'number': (181, 206, 168),
    #              'operator': (212, 212, 212), 'builtin': (78, 201, 176),
    #              'name': (156, 220, 254)}
    #   # --- recommended post-processing effect (GUI backend only) ---
    #   #   A full-screen CRT / phosphor "look" composited over the rendered
    #   #   frame. XeFM turns it on when this theme becomes active and off when you
    #   #   switch away. Only the GUI backend (`xefm/app.py --backend gui`) renders it;
    #   #   a terminal has no pixels to filter and silently ignores it.
    #   #     'post_effect': 'crt'       # preset: glow + bloom + scanlines + vignette + roll
    #   #     'post_effect': {'bloom': 0.3, 'vignette': 0.15, 'glow': 0.22,
    #   #                     'scanline': 0.15, 'roll': 0.1}  # custom (override any)
    #   # --- background behind the UI (GUI backend only) ---
    #   #   One background of two kinds (else the plain theme color). On/off with the
    #   #   theme, like post_effect; a terminal has no pixels and ignores it. NOTE the
    #   #   'background' key above is the base *color* — these choose the content:
    #   #   * animation — a slow moving scene, anchored on this theme's own colors
    #   #     (foreground for the scene, background for the backdrop) so it stays
    #   #     on-palette:
    #   #       'starfield'     stars streaming toward you, fading in with depth
    #   #       'rain'          falling streaks with fading tails
    #   #       'constellation' drifting nodes linked to their near neighbours
    #   #       'grid'          flying through a wireframe corridor, the camera
    #   #                       slowly drifting and turning as it goes
    #   #       'wave'          a dense particle wave with its own colour gradient
    #   #     Written as a bare type, or a dict to retune speed / opacity:
    #   #       'animation': 'starfield'                     # the tuned default
    #   #       'animation': {'type': 'rain', 'speed': 1.0, 'opacity': 0.8}
    #   #     ('cube', a spinning wireframe, also works — it is the UI toolkit's
    #   #      own reference scene rather than one of XeFM's.)
    #   #   * wallpaper — a single image scaled to fill the window:
    #   #       'wallpaper': '~/Pictures/bg.png'
    #   #       'wallpaper': {'image': '~/bg.png', 'fit': 'fit', 'opacity': 0.8}
    #   #       fit: 'fill' (cover, default) | 'fit' (contain) | 'stretch' | 'center'
    #   # --- surface opacity (GUI backend only) ---
    #   #   How opaque the UI's pane/row backgrounds are (0..1); below 1 the
    #   #   background behind them shows through. A single per-theme value, separate
    #   #   from the background so it applies to any kind. 1 = fully opaque UI.
    #   #     'opacity': 0.6
    #
    # Example:
    #
    # THEMES = {
    #     'Ocean': {                       # builds on Dark+
    #         'accent': (38, 139, 210),
    #         'file_types': {'directory': (120, 200, 220), 'link': (90, 200, 180)},
    #         'syntax': {'keyword': (0, 175, 215)},
    #     },
    #     'Paper': {                       # a light theme, from a light base
    #         'base': 'Light+',
    #         'file_types': {'directory': (150, 110, 0)},
    #     },
    # }
    THEMES = {
        # Phosphor: a monochrome phosphor-green CRT terminal — every color is a
        # shade of green on a near-black screen. A ready-made example of a full
        # custom theme; select it from View > Theme or with the T key. On the GUI
        # backend the 'post_effect' below adds a real CRT glow over the green.
        'Phosphor': {
            'post_effect': 'crt',            # CRT glow/bloom/scanlines (GUI backend)
            'animation': 'rain',             # falling phosphor streaks (GUI backend)
            'opacity': 0.6,                  # chrome opacity; < 1 lets the rain show through
            'background': (4, 15, 7),        # dark CRT green-black
            'foreground': (51, 245, 121),    # phosphor green
            'muted':      (33, 138, 74),     # dim green (secondary text / dividers)
            'accent':     (60, 235, 122),    # focus ring / selection accent
            'accent2':    (124, 255, 168),   # pale mint (i-search match base)
            'surface':    (11, 38, 20),      # raised panels (header / popup)
            'selection':  (24, 105, 54),     # active selection fill
            'status':     (12, 40, 22),      # status bar (dark green panel)
            'footer':     (22, 68, 40),      # per-pane info bar (lighter, so the
                                             # footer/status boundary reads on TUI)
            'file_types': {
                'directory': (150, 255, 150),  # directories (brightest green)
                'link':      (124, 255, 168),  # symlinks (pale mint)
            },
            'cursor': {                        # keep the cue on-palette, not red
                'active':   (180, 255, 180),   # bright green frame (focused pane)
                'inactive': (60, 150, 90),     # dim green frame (blurred pane)
            },
            'syntax': {
                'keyword':  (130, 255, 150),
                'string':   (90, 220, 120),
                'comment':  (36, 140, 78),
                'number':   (150, 255, 130),
                'operator': (70, 210, 110),
                'builtin':  (150, 255, 170),
                'name':     (60, 235, 120),
            },
        },
    }

    # Behavior settings
    CONFIRM_DELETE = True   # Show confirmation dialog before deleting files/directories
    CONFIRM_QUIT = True     # Show confirmation dialog before quitting XeFM
    CONFIRM_COPY = True     # Show confirmation dialog before copying files/directories
    CONFIRM_MOVE = True     # Show confirmation dialog before moving files/directories
    CONFIRM_DUPLICATE = True  # Show confirmation dialog before duplicating files/directories
    CONFIRM_EXTRACT_ARCHIVE = True  # Show confirmation dialog before extracting archives
    CONFIRM_ARCHIVE_CREATE = True   # Show confirmation dialog before creating archives
    FILE_OP_WORKERS_LOCAL = 4  # Copy/move worker threads, local disk (1 = sequential)
    FILE_OP_WORKERS_S3 = 8     # Copy/move worker threads when S3 is involved (ssh is always 1)
    
    # Key bindings - customize your shortcuts
    # Each action can have multiple keys assigned to it
    # 
    # Supported formats:
    # 1. Simple format: 'action': ['key1', 'key2']
    #    - Works regardless of selection status
    #    - Keys can be characters ('a', 'Q') or special key names ('HOME', 'END')
    # 
    # 2. Extended format: 'action': {'keys': ['key1', 'key2'], 'selection': 'any|required|none'}
    #    - 'any': works regardless of selection status (default)
    #    - 'required': only works when at least one item is explicitly selected
    #    - 'none': only works when no items are explicitly selected
    #
    # Special key names (use these strings in the keys list):
    #   'HOME', 'END', 'PPAGE', 'NPAGE', 'UP', 'DOWN',
    #   'LEFT', 'RIGHT', 'BACKSPACE', 'DELETE', 'INSERT',
    #   'F1' through 'F12'
    #
    KEY_BINDINGS = {
        # === Application Control ===
        'quit': ['Q'],                         # Exit XeFM application
        'help': ['?'],                         # Show help dialog with all key bindings
        'redraw': ['F5'],                      # Additional redraw trigger (Ctrl-L is always hardcoded)
        'menu': ['F10', 'ALT'],                # Open the menu bar (terminal; a bare Alt tap works on the Windows terminal, F10 everywhere)
        
        # === Navigation ===
        'cursor_up': ['UP'],                   # Move cursor up one item
        'cursor_down': ['DOWN'],               # Move cursor down one item
        'page_up': ['PAGE_UP'],                # Move cursor up one page
        'page_down': ['PAGE_DOWN'],            # Move cursor down one page
        'cursor_top': ['Ctrl-HOME'],           # Move cursor to the first item
        'cursor_bottom': ['Ctrl-END'],         # Move cursor to the last item
        'open_item': ['ENTER'],                # Open file/directory or enter directory
        'open_with_os': ['Command-ENTER'],     # Open file(s) with OS default application
        'reveal_in_os': ['Alt-ENTER'],         # Reveal focused file in OS file manager
        'go_parent': ['BACKSPACE'],            # Go to parent directory
        'switch_pane': ['TAB'],                # Switch between left and right panes
        'nav_left': ['LEFT'],                  # Left pane: go to parent, Right pane: switch to left pane
        'nav_right': ['RIGHT'],                # Right pane: go to parent, Left pane: switch to right pane
        
        # === File Selection ===
        'toggle_select_down': ['SPACE'],              # Toggle selection of current file
        'toggle_select_up': ['Shift-SPACE'],     # Toggle selection and move up
        'select_all': ['HOME'],                # Select all items (Home key)
        'unselect_all': ['END'],               # Unselect all items (End key)
        'toggle_select_files': ['A'],             # Toggle selection of all files in current pane
        'toggle_select_items': ['Shift-A'],       # Toggle selection of all items (files + dirs)
        'cursor_next_selected': ['Ctrl-DOWN'], # Move cursor to the next selected item
        'cursor_prev_selected': ['Ctrl-UP'],   # Move cursor to the previous selected item
        
        # === Clipboard (copy names/paths to the system clipboard) ===
        'copy_names': ['Command-Shift-C'],     # Copy selected/focused file name(s) to clipboard
        'copy_paths': ['Command-Shift-P'],     # Copy selected/focused full path(s) to clipboard

        # === File Operations ===
        'copy_files': {'keys': ['C'], 'selection': 'required'},  # Copy selected files to other pane
        'move_files': {'keys': ['M'], 'selection': 'required'},  # Move selected files to other pane
        'delete_files': {'keys': ['K', 'DELETE'], 'selection': 'required'}, # Delete selected files/directories
        'rename': ['R'],                  # Rename selected file/directory
        'create_file': ['Shift-E'],            # Create new file (prompts for filename)
        'create_directory': {'keys': ['M'], 'selection': 'none'},  # Create new directory (only when no files selected)
        
        # === File Viewing & Editing ===
        'view_file': ['V'],                    # View file using configured viewer
        'edit_file': ['E'],                    # Edit selected file with configured text editor (also inside the text viewer)
        'file_details': ['I'],                 # Show detailed file information dialog
        
        # === File Comparison ===
        'diff_files': ['EQUAL'],               # Compare two selected files side-by-side
        'diff_directories': ['Shift-EQUAL'],   # Compare directories recursively
        
        # === Archive Operations ===
        'create_archive': {'keys': ['P'], 'selection': 'required'}, # Create archive from selected files
        'extract_archive': ['U'],              # Extract selected archive file
        
        # === Search & Filter ===
        'isearch': ['F'],                       # Enter incremental search mode (isearch)
        'find_files': ['Shift-F'],          # Show filename search dialog
        'find_in_files': ['Shift-G'],         # Show content search dialog (grep)
        'filter': [';'],                       # Enter filter mode to show only matching files
        'clear_filter': [':'],                 # Clear current file filter
        
        # === Sorting ===
        'sort': ['S'],                    # Open the sort dialog (key + order)
        'quick_sort_name': ['1'],              # Quick sort by filename
        'quick_sort_ext': ['2'],               # Quick sort by file extension
        'quick_sort_size': ['3'],              # Quick sort by file size
        'quick_sort_date': ['4'],              # Quick sort by modification date
        
        # === Directory Navigation ===
        'favorites': ['J'],                    # Show favorite directories dialog
        'jump_to_path': ['Shift-J'],           # Jump to path
        'history': ['H'],                      # Show history for current pane
        'drives': ['D'],                # Show drives/volumes dialog
        
        # === Pane Management ===
        'sync_current_to_other': ['O'],        # Sync current pane directory to other pane
        'sync_other_to_current': ['Shift-O'],  # Sync other pane directory to current pane
        'compare_selection': ['W'],            # Show file and directory comparison options
        'adjust_pane_left': ['['],             # Make left pane smaller (move boundary left)
        'adjust_pane_right': [']'],            # Make left pane larger (move boundary right)
        'reset_pane_boundary': ['-'],          # Reset pane split to 50% | 50%
        
        # === Log Pane Control ===
        'adjust_log_up': ['{'],                # Make log pane larger (Shift+[)
        'adjust_log_down': ['}'],              # Make log pane smaller (Shift+])
        'reset_log_height': ['_'],             # Reset log pane height to default (Shift+-)
        'scroll_log_up': ['Shift-UP'],         # Scroll log pane up one line
        'scroll_log_down': ['Shift-DOWN'],     # Scroll log pane down one line
        'scroll_log_page_up': ['Shift-LEFT'],  # Scroll log pane up one page (to older messages)
        'scroll_log_page_down': ['Shift-RIGHT'], # Scroll log pane down one page (to newer messages)
        
        # === Text Viewer ===
        # Text-viewer-only actions. 'isearch' (F, above) opens incremental search
        # inside the viewers too. These deliberately share keys with file-list
        # actions -- 'W' with 'compare_selection', 'M' with 'move_files' /
        # 'create_directory', 'Shift-E' with 'create_file'. The two surfaces never
        # apply at once, and each only ever looks at its own context's actions, so
        # a shared key is never ambiguous. Plain 'E' (edit_file, under File
        # Operations) works inside the text viewer too, editing the viewed file.
        'toggle_wrap': ['W'],                  # Toggle line wrapping
        'toggle_view_mode': ['M'],             # Toggle rendered (Markdown) / raw text
        'change_encoding': ['Shift-E'],        # Choose the text encoding (auto / explicit)

        # === Image Viewer ===
        # Image-viewer-only actions, scoped like the text viewer's above. '-' and
        # '_' intentionally share with
        # 'reset_pane_boundary' / 'reset_log_height', and the arrow /
        # Shift-arrow keys with the file list's cursor and log-scroll actions:
        # all of those apply to the file list only, never to an open viewer,
        # and each context matches its own action by name via
        # KeyBindings.is_action_for_event, so the shared keys are unambiguous.
        # Home/End jump to the first/last image and stay viewer-local (not
        # rebindable), like the text viewer's scroll keys.
        'image_viewer.zoom_in': ['+', '='],           # Image viewer: zoom in ('=' is unshifted '+')
        'image_viewer.zoom_out': ['-', '_'],          # Image viewer: zoom out
        'image_viewer.zoom_reset': ['0'],             # Image viewer: fit the whole image to the window
        'image_viewer.next': ['DOWN'],                # Image viewer: next image in the file list
        'image_viewer.prev': ['UP'],                  # Image viewer: previous image in the file list
        'image_viewer.pan_up': ['Shift-UP'],       # Image viewer: pan up (while zoomed in)
        'image_viewer.pan_down': ['Shift-DOWN'],   # Image viewer: pan down
        'image_viewer.pan_left': ['Shift-LEFT'],   # Image viewer: pan left
        'image_viewer.pan_right': ['Shift-RIGHT'], # Image viewer: pan right

        # === Display & Appearance ===
        'toggle_hidden': ['.'],                # Toggle visibility of hidden files (dotfiles, Windows hidden attribute)
        # Unbound by default (use View → Theme in the menu bar). Assign a key
        # here to cycle themes from the keyboard, e.g. ['T'].
        'toggle_color_scheme': [],             # Cycle to the next color theme

        # === External Programs ===
        'programs': ['X'],                     # Show external programs menu
        'subshell': ['Shift-X'],               # Enter subshell (command line) mode

        # === Configuration ===
        # Unbound by default (reachable via the Tools menu). Assign a key here to
        # open/reload this file without leaving XeFM, e.g. 'edit_config': ['Y'].
        'edit_config': [],                     # Edit this config.py in TEXT_EDITOR, then reload
        'reload_config': [],                   # Re-read this config.py and apply live

        # === Viewer-local actions (rebindable, not listed above) ==============
        # Every key the modal viewers use is a named action too, and every one of
        # them can be rebound here. They are *not* listed as entries above,
        # because they already work without one: an action XeFM does not find in
        # this dictionary falls back to the default it declares in xefm/actions.py
        # (which is also what keeps a config written before an action existed
        # working). Add an entry only for the ones you want to change.
        #
        # The names are prefixed with the viewer they belong to, so they never
        # collide with the file list's own actions — and because each surface only
        # ever looks at its own names, a viewer action may share a key with a file
        # list action with no ambiguity at all. Their defaults:
        #
        #   Text viewer                        File diff
        #     'text_viewer.scroll_up':  UP       'file_diff.scroll_up':      UP
        #     'text_viewer.scroll_down': DOWN    'file_diff.scroll_down':    DOWN
        #     'text_viewer.page_up':    PAGE_UP  'file_diff.page_up':        PAGE_UP
        #     'text_viewer.page_down':  PAGE_DOWN 'file_diff.page_down':     PAGE_DOWN
        #     'text_viewer.scroll_top': HOME     'file_diff.scroll_top':     HOME
        #     'text_viewer.scroll_bottom': END   'file_diff.scroll_bottom':  END
        #     'text_viewer.scroll_left': LEFT    'file_diff.scroll_left':    LEFT
        #     'text_viewer.scroll_right': RIGHT  'file_diff.scroll_right':   RIGHT
        #                                        'file_diff.next_block':     n
        #   Image viewer                         'file_diff.prev_block':     Shift-N
        #     'image_viewer.first':     HOME
        #     'image_viewer.last':      END
        #
        #   Directory diff
        #     'dir_diff.cursor_up':   UP        'dir_diff.expand':      RIGHT
        #     'dir_diff.cursor_down': DOWN      'dir_diff.collapse':    LEFT
        #     'dir_diff.page_up':     PAGE_UP   'dir_diff.activate':    ENTER
        #     'dir_diff.page_down':   PAGE_DOWN 'dir_diff.switch_side': TAB
        #     'dir_diff.cursor_top':  HOME      'dir_diff.next_change': n
        #     'dir_diff.cursor_bottom': END     'dir_diff.prev_change': Shift-N
        #     'dir_diff.rescan':      r         'dir_diff.split_left':  [
        #                                       'dir_diff.split_right': ]
        #
        # Example -- page with space and b inside the text viewer only:
        # 'text_viewer.page_down': ['SPACE'],
        # 'text_viewer.page_up': ['B'],
        #
        # The same prefix also scopes a *shared* action to one viewer. 'quit',
        # 'help', 'isearch' and 'edit_file' are understood everywhere, so rebinding
        # 'quit' above changes it in the file list and in every viewer; writing
        # 'file_diff.quit' changes it in the file diff viewer alone:
        # 'file_diff.quit': ['X'],
    }

    # Windows has no Command key, and Alt-Enter is the platform fullscreen-toggle
    # convention — so the Mac-centric defaults above are unreachable there. Remap
    # them to Ctrl equivalents on Windows.
    if sys.platform == 'win32':
        KEY_BINDINGS['open_with_os'] = ['Ctrl-ENTER']    # Open file(s) with OS default application
        KEY_BINDINGS['reveal_in_os'] = ['Ctrl-Shift-E']  # Reveal focused file in Explorer
        KEY_BINDINGS['copy_names'] = ['Ctrl-Shift-C']    # Copy selected/focused file name(s) to clipboard
        KEY_BINDINGS['copy_paths'] = ['Ctrl-Shift-P']    # Copy selected/focused full path(s) to clipboard


    # -----------------------------------------------------------------------
    # In-process customization -- PREVIEW
    # -----------------------------------------------------------------------
    # This config file is executed Python, so it can define functions as well as
    # settings. ACTIONS binds your own functions to action names (which
    # KEY_BINDINGS above then binds to keys, exactly like a built-in action), and
    # EVENT_HOOKS runs them at set moments in XeFM's life.
    #
    # PREVIEW: this is not a stable API yet. The objects passed to your functions
    # and the shape of these two variables may change in any release until
    # xefm.user_api.API_VERSION reaches 1. XeFM logs one line saying so when a
    # config uses either variable. Everything else in this file is unaffected.
    #
    # Both reload with the rest of the config ('reload_config'), so iterating on
    # an action is edit-then-reload -- no restart.
    #
    # --- ACTIONS ----------------------------------------------------------
    # A function takes one argument, the context object, and is run on the UI
    # thread while XeFM waits -- so keep it quick. Anything it raises is logged
    # with a traceback and dropped; it never takes XeFM down.
    #
    # Define the functions ABOVE `class Config:` (module level), then:
    #
    # def select_documents(ctx):
    #     """Select every Word/PDF document in the active pane."""
    #     n = ctx.pane.select(lambda e: e.suffix.lower() in ('.docx', '.pdf'))
    #     ctx.message(f"Selected {n} document(s)")
    #
    # def go_to_sibling(ctx):
    #     """Point the other pane at this pane's directory."""
    #     ctx.other.cd(ctx.pane.path)
    #
    # ACTIONS = {
    #     'select-documents': select_documents,
    #     'go-to-sibling': go_to_sibling,
    # }
    # ...and bind them in KEY_BINDINGS above, like any built-in action:
    #     'select-documents': ['Shift-D'],
    #
    # An action name that already exists is ignored unless you say you meant it,
    # which also keeps the built-in reachable so you can wrap it:
    #
    # def confirm_then_quit(ctx):
    #     ctx.message("see you")
    #     ctx.invoke('quit')          # runs the built-in 'quit'
    #
    # ACTIONS = {'quit': {'func': confirm_then_quit, 'override': True}}
    #
    # What the context object offers:
    #   ctx.pane / ctx.other / ctx.left / ctx.right   the panes
    #   ctx.invoke(name)                              run another action
    #   ctx.message(text)                             one line in the log pane
    #   ctx.input(prompt, default, on_accept=fn)      ask for text
    #   ctx.choose(title, items, on_result=fn)        pick from a list
    #   ctx.confirm(prompt, on_result=fn)             yes / no
    # ...and on each pane:
    #   pane.path, pane.entries, pane.cursor, pane.focused, pane.selected()
    #   pane.select(predicate) / pane.unselect(predicate) / pane.refresh()
    #   pane.cd(path, focus_name=None)
    # Each entry has .name, .path, .suffix, .stem, .is_dir, .is_file, .is_link,
    # .size and .mtime.
    #
    # XeFM never blocks on a dialog, so input/choose/confirm hand their answer to
    # a callback instead of returning it -- put the rest of the action in there.
    ACTIONS = {}

    # --- EVENT_HOOKS ------------------------------------------------------
    # Functions run at set moments. Each event maps to a list, run in order.
    #
    #   'startup'           fn(ctx)            once the app is up
    #   'quit'              fn(ctx)            before XeFM shuts down
    #   'directory_changed' fn(ctx, pane, old_path, new_path)
    #   'file_open'         fn(ctx, path)      return True to claim the open
    #
    # 'file_open' fires before XeFM decides what to do with a file, so returning
    # True is how you route one file type somewhere of your own without touching
    # FILE_ASSOCIATIONS. It does not fire for directories -- entering one is
    # navigation, not opening.
    #
    # def log_visit(ctx, pane, old_path, new_path):
    #     with open(Path.home() / '.xefm' / 'visited.log', 'a') as f:
    #         f.write(f"{new_path}\n")
    #
    # def open_psd_in_gimp(ctx, path):
    #     if path.suffix.lower() != '.psd':
    #         return False
    #     subprocess.Popen(['gimp', str(path)])
    #     return True                 # claimed -- XeFM does nothing further
    #
    # EVENT_HOOKS = {
    #     'directory_changed': [log_visit],
    #     'file_open': [open_psd_in_gimp],
    # }
    EVENT_HOOKS = {}


    # Favorite directories - customize your frequently used directories
    # Each entry should have 'name' and 'path' keys
    FAVORITE_DIRECTORIES = [
        {'name': 'Home', 'path': '~'},
        {'name': 'Documents', 'path': '~/Documents'},
        {'name': 'Downloads', 'path': '~/Downloads'},
        {'name': 'Desktop', 'path': '~/Desktop'},
        {'name': 'Projects', 'path': '~/Projects'},
        {'name': 'Root', 'path': '/'},
        {'name': 'Temp', 'path': '/tmp'},
        {'name': 'Config', 'path': '~/.config'},
        # Add your own favorites here:
        # {'name': 'Work', 'path': '/path/to/work'},
        # {'name': 'Scripts', 'path': '~/bin'},
    ]
    
    # Drives dialog (D) - the fixed locations listed above everything the picker
    # discovers on its own (Windows drive letters, /Volumes, /media, /mnt, the
    # hosts in ~/.ssh/config, and your S3 buckets when AWS credentials are set).
    #
    # None = XeFM's built-in set: Home, Root (POSIX only), and whichever of
    # Documents / Downloads / Desktop exist in your home directory. Define a list
    # to replace that set entirely; [] removes the fixed rows and leaves the
    # picker showing only the discovered ones.
    #
    # Each entry needs 'name' and 'path'. A local path that does not exist is
    # skipped. A remote location (ssh:// s3://) is listed as written - nothing
    # connects until you select it.
    #
    # DRIVE_LOCATIONS = [
    #     {'name': 'Home', 'path': '~'},
    #     {'name': 'Work', 'path': '~/work'},
    #     {'name': 'NAS', 'path': 'ssh://nas/'},
    # ]
    DRIVE_LOCATIONS = None

    # Performance settings
    MAX_LOG_MESSAGES = 1000

    # History settings
    MAX_HISTORY_ENTRIES = 100  # Maximum number of history entries to keep
    
    # Progress animation settings
    PROGRESS_ANIMATION_PATTERN = 'spinner'  # 'spinner', 'dots', 'progress', 'bounce', 'pulse', 'wave', 'clock', 'arrow'
    PROGRESS_ANIMATION_SPEED = 0.2  # Animation frame update interval in seconds

    # Motion settings
    # Suppress decorative motion app-wide: dialogs appear at once instead of
    # scaling in, and an animated theme background (Sci-Fi's starfield) coasts to
    # a stop and holds a still frame. Everything lands in its FINAL state, never
    # frozen mid-animation, so nothing is hidden by turning this on. Set it if
    # motion is uncomfortable, or over a slow SSH link where every animated frame
    # is a screen repaint. Functional updates (progress, file-list reloads,
    # search results) are unaffected.
    REDUCED_MOTION = False
    
    # File display settings
    SEPARATE_EXTENSIONS = True  # Show file extensions separately from basenames
    MAX_EXTENSION_LENGTH = 5    # Maximum extension length to show separately

    # Incremental search settings
    # Migemo expands romaji into the Japanese it could spell, so incremental
    # search (the file panes, the text/diff viewers, and the filter-list
    # dialogs — favorites, history, drives …) finds Japanese names without an
    # IME: typing "kensaku" also matches 検索. Plain matching always still
    # applies — Migemo only ever adds matches. Patterns with glob characters
    # (* ? [) keep exact fnmatch behavior, and patterns shorter than
    # MIGEMO_MIN_LENGTH skip Migemo (1-2 character queries are slow to expand
    # and barely one kana anyway). Needs the pymigemo package (installed with
    # XeFM); without it searches quietly stay plain.
    MIGEMO_SEARCH = True   # Add Migemo (romaji -> Japanese) matches to incremental search
    MIGEMO_MIN_LENGTH = 3  # Shortest pattern handed to Migemo
    
    # Text editor settings
    # Supports both string and list formats:
    # - String format: 'vim' (single command, no arguments)
    # - List format: ['code', '--wait'] (command with arguments)
    # Automatically set based on actual running backend mode:
    # - Terminal mode (curses): vim
    # - Desktop mode (coregraphics): code (VS Code)
    TEXT_EDITOR = 'code' if is_desktop_mode() else 'vim'
    
    # Text diff tool settings
    # Tool invoked when pressing 'E' (edit_file) key in DiffViewer or DirectoryDiffViewer
    # Supports both string and list formats:
    # - String format: 'vimdiff' (single command, no arguments)
    # - List format: ['code', '--diff'] (command with arguments)
    # Automatically set based on actual running backend mode:
    # - Terminal mode (curses): vimdiff (string format example)
    # - Desktop mode (coregraphics): code --diff (list format example)
    TEXT_DIFF = ['code', '--diff'] if is_desktop_mode() else 'vimdiff'

    # Subshell settings
    # Shell launched by the 'subshell' action (Shift-X), terminal mode only.
    # None: use $SHELL if set, otherwise the platform default
    # (%COMSPEC% / cmd.exe on Windows, /bin/sh elsewhere).
    # Supports both string and list formats:
    # - String format: 'zsh' (single command, no arguments)
    # - List format: ['powershell', '-NoLogo'] (command with arguments)
    SUBSHELL = None

    # S3 settings
    S3_CACHE_TTL = 60  # S3 cache TTL in seconds (default: 60 seconds)
    
    # SSH/SFTP cache settings
    SSH_CACHE_TTL = 30        # SSH cache TTL in seconds for successful results (default: 30 seconds)
    SSH_CACHE_ERROR_TTL = 300  # SSH cache TTL in seconds for cached errors (default: 300 seconds / 5 minutes)
    
    # Archive cache settings
    ARCHIVE_CACHE_MAX_OPEN = 5   # Maximum number of archives to keep open simultaneously
    ARCHIVE_CACHE_TTL = 300       # Archive cache TTL in seconds (default: 300 seconds / 5 minutes)
    
    # File monitoring settings
    FILE_MONITORING_ENABLED = True                      # Enable/disable automatic file list reloading
    FILE_MONITORING_COALESCE_DELAY_MS = 200            # Event coalescing window in milliseconds
    FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5         # Maximum reloads per second (rate limiting)
    FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5       # Polling interval for fallback mode (seconds)
    
    # File extension associations
    # Maps file patterns to what each action should do.
    #
    # There are two tiers of "open", and they are bound to different keys:
    #
    #   'enter'  ENTER          Casual open. Stays inside XeFM. The value names
    #                           a built-in handler, NOT a program to launch:
    #                             'viewer'   - the built-in text/markdown viewer
    #                             'navigate' - browse the file as an archive
    #                                          (handy for *.jar, *.whl, ...)
    #                             None       - do nothing
    #                           With no rule, XeFM's default applies: directories
    #                           and archives are entered, files open in the
    #                           built-in viewer.
    #
    #   'open'   Cmd/Ctrl-ENTER Deliberate open. Hands the file to an external
    #                           program. Falls back to the OS default app.
    #
    # The other two actions are 'view' (V) and 'edit' (E), both external.
    #
    # Compact Format Features:
    # 1. Multiple patterns in one entry: ['*.jpg', '*.jpeg', '*.png']
    # 2. Combined actions: 'open|view' assigns same command to both actions
    # 3. Commands: List ['open', '-a', 'Preview'] or string 'open -a Preview'
    # 4. None: Action not available -- except 'view': None, which selects the
    #    built-in viewer, and 'enter': None, which does nothing.
    #
    # You do NOT declare whether a program takes over the terminal. That follows
    # from the backend, not from the program: in terminal mode XeFM suspends and
    # waits for the child (correct for less/vim; a launcher like `open -a` just
    # returns straight away), and in desktop mode there is no terminal to hand
    # over, so the child is detached and XeFM stays responsive. As with
    # TEXT_EDITOR above, pick programs that suit the mode you run in.
    #
    # Format:
    # {
    #     'pattern': '*.pdf' or ['*.jpg', '*.png'],  # Single or multiple fnmatch patterns
    #     'enter': 'viewer',         # Built-in handler for the ENTER key
    #     'open|view': ['command'],  # Same command for open and view
    #     'edit': ['command'],       # Different command for edit
    # }
    FILE_ASSOCIATIONS = [
        # PDF files
        {
            'pattern': '*.pdf',
            'open|view': ['open', '-a', 'Preview'],
            'edit': None,
        },
        # Image files. 'view' is deliberately None so V opens XeFM's own image
        # viewer (zoom / pan / prev-next, staying inside XeFM) rather than handing
        # the file to Preview; 'open' still hands it to the OS app for editing or
        # a full-fidelity look. Set 'open|view' back to Preview if you would
        # rather V left XeFM. Formats beyond these four still reach the built-in
        # viewer by falling through with no rule at all.
        {
            'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
            'open': ['open', '-a', 'Preview'],
            'view': None,
            'edit': ['open', '-a', 'GIMP'],
        },
        # Video files
        {
            'pattern': ['*.mp4', '*.mov'],
            'open|view': ['open', '-a', 'QuickTime Player'],
            'edit': None,
        },
        # Audio files
        {
            'pattern': ['*.mp3', '*.wav'],
            'open': ['open', '-a', 'Music'],
            'edit': None,
        },
        # Microsoft Word documents
        {
            'pattern': ['*.doc', '*.docx'],
            'open|view|edit': ['open', '-a', 'Microsoft Word'],
        },
        # Microsoft Excel spreadsheets
        {
            'pattern': ['*.xls', '*.xlsx'],
            'open|view|edit': ['open', '-a', 'Microsoft Excel'],
        },
        # Microsoft PowerPoint presentations
        {
            'pattern': ['*.ppt', '*.pptx'],
            'open|view|edit': ['open', '-a', 'Microsoft PowerPoint'],
        },
        # Note there is deliberately no entry listing text/code extensions.
        # Enter and V already fall through to the built-in viewer when no rule
        # matches, and the viewer sniffs the bytes -- so it reads text with no
        # configuration and shows a placeholder for binaries, including for
        # files with no extension or an unknown one that a list would miss.
        #
        # Zip-shaped archives XeFM does not enter by extension. This one *is*
        # worth stating, because it cannot be sniffed: .docx and .xlsx are zip
        # files too, and you want Word for those, not a file listing.
        {
            'pattern': ['*.jar', '*.whl', '*.egg'],
            'enter': 'navigate',
        },
        # Add your own file associations here:
        # {
        #     'pattern': ['*.ext1', '*.ext2'],
        #     'enter': 'viewer',                  # what ENTER does (in XeFM)
        #     'open|view': ['command', 'args'],   # external programs
        #     'edit': ['command', 'args'],
        # },
        # Terminal programs need no special marking -- in terminal mode XeFM
        # hands the display over and waits:
        # {
        #     'pattern': '*.log',
        #     'view': ['less'],
        # },
    ]
    
    # External programs - each item has "name", "command", and optional "options" fields
    # The "command" field is a list for safe subprocess execution
    # Relative paths in the first element are resolved relative to the XeFM root directory (where xefm/app.py is located)
    # Use xefm_tool('tool_name') to search for tools in:
    #   1. ~/.xefm/tools/ (user-specific tools, highest priority)
    #   2. {xefm/app.py directory}/tools/ (system tools, fallback)
    # ~/.xefm/tools/ is created on first launch with example_tool.py in it —
    # copy that file as the starting point for your own tools.
    # The "options" field is a dictionary with program-specific options:
    #   - terminal: if True, hand the terminal over to the program and wait for
    #     it to exit — for full-screen / interactive programs (vim, less, a
    #     REPL). If it exits with an error, XeFM waits for Enter so the output
    #     stays readable. Terminal mode only; desktop mode has no terminal to
    #     hand over and refuses the launch with an error in the log pane.
    #   - auto_return: deprecated and ignored — launches never block XeFM.
    PROGRAMS = [
        {'name': 'Open in VSCode', 'command': [xefm_python, xefm_tool('vscode.py')]},
        {'name': 'Open in Kiro', 'command': [xefm_python, xefm_tool('kiro.py')]},
        {'name': 'Example Tool (show XeFM environment)', 'command': [xefm_python, xefm_tool('example_tool.py')]},

        # Add your own programs here:
        # {'name': 'My Custom Tool', 'command': [xefm_python, xefm_tool('my_custom_tool.py')]},
        # {'name': 'My Script (direct path)', 'command': [xefm_python, '/path/to/script.py']},
        # {'name': 'Quick Command', 'command': ['ls', '-la']},

        # Full-screen / interactive programs need the terminal handed over:
        # {'name': 'View with less', 'command': ['less'], 'options': {'terminal': True}},
        # {'name': 'Python REPL', 'command': ['python3'], 'options': {'terminal': True}},
    ]