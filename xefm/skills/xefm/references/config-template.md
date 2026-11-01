# XeFM's configuration template

Generated from XeFM {XEFM_VERSION}'s `xefm/_config.py` by
`tools/gen_skill_references.py` — do not edit by hand.

This is the file XeFM copies to `~/.xefm/config.py` on first launch, and
the one it fills every setting the user's file leaves out from. It is the
authority on what each setting is called, what it holds by default, and
what it does. Read it here rather than in the user's own file: theirs may
have had its comments deleted, or date from an older XeFM.

A setting the user's file does not have keeps the value shown here. Adding
it to their file **replaces** that value whole: to extend a default list
or table (FILE_ASSOCIATIONS, PROGRAMS, FAVORITES, THEMES…), copy its
default entries from here and add to them.

```python
#!/usr/bin/env python3
"""
XeFM User Configuration

This file contains your personal XeFM configuration.
You can modify any of these settings to customize XeFM behavior.
"""

import platform
import sys

# xefm_tool and xefm_python, for PROGRAMS; is_desktop_mode, to tell the desktop
# window from the terminal. (Older configs import them from
# xefm.external_programs and xefm.backend_detector, which keeps working.)
from xefm.user_api import is_desktop_mode, xefm_python, xefm_tool

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
    DEFAULT_SORT_MODE = 'filename'  # 'filename', 'extension', 'size', 'timestamp'
    DEFAULT_SORT_REVERSE = False
    
    # -----------------------------------------------------------------------
    # Custom themes (optional)
    # -----------------------------------------------------------------------
    # Register your own named themes here. Each one is added to the theme picker
    # (View > Theme) and View > Theme > Next Theme alongside the built-ins — Dark+, Monokai,
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
    #                  'link':      (86, 194, 214),   # symlinks (default: cyan)
    #                  'hidden':    0.4}              # hidden entries (see below)
    #   #   ('directory' may also be given as a flat top-level key — shorthand for
    #   #    file_types['directory']. A symlink is colored as a link even when it
    #   #    points at a directory.)
    #   #   'hidden' is not a fourth type but a treatment of the other three: a
    #   #    hidden entry keeps its own color and fades toward the background by
    #   #    this much (0 = no fading; default 0.4), so a hidden folder still reads
    #   #    as a folder. Fading stops where a name would stop being findable, so
    #   #    a very high number fades that far and no further. Give it an
    #   #    (r, g, b) instead to paint every hidden entry one flat color, type
    #   #    and all — what a monochrome theme wants, having no second hue to spend.
    #   # --- file pane cursor cue (a sub-dict; the row outline on the desktop
    #   #     app, the [ ] brackets and the rule under the row in a terminal,
    #   #     distinct from the selection fill) ---
    #   'cursor': {'active':   (231, 76, 76),  # focused pane (default: red)
    #              'inactive': (140, 92, 94)}  # resting pane (default: a gray
    #   #     derived from the theme — only the focused pane's cue is colored)
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
    #   #       'earth'         the planet from orbit, in its own natural colours
    #   #                       (the one scene that ignores the foreground)
    #   #       'blocks'        metal columns in fog, light leaking between them
    #   #       'crystal'       a macro of crystals growing out of basalt
    #   #     Written as a bare type, or a dict to retune speed / opacity:
    #   #       'animation': 'starfield'                     # the tuned default
    #   #       'animation': {'type': 'rain', 'speed': 1.0, 'opacity': 0.8}
    #   #     'earth' also takes a shot, a lens look, a cloud height, exposure and
    #   #     brightness (its ceiling, 0..1, default 0.5 — kept dim for the text):
    #   #       'animation': {'type': 'earth', 'shot': 'rise', 'lens': 'film',
    #   #                     'clouds': 3.0, 'exposure': 0.85}
    #   #       shot: 'auto' (default: a random one per scene) | 'day' | 'dawn' |
    #   #             'crescent' | 'leo' | 'terminator' | 'glint' | 'rise' | 'polar' |
    #   #             'horizon' | 'ocean'
    #   #       lens: 'auto' (default: a random one per scene) | 'clean' |
    #   #             'aberration' | 'mono' | 'film' | 'anamorphic' | 'flare' |
    #   #             'fisheye' | 'crt' | 'infrared' | 'night-vision' — a list to
    #   #             pick among, or {'preset': 'film', 'grain': 0} to tune one
    #   #     'blocks' takes leaks, leak_strength, motion, camera (each 1 as tuned),
    #   #     exposure and brightness; 'crystal' takes focus (1 as tuned, 0 = all
    #   #     sharp), exposure and brightness:
    #   #       'animation': {'type': 'blocks', 'leaks': 1.5, 'camera': 0.5}
    #   #       'animation': {'type': 'crystal', 'focus': 0.5}
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
        # custom theme; select it from View > Theme or View > Theme > Next Theme. On the GUI
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
    CONFIRM_TRASH = True    # Show confirmation dialog before moving files to the Trash / Recycle Bin
    # Delete key (delete_files): True sends local files to the system's Trash
    # (Recycle Bin on Windows) where their drive has one, and deletes for good
    # only where there is none (remote, archives, USB/network drives on
    # Windows) -- saying so first. False makes it delete permanently, as
    # delete_permanently always does.
    DELETE_TO_TRASH = True
    CONFIRM_QUIT = True     # Show confirmation dialog before quitting XeFM
    CONFIRM_COPY = True     # Show confirmation dialog before copying files/directories
    CONFIRM_MOVE = True     # Show confirmation dialog before moving files/directories
    CONFIRM_DUPLICATE = True  # Show confirmation dialog before duplicating files/directories
    CONFIRM_EXTRACT_ARCHIVE = True  # Show confirmation dialog before extracting archives
    CONFIRM_ARCHIVE_CREATE = True   # Show confirmation dialog before creating archives
    # How many files a copy, move or extraction may have in flight. "auto"
    # takes the number from the storage at each end — a local disk or mounted
    # volume four, S3 eight, ssh and archives one — "none" runs everything
    # sequentially, and an integer overrides the lot (an endpoint that allows
    # only one transfer still caps it at one). Closing a file is serialised
    # whatever this says: where the destination defers a file's transfer to its
    # close, that is the transfer, and one at a time is what a server was seen
    # to require.
    TRANSFER_CONCURRENCY = "auto"

    # Keymap preset: the whole keymap, chosen at first launch and changed from
    # Tools > Advanced > Keymap…. The presets are peers; none is the default.
    #   None        -- whatever you chose at first launch or in
    #                  Tools > Advanced > Keymap…
    #   'afx'       -- letters: C copy, K delete, M move ... The single-key
    #                  style of the X68000 filers and AFX (あふ). 'default' is
    #                  accepted as an old name for it.
    #   'orthodox'  -- function keys: F3 view, F4 edit, F5 copy, F6 move,
    #                  F7 new folder, F8 delete. No bare letter runs anything;
    #                  typing a letter starts incremental search.
    #   'native'    -- Finder's keys on macOS, Explorer's elsewhere: Cmd/Ctrl-C,
    #                  X, V for files, F2 rename, Delete. F5 / F6 copy and move
    #                  to the other pane; typing a letter searches. In a
    #                  terminal, chords it cannot send (Command, Ctrl-Shift)
    #                  have Ctrl / function-key stand-ins.
    #   'vim'       -- Vim-style keys: hjkl to move, gg / G, yy / dd / p, cw
    #                  rename, / and n to search, ZZ to quit. Two-key commands
    #                  are key sequences (see KEY_SEQUENCE_TIMEOUT below).
    # Setting this wins over the Tools > Advanced > Keymap… dialog. KEY_BINDINGS
    # below is laid over whichever preset is in force. See
    # doc/KEYMAP_PRESETS_FEATURE.md.
    KEY_PRESET = None

    # Key bindings - your changes to the keymap preset above
    #
    # Every action already has its keys from the preset in force. An entry
    # here replaces that action's keys under every preset; an action you do
    # not list keeps the preset's. Help (F1) lists every action with its keys,
    # and https://crftwr.github.io/xefm/doc/KEY_BINDINGS_FEATURE.html names them all.
    #
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
    # Every key name XeFM accepts, and what a modifier prefix does, is listed in
    # https://crftwr.github.io/xefm/doc/KEY_BINDINGS_FEATURE.html under "Key
    # Expression Format". One of each, so the shape is visible here:
    #
    #   'Q'  '?'                    a character (a capital letter is not Shift)
    #   'Shift-F'                   ...which is why Shift is written out
    #   'ENTER'  'PAGE_UP'  'F10'   a named key
    #   'BACKQUOTE'  'SEMICOLON'    a punctuation key by name
    #   'Ctrl-O'  'Command-ENTER'   a chord
    #   'g h'                       a sequence: g, then h (the file list only)
    #
    # A name XeFM does not know is not silently ignored: it logs
    # "Unknown key in expression: ..." and that binding never fires.
    #
    KEY_BINDINGS = {
        # Examples that combine with every preset -- remove the '#' to use one.
        #
        # A key no preset uses, for an action that has none:
        # 'reload_config': ['F12'],
        #
        # Take a key away: an empty list unbinds the action.
        # 'quit': [],
        #
        # Run only with a selection (the extended format):
        # 'delete_permanently': {'keys': ['Shift-DELETE'], 'selection': 'required'},
        #
        # Inside one viewer only, with the viewer's name as a prefix:
        # 'text_viewer.page_down': ['SPACE'],
        # 'file_diff.quit': ['X'],
        #
        # The search bar's own keys (it takes typed text, so modified keys):
        # 'search.toggle_case': ['Ctrl-T'],
        #
        # A key sequence, keys separated by spaces (see KEY_SEQUENCE_TIMEOUT):
        # 'go_root': ['g r'],
    }

    # Key sequences ('g r' above): how long XeFM waits for the next key when
    # what you have pressed so far is a binding of its own and also the start
    # of a longer one -- 'g' bound alone as well as in 'g r'. After this many
    # seconds the shorter binding runs. None waits for as long as it takes:
    # the shorter one then runs when the next key continues no sequence. Esc
    # drops the keys pressed so far either way; the status bar shows them.
    KEY_SEQUENCE_TIMEOUT = 1.0



    # -----------------------------------------------------------------------
    # In-process customization
    # -----------------------------------------------------------------------
    # This config file is executed Python, so it can define functions as well as
    # settings. ACTIONS binds your own functions to action names (which
    # KEY_BINDINGS above then binds to keys, exactly like a built-in action),
    # EVENT_HOOKS runs them at set moments in XeFM's life, SORT_KEYS lets you
    # write the order the file list is sorted in, FILTERS lets you write what
    # it shows, IMAGE_DECODERS lets you add picture formats the image viewer
    # does not read yet, PATH_SCHEMES lets you add a browsable folder that
    # is not a folder, LEXERS lets you color a language the text viewer
    # does not know, MENU_ITEMS puts an action in a menu, and ATTRIBUTES,
    # LAYOUTS and LAYOUT_EXTRAS change what the file list's rows show.
    #
    # STABLE AND PREVIEW: this is API version 1 (xefm.user_api.API_VERSION).
    # ACTIONS, SORT_KEYS, FILTERS and PATH_SCHEMES, and the panes and entries
    # your functions are handed, are stable: a change that would break them
    # comes with a new API_VERSION and a line in the release notes. EVENT_HOOKS,
    # MENU_ITEMS, IMAGE_DECODERS, LEXERS, ATTRIBUTES, LAYOUTS, LAYOUT_EXTRAS and
    # a few ctx methods (run_task, show_markdown, the prompts) are Preview and
    # may change in any release; XeFM logs one line when a config uses them.
    # doc/CUSTOMIZATION_FEATURE.md has the full list.
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
    #     'select-documents': ['Shift-Y'],
    #
    # Every action of yours is in the command palette (Ctrl-T), key or no
    # key. The docstring is how it is described there: its first line is the
    # one-line description (also the Help dialog's row), and the paragraphs
    # after a blank line are the page F1 opens in the palette (Markdown):
    #
    # def open_in_vscode(ctx):
    #     """Open the item under the cursor in VS Code.
    #
    #     Works on directories too -- VS Code opens them as a workspace.
    #     """
    #     ctx.run_program(['code', str(ctx.pane.focused.path)])
    #
    # Without a docstring the palette has only the name to show. (The dict
    # form below also takes a 'description', written and split the same way,
    # which replaces the docstring -- for a function that cannot carry one,
    # such as a lambda.)
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
    #   ctx.run_program(['cmd', ...], terminal=False) run an external program;
    #       terminal=True lends it the terminal (vim, massren...) and waits.
    #       Don't subprocess.run() one yourself -- the screen breaks.
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
    # Every hook is fn(ctx, event); what happened is on the event:
    #
    #   'startup'           (nothing more)     once the app is up
    #   'quit'              (nothing more)     before XeFM shuts down
    #   'directory_changed' event.pane, event.old_path, event.new_path
    #   'file_open'         event.path         return True to claim the open
    #
    # 'file_open' fires before XeFM decides what to do with a file, so returning
    # True is how you route one file type somewhere of your own without touching
    # FILE_ASSOCIATIONS. It does not fire for directories -- entering one is
    # navigation, not opening.
    #
    # def log_visit(ctx, event):
    #     with open(Path.home() / '.xefm' / 'visited.log', 'a') as f:
    #         f.write(f"{event.new_path}\n")
    #
    # def open_psd_in_gimp(ctx, event):
    #     if event.path.suffix.lower() != '.psd':
    #         return False
    #     subprocess.Popen(['gimp', str(event.path)])
    #     return True                 # claimed -- XeFM does nothing further
    #
    # EVENT_HOOKS = {
    #     'directory_changed': [log_visit],
    #     'file_open': [open_psd_in_gimp],
    # }
    EVENT_HOOKS = {}

    # --- SORT_KEYS --------------------------------------------------------
    # Your own sort orders. Each one becomes a row in the sort dialog ('s') and
    # in the Sort By menu, alongside Filename / Extension / Size / Timestamp.
    #
    # A sort key takes one entry and returns anything that can be compared --
    # XeFM sorts by whatever comes back. Return a tuple for a multi-level order;
    # tuples compare item by item, so (e.size, e.name) means "by size, and by
    # name within the same size".
    #
    # def size_then_name(entry):
    #     return (entry.size, entry.name)
    #
    # SORT_KEYS = {
    #     'biggest': {'label': 'Size, then name', 'key': size_then_name},
    # }
    #
    # Two things you do NOT have to handle: directories always come first, and
    # ascending/descending is applied for you. Your key only decides the order
    # inside one group. Reading entry.size or entry.mtime is free -- XeFM already
    # collected them for the listing.
    #
    # Naming one of the four built-in sorts -- 'filename', 'extension', 'size',
    # 'timestamp', the dialog's own rows in lower case -- replaces it, which
    # needs 'override': True so a typo cannot quietly change what Filename means. XeFM orders names by character code, which is not how
    # Explorer or Finder order a directory; this is where you change that:
    #
    # import locale, re                       # at the top of this file
    # locale.setlocale(locale.LC_COLLATE, '')  # your system's own ordering
    #
    # def by_system_order(entry):
    #     # digit runs as numbers, everything else through the system's ordering
    #     parts = re.split(r'(\d+)', entry.name)
    #     return [int(p) if i % 2 else locale.strxfrm(p) for i, p in enumerate(parts)]
    #
    # SORT_KEYS = {'filename': {'key': by_system_order, 'override': True}}
    #
    # That follows your locale, which is close to but not the same as the shell's
    # own order. Matching Explorer or Finder exactly means their comparison
    # functions -- StrCmpLogicalW and localizedStandardCompare: -- which compare
    # two names rather than producing a key, so wrap one in
    # functools.cmp_to_key(...) and expect it to cost more on a large directory.
    #
    # The rest of an entry: 'label' is the row text (defaults to the name),
    # 'explain' is the example line the dialog shows under the order, and
    # 'hotkey' is a letter that applies the sort straight from the dialog (a new
    # row gets its label's initial when no other row has claimed it).
    #
    # A key runs on a background thread, so keep it to arithmetic and strings.
    # One that fails, or returns things that cannot be compared with each other,
    # loses the sort rather than the listing: the pane falls back to ordering by
    # filename and says so once in the log pane.
    SORT_KEYS = {}

    # --- FILTERS ----------------------------------------------------------
    # Your own filters. Each one becomes a fixed row in the Filter dialog (';'),
    # under "clear filter" and above the patterns you have typed there before.
    #
    # The simple kind is one or more wildcard patterns:
    #
    # FILTERS = {
    #     'images': ['*.jpg', '*.jpeg', '*.png', '*.gif'],   # any one matches
    # }
    #
    # The other kind is a function, which is how you filter by something the
    # name does not say -- size, date, whatever you can work out from the entry.
    # It takes one entry and returns True to show it:
    #
    # import time                              # at the top of this file
    #
    # def modified_today(entry):
    #     return entry.mtime >= time.time() - 24 * 3600
    #
    # FILTERS = {
    #     'today': {'label': 'Modified today', 'match': modified_today},
    #     'big': {'label': 'Over 100 MB', 'match': lambda e: e.size > 100 << 20},
    # }
    #
    # 'label' is the row text and defaults to the name you gave it. An entry has
    # the same fields a sort key sees -- .name, .path, .suffix, .stem, .is_dir,
    # .is_file, .is_link, .size and .mtime -- and reading .size or .mtime is free.
    #
    # Directories are always shown, exactly as they are under a typed pattern: a
    # filter that hid them would take away the folder you were about to open. So
    # your function only decides which files are visible -- and "directories
    # only" is written 'match': lambda e: False.
    #
    # A name may not contain * ? or [ -- XeFM remembers a filter by its name and
    # a typed pattern as itself, and one that read as both could not be told
    # apart. Put the wildcards in 'pattern' and give the filter a plain name.
    #
    # Like a sort key, a filter function runs on a background thread, so keep it
    # to arithmetic and strings. One that fails loses the filter rather than the
    # listing: the pane shows everything and says so once in the log pane --
    # deliberately that way round, so a broken filter never hides files from an
    # operation you are about to run.
    FILTERS = {}

    # --- IMAGE_DECODERS ---------------------------------------------------
    # Picture formats the built-in image viewer does not read yet.
    #
    # It already reads a lot without help, and which formats depends on your
    # machine rather than on XeFM: on macOS it draws HEIC, JPEG XL and camera
    # RAW through the system's own decoder; on Windows through whichever WIC
    # codecs are installed (the HEIF and AV1 extensions from the Store, if you
    # have them); in a terminal through Pillow, including any Pillow plugin you
    # installed. Installing pillow-heif is enough to add HEIC anywhere: add a
    # line to ~/.xefm/requirements.txt, then Tools > Advanced > Sync Python
    # Packages (or `xefm deps sync` from a shell). The same goes for rawpy,
    # cairosvg and any other library a decoder below imports.
    #
    #     pillow-heif
    #
    # What is left after all that is the formats only a library XeFM does not
    # ship can read. Write a function that turns the file's bytes into a
    # picture, and name the suffix it is for:
    #
    #     import io                             # at the top of this file
    #
    #     def open_svg(data):
    #         import cairosvg
    #         from PIL import Image
    #         return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=data)))
    #
    #     def open_raw(data):
    #         import rawpy
    #         from PIL import Image
    #         with rawpy.imread(io.BytesIO(data)) as raw:
    #             return Image.fromarray(raw.postprocess())
    #
    #     IMAGE_DECODERS = {
    #         '.svg': open_svg,
    #         '.dng': open_raw,
    #         '.cr2': open_raw,
    #     }
    #
    # Your function gets the file's bytes -- not a path -- so the same decoder
    # works on a picture inside a zip or on an S3 bucket, with nothing copied to
    # a temp file first. Return a PIL.Image (the usual answer), or None for "I
    # cannot read this one".
    #
    # Registering a suffix is also what makes the viewer OFFER that format:
    # Enter on a .dng opens the picture rather than the binary viewer. XeFM only
    # ever claims formats something on the machine can actually decode, so it
    # never opens onto an "I cannot show this" card.
    #
    # Registering a suffix XeFM already reads replaces its decoder with yours --
    # that is how you override how a format is read, and it is the only way.
    #
    # Like a sort key or a filter, a decoder may run on a background thread, so
    # it must not touch the UI. One that fails costs that picture and nothing
    # else: the viewer shows the reason on its card and the log pane gets the
    # traceback.
    IMAGE_DECODERS = {}

    # --- PATH_SCHEMES -----------------------------------------------------
    # Your own browsable locations. A scheme like 'reg' makes 'reg://...' a
    # place XeFM can open in a pane, jump to (Shift-J), and keep in FAVORITES
    # -- listed by your class rather than read off a disk.
    #
    # Inherit ReadOnlyPathImpl and write five methods. Everything else -- the
    # path arithmetic, refusing writes, what the pane and the status bar show --
    # comes with it.
    #
    # Define the class ABOVE `class Config:` (module level), with anything it
    # reads. Inside the class body it would *load* fine and then fail on every
    # call: a class body is not a scope the methods defined in it can see, so
    # NOTES and io below would come back as NameError the first time XeFM asked
    # the folder a question.
    #
    #     import io
    #     from xefm.path_base import ReadOnlyPathImpl, UriStatResult
    #
    #     NOTES = {'': ['todo', 'ideas'], 'todo': [], 'ideas': []}
    #
    #     class NotesPathImpl(ReadOnlyPathImpl):
    #         def exists(self):   return self.key in NOTES
    #         def is_dir(self):   return self.key in NOTES
    #         def iterdir(self):
    #             for name in NOTES.get(self.key, []):
    #                 yield self.child(name)
    #         def stat(self):     return UriStatResult(is_dir=self.is_dir())
    #         def open(self, mode='r', buffering=-1, encoding=None,
    #                  errors=None, newline=None):
    #             return io.StringIO('')
    #
    #     class Config:
    #         ...
    #
    # Then name it here -- this line, in the class, is the only part that
    # belongs at this indentation:
    #
    #     PATH_SCHEMES = {'notes': NotesPathImpl}
    #
    # self.key is the part after 'notes://', with no leading or trailing
    # slash -- '' at the root, 'todo/monday' further in. self.child(name)
    # builds a child; XeFM works out parents, names and suffixes itself.
    #
    # Writing is refused for you, with a clear message. Say why in your own
    # words with READ_ONLY_MESSAGE = 'edit these in the Notes app'.
    #
    # A class that is missing one of the five methods, or whose scheme name is
    # not a valid one, is skipped with a line in the log pane -- the rest of
    # your config still loads. A method that *raises* is reported the same way,
    # with its traceback, when something asks the folder a question.
    # See doc/VIRTUAL_FOLDERS_FEATURE.md.
    PATH_SCHEMES = {}

    # --- LEXERS -----------------------------------------------------------
    # Syntax highlighting for files the text viewer shows as plain text, or
    # colors as the wrong language. The coloring comes from Pygments, which
    # knows hundreds of languages; this names the lexer for a file name.
    #
    # The key is a file-name pattern ('*.mnl', or just '.mnl'; 'Jenkinsfile'
    # for a name with no suffix). The value is either the name of a lexer
    # Pygments already has -- `pygmentize -L lexers` lists them -- or a lexer
    # class of your own:
    #
    #     from autocad_lexers import DclLexer   # at the top of this file
    #
    #     LEXERS = {
    #         '*.dcl': DclLexer,      # your own lexer
    #         '*.mnl': 'newlisp',     # an existing one, for another suffix
    #     }
    #
    # Your own lexer is an ordinary Pygments lexer -- a RegexLexer subclass,
    # written the way https://pygments.org/docs/lexerdevelopment/ describes,
    # with nothing from XeFM in it. Keep it in its own file in
    # ~/.xefm/extensions/ (autocad_lexers.py above) and import it here. Its
    # own `filenames` attribute is not used: the key here alone decides which
    # files it colors. Its `aliases` are -- once registered, its alias can be
    # a value here too ('*.dclx': 'dcl').
    #
    # An entry here wins over Pygments' own choice for the same files, which
    # is how you recolor a suffix Pygments gives to another language. An
    # entry naming a lexer that does not exist is skipped with a line in the
    # log pane.
    LEXERS = {}

    # --- MENU_ITEMS -------------------------------------------------------
    # Put an action in a menu: the File menu ('file') and/or the menu a row
    # opens with a right-click or the Menu key ('context'). The key is the
    # action's name -- one of your ACTIONS, or a built-in one:
    #
    #     MENU_ITEMS = {
    #         'select-docs': {
    #             'menus': ['context'],
    #             'label': 'Select Documents',
    #             'when': 'entry',      # optional
    #         },
    #     }
    #
    # 'when' greys the item out unless it applies: 'entry' needs an entry under
    # the cursor, 'selection' needs at least one selected; the default is
    # 'always'. Your items gather in a group of their own near the foot of
    # each menu, in the order written here -- up to three; more go under a
    # Custom submenu, so the menu still fits a terminal.
    MENU_ITEMS = {}

    # --- ATTRIBUTES -------------------------------------------------------
    # Values XeFM can know about each entry beyond its name, size and date --
    # a Git status, a line count, an image's dimensions. Defining one shows it
    # nowhere: LAYOUT_EXTRAS (or LAYOUTS) below puts it in a row. XeFM has a
    # few of its own already: 'name', 'ext', 'size' (a folder's recursive size
    # once View > Resolve Attribute has counted it), 'mtime' and 'tags'.
    #
    # One function, read(directory, entries), computes the values on a
    # background thread: `entries` are rows of one folder, `directory` is that
    # folder, and it returns one value per entry, in the same order. XeFM
    # hands it a whole folder at once, so a source that answers a folder in
    # one go -- git, where a call per file would be hundreds of processes --
    # is asked once:
    #
    #     def line_count(directory, entries):
    #         def count(entry):
    #             with open(entry.path, 'rb') as f:
    #                 return sum(1 for _ in f)
    #         return [count(e) for e in entries]
    #
    #     import subprocess                    # at the top of this file
    #
    #     def git_status(directory, entries):
    #         try:
    #             def git(*args):
    #                 return subprocess.run(['git', *args], cwd=str(directory), check=True,
    #                                       capture_output=True, text=True).stdout
    #             prefix = git('rev-parse', '--show-prefix').strip()
    #             items = git('status', '--porcelain', '-z', '--', '.').split('\0')
    #         except (OSError, subprocess.CalledProcessError):
    #             return [None] * len(entries)        # not a Git working tree
    #         codes, skip = {}, False
    #         for item in items:
    #             if skip or len(item) < 4:
    #                 skip = False
    #                 continue
    #             code, path = item[:2], item[3:]
    #             skip = code[0] in 'RC'              # a rename's old path follows
    #             if path.startswith(prefix):
    #                 # the entry here the change is in: a file, or the folder holding it
    #                 name = path[len(prefix):].split('/')[0]
    #                 codes.setdefault(name, code.strip()[:1])
    #         return [codes.get(e.path.name) for e in entries]
    #
    #     ATTRIBUTES = {
    #         'lines': {'label': 'Lines', 'type': 'count', 'read': line_count},
    #         'git': {
    #             'label': 'Git status', 'type': 'enum', 'read': git_status,
    #             'values': {                  # each value's meaning, and a color
    #                 'M': {'label': 'Modified',  'color': 'yellow'},
    #                 'A': {'label': 'Added',     'color': 'green'},
    #                 '?': {'label': 'Untracked', 'color': 'muted'},
    #             },
    #         },
    #     }
    #
    # 'type' is how the value is shown and compared: 'text', 'count', 'size'
    # (bytes), 'time' (a timestamp), 'duration' (seconds), 'enum' (one of
    # 'values'), or 'tags'.
    # 'where' lists the storage it is asked about -- 'local' (the default),
    # 'archive', 'ssh', 's3' -- since a call per file is cheap on a disk and
    # a request each on S3.
    #
    # Values are worked out for every row of a folder as soon as a layout on
    # screen shows them, so a definition should answer a folder's worth in no
    # time. One that cannot -- it reads every file whole, it walks a tree --
    # says 'compute': 'on_request' and is computed only for the entries you
    # ask about: View > Resolve Attribute, for the selection or the entry
    # under the cursor, one entry per call -- as a folder's size is.
    #
    # A value is None until it arrives. A function that fails, or returns a
    # list of the wrong length, costs that call's values and says so once in
    # the log pane. Your own functions can read a value
    # XeFM already has with entry.attr('git') -- it never waits for one.
    ATTRIBUTES = {}

    # --- LAYOUTS ----------------------------------------------------------
    # How a file list row is presented: which of the usual columns, in what
    # order, and how each value is written -- a matter of taste and of how
    # wide your panes are. View > Layout picks one per tab; DEFAULT_LAYOUT
    # below is the one a new tab starts with. The built-in 'default' is what
    # you see now:
    #
    #     'columns': ['name', 'ext', 'size', {'attr': 'mtime', 'priority': 1}]
    #
    # A column is an attribute's name, or a dict:
    #
    #     {'attr': 'mtime',            # what to show
    #      'format': 'relative',      # how (below), or a function of yours
    #      'width': 10,               # cells; the format's own by default
    #      'align': 'right',          # 'left' or 'right'
    #      'priority': 1}             # dropped first when the pane is narrow
    #
    # Every layout has a 'name' column, and it takes the width the others
    # leave. A column with a 'priority' is dropped when the name would get
    # narrower than 12 cells, lowest first; one without stays. Leave out
    # 'ext' and the extension stays in the name.
    #
    # Formats by type: 'size' -- 'compact' (12.3K, the default) or 'bytes';
    # 'time' -- 'short', 'full' (DATE_FORMAT picks between the two by
    # default), 'iso', 'relative' ("5 min ago") or 'recent' (13:24 today,
    # 10/21 this year, 2024 before that); 'enum' -- 'letter' or
    # 'word' (its label from 'values'); 'tags' -- 'dots' or 'names';
    # 'duration' -- 'clock' (3:07, 1:02:45); 'count' -- 'number'; 'text' --
    # 'text'. A function of yours takes (value, entry)
    # and returns text, or a Cell to give it a color: color is 'muted',
    # 'accent', 'accent2', 'text', a name ('red', 'green', 'yellow', 'blue',
    # 'purple', 'orange', 'gray') or an (r, g, b). value is None while it is
    # being computed. Give it a 'width'.
    #
    #     LAYOUTS = {
    #         'short': {'label': 'Short time', 'columns': [
    #             'name', 'ext', 'size',
    #             {'attr': 'mtime', 'format': 'recent', 'priority': 1}]},
    #         'names': {'label': 'Names only', 'columns': ['name']},
    #     }
    #
    # Replacing 'default' itself needs 'override': True.
    LAYOUTS = {}
    DEFAULT_LAYOUT = 'default'

    # --- LAYOUT_EXTRAS -----------------------------------------------------------
    # What a folder adds to its rows because of what it holds -- a Git status
    # in a working tree, your tags where the system keeps them. Each extra
    # says where it applies ('when'), and puts its attributes in the row as
    # markers beside a column's text and/or as columns of their own. Several
    # can show at once, on top of whichever layout the tab has. View > Show
    # turns each one Auto (follow 'when', where every tab starts), On or Off
    # for the tab. XeFM has one of its own, 'tags': the colored dots after a
    # name.
    #
    #     from xefm.user_api import Cell       # at the top of this file
    #
    #     GIT_MARK = {'M': Cell('M', color='yellow'),
    #                 'A': Cell('A', color='green'),
    #                 '?': Cell('?', color='muted')}
    #
    #     def git_mark(value, entry):
    #         return GIT_MARK.get(value, '')
    #
    #     def in_git_tree(path):
    #         return any((p / '.git').exists() for p in (path, *path.parents))
    #
    #     LAYOUT_EXTRAS = {
    #         'git': {
    #             'label': 'Git status',
    #             'when': in_git_tree,
    #             'markers': [{'attr': 'git', 'format': git_mark,
    #                          'on': 'name', 'side': 'before'}],
    #             'columns': [{'attr': 'git', 'format': 'word',
    #                          'replace': 'mtime'}],
    #         },
    #     }
    #
    # 'when' is 'always' (the default), 'never', a path pattern ('s3://*'),
    # or a function of the folder's path, run on a background thread so it
    # may look at the disk.
    #
    # A marker is {'attr', 'format', 'on', 'side', 'limit'}: 'on' is the
    # column whose text it marks ('name' by default, and when the tab's layout
    # has no such column), 'side' is 'before' or 'after' (the default),
    # 'limit' the most pieces of the format's result shown (the tag dots:
    # three). A mark sits against the text it marks on the rows that have
    # one, and that text gives way; rows without one keep no room for it, so
    # a name with a mark in front starts a little later than its neighbours.
    #
    # A column is as in LAYOUTS, plus where it goes: 'before' or 'after' a
    # column, in place of one ('replace' -- to save room; it keeps that
    # column's priority), or at the end (also when the named column is not
    # in the layout). A column before the name keeps a value in one place on
    # every row. It is as wide as its widest value, and left out of a folder
    # where no file has one.
    #
    # An extension can bring extras, already saying where they apply. To
    # change one -- or the built-in 'tags' -- name it here with only the keys
    # you change; the rest stays as it was:
    #
    #     LAYOUT_EXTRAS = {'tags': {'when': 'never'}}            # no tag dots
    #     LAYOUT_EXTRAS = {'git': {'when': 'always'}}            # an extension's, changed
    #
    # The sort dialog lists what the pane shows beyond its own keys (Git
    # status above). Sorting by one orders this folder only, by the values
    # already there; going to another folder goes back to the pane's own
    # sort. F1 lists what the marks in the active pane mean.
    LAYOUT_EXTRAS = {}


    # Favorites (J) - the places and files you jump to by name.
    #
    # (This was FAVORITE_DIRECTORIES, when it could only hold directories. A
    # config that still uses that name keeps working; if both are set, the two
    # lists are joined.)
    #
    # B adds one without editing this file: the directory you are in, or the
    # item under the cursor (a file too - selecting it lands the cursor on it).
    # Those live in XeFM's state database, are listed after the entries below,
    # and are removed from the picker with Shift-DELETE. The entries below are
    # yours: the picker lists them but never removes them.
    #
    # Each entry needs 'name' and 'path'. Every entry is listed as written -
    # XeFM does not check that a favorite exists before showing it, so a network
    # share, a removable volume or an ssh:// / s3:// location can live here
    # without the picker stalling on it. Nothing connects until you select a
    # row; if the place turns out to be unreachable, the pane says so then.
    #
    # A path may name a file as well as a directory: selecting it opens the
    # file's directory with the cursor on the file. Nothing needs to say which
    # it is - XeFM finds out when you select the row.
    #
    # The four below are the ones almost every machine has. Delete what you do
    # not use - a favorite you never selected costs nothing, but it is a row
    # between you and the one you want.
    FAVORITES = [
        {'name': 'Home', 'path': '~'},
        {'name': 'Documents', 'path': '~/Documents'},
        {'name': 'Downloads', 'path': '~/Downloads'},
        {'name': 'Desktop', 'path': '~/Desktop'},
        # Add your own favorites here:
        # {'name': 'Work', 'path': '/path/to/work'},
        # {'name': 'Scripts', 'path': '~/bin'},
        # {'name': 'Todo', 'path': '~/notes/todo.md'},
        # {'name': 'NAS', 'path': '/Volumes/share'},
        # {'name': 'Dev Server', 'path': 'ssh://devbox/var/www'},
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

    # Connect to Server (Shift-D) - network servers you connect to often.
    # macOS and Windows only; on Linux the dialog is not offered.
    #
    # These are listed above the servers you save from the dialog itself, and
    # cannot be removed with Shift-Delete (this file is where they live, so
    # delete them here). Nothing is contacted until you pick a row.
    #
    # Each entry needs 'url'; 'name' labels the row (the URL is used when it is
    # missing) and 'user' prefills the account.
    #
    # NEVER put a password here. There is no field for one, and XeFM will not
    # read one. Tick "Save password" in the connection form instead - it goes
    # into the login keychain (macOS) or Credential Manager (Windows).
    #
    # NETWORK_SERVERS = [
    #     {'name': 'NAS Photo',  'url': 'smb://nas/photo', 'user': 'me'},
    #     {'name': 'NAS Backup', 'url': 'smb://nas/backup'},
    #     {'name': 'Docs',       'url': 'https://dav.example.com/files'},
    # ]
    NETWORK_SERVERS = []

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
    # MIGEMO_ROMAJI_TABLE names the romaji spelling Migemo also understands.
    # 'default' is plain romaji only. 'azik' adds AZIK, the extended romaji
    # input scheme: a second stroke below the vowel spells the kana plus "n"
    # (kz -> かん, kk -> きん), q/h/w/p spell the double vowels (kq かい, kp
    # こう), and x/c are the sha/cha rows (xa しゃ, ca ちゃ). AZIK is added
    # alongside plain romaji rather than replacing it, so the handful of keys
    # the two spell differently match either reading and no query that worked
    # before stops working.
    MIGEMO_SEARCH = True   # Add Migemo (romaji -> Japanese) matches to incremental search
    MIGEMO_MIN_LENGTH = 3  # Shortest pattern handed to Migemo
    MIGEMO_ROMAJI_TABLE = 'default'  # 'default' or 'azik'
    
    # Text editor settings
    # Supports both string and list formats:
    # - String format: 'vim' (single command, no arguments)
    # - List format: ['code', '--wait'] (command with arguments)
    # Automatically set based on actual running backend mode:
    # - Terminal mode (TUI): vim
    # - Desktop mode (GUI): code (VS Code)
    TEXT_EDITOR = 'code' if is_desktop_mode() else 'vim'
    
    # Text diff tool settings
    # Tool invoked when pressing 'E' (edit_file) key in DiffViewer or DirectoryDiffViewer
    # Supports both string and list formats:
    # - String format: 'vimdiff' (single command, no arguments)
    # - List format: ['code', '--diff'] (command with arguments)
    # Automatically set based on actual running backend mode:
    # - Terminal mode (TUI): vimdiff (string format example)
    # - Desktop mode (GUI): code --diff (list format example)
    TEXT_DIFF = ['code', '--diff'] if is_desktop_mode() else 'vimdiff'

    # Subshell settings
    # Shell launched by the 'subshell' action (Shift-X), in both modes.
    # None: use $SHELL if set, otherwise the platform default
    # (%COMSPEC% / cmd.exe on Windows, /bin/sh elsewhere).
    # Supports both string and list formats:
    # - String format: 'zsh' (single command, no arguments)
    # - List format: ['powershell', '-NoLogo'] (command with arguments)
    SUBSHELL = None

    # Terminal application (desktop mode only)
    # Desktop mode has no terminal of its own to hand over, so the subshell and
    # PROGRAMS entries with {'terminal': True} open in this application instead.
    # TERMINAL decides the window; SUBSHELL decides the shell inside it. The
    # command to run is appended as trailing arguments.
    # None: the platform default -- Terminal.app on macOS; Windows Terminal
    # (wt.exe) on Windows if installed, otherwise a new console window.
    # Supports both string and list formats:
    # - ['open', '-a', 'iTerm']      (macOS: any app that runs a script it opens)
    # - ['wezterm', 'start', '--']   (a terminal that takes the command as args)
    TERMINAL = None

    # S3 settings
    S3_CACHE_TTL = 60  # S3 cache TTL in seconds (default: 60 seconds)
    
    # SSH/SFTP cache settings
    SSH_CACHE_TTL = 30        # SSH cache TTL in seconds for successful results (default: 30 seconds)
    SSH_CACHE_ERROR_TTL = 300  # SSH cache TTL in seconds for cached errors (default: 300 seconds / 5 minutes)
    
    # Archive cache settings
    ARCHIVE_CACHE_MAX_OPEN = 5   # Idle archives kept open before the oldest are closed
    ARCHIVE_CACHE_TTL = 300       # Seconds an idle remote archive is kept (a local one closes within seconds)
    
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
    #                                          (for one XeFM does not
    #                                          recognise by its name)
    #                             'list'     - open the file as a file list,
    #                                          one path per line (*.m3u8, ...)
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
    # 'open_with' is not an action: it lists programs for Open With
    # (File > Open With > Choose App...), which asks which one to use this
    # time. Each item is shaped like a PROGRAMS entry below ('name', 'command',
    # optional 'options'). Unlike the actions, where the first matching rule
    # wins, every matching rule's list is offered, so a '*' rule's programs
    # appear for every file. The OS's own applications are listed after these.
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
    #     'open_with': [{'name': 'App', 'command': ['command']}],  # Open With
    # }
    FILE_ASSOCIATIONS = [
        # PDF files. 'view' is None so V shows the document's text in XeFM's
        # own viewer -- searchable, selectable, and on remote or archived files
        # too; 'open' still hands it to Preview for how the pages look.
        {
            'pattern': '*.pdf',
            'open': ['open', '-a', 'Preview'],
            'view': None,
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
        # Microsoft Office documents. The current formats (.docx .xlsx .pptx)
        # are read as text by XeFM's own viewer on V; the old binary ones
        # (.doc .xls .ppt) cannot be, and V hands them to the application.
        {
            'pattern': ['*.docx'],
            'open|edit': ['open', '-a', 'Microsoft Word'],
            'view': None,
        },
        {
            'pattern': ['*.doc'],
            'open|view|edit': ['open', '-a', 'Microsoft Word'],
        },
        {
            'pattern': ['*.xlsx'],
            'open|edit': ['open', '-a', 'Microsoft Excel'],
            'view': None,
        },
        {
            'pattern': ['*.xls'],
            'open|view|edit': ['open', '-a', 'Microsoft Excel'],
        },
        {
            'pattern': ['*.pptx'],
            'open|edit': ['open', '-a', 'Microsoft PowerPoint'],
            'view': None,
        },
        {
            'pattern': ['*.ppt'],
            'open|view|edit': ['open', '-a', 'Microsoft PowerPoint'],
        },
        # Note there is deliberately no entry listing text/code extensions.
        # Enter and V already fall through to the built-in viewer when no rule
        # matches, and the viewer sniffs the bytes -- so it reads text with no
        # configuration and shows a placeholder for binaries, including for
        # files with no extension or an unknown one that a list would miss.
        #
        # Archives under another name. ENTER browses .zip, .tar, .7z and the
        # other archive names by itself; these are packages that are an archive
        # inside but named for what they hold, and 'navigate' browses them like
        # one -- XeFM tells the format from the file's bytes. Add a name of your
        # own here, or take one out to have ENTER open the viewer instead.
        #
        # Zip-based documents are deliberately absent: .docx, .xlsx, .epub and
        # .odt are zip files too, and you want the document, not a listing of
        # its XML. The same goes the other way: 'enter': None or 'viewer' on
        # *.zip stops ENTER browsing a zip.
        {
            'pattern': [
                '*.jar', '*.war', '*.ear',                    # Java
                '*.apk', '*.aab', '*.aar',                    # Android
                '*.ipa',                                      # iOS
                '*.whl', '*.egg',                             # Python
                '*.nupkg', '*.snupkg',                        # NuGet
                '*.vsix',                                     # VS Code
                '*.xpi',                                      # Firefox add-on
                '*.appx', '*.msix', '*.appxbundle', '*.msixbundle',  # Windows apps
                '*.gem',                                      # Ruby (tar)
                '*.crate',                                    # Rust (tar.gz)
                '*.ova',                                      # VM appliance (tar)
                '*.cbz', '*.cbt', '*.cbr', '*.cb7',           # comic books
                '*.kmz',                                      # Google Earth
            ],
            'enter': 'navigate',
        },
        # Playlists are file lists: ENTER shows the files a playlist names in the
        # pane, with every file operation working on them, and open_with_os
        # still plays it. A list you keep yourself can join this entry --
        # '*.lst', say -- as long as it holds one path per line.
        {
            'pattern': ['*.m3u', '*.m3u8'],
            'enter': 'list',
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
        # Programs for Open With. A '*' rule's programs are offered for every
        # file, so a mixed selection always has them in common:
        # {
        #     'pattern': '*',
        #     'open_with': [
        #         {'name': 'VS Code', 'command': ['code']},
        #         {'name': 'Hex view', 'command': ['hexyl'], 'options': {'terminal': True}},
        #     ],
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
    #     stays readable. Desktop mode has no terminal to hand over, so the
    #     program opens in a TERMINAL window instead (see TERMINAL above).
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
```
