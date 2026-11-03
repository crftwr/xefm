# .xft Tree Files — Implementation

[#573](https://github.com/crftwr/xefm/issues/573), from discussion
[#549](https://github.com/crftwr/xefm/discussions/549) and its "Where this
landed" comment. The format is [`doc/XFT_FORMAT.md`](../XFT_FORMAT.md),
and user-facing behavior is [`doc/TREE_FILES_FEATURE.md`](../TREE_FILES_FEATURE.md).

The extension is kept to four characters so it fits the file list's extension
column ([#613](https://github.com/crftwr/xefm/issues/613)).

## Pieces

| Piece | Where |
|---|---|
| Parse, cache, find a group by its anchor | `xefm/xft.py`: `parse`, `load`, `forget`, `find_group` |
| The scheme | `XftPathImpl` (`ReadOnlyPathImpl`), registered as `xft` in `path_schemes` |
| The reference hook | `PathImpl.target()` / `Path.target()`, default `None` |
| Entering, references to folders | `XeFMApp._enter_file` |
| Reveal and bulk reveal | `_virtual_focused_entry`, `_reveal_result_other`, `_reveal_selected_targets` |
| Provisional trees | `_note_xft_anchor` (from `_list_pane`), `_watch_xft`, `_pump_xft`, `_xft_header_text` |

## The scheme

`xft://<file>#<group>/<entry>`, the archive's shape. `parse_uri` keeps the file
part, and `root_prefix` is `xft://<file>#`. At the top, `name` is the
file's name and `parent` is the file's directory. That is exactly what
`_go_parent` needs to land on the file when leaving, with no special case,
the same way leaving an archive lands on the archive.

`XftPathImpl` implements the five methods `UriPathImpl` leaves abstract:

- `exists` / `is_dir`: a node is found by walking names from the root. A group
  (`children`) is a directory. A reference is never one, even when it points
  at a folder: listing the real folder inside the tree would turn a snapshot
  into a live view, so `Enter` on it goes there instead (`_enter_file` asks
  `target().is_dir()`).
- `stat`: recorded `attrs` first, through `UriStatResult`. This is what
  lets a group of `ssh://` files list without a round trip per row. A
  reference with nothing recorded falls back to the target's `stat`.
- `open`: read modes delegate to the target, and any write mode is refused.
  View, diff, copy-out and quick view read real bytes this way.
- `iterdir`: the children, as `child(name)`.

Every write is refused with `EROFS` by `ReadOnlyPathImpl`, with a
`READ_ONLY_MESSAGE` that names the way to the real file.

**Names.** `parse` makes sibling names unique (` [2]`, ` [3]`, NFC +
casefold), and turns `/` and `\` into `_`, because a name is a path segment.

**Cache.** `load(file)` keeps one parsed `Document` per file, keyed by the
file's `(size, mtime)`. It looks at the file again at most once a second
(`_RECHECK_S`). A listing asks `exists`, `is_dir` and `stat` of every entry, so
without the cache it would parse the file once per row. With it, a rewrite
is seen on the next look.

## `target()`

`PathImpl.target()` returns the real place a path stands for, or `None`. It
has a default, as #426's rule for the published base requires, so every
existing scheme, external ones included, keeps working.
`test_xefm_app_archive_browse.py`'s `FakeEntry` gained it, because
`_enter_file` now asks every entry.

`_virtual_focused_entry` was the reveal keys' single question, "which real
file does the cursor stand for". It now answers for both kinds of pane: a
virtual pane's row, or a tree entry's target. So `O` from the other pane and
`Shift-O` from the tree work through the existing code. `Shift-O` with a
selection in a tree goes to `_reveal_selected_targets` instead. It collects
the targets (a selected group contributes its references) and opens them in
the other pane through `open_path_list`, the same door as Open List. That
pane is where they can be deleted, so the guard against deleting from a
snapshot never needs an exception.

## Provisional trees

`final: false` means a producer may rewrite the file.

- **Header.** `_xft_header_text`: `[scan.xft]/group  ·  scanning 25% —
  groups may change`. The note has priority over the path.
- **Watching.** `_list_pane` calls `_note_xft_anchor` for an `xft://`
  path. That records the anchor target of the group the pane is in (the old
  document is gone once the file is rewritten, so the anchor has to be known
  beforehand), and starts `_watch_xft` when the document is provisional.
  The watcher is a daemon thread polling every 2 s. When a tree's `stamp`
  changes, it sets `_xft_dirty` and calls `_wake_pump()`, and it ends when no
  pane shows a provisional tree.
- **Re-reading.** `_pump_xft`, from `_pump_monitoring`, re-lists each pane
  inside a tree. If the pane's path is gone (the group was renamed, for
  example because its member count is in its name), `find_group` finds the
  group with the same anchor and the pane follows it. Otherwise the pane goes
  to the top and the log says why.
- **Bulk reveal asks first.** On a provisional tree, `_reveal_selected_targets`
  shows a confirmation, defaulting to Cancel. Single-entry reveal does not ask,
  because the user is looking at the one file.

## Declared attributes

A tree's top-level `attributes` declares values its references keep in
`extra`, with a type and, in `show`, how to show them
([`XFT_FORMAT.md`](../XFT_FORMAT.md#attributes)). XeFM has no knowledge of
any one of them, similarity included.

- **Registered when read.** `load` calls `_declare` for each new parse
  (never on a cache hit). Each declaration becomes a synchronous
  `attributes.Attribute` named `xft.<key>` (`attributes.declare`), read off
  the node's `extra` by `_reader(key)` and checked against the type by
  `_typed`. A `show` becomes the `LAYOUT_EXTRAS` spec of an extra of the same
  name (`layouts.declare_extra`), whose `when` (`_when(key)`) holds in a
  folder of a tree that shows that key.
- **Why a prefix.** A tree is data from another program: it must not shadow
  `size` or a user's `git`, and config.py must be able to name its
  attributes before any tree is open, which only a recognizable name allows
  (`attributes.is_declarable`). The config's unknown-attribute warnings skip
  those names, `ATTRIBUTES` refuses them, and a `LAYOUT_EXTRAS` entry for one
  is kept as an override (`layouts.override_declared`) and merged key by key
  when a tree declares it.
- **What a file may give** in `show` is the placement and format keys
  (`_COLUMN_KEYS`, `_MARKER_KEYS`). `when` and functions stay the user's;
  `build_extra` validates the rest. A declaration XeFM cannot use is logged
  as a warning and left out, and the tree still opens.
- **Kept across a config reload.** `attributes.clear` leaves `_declared`
  alone, and `layouts.clear` rebuilds the declared extras with the new
  overrides.
- **One name, latest declaration.** Two trees declaring the same key share
  the attribute, and the one read last sets its type, label and placement.
  A tree that declares a key without `show` does not withdraw another tree's
  column: `_when` asks the tree the pane is in.
- **Synchronous.** The value is in the cached `Document`, so it is never
  pending: the column is measured on the first draw, and the attribute sort
  is offered at once. File Details reads a sync attribute where it is
  (`AttributeStore.get`) instead of waiting for the store, which never holds
  one, so it lists `Similarity | 93%` with no "reading…".
- **`ratio`** is a type of its own, not a `count`: a 0-1 float. Its default
  format, `percent`, rounds **down**, so `100%` means an exact match and a
  `0.996` near-duplicate does not look identical.

## Not done

Line positions on references (#549 question 2), saving search results as a
tree, flat lists as one-level trees (#549 decision 6), and an `.xft`
produced by XeFM itself.

## Tests

`test/test_xft.py`. Format tests cover unique names, defaults and version
refusal, and the anchor lookup. Scheme tests cover browsing, `parent`/`name`
at the top, recorded attributes winning over the real file, reading through
to the target, every write refused, a rewrite picked up, and `target()` of an
ordinary path. Pane tests cover `Enter` in and `Backspace` back onto the file,
a reference to a folder, `Shift-O` on one entry and on a selection, the
provisional header and the bulk-reveal confirmation, a renamed group followed
by its anchor, and a vanished group returning to the top.
