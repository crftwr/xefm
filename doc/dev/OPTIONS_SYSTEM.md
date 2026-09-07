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
`options`, `Ctrl-O` — that opens a surface with *no text field*, where every
plain letter is free to be an accelerator. One key, spent once, for as many
options as any surface ever grows.

## The parts

| File | Holds |
|------|-------|
| `xefm/options.py` | `Option` (the declaration) and `OptionSet` (the live values) |
| `xefm/options_dialog.py` | The shared box the `options` key opens |
| `xefm/search_options.py` | The search dialog's declarations *and* what they mean |
| `xefm/actions.py` | The `search` context, the `options` action, the generated `toggle_*` actions |
| `xefm/config.py` | `printable_text_bindings` — the config check, now covering every text surface |

## One declaration, four readers

`Option` is frozen and says everything about one setting: its cycle of values
(the **first is the default**), the chip text, the dialog label, its
accelerator, which modes it applies to, when its chip is lit, and whether it
outlives one opening of the surface.

Four things read that same list, which is what keeps them from drifting:

1. **The chip strip** — `OptionSet.chips(mode)` returns `(text, lit)` pairs,
   drawn at the right end of the search dialog's status row.
2. **The options dialog** — rows, labels, and `accel_map` for the letters.
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

### The `active` hook

The default lit rule is "not at its default value". An option whose real state
depends on something else passes its own predicate, taking `(value, hint)` where
`hint` is what the surface put on `OptionSet.hint` — the query text, for search.
That is what lets the strip show *what the search is actually doing*:

- the `Aa` chip lights when smart case has decided the query is case-sensitive,
  which teaches the rule without a word of explanation;
- the `.*` chip lights when the query contains a metacharacter, which is the
  one thing issue #305's reporters could not have guessed.

## Naming: why `options` carries no context prefix

The same rationale `remove_list_item` states in `xefm/actions.py`. The registry
keeps a table per context, so the name can be registered again in `dir_diff` or
`file_diff` with its own default key, while a config naming it unqualified
(`'options': ['F9']`) rebinds every one of them at once. `'search.options'`
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
4. In the widget: draw `options.chips(mode)`, route the key with
   `is_action_for_event(event, "options", context=…)`, and read the key label
   back from the keymap so a rebind is what the surface shows.

One convention makes the key an idiom rather than trivia, and a new surface
should keep it: **the key and then the chips, at the right end of the surface's
status row**. The search dialog puts them there rather than naming the key in
the hint band because that band already elides its fourth entry at the width a
pane-anchored box gets — and because the key belongs against the things it
changes anyway. A surface with no options shows no strip, so a strip on screen
always means the key will do something.

## Persistence

Three layers, and only the middle one exists today:

- **A config default** — for "always case sensitive, forever". Not implemented;
  the shape would be a `Config` setting seeding the `OptionSet`.
- **A session value** — where an option lives now. `XeFMApp._search_option_set`
  builds the set once and keeps it, so a case choice survives closing and
  reopening the dialog.
- **Derived from the query** — smart case, and the metacharacter check. No
  storage at all, which is why they are the defaults.

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
