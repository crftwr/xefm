# Filename Normalization System

An entry has the name it carries on disk and the name XeFM *compares* it by, and
those are deliberately not the same string. This is the contract for the second
one: what it is, where it is used, and — the part that has bitten every feature
that guessed — where it must never be used.

Source: [`xefm/name_key.py`](../../xefm/name_key.py).
Tests: [`test/test_name_key.py`](../../test/test_name_key.py).

```python
name_key.nfc(text)                 # text in NFC
name_key.rel_name(path, root)      # "sub/dir/a.txt", or the basename
name_key.compare_name(path, root)  # rel_name in NFC — what everything compares
```

---

## Why there is a compared name at all

Two questions were being answered differently by every feature that asked them.

**Which normal form?** A filesystem stores whatever form it was handed. `が`
written NFD is `か` (U+304B) followed by a combining mark (U+3099); written NFC
it is one character (U+304C). Both render identically. Decomposed names arrive
routinely — from HFS+ volumes, network mounts, archives, and from Finder, which
still writes them (see below).

**Which scope?** A search-results pane displays the whole path below the search
root. Everything else about it used the bare basename.

Answering both in one place is what the module exists for. The rule:

> **Everything but a filesystem call compares, sorts, matches and displays
> `compare_name`. Filesystem calls use `Path` and `EntryInfo.name`, verbatim.**

There is no setting. A user who could choose the wrong answer here has been given
a way to make their file manager lie to them.

---

## Scope: names, not content

This system is about **filenames**. File *content* is matched exactly as it is
written — the content search ([`app.py`](../../xefm/app.py)
`_iter_content_matches`) and the text viewer's search both compare raw text, and
that is deliberate, not an oversight to be tidied up later.

A filename is metadata the platform re-spells behind the user's back: Finder
decomposes every name it touches, so the name a user types and the name on disk
routinely disagree about a file the user is looking at. Content is what somebody
wrote and saved. A search over it that quietly matched a different spelling would
be reporting text that is not there, and `grep` does not do that either.

There is a mechanical reason to keep the two apart as well. The text viewer
indexes highlight spans into the line **as drawn**
([`text_viewer.py`](../../xefm/text_viewer.py), `migemo_search.find_spans`), so
normalizing for the match would slide the highlights off the characters they
mark. The content search has no spans and *could* normalize safely — it stays
literal anyway, so that a search over a file's text means the same thing in both
places.

The one content-adjacent thing that is normalized is the content search's
**filename pre-filter** (`*.py` and friends), because that is a name.

---

## What went wrong before it existed

All three were reproduced before being fixed, and are pinned by tests.

**A decomposed name was invisible to the incremental search.** `search_match.hit`
globbed the raw name while only its Migemo branch normalized. An IME emits
composed text, so typing `が` never matched a file stored `か`+U+3099 — a file
whose name is on screen, spelled the way it was typed. The pane filter had the
same hole, and so did the directory walk behind the search dialogs, which
mattered most: a name the walk never yields cannot be found in the results pane
either, however well the pane matches.

**Decomposed names sorted where they do not belong.** `が` decomposed sorts after
every `か`-something rather than between `か` and `き`:

| | order |
|---|---|
| raw codepoints | `か.txt`, `が.txt`, `かア.txt` |
| composed first | `か.txt`, `かア.txt`, `が.txt` |

**Batch rename could destroy a file.** The same-name check keyed on the raw
string, so two rows landing on one file under two spellings of one name were both
reported conflict-free. On APFS they *are* one file, and the second rename
replaced the first.

---

## Where the compared name is used

| Site | Source |
|---|---|
| Sort (name and extension modes) | [`file_list_manager.py`](../../xefm/file_list_manager.py) `sort_entries` |
| Pane filter | `_assemble_listing` |
| Incremental search | `find_matches` |
| Search dialogs' directory walk | [`app.py`](../../xefm/app.py) `_iter_filename_matches`, the content search's name pre-filter |
| The name column | [`file_pane.py`](../../xefm/file_pane.py) `_display_name` |
| Compare and Select pairing | [`compare_selection.py`](../../xefm/compare_selection.py) `_pair_key` |
| Batch rename: match, output, collision key | [`batch_rename_dialog.py`](../../xefm/batch_rename_dialog.py) `compute_preview` |
| Single rename: field seed, cursor landing | `app.py` `rename`, `_select_by_name` |
| Query compilation (once, not per candidate) | [`search_match.py`](../../xefm/search_match.py) `compile_query` |

The one place that deliberately keeps the basename is **Compare and Select's
pairing**, because matching `a.txt` against `a.txt` wherever each side keeps it is
what the compare is for. It is a checkbox instead — see
[Pane-relative scope](#pane-relative-scope).

---

## Caching: eager, on the worker

`_assemble_listing` fills `attrs['cmp_name']` the first time a listing is
assembled, and `_build_file_info` carries it into the per-entry display cache.

Eager, not lazy — deliberately. Laziness pays when only some entries are touched,
and here every consumer touches all of them: the sort, the filter and each
i-search keystroke sweep the whole pane. The only partial consumer is drawing the
visible rows. Deferring would move the cost to the first keystroke, on the UI
thread, which is the one place it must not land. Filling it in `_assemble_listing`
puts it on the worker for a directory pane, and the record travels on in
`entries`, so re-sorts and keystrokes read it back rather than recomputing.

Costs, per 10,000 entries:

| | ns/entry | per 10k |
|---|---|---|
| `normalize('NFC', …)` on an ASCII or already-composed name | 14–25 | 0.14–0.25 ms |
| `normalize('NFC', …)` on a genuinely decomposed name | 920 | 9.2 ms |
| `str.lower()`, which the search already does per keystroke | 17–48 | 0.17–0.48 ms |

Do **not** guard the call with `is_normalized`. CPython's `normalize` quick-checks
first and returns an already-composed string in the same 14 ns, so the guard only
pays for the check twice.

End to end on a real directory of 5,000 decomposed names: the listing absorbs the
normalization once (43 ms, on the worker), and an i-search keystroke costs 3.4 ms
instead of the 8.2 ms it would cost re-normalizing each time.

---

## Pane-relative scope

`rel_name` returns the path below `root`, falling back to the basename when there
is no root, when the path does not lie under it, or when the two name the same
place. That fallback is also an ordinary directory pane's answer — its entries are
direct children, so the relative name *is* the basename and nothing changes there.

This is what fixes a search-results pane displaying `sub/dir/a.txt` while ordering,
filtering and searching by the bare `a.txt`: the name column looked unsorted
because it was sorted by a string it was not showing, and the directory part of
every visible row was unmatchable.

**Compare and Select gets a checkbox rather than the change.** Pairing by basename
is right nearly always. It is wrong when a result set holds a dozen files called
`index.html`, which all collapse onto each other — only the path below the search
root separates them. The row is offered *only when a side is virtual*, because
between two directory listings the answer cannot change. It is left out rather
than drawn dead: PuiKit's `Checkbox` has no disabled state, and giving it one is
the toolkit's business, not this repo's.

Each side brings **its own root** — a virtual pane's search root, an ordinary
pane's directory (`app.py` `_pane_root`). That is what makes the option mean what
it looks like: a listing of `/a` and a search rooted at `/a` agree on `x.txt` for a
hit sitting in `/a`, and disagree on `sub/x.txt` for one a level down, exactly as
the two panes show them.

---

## What Finder does, and where XeFM parts company

Measured by renaming eight probe files by hand in Finder and reading back their
codepoints. Two answers were adopted; one was not.

**Finder normalizes before matching.** Its batch rename's Replace Text matched an
IME-typed (composed) `が` against a decomposed name. XeFM does the same.

**Finder catches a collision that is only a difference of form.** Renaming
`DX_が` (NFD) onto the existing `DY_が` (NFC) — the same file on APFS — was
detected and disambiguated with a `" 2"` suffix rather than overwriting. XeFM
catches it too, though it *blocks* the rename, which is the batch dialog's
existing model for conflicts.

**Finder writes NFD, and XeFM writes NFC.** This is the deliberate divergence.
Finder still composes down to the decomposed form HFS+ used, and aggressively: the
composed control file came back decomposed after an ordinary rename, and so did a
file the batch rename matched *nothing* in — Finder issues a rename for every
selected item, and on APFS a rename onto the same file still rewrites the stored
spelling:

```
created NFC          -> 304C
renamed to NFD form  -> 304B 3099      # one file throughout, spelling rewritten
```

XeFM writes NFC on every platform instead. On APFS the choice is cosmetic — lookup
ignores the difference and either spelling opens the file. Off it, the bytes *are*
the name: ext4 and NTFS match them exactly, and so do S3 keys and archive members.
This is one program on three platforms whose job is moving files between them, and
a per-OS spelling of the same rename is not cosmetic there.

**Normalization never happens on its own.** A name a rename pattern does not match
comes out equal to what went in, and the apply loop already skips those, so a file
nobody asked to rename keeps its bytes. Composing only ever rides along with a
rename that was requested.

---

## The trap: a compared name is not a path

The temptation to reuse `compare_name` as a path is real, because on macOS it
works. APFS lookup is normalization-*insensitive*, so completely that both
spellings of a name are the same file, and a composed string happily opens a file
stored decomposed. **None of that surfaces on the machine most of this was written
on.**

```python
open(d/nfd_name, "w")                    # created decomposed
os.path.exists(d/nfc_name)   # -> True   # …and the composed name finds it
```

ext4, NTFS, S3 keys and archive members all match bytes exactly, and there the
same call fails — or, for a remote key, quietly addresses something else.

Hence the naming, which is the enforcement mechanism: nothing in `name_key` is
called `name`, the cached field is `cmp_name`, and `Path` / `EntryInfo.name` stay
verbatim. A reviewer who sees `cmp_name` passed to `open()` has enough to catch it.

APFS is also normalization-preserving *within* that insensitivity: it stores the
spelling it was first given. So a directory cannot hold both forms of one name —
they are one file — but it can perfectly well hold decomposed names, which is why
this system exists at all.

---

## Collation is exposed, not built in (#380)

The built-in sort still compares codepoints, so its order is not Explorer's:
symbols sort after digits rather than before, and kanji sort by codepoint rather
than by the platform's collation. Normalization was the prerequisite and landed
first — it fixes the order of decomposed names on its own — but parity is
deliberately **not** built in. `SORT_KEYS` exposes the choice instead
([`CUSTOMIZATION_API_IMPLEMENTATION.md`](CUSTOMIZATION_API_IMPLEMENTATION.md)
§8b).

The measurements are why. Native collation forces a *comparator*: Windows has
`StrCmpLogicalW`, macOS `localizedStandardCompare:`, and neither platform's
shell order is reachable as a sort key — measured at 0.254 s per 10,000 entries
against 0.0024 s for a codepoint sort. `locale.strxfrm` is the portable
key-shaped alternative and does not reproduce either shell: on macOS it puts
symbols after digits and reorders again with the locale.

So a built-in parity mode would have meant carrying one contract for itself
(comparator, O(N log N)) and another for the registry (key, O(N)) — and would
have picked one shell's order for a program that runs under three. Exposing it
leaves one contract, and puts the cost next to the config that asked for it.
Sorting moved to a worker thread to make that safe
([`ASYNC_LISTING_SYSTEM.md`](ASYNC_LISTING_SYSTEM.md)).
