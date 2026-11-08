"""The Orthodox keymap preset: function keys, and typing a letter searches.

F3 view, F5 copy, F8 delete — the layout shared by the "orthodox" two-pane
file managers. Laid over :mod:`xefm.keymaps.common` by
:func:`xefm.keymap_presets.table`; the preset's label and its type-ahead flag
are in :mod:`xefm.keymap_presets`.
"""


def own_bindings() -> dict:
    """Orthodox's keys: action name -> keys, each replacing that action's
    entry in the common table. A new dict on every call."""
    # Total Commander's default keys wherever XeFM has the action (its
    # keyboard map: Configuration > Keyboard, KEYBOARD.TXT). Where TC's key
    # does something XeFM has no action for, the key is simply not bound;
    # where XeFM has an action TC has no key for, the action keeps no key
    # here and is reached from the menus and the command palette. Actions
    # from features not merged yet are listed too: ``apply`` skips any the
    # running XeFM does not have.
    return {
        # Application
        "help": ["F1"],
        "reread": ["F2", "Ctrl-R"],
        "menu": ["F9", "F10", "ALT"],
        "quit": ["Alt-F4"],
        "redraw": [],
        "programs": [],
        "context_menu": ["Shift-F10", "APPS"],
        "command_palette": ["Ctrl-Shift-P"],   # TC has none; Ctrl-T is tabs
        # Files
        "view_file": ["F3"],
        "edit_file": ["F4"],
        "create_file": ["Shift-F4"],
        "copy_files": ["F5"],
        "duplicate_files": ["Shift-F5"],        # TC: copy with rename, same dir
        "move_files": ["F6"],
        "rename": ["Shift-F6", "Ctrl-M"],       # Ctrl-M: multi-rename
        "create_directory": ["F7"],
        "delete_files": ["F8", "DELETE"],
        "delete_permanently": ["Shift-F8", "Shift-DELETE"],
        "copy_files_to": [],
        "move_files_to": [],
        "file_details": ["Alt-ENTER"],          # TC: properties
        "create_archive": ["Alt-F5"],
        "extract_archive": ["Alt-F9", "Alt-F6"],
        "clipboard_copy": ["Ctrl-C"],
        "clipboard_cut": ["Ctrl-X"],
        "clipboard_paste": ["Ctrl-V"],
        "copy_names": [],
        "copy_paths": ["Ctrl-P"],
        # Search and filter
        "find_files": ["Alt-F7"],
        "find_in_files": [],
        "filter": ["Ctrl-S"],                   # TC: quick filter
        "clear_filter": ["Ctrl-F10"],           # TC: show all files
        "isearch": [],                          # typing a letter searches
        "index_search": [],
        "find_by_tag": [],
        # Places
        "open_item": ["ENTER", "Ctrl-PAGE_DOWN"],
        "go_parent": ["BACKSPACE", "Ctrl-PAGE_UP"],
        "go_root": ["Ctrl-BACKSLASH"],
        "drives": ["Alt-F1", "Alt-F2"],          # TC: left / right drive
        "history": ["Alt-DOWN"],
        "go_back": ["Alt-LEFT"],
        "go_forward": ["Alt-RIGHT"],
        "favorites": ["Ctrl-D"],                # TC: directory hotlist
        "connect_server": ["Ctrl-F", "Ctrl-N"],  # TC: FTP connect / new URL
        "compare_selection": ["Shift-F2"],      # TC: compare file lists
        "diff_directories": [],
        "flat_view": ["Ctrl-B"],                # TC: branch view
        "quick_view": ["Ctrl-Q"],
        # Tabs
        "new_tab": ["Ctrl-T"],
        "open_in_new_tab": ["Ctrl-UP"],
        "close_tab": ["Ctrl-W"],
        "next_tab": ["Ctrl-TAB"],
        "prev_tab": ["Ctrl-Shift-TAB"],
        # Selection and cursor
        "toggle_select_down": ["INSERT", "SPACE"],
        "select_by_pattern": ["+"],             # TC: Num +
        "unselect_by_pattern": ["-"],           # TC: Num -
        "toggle_select_files": ["*"],           # TC: Num * (invert)
        "select_all": ["Ctrl-A"],
        "unselect_all": ["Ctrl-MINUS"],         # TC: Ctrl-Num -
        "select_same_extension": ["Alt-+"],     # TC: Alt-Num +
        "cursor_top": ["HOME", "Ctrl-HOME"],
        "cursor_bottom": ["END", "Ctrl-END"],
        "cursor_next_selected": [],             # Ctrl-Up opens a tab here
        "cursor_prev_selected": [],
        "reveal_in_os": [],                     # Ctrl-R rereads here
        "reset_pane_boundary": [],              # '-' unselects here
        "reset_log_height": [],                 # '_' starts names (__init__.py)
        # Sorting
        "quick_sort_name": ["Ctrl-F3"],
        "quick_sort_ext": ["Ctrl-F4"],
        "quick_sort_date": ["Ctrl-F5"],
        "quick_sort_size": ["Ctrl-F6"],
        # The viewers, as Lister: F7 searches, F3 / Shift-F3 find again —
        # scoped, since F7 and F3 are the file list's new folder and view
        # (#737). The isearch bar takes F3 / Shift-F3 from these too.
        "text_viewer.isearch": ["F7"],
        "text_viewer.search_next": ["F3"],
        "text_viewer.search_prev": ["Shift-F3"],
        "file_diff.isearch": ["F7"],
        "file_diff.search_next": ["F3"],
        "file_diff.search_prev": ["Shift-F3"],
    }
