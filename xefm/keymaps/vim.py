"""The Vim style keymap preset: hjkl, gg / G, yy / dd / p, / and n.

Laid over :mod:`xefm.keymaps.common` by :func:`xefm.keymap_presets.table`;
the preset's label is in :mod:`xefm.keymap_presets`.
"""

# vifm's normal-mode keys (vifm 0.15 manual, and the sample vifmrc a new
# install gets: F3-F8, w, s, S), wherever XeFM has the action. Like AFX it
# is a letter layout, laid over the common table (which binds no letter), and
# nothing is typed ahead: search is '/', as in Vim. Sequences ('g g', 'y y') are
# KEY_BINDINGS key sequences, waiting KEY_SEQUENCE_TIMEOUT where a prefix is
# also a key of its own.
_BINDINGS = {
    # Moving: h is the parent directory and l opens, as in vifm, not a column
    # step; the arrows keep AFX's meaning.
    "cursor_down": ["j", "DOWN"],
    "cursor_up": ["k", "UP"],
    "go_parent": ["h", "g h", "BACKSPACE"],
    "open_item": ["l", "g l", "ENTER"],
    "cursor_top": ["g g", "HOME", "Ctrl-HOME"],
    "cursor_bottom": ["Shift-G", "END", "Ctrl-END"],
    "page_down": ["Ctrl-F", "PAGE_DOWN"],
    "page_up": ["Ctrl-B", "PAGE_UP"],
    "half_page_down": ["Ctrl-D"],
    "half_page_up": ["Ctrl-U"],
    "switch_pane": ["TAB", "SPACE"],
    "go_back": ["Ctrl-O", "Alt-LEFT"],
    "go_forward": ["Alt-RIGHT"],               # vifm's Ctrl-I is Tab here
    "jump_to_path": ["g p"],
    "favorites": ["'"],                        # vifm's marks
    # Selecting. vifm's v starts a visual block; here it fills from the
    # nearest mark to the cursor, which is what a block ends as.
    "toggle_select_in_place": ["t"],
    "toggle_select_down": ["INSERT"],
    "select_range": ["v", "Shift-SPACE"],
    "select_all": [],
    "unselect_all": ["ESCAPE"],                # vifm: Esc clears the selection
    "select_by_pattern": [],                   # ' is marks here
    # Files: yank / delete / put. dd goes to the Trash and DD past it, as in
    # vifm; p pastes what yy yanked, and x cuts (vifm's P moves a yank; here a
    # cut and a paste do).
    "clipboard_copy": ["y y", "Ctrl-C"],
    "clipboard_cut": ["x", "Ctrl-X"],
    "clipboard_paste": ["p", "Ctrl-V"],
    "delete_files": ["d d", "DELETE", "F8"],
    "delete_permanently": ["Shift-D Shift-D", "Shift-DELETE", "Shift-F8"],
    "rename": ["c w"],
    "view_file": ["e", "F3"],
    "open_with_os": ["g x"],                   # Vim's gx; Ctrl-O goes back here
    "diff_files": [],                          # '=' filters here
    "edit_file": ["F4"],
    "copy_files": ["F5"],
    "move_files": ["F6"],
    "create_directory": ["F7"],
    "quick_view": ["w"],
    "file_details": ["Ctrl-G"],
    "jobs": [],                                # Ctrl-G is file details here
    # Search, hidden files, filters
    "isearch": ["/"],
    "search_next": ["n"],
    "search_prev": ["Shift-N"],
    "index_search": [],                        # Ctrl-F pages here
    "toggle_hidden": ["z a"],
    "filter": ["="],
    "clear_filter": ["z r"],
    "sort": ["Shift-S"],
    # Application
    "command_palette": [":", "Ctrl-T"],
    "context_menu": ["APPS", "Shift-F10"],     # '/' searches here
    "subshell": ["s"],
    "reread": ["Ctrl-L"],
    "redraw": [],                              # F5 copies here
    "quit": ["Shift-Z Shift-Z", "Shift-Z Shift-Q"],
    # The text viewer, as vifm's view mode with Vim's motions
    "text_viewer.scroll_down": ["j", "DOWN"],
    "text_viewer.scroll_up": ["k", "UP"],
    "text_viewer.scroll_left": ["h", "LEFT"],
    "text_viewer.scroll_right": ["l", "RIGHT"],
    "text_viewer.page_down": ["Ctrl-F", "Ctrl-D", "PAGE_DOWN", "SPACE"],
    "text_viewer.page_up": ["Ctrl-B", "Ctrl-U", "PAGE_UP"],
    "text_viewer.scroll_top": ["g g", "HOME"],
    "text_viewer.scroll_bottom": ["Shift-G", "END"],
    "text_viewer.quit": ["q", "Shift-Z Shift-Z"],
}


def own_bindings() -> dict:
    """Vim style's keys: action name -> keys, each replacing that action's
    entry in the common table. A new dict on every call."""
    return {action: list(keys) for action, keys in _BINDINGS.items()}
