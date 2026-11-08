"""The AFX-style keymap (#565, #597): one letter runs one command.

``C`` copies, ``M`` moves, ``K`` deletes — the single-key style of the
Japanese two-pane filers: the X68000 file managers, then AFX (あふ) on
Windows, then cfiler. XeFM follows that direction rather than copying any one
of them key for key.

This is one of the keymap presets (:mod:`xefm.keymap_presets`), a peer of the
others. Like each of them it is laid over :mod:`xefm.keymaps.common`, the keys
every preset shares — the viewers', dialogs' and search bars', the
non-letter file-list keys, the desktop app's platform keys. What is here is
what makes it AFX: the file list's letters and digits.

``config.py``'s ``KEY_BINDINGS`` overrides whatever preset is in force, action
by action; it ships nearly empty.
"""

import sys

from xefm.keymaps import common
from xefm.backend_detector import is_desktop_mode


def own_bindings() -> dict:
    """AFX's own keys — action name → keys, or ``{'keys': …, 'selection':
    …}`` — each replacing that action's entry in the common table, so an
    action that keeps a shared key (``DELETE`` beside ``K``) names it too. A
    new dict on every call."""
    keys = {
        # === Application ===
        'quit': ['Q'],                         # Exit XeFM application

        # === Navigation ===
        # Shift-B, not Ctrl-B: that is tmux's prefix, so inside tmux it would
        # never arrive. A capital is a glyph, which every terminal delivers.
        'flat_view': ['Shift-B'],              # Show every file below this directory as one flat list (again to go back)

        # === File Selection ===
        'toggle_select_files': ['A'],          # Toggle selection of all files in current pane
        'toggle_select_items': ['Shift-A'],    # Toggle selection of all items (files + dirs)

        # === File Clipboard ===
        # Copy, cut, paste beside the shared Ctrl-C / X / V. C and M (below)
        # stay the one-step way to the other pane.
        'clipboard_copy': ['Ctrl-C', 'Y'],     # Copy files to the clipboard
        'clipboard_cut': ['Ctrl-X', 'Shift-Y'],  # Cut files to the clipboard (moved on paste)
        'clipboard_paste': ['Ctrl-V', 'G'],    # Paste the clipboard into this folder

        # === File Operations ===
        'copy_files': {'keys': ['C'], 'selection': 'required'},  # Copy selected files to other pane
        'move_files': {'keys': ['M'], 'selection': 'required'},  # Move selected files to other pane
        'copy_files_to': {'keys': ['Shift-C'], 'selection': 'required'},  # Copy selected files to a typed directory
        'move_files_to': {'keys': ['Shift-M'], 'selection': 'required'},  # Move selected files to a typed directory
        'delete_files': {'keys': ['K', 'DELETE'], 'selection': 'required'},  # Delete selected files/directories (to the Trash where there is one)
        'delete_permanently': {'keys': ['Shift-K', 'Shift-DELETE'], 'selection': 'required'},  # Delete for good, skipping the Trash
        'rename': ['R'],                       # Rename selected file/directory
        'rename_in_editor': ['Shift-R'],       # Rename the selection by editing a name list in TEXT_EDITOR
        'create_file': ['Shift-E'],            # Create new file (prompts for filename)
        # M again, with nothing marked: the two selection gates never hold
        # together, so the key is never ambiguous.
        'create_directory': {'keys': ['M'], 'selection': 'none'},  # Create new directory (only when no files selected)

        # === File Viewing & Editing ===
        'view_file': ['V'],                    # View file using configured viewer
        'quick_view': ['Shift-V'],             # Preview the cursor item in the other pane (again to close)
        'edit_file': ['E'],                    # Edit selected file with configured text editor (also inside the text viewer)
        'file_details': ['I'],                 # Show detailed file information dialog

        # === Archive Operations ===
        'create_archive': {'keys': ['P'], 'selection': 'required'},  # Create archive from selected files
        'extract_archive': ['U'],              # Extract selected archive file

        # === Search ===
        'isearch': ['F'],                      # Enter incremental search mode (isearch)
        'find_files': ['Shift-F'],             # Show filename search dialog
        'find_in_files': ['Shift-G'],          # Show content search dialog (grep)

        # === Sorting ===
        'sort': ['S'],                         # Open the sort dialog (key + order)
        'quick_sort_name': ['1'],              # Quick sort by filename
        'quick_sort_ext': ['2'],               # Quick sort by file extension
        'quick_sort_size': ['3'],              # Quick sort by file size
        'quick_sort_date': ['4'],              # Quick sort by modification date

        # === Places ===
        'favorites': ['J'],                    # Show favorites dialog
        'add_favorite': ['B'],                 # Add this directory / the cursor item to favorites
        'jump_to_path': ['Shift-J'],           # Jump to path
        'history': ['H'],                      # Show history for current pane
        'drives': ['D'],                       # Show drives/volumes dialog
        'connect_server': ['Shift-D'],         # Connect to a network server (macOS/Windows)

        # === Panes and Tabs ===
        # T is a bare letter nothing else uses.
        'new_tab': ['T'],                      # Open a new tab in this pane at the same place
        'open_in_new_tab': ['Shift-T'],        # Open the directory under the cursor in a new tab
        'sync_current_to_other': ['O'],        # Sync current pane directory to other pane
        'sync_other_to_current': ['Shift-O'],  # Sync other pane directory to current pane
        'compare_selection': ['W'],            # Show file and directory comparison options

        # === External Programs ===
        'programs': ['X'],                     # Show external programs menu
        'subshell': ['Shift-X'],               # Enter subshell (command line) mode
    }
    if is_desktop_mode() and sys.platform == 'darwin':
        # The common table's Command-C / X / V come first on macOS; the
        # letters ride along.
        keys['clipboard_copy'] = ['Command-C', 'Ctrl-C', 'Y']
        keys['clipboard_cut'] = ['Command-X', 'Ctrl-X', 'Shift-Y']
        keys['clipboard_paste'] = ['Command-V', 'Ctrl-V', 'G']
    return keys

