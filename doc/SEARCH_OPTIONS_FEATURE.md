# Search Options Feature

## Overview

The search dialog (`Shift-F` for filenames, `Shift-G` for contents) carries
three live options: how it reads capital letters, whether the query is a regular
expression or plain text, and whether it looks inside subfolders. They change
the search you are already looking at — results re-run as you flip one — and
they are all behind one key.

Press **Ctrl-O** (or **F9**) while the search dialog is open.

## The chips

The right-hand end of the status row, next to the result count, always shows the
key and one chip per option that applies:

```
⠹ Searching…  37 found        Ctrl-O  Aa  .*  sub
```

The key sits with the chips rather than in the hint band along the bottom: that
band is already full at the width the dialog gets, and a key you cannot see is
not a key.

A chip is **dim** when the option is doing the plain thing and **lit** when it is
not — so at a glance the strip says what this particular search is doing, and you
never have to open anything to find out.

| Chip | Means |
|------|-------|
| `Aa` dim | Case is being ignored |
| `Aa` lit | Capital letters are being matched exactly |
| `aa` lit | Case is being ignored even though you typed a capital |
| `.*` dim | The query is a regular expression and contains nothing special |
| `.*` lit | The query is a regular expression and contains something a regex reads specially |
| `abc` lit | The query is being searched as plain text |
| `sub` dim | Subfolders are being searched |
| `no sub` lit | Only this directory is being searched |

Filename search shows no `.*` chip: filenames are matched as glob patterns, not
regular expressions, so the option does not apply there and is not listed.

## The options box

`Ctrl-O` opens a small box over the search. There is no typing in it, so **every
option has a plain letter**:

```
 c  Case                smart — a capital makes it exact
 p  Pattern             regular expression
 s  Search subfolders   on
```

- `c` / `p` / `s` — change that option straight away
- `↑` `↓` — move, `Space` / `←` `→` — change what is selected
- `Esc` or `Enter` — close

Changes apply the moment you make them; the search behind the box re-runs while
you watch. There is nothing to confirm, and closing does not undo anything.

### Case

- **smart** (default) — an all-lowercase query matches either case, and any
  capital letter means you typed it on purpose. `todo` finds `TODO`; `TODO`
  finds only `TODO`.
- **always case sensitive** / **always case insensitive** — for the times the
  rule guesses wrong.

Applies to both filename and content search.

### Pattern

- **regular expression** (default) — what content search has always been.
  `.`, `*`, `+`, `^`, `$`, `[…]` and friends are live. The `.*` chip lights up as
  soon as your query contains one, which is the quickest way to notice that
  `C++` is not being searched literally.
- **plain text** — the characters you typed, and nothing more. A query like
  `a.c` matches `a.c` and not `abc`, and a query that would be an invalid regular
  expression (`C++(`) simply searches for itself instead of reporting an error.

Content search only.

### Search subfolders

- **on** (default) — the whole tree under the current directory.
- **off** — this directory alone. Useful right after filtering the pane, when
  you mean "these files here".

Subdirectories still *match* by name in filename search when this is off; they
are just not walked into.

## What is remembered

Case and Pattern stay as you set them for the rest of the session, so a
preference you express once keeps applying. **Search subfolders always goes back
to on** when you reopen the dialog: a scope you narrowed for one search should
not silently narrow the next one, especially since it is the option that decides
how much of your disk gets read.

Nothing is written to disk — reopening XeFM starts from the defaults again.

## Changing the keys

`Ctrl-O` and `F9` are the defaults for the `options` action, and both are
rebindable in `~/.xefm/config.py`:

```python
KEY_BINDINGS = {
    'search.options': ['Ctrl-P'],
}
```

Each option also has an action of its own, deliberately left **unbound**, for
the one you change often enough to want a direct key:

```python
KEY_BINDINGS = {
    'search.toggle_case': ['Ctrl-T'],       # smart / always on / always off
    'search.toggle_pattern': ['Ctrl-R'],    # regular expression / plain text
    'search.toggle_subdirs': ['Ctrl-Y'],    # subfolders, or this directory only
}
```

The key must be one the query field does not want: the search dialog is a text
field, so anything printable — including Space — is typing and can never fire an
action. Use a modified or non-printable key. XeFM says so in the log pane at
startup if a binding breaks this rule.

## See also

- `doc/KEY_BINDINGS_FEATURE.md` — the full key-binding reference
- `doc/MIGEMO_SEARCH_FEATURE.md` — finding Japanese names by typing romaji
- `doc/dev/OPTIONS_SYSTEM.md` — how the options mechanism is built
