# Migemo Search Feature

## Overview

Migemo lets incremental search find Japanese names by typing romaji — no IME
needed. Typing `kensaku` also matches `検索`, `けんさく`, `ケンサク`, `ｹﾝｻｸ`,
and `ｋｅｎｓａｋｕ`; typing `mudai` finds `無題.png`, and `daunro-do` finds
`ダウンロード` (typed hiragana finds katakana too). It is on by default and
needs no mode or switch: plain matching always still applies, Migemo only
ever *adds* matches.

## Where it works

Migemo applies to every incremental-search surface:

- **File pane incremental search** (`F`) — each space-separated token matches
  by substring *or* by Migemo, so `tenki yohou` finds `天気予報.csv`.
- **Text viewer search** (`F` inside the viewer) — matching lines are
  highlighted, including the Japanese text a romaji pattern matched.
- **Diff viewer search** — both sides of every row.
- **Rich view modes** (Markdown / JSON / CSV) — the embedded renderer's search
  uses the same matcher.
- **Filter-list dialogs** — favorites, history, drives, external programs:
  typing romaji in the filter field finds Japanese labels.

## How patterns behave

- **Plain patterns** (`kensaku`, `TenkiYohou`, `KENSAKU`) match by substring
  and by Migemo. Capitalization doesn't matter; camel case splits words, so
  `TenkiYohou` finds `天気予報`.
- **Glob patterns** — anything containing `*`, `?`, or `[` — keep their exact
  wildcard behavior and skip Migemo entirely. `*.py` matches only `.py` files.
- **Short patterns** (fewer than 3 characters by default) match by substring
  only. Two romaji characters are barely one kana, and expanding them is
  slow, so Migemo waits for the third character.
- Filenames macOS stores in decomposed form (NFD) match correctly.

## Configuration

```python
# In ~/.xefm/config.py
MIGEMO_SEARCH = True   # Add Migemo (romaji -> Japanese) matches to incremental search
MIGEMO_MIN_LENGTH = 3  # Shortest pattern handed to Migemo
```

Set `MIGEMO_SEARCH = False` to turn the feature off — searches then behave
exactly as before. Raise or lower `MIGEMO_MIN_LENGTH` to move the point where
Migemo kicks in (1 sends even single characters through Migemo; expect a
noticeable pause on the first keystroke).

## Requirements

Migemo uses the `pymigemo` package, installed automatically with XeFM (its
dictionary is bundled — about 1.4 MB, loaded lazily on first use). If the
package is missing, searches quietly fall back to plain matching; nothing
breaks.
