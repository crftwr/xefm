# Migemo Search Implementation

The design was worked out in [discussion #332](https://github.com/crftwr/xefm/discussions/332)
(engine choice, activation policy, measurements); this document records what
was actually built. Requested in #302.

## Module: `xefm/migemo_search.py`

Everything Migemo lives in one module; the search surfaces call four small
functions and otherwise keep their native matching untouched.

| Function | Purpose |
|---|---|
| `get_regex(pattern)` | The compiled Migemo regex, or `None` when Migemo doesn't apply (disabled, under the length gate, a glob, engine failed). Callers union a non-`None` regex with their native match — never replace it. |
| `search_nfc(regex, text)` | Membership test against the NFC-normalized text (filenames, dialog labels). |
| `has_hit(regex, text)` | Membership test against the raw text (viewer lines, whose highlight offsets index the raw string). |
| `match(pattern, text)` | `get_regex` + `search_nfc` in one call. |
| `find_spans(pattern, text)` | `(start, end)` hit spans in the raw text for span-level highlights, or `None`. Doubles as the `search_matcher` PuiKit's rich viewers accept. |

### Engine: pymigemo, patched at runtime

oguna's pymigemo (BSD-3, pure Python, dictionary bundled in the wheel) was
chosen over C/Migemo so one artifact ships through PyPI, the dmg, and the
Store with no native library or GPL-family dictionary (#332 §4).

pymigemo 0.0.1 cannot load its dictionary on LP64 platforms: the reader
builds `array.array('L')` for a 32-bit on-disk field, and `'L'` is 8 bytes on
macOS/Linux (`EOFError` on load). `_Array32` is swapped in for the `array`
binding of `migemo.migemocompactdictionary` before the engine is constructed;
it rewrites typecode `'L'` to the always-32-bit `'I'` only when `'L'` isn't
4 bytes, so the patch is inert on Windows and after any upstream fix.
`requirements.txt` pins `pymigemo==0.0.1` because a new upstream release
could move the internals the patch touches.

Importing `migemo.migemocompactdictionary` doubles as the identity check:
atzm's PyMigemo (a C/Migemo binding) also imports as `migemo` but has no such
submodule, so on a collision the import raises and Migemo stays off.

The engine loads lazily inside `_load_engine()` on the first gated query
(~20–50ms dictionary read), and a failure is cached as "unavailable" — one
warning, then silence.

### Expansion: per-word, lowercased

`_compiled()` does **not** call `engine.query(pattern)` directly. pymigemo's
own query has two case-sensitivity defects (its romaji converter only reads
lowercase):

- `Mudai` expands without 無題 — cfiler#9's confusion, inverted;
- an all-caps word expands to a degenerate alternative
  (`KENSAKU` → `(ＫＥＮＳＡＫＵ|KE)`) that, under `IGNORECASE`, would match
  every name containing "ke".

Instead the pattern is split with pymigemo's own word parser
(`Migemo.parse_query`: camel case and whitespace break words) and each word
is expanded **lowercased**, the pieces concatenated. Words under the length
gate become escaped literals — expanding 1–2 character words is the
seconds-slow path (#332 §3.3), and inside a camel pattern (`abC`) they would
dodge the whole-pattern gate. The result compiles with `re.IGNORECASE` and is
cached per `(pattern, gate)` in an `lru_cache` — generation is the expensive
step; matching is cheap.

A mixed-case pattern is ambiguous: `TenkiYohou` means two camel words, but
`Sa-bisu` is one word typed with a capital — and its camel split
(`Sa` + `-bisu`) demands a literal `Sa` no Japanese text contains. Since
Migemo is additive, both readings are expanded and unioned: the camel split
and the whole pattern lowercased (skipped when they agree, which is every
single-word and all-lowercase pattern).

A third pymigemo defect is repaired per word (`_word_expansion`): its
expansions stop at hiragana, where C/Migemo also unions the katakana and
half-width-katakana forms — so `kensaku` could never find `ケンサク`, nor
typed hiragana find katakana. Each hiragana reading of the word (its
predictive romaji conversions via pymigemo's `romajiconverter`, plus the
word itself when it is hiragana) is translated to katakana (a parallel-block
`str.translate`) and to half-width katakana (pymigemo's
`characterconverter.zen2han`), and the results join the expansion as escaped
literals, longest first so a highlight span covers the whole hit.

### Alternate romaji tables (`xefm/romaji_azik.py`, #346)

C/Migemo keeps its romaji→hiragana table in an editable `roma2hira.dat`, which
is how AZIK typists made C/Migemo understand their spellings. pymigemo has no
such seam: the table is two module-level parallel lists in
`migemo/romajiconverter.py`, prefix-searched with `bisect` inside
`convert_romaji_to_hiragana_predictively`, which `Migemo.query_word` calls
directly. So an alternate table has to be *installed* over those globals
(`_installed()`, a context manager under `_table_lock` — the swap is process
global, so no other thread may be expanding meanwhile).

**Union, not replacement.** AZIK reassigns ~13 keys plain romaji already uses
(`ca` か → ちゃ, `xa` ぁ → しゃ, `wi` ゐ → うぃ). Swapping the table would take
those readings away, breaking the module's founding rule that Migemo only ever
*adds* matches. `_compiled()` therefore expands the pattern twice — once under
the plain table, once under the alternate — and unions the two expansions, the
same shape as the camel/lowercase union above. The cache key carries the table
name so a runtime config reload cannot serve a regex built for the other one.

**The table is generated, not shipped.** `romaji_azik.build(plain)` takes the
engine's own table as a mapping and returns AZIK's entries: 44 first strokes ×
(5 vowels + 10 extension keys) plus ~60 hand-listed 互換キー and 特殊拡張, 703
entries from ~90 lines. Base kana are read from `plain` (`_BORROWED` maps
AZIK's `kg`/`zy`/`tg`/`dc` onto the plain `ky`/`jy`/`th`/`dh` rows; `_OWN` holds
the five rows AZIK spells itself), so the kana always match the engine's and a
prefix `plain` cannot spell is skipped rather than guessed. Two reasons not to
bundle a data file: the published AZIK tables for Google IME carry no
redistribution licence (and the one under BSD-2 is a personal variant), and the
generator is checkable against the spec — [AZIK総合解説書](http://www1.vecceed.ne.jp/~bemu/azik/azikinfo.htm) —
in a way a 700-line table is not.

Merging sorts the keys, which also repairs upstream's one out-of-order entry
(`~` is stored before `a` in `ROMAJI_KEYS` though it sorts after, so
`bisect` can never find it). Longest
AZIK key is 3 characters, inside the converter's 4-character lookahead window.

### The ASCII filter

A Migemo hit only counts when the matched span contains a non-ASCII
character (`has_hit` / `search_nfc` / `find_spans` all enforce this). Two
reasons:

- ASCII hits are redundant by construction — the regex keeps the typed
  romaji as an alternative, and every caller unions the regex with its own
  substring/glob matching, which already found them.
- pymigemo's expansion of an ASCII word can be buggy-broad: `x25` expands to
  `(ｘ２５|x2)`, whose truncated `x2` alternative would make `x25` "match"
  `x24`. Discarding ASCII-only hits makes this whole bug class harmless —
  Migemo can only ever contribute what it exists for, Japanese (and other
  non-ASCII, e.g. full-width) matches.

### Gates (`get_regex`)

1. `MIGEMO_SEARCH` config off → `None`.
2. `len(pattern) < MIGEMO_MIN_LENGTH` (default 3) → `None`. Generation cost
   concentrates in short queries (2s worst for one char, ~5ms p90 at 3).
3. Pattern contains `*`, `?`, or `[` → `None`. Globs keep fnmatch semantics.
4. Engine failure or empty expansion → `None` (an empty regex would match
   every row). Known 0.0.1 landmines (a lone `s` raises `IndexError` in its
   bit vector) are absorbed here.

Config is read through `_config()` (→ `xefm.config.get_config()`, `None`
tolerated), which tests monkeypatch for determinism.

## Integration per surface

| Surface | Membership | Highlight |
|---|---|---|
| `FileListManager.find_matches` (pane isearch) | `search_match.hit` per file — per-token `fnmatch(wrapped) or search_nfc(regex, name)`; the query (and so each token's regex) compiled once, outside the file loop | row-level (`search_matches` index set) — unchanged |
| `TextViewer._search_recompute` | `pat in line.lower() or has_hit(regex, line)` | `_draw_matches` collects literal spans + `find_spans` |
| `DiffViewer._search_recompute` | either side, same shape | `_DiffPane._draw_search`, same shape |
| `FilterListDialog._refilter` / `add_items` | `_label_hit`: the same `search_match.hit`, on the rendered label (#349) | row selection only |
| Rich viewers (Markdown/JSON/CSV) | PuiKit hook, below | markdown: spans; json/table: row-level |

NFC vs raw: filenames and labels are membership-only, so they normalize
(macOS serves NFD names, Migemo emits NFC kana). Viewer lines are matched
**raw** because the highlight spans index into the line as drawn —
normalizing would shift offsets. A decomposed haystack inside file content is
rare and accepted as unmatched there.

## The PuiKit `search_matcher` hook

PuiKit stays Migemo-free. `MarkdownView`, `JsonView`, and `TableView` each
grew a public attribute:

```python
search_matcher: Callable[[str, str], list[tuple[int, int]] | None] | None
```

`(pattern, row_text) → hit spans`, `None` for "no opinion". A row matches
when the literal test *or* the matcher hits; `MarkdownView._draw_search_row`
also draws the matcher's spans (json/table highlight row-level and only
truth-test them). `TextViewer._ensure_rich_widget` assigns
`migemo_search.find_spans` to the built widget — on a released PuiKit
without the hook the attribute is simply never read, so XeFM works against
both (rich-mode Migemo lights up once PuiKit ships the hook).

## Config plumbing

`MIGEMO_SEARCH` (bool, default `True`), `MIGEMO_MIN_LENGTH` (int ≥ 1, default
3) and `MIGEMO_ROMAJI_TABLE` (`'default'` or `'azik'`) live in
`xefm/_config.py` under "Incremental search settings" and are validated in
`ConfigManager.validate_config`. Existing user configs pick
them up through `_copy_missing_fields`.

## Out of scope (deliberately)

- **Filter (`;`), Shift-F, Shift-G** — not incremental search; Shift-F is a
  whole-name glob by design (#231) and content grep is already a regex.
  Extending Migemo there is a separate decision (#332 §5).
- **Async / two-phase result delivery** (#332 comment 2) — unnecessary at
  the current numbers: measured ~31ms for the first gated keystroke
  (dictionary load included) and 4–9ms per keystroke over a 10,000-file
  pane.
- **Sub-span highlight in the file pane** — pane isearch highlights whole
  rows today; unchanged.

## Tests

- `test/test_migemo_search.py` — loader/patch, gates, expansion casing, the
  ASCII filter, NFD, engine-landmine absorption, the AZIK table's rules and
  its union/cache-key/global-restore behaviour, `find_matches` and
  `FilterListDialog` integration. Engine-dependent tests skip without
  pymigemo.
- `test/test_search_match.py` — the query language the Migemo union sits in
  (tokens, wildcards, AND/OR, dialog integration, pane/dialog parity), with
  Migemo switched off so the two halves are testable apart.
- `test/test_viewer_isearch.py` — romaji matching (and highlight drawing via
  `render()`) in the text and diff viewers.
- `test/test_markdown_viewer.py` — the matcher is injected into rich widgets.
- PuiKit `tests/test_{markdown,json,table}_view.py` — the `search_matcher`
  hook, with a fake matcher.
