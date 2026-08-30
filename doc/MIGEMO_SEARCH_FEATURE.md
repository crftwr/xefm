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
  the filter field takes the same query as the pane (space-separated tokens,
  wildcards), so typing romaji finds Japanese labels.

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

## AZIK

If you type Japanese with AZIK — the extended romaji scheme where a second
stroke below the vowel spells the kana plus "n" — set:

```python
MIGEMO_ROMAJI_TABLE = 'azik'
```

Search then also understands the spellings AZIK trained your fingers on:

| You type | You get | Rule |
|---|---|---|
| `kz` `kk` `kj` `kd` `kl` | かん きん くん けん こん | 撥音拡張 (`sn` さん on the あ段) |
| `kq` `kh` `kw` `kp` | かい くう けい こう | 二重母音拡張 |
| `xa` `ca` | しゃ ちゃ | シャ行・チャ行互換キー |
| `kga` `kgp` | きゃ きょう | 拗音のＹ互換キー |
| `;` `:` `q` | っ ー ん | |
| `kf` `nf` | き ぬ | 同指打鍵互換キー |
| `kt` `mn` `ds` | こと もの です | 特殊拡張 |

So `kdsaku` finds 検索, `kzxa` finds 感謝, and `se;kw` finds 設計.

AZIK is added *alongside* plain romaji, never in place of it: the handful of
keys the two spell differently (`ca` is か in plain romaji and ちゃ in AZIK)
match either reading, so turning this on cannot make a search you already use
stop working.

## Configuration

```python
# In ~/.xefm/config.py
MIGEMO_SEARCH = True   # Add Migemo (romaji -> Japanese) matches to incremental search
MIGEMO_MIN_LENGTH = 3  # Shortest pattern handed to Migemo
MIGEMO_ROMAJI_TABLE = 'default'  # 'default' or 'azik'
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
