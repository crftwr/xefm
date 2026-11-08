"""The AFX-style keymap (#565, #597): one letter runs one command.

``C`` copies, ``M`` moves, ``K`` deletes — the single-key style of the
Japanese two-pane filers: the X68000 file managers, then AFX (あふ) on
Windows, then cfiler. XeFM follows that direction rather than copying any one
of them key for key.

This is one of the keymap presets (:mod:`xefm.keymap_presets`), a peer of the
others, not a default they are laid over. It is also where every viewer's,
dialog's and search bar's keys live: those surfaces take typed text or have
no file list, so their keys are the same under every preset, and the other
presets start from this table's copy of them.

``config.py``'s ``KEY_BINDINGS`` overrides whatever preset is in force, action
by action; it ships nearly empty.
"""

import sys

from xefm.backend_detector import is_desktop_mode


def bindings() -> dict:
    """The whole table — action name → keys, or ``{'keys': …, 'selection':
    …}`` — with the per-platform desktop overrides for the platform running.
    A new dict on every call, so a caller may change it freely."""
    KEY_BINDINGS = {
        # === Application Control ===
        'quit': ['Q'],                         # Exit XeFM application
        'quit_app': [],                        # Cmd-Q / Alt-F4 in the desktop app (below)
        # F1, not '?': Shift-/ is the directory context menu below, and a
        # terminal cannot tell Shift-/ from '?' -- both arrive as the glyph.
        'help': ['F1'],                        # Show help dialog with all key bindings
        # A repaint should never be something you have to ask for, so this gets a
        # function key and none of the scarce Ctrl+letters: it is the escape hatch
        # for a screen a *multiplexer* or another program wrote over, not a part
        # of using XeFM.
        'redraw': ['F5'],                      # Repaint the screen
        'menu': ['F10', 'ALT'],                # Open the menu bar (terminal; a bare Alt tap works on the Windows terminal, F10 everywhere)
        # Ctrl-T -- the palette lives in the Tools menu. Not the Ctrl-Shift-P
        # other applications use: Windows Terminal takes that chord for its own
        # palette, and a POSIX terminal cannot tell it from Ctrl-P (copy_paths).
        # Shift-P is left to the archive family (P), and Ctrl-K was passed over
        # because a missed Ctrl would land on K, delete. A missed Ctrl here
        # lands on T, which nothing is bound to.
        'command_palette': ['Ctrl-T'],         # Search every action by name and run it
        # The background jobs list. The status bar's right end shows what is
        # running; this brings a job forward (its prompt, or Esc to cancel).
        'jobs': ['Ctrl-G'],                    # List background jobs
        
        # === Navigation ===
        'cursor_up': ['UP'],                   # Move cursor up one item
        'cursor_down': ['DOWN'],               # Move cursor down one item
        'page_up': ['PAGE_UP'],                # Move cursor up one page
        'page_down': ['PAGE_DOWN'],            # Move cursor down one page
        'cursor_top': ['Ctrl-HOME'],           # Move cursor to the first item
        'cursor_bottom': ['Ctrl-END'],         # Move cursor to the last item
        'open_item': ['ENTER'],                # Open file/directory or enter directory
        'open_with_os': ['Ctrl-O'],            # Open file(s) with OS default application (desktop adds Cmd/Ctrl-ENTER)
        'reveal_in_os': ['Ctrl-R'],            # Reveal focused file in OS file manager
        'go_parent': ['BACKSPACE'],            # Go to parent directory
        'go_root': ['\\'],                     # Go to the root of the current drive/location
        # Shift-B, not Ctrl-B: that is tmux's prefix, so inside tmux it would
        # never arrive. A capital is a glyph, which every terminal delivers.
        'flat_view': ['Shift-B'],            # Show every file below this directory as one flat list (again to go back)
        'switch_pane': ['TAB'],                # Switch between left and right panes
        'nav_left': ['LEFT'],                  # Left pane: go to parent, Right pane: switch to left pane
        'nav_right': ['RIGHT'],                # Right pane: go to parent, Left pane: switch to right pane
        'focus_left': [],                      # Focus the left pane (unbound; bind a key here)
        'focus_right': [],                     # Focus the right pane (unbound; bind a key here)
        
        # === File Selection ===
        'toggle_select_down': ['SPACE'],              # Toggle selection of current file
        # Mark one item, move the cursor, then Shift-SPACE fills the span between
        # them -- a Shift-click from the keyboard. The nearest marked item above
        # the cursor is the anchor (below, when there is none above), and nothing
        # outside the span is touched, so several runs add up.
        #
        # Shift-SPACE is the desktop app's and the Windows console's key. A POSIX
        # terminal has no room for a modifier on a printable, so Shift-SPACE
        # arrives there as a plain SPACE and toggles one item instead; under
        # Terminal.app, iTerm2 or a Linux terminal, put this on a chord the
        # terminal can carry ('Ctrl-LEFT', 'Ctrl-Y', 'F6').
        #
        # A file-list key only: an open search has no range of its own. Press
        # Enter to leave the search -- the cursor stays on the match it found --
        # and the range is this key again.
        'select_range': ['Shift-SPACE'],       # Select from the nearest marked item to the cursor
        # Unbound: SPACE already marks and moves, and Shift-SPACE now fills a
        # range. Put it back on a key of your own if you mark upwards often.
        'toggle_select_up': [],                # Toggle selection and move up
        'select_all': ['HOME'],                # Select all items (Home key)
        'unselect_all': ['END'],               # Unselect all items (End key)
        'toggle_select_files': ['A'],             # Toggle selection of all files in current pane
        'toggle_select_items': ['Shift-A'],       # Toggle selection of all items (files + dirs)
        # Select / unselect by pattern sit beside the filter's ';' and ':' --
        # the same pattern language, one key over. Both are glyphs, so a
        # terminal delivers them like any printable (cfiler's keys, too).
        # Total Commander's Num+ / Num- cannot be told from '+' / '-' here, and
        # those two already compare directories and reset the pane split.
        'select_by_pattern': ["'"],            # Select the files matching a pattern (prompts)
        'unselect_by_pattern': ['"'],          # Unselect the files matching a pattern (prompts)
        'select_same_extension': [],           # Select every file with the cursor file's extension (Select menu)
        'cursor_next_selected': ['Ctrl-DOWN'], # Move cursor to the next selected item
        'cursor_prev_selected': ['Ctrl-UP'],   # Move cursor to the previous selected item
        
        # === Clipboard (copy names/paths to the system clipboard) ===
        # Ctrl+letter, not the Command-Shift / Ctrl-Shift chords these used to
        # carry, for the reason spelled out under "Three cases" at the foot of
        # KEY_BINDINGS: a terminal cannot deliver either of those.
        'copy_names': ['Ctrl-N'],              # Copy selected/focused file name(s) to clipboard
        'copy_paths': ['Ctrl-P'],              # Copy selected/focused full path(s) to clipboard

        # === File Clipboard ===
        # Copy or cut now, paste wherever you go next -- the folder you stand
        # in, or (macOS / Windows) another application. C / M above stay the
        # one-step way to the other pane. The copy key copies the log's
        # selected text instead when the log has a selection.
        'clipboard_copy': ['Ctrl-C', 'Y'],     # Copy files to the clipboard
        'clipboard_cut': ['Ctrl-X', 'Shift-Y'],  # Cut files to the clipboard (moved on paste)
        'clipboard_paste': ['Ctrl-V', 'G'],    # Paste the clipboard into this folder
        'clipboard_clear': [],                 # Empty the file clipboard (Edit menu)

        # === File Operations ===
        'copy_files': {'keys': ['C'], 'selection': 'required'},  # Copy selected files to other pane
        'move_files': {'keys': ['M'], 'selection': 'required'},  # Move selected files to other pane
        'copy_files_to': {'keys': ['Shift-C'], 'selection': 'required'},  # Copy selected files to a typed directory
        'move_files_to': {'keys': ['Shift-M'], 'selection': 'required'},  # Move selected files to a typed directory
        'delete_files': {'keys': ['K', 'DELETE'], 'selection': 'required'}, # Delete selected files/directories (to the Trash where there is one)
        'delete_permanently': {'keys': ['Shift-K', 'Shift-DELETE'], 'selection': 'required'},  # Delete for good, skipping the Trash
        'rename': ['R'],                  # Rename selected file/directory
        'rename_in_editor': ['Shift-R'],  # Rename the selection by editing a name list in TEXT_EDITOR
        'create_file': ['Shift-E'],            # Create new file (prompts for filename)
        'create_directory': {'keys': ['M'], 'selection': 'none'},  # Create new directory (only when no files selected)
        
        # === File Viewing & Editing ===
        'view_file': ['V'],                    # View file using configured viewer
        'quick_view': ['Shift-V'],             # Preview the cursor item in the other pane (again to close)
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
        # The OS's own index: Spotlight on macOS, Windows Search on Windows.
        'index_search': ['Ctrl-F'],           # Search the OS index under this folder (results as a list)
        'find_by_tag': [],                    # Find files by tag under this folder (View > Search Tags…)
        'filter': [';'],                       # Enter filter mode to show only matching files
        'clear_filter': [':'],                 # Clear current file filter
        
        # === Sorting ===
        'sort': ['S'],                    # Open the sort dialog (key + order)
        'quick_sort_name': ['1'],              # Quick sort by filename
        'quick_sort_ext': ['2'],               # Quick sort by file extension
        'quick_sort_size': ['3'],              # Quick sort by file size
        'quick_sort_date': ['4'],              # Quick sort by modification date
        
        # === Directory Navigation ===
        'favorites': ['J'],                    # Show favorites dialog
        'add_favorite': ['B'],                 # Add this directory / the cursor item to favorites

        # === Context Menus ===
        # The right-click menus, from the keyboard: '/' for the item under the
        # cursor (opened just below it), Shift-/ -- the '?' glyph -- for the
        # directory itself. APPS is the PC keyboard's Menu key; a POSIX terminal
        # never sends it, so the punctuation keys are the ones that work there.
        'context_menu': ['/', 'APPS'],         # Context menu for the cursor item
        'context_menu_dir': ['?', 'Shift-APPS'],  # Context menu for the current directory
        'jump_to_path': ['Shift-J'],           # Jump to path
        'history': ['H'],                      # Show history for current pane
        'go_back': ['Alt-LEFT'],               # Back to the directory shown before (also the mouse's back button)
        'go_forward': ['Alt-RIGHT'],           # Forward again (also the mouse's forward button)
        'drives': ['D'],                # Show drives/volumes dialog
        'connect_server': ['Shift-D'],  # Connect to a network server (macOS/Windows)
        
        # === Pane Management ===
        # Folder tabs, per pane. T is a bare letter nothing else uses; Ctrl-W
        # is the close every tabbed program has. Next/previous are on
        # Ctrl-PAGE_DOWN / Ctrl-PAGE_UP because a terminal never delivers
        # Ctrl-TAB.
        'new_tab': ['T'],                      # Open a new tab in this pane at the same place
        'open_in_new_tab': ['Shift-T'],        # Open the directory under the cursor in a new tab
        'close_tab': ['Ctrl-W'],               # Close this pane's current tab
        'next_tab': ['Ctrl-PAGE_DOWN'],        # Show this pane's next tab
        'prev_tab': ['Ctrl-PAGE_UP'],          # Show this pane's previous tab
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
        # Drag across the log with the mouse to select, then copy. Ctrl-C works
        # everywhere; the macOS desktop adds Command-C below, because copying
        # text is the one place that chord is the whole platform's convention.
        'copy_log_selection': [],              # Copy the log pane's selected text (Edit menu; the copy key below does it when the log has a selection)
        'copy_log_all': [],                    # Copy the whole log (unbound; Edit menu, or bind a key here)
        
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
        # Font size for this run, in the desktop app (below): a terminal draws
        # in its own font.
        'increase_font_size': [],
        'decrease_font_size': [],
        'reset_font_size': [],

        # === External Programs ===
        'programs': ['X'],                     # Show external programs menu
        'subshell': ['Shift-X'],               # Enter subshell (command line) mode

        # === Configuration ===
        # Unbound by default (reachable via the Tools menu). Assign a key here to
        # open/reload this file without leaving XeFM, e.g. 'edit_config': ['Y'].
        'edit_config': [],                     # Edit this config.py in TEXT_EDITOR, then reload
        'reload_config': [],                   # Re-read this config.py and apply live
        'install_extension': [],               # Install an extension package: folder, .zip, URL or github:owner/repo
        'extensions': [],                      # List extension packages and why any did not load
        'check_extension_updates': [],         # Look for newer versions of extension packages
        'sync_python_packages': [],            # Install what ~/.xefm/requirements.txt lists

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

        # === Incremental-search keys (rebindable, not listed above) ===========
        # The search bar ('F') is a surface of its own, and its keys are named
        # the same way. Their defaults:
        #
        #   'isearch.next_match':         DOWN        next match
        #   'isearch.prev_match':         UP          previous match
        #   'isearch.toggle_select_down': Ctrl-SPACE  select, then next match
        #   'isearch.toggle_select_up':   (unbound)   select, then previous match
        #   'isearch.select_matches':     Ctrl-A      select every match
        #                                             (again: clear them)
        #   'isearch.accept':             ENTER       stop at the current match
        #   'isearch.cancel':             ESCAPE      cancel, restoring the cursor
        #
        # One rule applies here and nowhere else: the key must NOT be one that
        # types a character. Everything printable belongs to the pattern you are
        # typing -- SPACE included, which the search reads as the separator
        # between the pattern's words ('re 24' finds 'report_2024.txt'), and
        # which is exactly why marking a file here is Ctrl-SPACE rather than
        # the file list's bare SPACE. Bind one of these to 'N' and it can never fire;
        # XeFM says so in the log pane at startup rather than leaving you to
        # wonder. Modified and non-printable keys are all free: 'Shift-DOWN',
        # 'Ctrl-Y', 'F2', 'INSERT' (on Windows and in the terminal -- macOS
        # keyboards have no Insert key).
        #
        # The marking key spells the file list's out loud: SPACE selects, so
        # Ctrl-SPACE selects here, Ctrl being what makes a command of a key that
        # would otherwise type. It reaches every backend (in a terminal it is the
        # NUL byte). This was Shift-DOWN / Shift-UP, which read as the log pane's
        # scroll keys, since that is what the same chord does in the file list a
        # row away; marking backwards has no default now, in either surface,
        # because a search walks forwards.
        #
        # There is no range key here on purpose. The file list's 'select_range'
        # fills the span between a marked item and the cursor, and its anchor is
        # something you marked before the search started -- not a match. Enter
        # leaves the search on the match it found, so the range is one keystroke
        # away where it means what it says.
        #
        # Ctrl-A is the one default that takes a key the pattern field would
        # otherwise use (select-all-text), and only in the Ctrl form -- Command-A
        # still selects the text on macOS.
        #
        # Example -- select with Insert, on a keyboard that has one:
        # 'isearch.toggle_select_down': ['INSERT'],

        # === Searchable-list picker keys (rebindable, not listed above) =======
        # The picker dialogs -- Favorites, Drives, History, External Programs and
        # the ';' Filter prompt -- are a surface of their own ('filter_list'), and
        # two of their keys are yours to move:
        #
        #   'remove_list_item':    Shift-DELETE  forget the highlighted row
        #   'describe_list_item':  F1            help for the highlighted row
        #
        # The help key is offered where a row has more to say than its label:
        # the command palette (Ctrl-T) today.
        #
        # It only does anything where the rows are *remembered* rather than
        # declared: History and the Filter prompt, whose lists XeFM built by
        # watching you, and the favorites you added with B. Favorites written in
        # this file and External Programs are yours to edit here, so the key
        # leaves them alone (in Drives it disconnects or ejects instead).
        #
        # The name has no context prefix on purpose: removing the highlighted row
        # is an operation other lists may grow later, and an unqualified entry
        # rebinds it in all of them at once. Prefix it to move just one --
        # 'filter_list.remove_list_item'.
        #
        # The printable-key rule from the search bar applies here too: the query
        # field takes every character you type, so a remove key has to be
        # modified or non-printable.
        #
        # Example -- forget a row with Ctrl-D instead:
        # 'remove_list_item': ['Ctrl-D'],

        # === Search dialog keys (rebindable, not listed above) ================
        # The live search dialog (Shift-F / Shift-G) is a surface of its own,
        # 'search'. Its one key opens the options for the search in front of you:
        #
        #   'options':  Ctrl-O, F9   case, pattern language, subfolders
        #
        # It is one key rather than one key per option on purpose. A surface with
        # a query field has no keys to spare -- every printable key belongs to the
        # query -- and the modified keys that remain are few enough to count, so
        # a dialog that spent three of them would leave nothing for the next one.
        # The options box has no query field, which is what makes every plain
        # letter in it a key: an option is toggled by its label's initial (c, w,
        # r, s here), however many an option list grows to. The letters are not
        # drawn, for the reason the Sort dialog does not draw F/E/S/T -- the word
        # already carries its initial.
        #
        # The name carries no context prefix, for the same reason
        # 'remove_list_item' above carries none: "open the options for the thing
        # in front of you" is an operation other surfaces will grow, and an
        # unqualified entry rebinds it in all of them at once. Prefix it to move
        # just one -- 'search.options'.
        #
        # Ctrl-O works in the terminal and in both native windows; F9 rides along
        # next to F10 (the menu bar) where a keyboard has real function keys.
        # Alt chords cannot carry this: macOS spends Option on glyphs and IME, and
        # an Alt chord the terminal does not recognize arrives as ESCAPE, which
        # would close the dialog instead of opening its options.
        #
        # Each option also has an action of its own, deliberately UNBOUND, for the
        # one option you change hourly and would rather not open a box for:
        #
        #   'search.toggle_case'      match capitals exactly
        #   'search.toggle_word'      whole words only (content search)
        #   'search.toggle_regex'     read the query as a regular expression
        #   'search.toggle_subdirs'   search subfolders, or this directory alone
        #
        # The printable-key rule from the search bar applies to all of these: the
        # query field takes every character you type, so these must be modified or
        # non-printable keys. XeFM says so in the log pane at startup if one is not.
        #
        # Example -- put case sensitivity on a direct chord:
        # 'search.toggle_case': ['Ctrl-T'],
    }

    # -----------------------------------------------------------------------
    # Three cases: macOS desktop / Windows desktop / any terminal
    # -----------------------------------------------------------------------
    # The table above is the COMMON set — every key in it is one all three cases
    # can actually deliver, with one deliberate exception named below. What a
    # terminal cannot carry, and why the OS-flavoured actions above are plain
    # Ctrl+letter rather than the chord each platform would use in a GUI:
    #
    #   Command-<key>        no terminal encodes Command at all — not
    #                        Terminal.app, not iTerm2, not VS Code's.
    #   Ctrl-Shift-<letter>  a POSIX terminal sends Ctrl+letter as one control
    #                        byte with no room for Shift, so 'Ctrl-Shift-C' is
    #                        the same key as 'Ctrl-C' there. (Only the Windows
    #                        console reports a real key with its modifiers.)
    #   Shift-<printable>    the same gap on the other side: a terminal reports
    #                        the character, and the character for Shift-SPACE is
    #                        a space. This is the exception — 'select_range' takes
    #                        Shift-SPACE anyway, because Shift is the range
    #                        gesture users bring with them and no key a terminal
    #                        can carry says "range" at all. In a POSIX terminal
    #                        it toggles one item (plain SPACE's job) until you
    #                        rebind it; the file's File Selection block says so.
    #   Ctrl-ENTER           likewise indistinguishable from plain ENTER.
    #   Alt-ENTER            macOS keyboards spend Option on glyphs and IME, and
    #                        the Windows terminal takes Alt-Enter for fullscreen.
    #
    # Ctrl-SPACE is the way round it, and is why the search bar's marking key is
    # that rather than a Shift chord: a terminal sends it as the NUL byte, which
    # PuiKit decodes (1.7.2), and both consoles report it natively.
    #
    # Shift and Ctrl on a NAMED key (Ctrl-UP, Shift-DOWN, Ctrl-HOME) are fine
    # everywhere — a terminal has a sequence for those — which is why the rest of
    # this table needs no per-case treatment.
    #
    # The letters were chosen against what the host takes first: Ctrl-P is VS
    # Code's Quick Open in its own terminal on Windows and Linux (the one
    # deliberate compromise here — the mnemonic is worth more than that case),
    # Ctrl-E is the same dialog, Ctrl-B is tmux's prefix and Ctrl-A screen's,
    # Ctrl-S / Ctrl-Q are flow control, Ctrl-L clears a screen by convention, and
    # Ctrl-I / M / J / H / [ are tab, enter, backspace and escape before they are
    # letters. Ctrl-O is also the search dialog's options key, in its own context
    # — the two surfaces never apply at once, so the letter carries both.
    #
    # Only two things are worth overriding per case, and both are strong
    # platform idioms rather than missing keys:
    if is_desktop_mode():
        if sys.platform == 'darwin':
            # The Finder gesture: a modifier on the same Enter that opens.
            KEY_BINDINGS['open_with_os'] = ['Command-ENTER', 'Ctrl-O']
            # Copy, cut and paste on macOS are Command-C / X / V, wherever --
            # files in a pane, text in the log.
            KEY_BINDINGS['clipboard_copy'] = ['Command-C', 'Ctrl-C', 'Y']
            KEY_BINDINGS['clipboard_cut'] = ['Command-X', 'Ctrl-X', 'Shift-Y']
            KEY_BINDINGS['clipboard_paste'] = ['Command-V', 'Ctrl-V', 'G']
            # Finder's and every Mac browser's Back / Forward.
            KEY_BINDINGS['go_back'] = ['Command-LEFT_BRACKET', 'Alt-LEFT']
            KEY_BINDINGS['go_forward'] = ['Command-RIGHT_BRACKET', 'Alt-RIGHT']
            # Quitting the way every app quits, from anywhere -- a dialog or a
            # viewer open too -- and asking only while a task runs.
            KEY_BINDINGS['quit_app'] = ['Command-Q']
            # Every Mac app's text size keys. Cmd-+ is Shift-= on a US
            # keyboard, so Cmd-= without Shift counts too, as in a browser.
            KEY_BINDINGS['increase_font_size'] = ['Command-+', 'Command-=']
            KEY_BINDINGS['decrease_font_size'] = ['Command-MINUS']
            KEY_BINDINGS['reset_font_size'] = ['Command-0']
        elif sys.platform == 'win32':
            KEY_BINDINGS['open_with_os'] = ['Ctrl-ENTER', 'Ctrl-O']
            KEY_BINDINGS['quit_app'] = ['Alt-F4']
    return KEY_BINDINGS
