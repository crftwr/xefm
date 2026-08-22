# Text Encoding — Implementation

Issue #289. User doc: `doc/TEXT_ENCODING_FEATURE.md`.

## The problem being replaced

`_read_lines` / `_read_source` in `xefm/text_viewer.py` decoded with the loop
`utf-8 → latin-1 → cp1252`. latin-1 maps all 256 byte values and never raises,
so the loop always "succeeded" on the second attempt: cp1252 was unreachable,
and every non-UTF-8 file — every Shift-JIS, EUC-JP, ISO-2022-JP file — rendered
as latin-1 mojibake. (The same latin-1 property is why binary detection must
sniff bytes *before* decoding; see `test_binary_file_handling.py`.)

## Module layout

| Piece | Where | Role |
|-------|-------|------|
| Detection + decoding | `xefm/text_encoding.py` | pure bytes → `(text, label)`; no UI, no Path; also owns `AUTO_ENCODING` |
| Generic list picker | `xefm/choice_dialog.py` | `ChoiceDialog`: reusable pick-one modal over `(value, label)` rows, with type-ahead |
| Viewer integration | `xefm/text_viewer.py` | readers take an `encoding` override; `_encoding_rows` + `change_encoding` wire the picker; `edit_file` shares the reload path |
| Picker list config | `Config.TEXT_ENCODINGS` in `xefm/_config.py` | manual picker entries only — detection is fixed |

`ChoiceDialog` is deliberately encoding-agnostic — a titled pick-one list in
the Sort dialog's visual mold, reusable by any future picker. Rows are
`(value, label)` pairs; the encoding-specific parts (the **Auto** row naming
what detection chose, labels via `encoding_label`) are assembled by
`text_viewer._encoding_rows`. Type-ahead lives in the dialog: printable keys
accumulate into a buffer (shown in the footer, `Backspace` trims, a second of
quiet resets it via an injectable clock) and the selection jumps to the first
label match, prefix beating substring, case-insensitive. Cancel reports
`None`, which is why "auto" is a real value (`AUTO_ENCODING`) rather than
`None`.

The diff viewer imports `_read_lines` from the text viewer, so it inherits
detection with no changes beyond the wider return tuple.

Content search reuses the BOM half only: `XeFMApp._sniff_text_encoding`
(`xefm/app.py`) calls `sniff_bom` on a file's first chunk to pick a streaming
codec (`utf-8-sig` / `utf-16` / `utf-32`) before the NUL binary sniff, so
BOM-tagged Unicode files are grepped line-by-line without loading whole files
the way `decode_text` does (issue #305). Full charset detection (Shift-JIS,
EUC-JP) stays viewer-only — grep reads BOM-less files as UTF-8 with
`errors="ignore"`.

## Detection order (`decode_text`)

Each step only fires when it is *decisive*:

1. **BOMs** (`sniff_bom`) — UTF-8, UTF-16 LE/BE, UTF-32 LE/BE, longest prefix
   first (UTF-32 LE's BOM starts with UTF-16 LE's). A BOM is an explicit
   declaration, so it wins outright; the rest of the data decodes with
   `errors="replace"` rather than failing over to a guess.
2. **ISO-2022-JP** — attempted only when its escape introducers (`ESC $`,
   `ESC (`) are present. It is pure 7-bit, so it would also strict-decode as
   UTF-8; the escapes are the tell, which is why it runs *before* UTF-8.
3. **UTF-8 strict** — multi-byte sequences validate strictly enough that other
   encodings essentially never pass by accident. Plain ASCII lands here.
4. **CP932 vs EUC-JP** — the classic ambiguity: EUC-JP Japanese often
   strict-decodes as CP932 too (its kana bytes 0xA1–0xDF read as CP932
   half-width katakana), so order alone cannot pick. Both are strict-decoded
   and scored by `_jp_score` — +2 kana/kanji, +1 CJK punctuation and
   full/half-width forms, −2 private-use/replacement — and the higher score
   wins. The correct decode always out-scores the misread (kana +2 beats
   half-width katakana +1); the reverse misread (CP932 as EUC-JP) mostly fails
   strictness outright, since CP932 lead bytes 0x81–0x9F are invalid EUC-JP
   leads. Ties keep CP932, the Windows default. The score must be **positive**
   to win — a Western single-byte file can strict-decode as CP932 by
   coincidence, but its "Japanese" scores ~0 and must not shadow CP1252.
5. **CP1252 strict**, then **latin-1** — the never-fails tail, preserving the
   old chain's "any file still displays" property.

Scoring caps at 64 KiB of decoded text — enough to judge any real file.

Known imperfection, accepted deliberately: a *short* Western text whose
accented bytes happen to form valid CP932 pairs (e.g. `ï` + a consonant) can
be misread as Shift-JIS with a small positive score. Raising the threshold
would instead misread short genuine Japanese files, which this codebase's
audience hits far more often — and the manual override exists exactly for the
residue no heuristic covers.

## Forced decoding

A codec name forces `errors="replace"` — an explicit choice always produces
something; replacement marks beat both refusal and silently ignoring the user.
Two refinements:

- Forcing `utf-8` on a BOM file routes through `utf-8-sig`, so the mark doesn't
  surface as a stray U+FEFF.
- An unknown codec name (config typo) logs a warning and falls back to
  detection rather than crashing the viewer.

## Binary sniff vs UTF-16/32

`looks_binary` (NUL byte in the first 1 KiB) is now BOM-aware via
`looks_binary_bytes`: UTF-16/32 text contains NULs *by construction*, so a
Unicode BOM exempts the data. This matters in two places — `_read_lines`'s
placeholder decision, and the `looks_binary` gate in `app.py` that decides
whether opening a file spends a viewer at all; without the exemption, a
BOM-tagged UTF-16 file could never reach the viewer.

BOM-less UTF-16 still reads as binary (nothing distinguishes it), which is why
an **explicit** encoding bypasses the sniff in `_read_lines`: the override
exists precisely for files the sniff gets wrong.

## Viewer integration

`TextViewer` keeps two fields: `forced_encoding` (the override; `None` = auto)
and `encoding` (the display label of what was actually used, shown in the
header's right info tag; empty on the error/binary placeholder). The state is
viewer-local and deliberately **not persisted** — a wrong detection is a
property of one file, not a preference like the rich/raw view mode (#217).

`_apply_encoding` (the picker's callback) sets the override and calls
`_reload_text`, which re-decodes and rebuilds everything derived from the
text: lines, highlight, `_max_line`, the wrap-layout cache (`_wrap_w = -1`);
it clears the selection and search chrome (their line/column coordinates
described the old text), and drops the cached rich widget so a rendered view
rebuilds from the re-decoded source (`_ensure_rich_widget` and `_read_source`
take the override too). Scroll position is kept, clamped.

The `change_encoding` binding (default `Shift-E`) follows the
established viewer-action pattern: it is a named action of the `text_viewer`
context, so it safely shares the key with the file list's `create_file` — the
two surfaces never apply at once, and neither can see the other's actions. A
config that predates the action falls back to the default the action declares in
`xefm/actions.py`, which is `Shift-E` rather than plain `e` because plain `e` is
`edit_file`, in the viewer too.

## Editing from the viewer

`edit_file` (plain `E`) works inside the text viewer too. The viewer doesn't
launch editors itself: `show_text_viewer` takes an `on_edit` callback and the
app passes `lambda path: self._edit_entries([path])` — `_edit_entries` being
the body extracted from `XeFMApp.edit_file` (#273), so the viewer gets the
full machinery: `FILE_ASSOCIATIONS['edit']` wins, `TEXT_EDITOR` via terminal
suspend/resume otherwise, local-file guards included. On return the viewer
calls `_reload_text` — a terminal editor ran synchronously, so its changes
appear immediately; a GUI editor returns at once and the reload is a no-op. A
viewer constructed without `on_edit` (tests) offers no edit action or chrome.

## Tests

- `test/test_text_encoding.py` — detection/decoding contract, pure bytes.
- `test/test_choice_dialog.py` — the generic picker: seeding, results, and
  the type-ahead model (prefix vs substring, timeout, backspace) on a fake
  clock.
- `test/test_text_viewer_encoding.py` — `_read_lines` with overrides, the
  viewer's `_apply_encoding` path, the encoding-row assembly, and the
  `edit_file` hook sharing `_reload_text`.
- `test/test_binary_file_handling.py` — the pre-existing sniff-before-decode
  regression tests, updated for the wider `_read_lines` return.
