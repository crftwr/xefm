"""The OS native keymap preset: Finder's keys on macOS, Explorer's elsewhere.

Laid over :mod:`xefm.keymaps.common` by :func:`xefm.keymap_presets.table`;
the preset's label and its type-ahead flag are in :mod:`xefm.keymap_presets`.
"""

import sys

from xefm.backend_detector import is_desktop_mode


def own_bindings() -> dict:
    """The OS native table for the case XeFM is running in (#587).

    Finder's keys in the macOS desktop app, Explorer's in the Windows one, and
    in a terminal on any OS the same layout with every chord a terminal can
    actually send — the "three cases" note at the foot of
    :mod:`xefm.keymap_common` says which those are. The preset is chosen once for
    both apps (``~/.xefm``), so the terminal case has to stand on its own: the
    desktop tables are it with the platform chord in front, never a different
    layout.

    The two-pane operations have no OS convention, so they take the function
    keys every two-pane manager uses (F5 copy, F6 move to the other pane), as
    Orthodox does. Enter opens, on macOS too: Finder's Enter-renames would
    leave no key to open a folder that every other preset opens with Enter.
    """
    keys = {
        # Opening and moving around
        "open_item": ["ENTER"],
        "go_parent": ["BACKSPACE", "Alt-UP"],
        "go_back": ["Alt-LEFT"],
        "go_forward": ["Alt-RIGHT"],
        "cursor_top": ["HOME", "Ctrl-HOME"],
        "cursor_bottom": ["END", "Ctrl-END"],
        "jump_to_path": ["Ctrl-L", "Alt-D"],
        "history": ["Alt-DOWN"],
        "new_tab": ["Ctrl-T"],
        # Files
        "rename": ["F2"],
        "view_file": ["F3"],
        "edit_file": ["F4"],
        "copy_files": ["F5"],
        "move_files": ["F6"],
        "create_directory": ["F7"],
        "delete_files": ["DELETE", "F8"],
        "delete_permanently": ["Shift-DELETE", "Shift-F8"],
        "clipboard_copy": ["Ctrl-C"],
        "clipboard_cut": ["Ctrl-X"],
        "clipboard_paste": ["Ctrl-V"],
        "file_details": ["Alt-I"],
        "quick_view": ["Alt-P"],                # Explorer's preview pane
        "context_menu": ["Shift-F10", "APPS"],
        # Selection: Space marks, as in Explorer; typing a letter selects by name
        "toggle_select_down": ["SPACE", "INSERT"],
        "select_all": ["Ctrl-A"],
        "unselect_all": [],
        # Search
        "find_files": ["Ctrl-F"],
        "index_search": [],
        "isearch": [],                          # typing a letter searches
        # Application
        "help": ["F1"],
        "reread": ["Ctrl-R"],
        "reveal_in_os": [],                     # Ctrl-R rereads here
        "redraw": [],                           # F5 copies here
        "command_palette": ["Ctrl-K"],
        # Ctrl-Q always asks. Cmd-Q / Alt-F4 (quit_app) come with the AFX
        # table's desktop keys, which every preset starts from.
        "quit": ["Ctrl-Q"],
        # The viewers find as Windows' own viewers do (#737): scoped, since
        # Ctrl-F is the file list's find_files.
        "text_viewer.isearch": ["Ctrl-F"],
        "text_viewer.search_next": ["F3"],
        "text_viewer.search_prev": ["Shift-F3"],
        "file_diff.isearch": ["Ctrl-F"],
        "file_diff.search_next": ["F3"],
        "file_diff.search_prev": ["Shift-F3"],
    }
    if not is_desktop_mode():
        return keys
    if sys.platform == "darwin":
        # Finder. A Command chord goes first, since a menu shows keys[0].
        keys.update({
            "open_item": ["ENTER", "Command-DOWN"],
            "go_parent": ["Command-UP", "BACKSPACE", "Alt-UP"],
            "go_back": ["Command-LEFT_BRACKET", "Alt-LEFT"],
            "go_forward": ["Command-RIGHT_BRACKET", "Alt-RIGHT"],
            "jump_to_path": ["Command-Shift-G", "Ctrl-L"],
            "new_tab": ["Command-T", "Ctrl-T"],
            "close_tab": ["Command-W", "Ctrl-W"],
            "delete_files": ["Command-BACKSPACE", "DELETE", "F8"],
            "delete_permanently": ["Command-Alt-BACKSPACE", "Shift-DELETE", "Shift-F8"],
            "create_directory": ["Command-Shift-N", "F7"],
            "clipboard_copy": ["Command-C", "Ctrl-C"],
            "clipboard_cut": ["Command-X", "Ctrl-X"],
            "clipboard_paste": ["Command-V", "Ctrl-V"],
            "copy_paths": ["Command-Alt-C", "Ctrl-P"],
            "file_details": ["Command-I", "Alt-I"],
            # Quick Look is Space; marking moves to Ctrl-Space, which every
            # backend delivers.
            "quick_view": ["SPACE", "Alt-P"],
            "toggle_select_down": ["Ctrl-SPACE", "INSERT"],
            "select_all": ["Command-A", "Ctrl-A"],
            "find_files": ["Command-F", "Ctrl-F"],
            "toggle_hidden": ["Command-Shift-.", "."],
            "command_palette": ["Command-Shift-P", "Ctrl-K"],
            # The standard macOS find keys in the viewers.
            "text_viewer.isearch": ["Command-F", "Ctrl-F"],
            "text_viewer.search_next": ["Command-G", "F3"],
            "text_viewer.search_prev": ["Command-Shift-G", "Shift-F3"],
            "file_diff.isearch": ["Command-F", "Ctrl-F"],
            "file_diff.search_next": ["Command-G", "F3"],
            "file_diff.search_prev": ["Command-Shift-G", "Shift-F3"],
        })
    elif sys.platform == "win32":
        keys.update({
            "create_directory": ["Ctrl-Shift-N", "F7"],
            "copy_paths": ["Ctrl-Shift-C", "Ctrl-P"],
            "file_details": ["Alt-ENTER", "Alt-I"],
            "command_palette": ["Ctrl-Shift-P", "Ctrl-K"],
        })
    return keys
