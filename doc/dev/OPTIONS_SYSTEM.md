# Options System

How a XeFM surface grows live settings, and why they all share one key.

Introduced for the search dialog (discussion #312); built so the diff viewers,
the batch-rename dialog and the archive dialogs can take the same road without
spending a key each.

## The problem it solves

A surface with a query field has no keys to spare. Every printable key belongs
to the query — the rule `xefm/actions.py` already states for `isearch` and
`filter_list` — so an option needs a modified key, and the modified keys that
actually work everywhere are countable:

- **Alt is unusable.** macOS spends Option on glyphs and IME, and an Alt chord
  the VT input path does not recognize arrives as `escape`
  (`puikit/backends/_vt_input.py`), which would *close* the dialog.
- **Ctrl+letter is the only modifier that lands identically on all four
  backends** — VT and curses decode the control byte back to a letter
  (`vt_backend.py`, `curses_backend.py`), the Windows backend synthesizes the
  chord from `WM_KEYDOWN`, and the macOS backend reads
  `charactersIgnoringModifiers`.
- Of the 26, `A/C/X/V` belong to `TextEdit`, `I/M/J/H/[` are renamed by the
  terminal, and `L` is the hardcoded redraw. Nineteen are left, **for the whole
  application**.

Three options per surface would exhaust that in six surfaces, and nothing would
guarantee that the same option meant the same chord in two of them.

So options are not reached by a key each. They are reached by **one** key —
`options` — that opens a surface with *no text field*, where every
plain letter is free. One key, spent once, for as many options as any surface
ever grows.

## Every option is on or off

Two states is what makes the idiom legible, not a simplification of something
richer. A chip can say "on" by being **filled**, a row can say it in a word, and
a key can *toggle* rather than cycle through states a user has to press
repeatedly to find. It also keeps a chip's name constant: a tri-state option
ends up wanting its text to carry the state ("no sub"), which puts a space
inside one chip while spaces are also what divide the chips from each other.

Where a setting has three answers, the surface declares three options or opens a
picker of its own — it does not go here.

## The parts

| File | Holds |
|------|-------|
| `xefm/options.py` | `Option` (the declaration) and `OptionSet` (the live values) |
| `xefm/options_dialog.py` | The shared box the `options` key opens |
| `xefm/search_options.py` | The search dialog's declarations *and* what they mean |
| `xefm/actions.py` | The `search` context, the `options` action, the generated `toggle_*` actions |
| `xefm/config.py` | `printable_text_bindings` — the config check, now covering every text surface |

## One declaration, four readers

`Option` is frozen and says everything about one setting: its default, the chip
text, the dialog label (whose initial is its key), which modes it applies to,
and whether it outlives one opening of the surface.

Four things read that same list, which is what keeps them from drifting:

1. **The chip strip** — `OptionSet.chips(mode)` returns `(Option, on)` pairs,
   drawn at the right end of the search dialog's status row as filled blocks.
   The whole option rather than its flag, because a chip is a *control*: the
   surface records a rect per block during draw (`_chip_hits`) and a click on
   one toggles it, so the strip needs the name to hand back.
2. **The options dialog** — rows, labels, and `accel_map` for the letters. The
   letter is the label's **initial** (`Option.key`), and it is not drawn, for
   the reason SortDialog does not draw F/E/S/T: the word already carries it, and
   a column of single letters costs more width than it explains. `Option.accel`
   overrides the initial where two labels on one surface start alike.
3. **The action registry** — `_SEARCH_ACTIONS` generates one unbound
   `toggle_<name>` action per declared option, so the default keymap stays a
   single chord while a config can still bind a direct key. Generated rather
   than written out, because a hand-written list is the thing that silently
   falls behind when an option is added.
4. **The search itself** — through the closure in `XeFMApp._open_search`.

### Who interprets a value

Nobody in the widget layer. `ProgressiveSearchDialog` shows the options, opens
the box, and re-runs on a change; it never reads a value. The meaning lives with
whoever wrote `search_iter` — the same division as `titles` and `accept_hint`,
and why `search_iter`'s signature never changed: the closure that needs the
values already has them.

## Naming: why `options` carries no context prefix

The same rationale `remove_list_item` states in `xefm/actions.py`. The registry
keeps a table per context, so the name can be registered again in `dir_diff` or
`file_diff` with its own default key, while a config naming it unqualified
(`'options': ['Ctrl-T']`) rebinds every one of them at once. `'search.options'`
moves just the one.

## Adding options to another surface

1. Declare them — an `Option` tuple in a module next to the code that
   interprets them (the `search_options.py` shape: declarations and their
   meaning in one file, so a value nothing reads is visibly dead).
2. Register the context's `options` action in `xefm/actions.py`, plus the
   generated `toggle_*` list, and add the context to `CONTEXTS` (and to
   `TEXT_SURFACES` if it takes typing).
3. Build an `OptionSet` where the *state* should live — on the app for something
   that should survive closing the surface, on the widget otherwise — and call
   `reset_transient()` as the surface opens.
4. In the widget: draw `options.chips(mode)` as filled blocks, route the key
   with `is_action_for_event(event, "options", context=…)`, and name the key in
   the hint band by reading it back from the keymap.

Two conventions make the key an idiom rather than trivia, and a new surface
should keep both: **the chips at the right end of the status row**, and **the
hint band naming the key just before `Esc`**. A surface with no options shows
neither, so a strip on screen always means the key will do something.

Chips are hit-tested from rects captured in the same pass that draws them, so
what is on screen is what answers to the mouse — there is no second layout to
keep in step. Only a completed `MOUSE_CLICK` toggles: press and drag belong to
the text field and the list, which sit either side of the strip.

### Fitting the hint band

`ProgressiveSearchDialog.hint(width, measure)` **drops whole entries** it cannot
fit rather than letting `draw_hint_row` cut the last one in half — a truncated
entry spends the width and says nothing, and it is always the rightmost that
loses rather than the one that deserves to. Two entries are droppable, in order:
`↑/↓ select` (arrows moving a list is the one thing nobody has to be told), then
`Esc cancel` (every XeFM dialog answers to it). What survives to the narrowest
box is what a user cannot guess — what Enter does, which mode Tab switches to,
and the key that opens the options.

That is also why `accept_hint` is one word. "Enter results to pane" was accurate
and cost more width than the options key it was crowding out; the band names the
verb and the feature doc explains it.

## Persistence

Three layers, and only the middle one exists today:

- **A config default** — for "always case sensitive, forever". Not implemented;
  the shape would be a `Config` setting seeding the `OptionSet`.
- **A session value** — where an option lives now. `XeFMApp._search_option_set`
  builds the set once and keeps it, so a case choice survives closing and
  reopening the dialog.
- **The declared default** — what every option starts at, chosen so the shipped
  behaviour is unchanged: content search is still a case-insensitive regular
  expression over the whole tree.

`Option.persist=False` opts out of the middle layer: `reset_transient()` puts
the value back as the surface opens. Everything that changes what gets *walked*
should use it — a scope narrowed for one search must not silently narrow the
next, and it is the option that decides how much disk the next search reads.

## The config check

`printable_text_bindings` (was `printable_isearch_bindings`, which survives as
the isearch-only view) scans every context in `actions.TEXT_SURFACES` for an
action bound to a key that types a character — a binding that can never fire
while the character it names goes on being typed. Generalizing it was not
optional: an unqualified `'options': ['O']` silences one key on three surfaces
at once, and a check that knew only about `isearch` would have reported none of
it.

Only actions a context *owns* are checked (`action.context != context` skips the
ones inherited from `common`, which are the file list's and are bound for it),
and a chord holding Ctrl or Cmd is never reported: the field reads those as
commands, so the surface sees them.

## Not done here

**Searching inside archives**, the third request in #312, is not an option yet,
and it is not merely more of the same. Content results are fed into the pane as
a flat listing of real `Path` objects (`_feed_search_results`), and a hit inside
`archive.zip` has no path a pane row can be. That is a design decision about
what accepting such a result *means* — collapse to the archive file, or teach
the pane to hold archive-internal entries — not a toggle. The mechanism above is
ready for it once that is settled: one more `Option` in `SEARCH_OPTIONS`.

## See also

- `doc/SEARCH_OPTIONS_FEATURE.md` — the user-facing description
- `doc/dev/KEY_BINDINGS_IMPLEMENTATION.md` — key expressions and contexts
- `doc/dev/DIALOG_SYSTEM.md` — the shared modal chrome the options box uses
