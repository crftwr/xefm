"""The AZIK romaji table, generated from AZIK's own rules (#346).

AZIK, an 拡張ローマ字入力 (extended romaji input scheme), leaves standard
romaji's key assignments where they are and adds two-stroke spellings for the
readings Japanese repeats most:

- **撥音拡張** — the second stroke uses the key *below* the vowel, and the
  kana comes back with ん attached: ``ka`` is か, ``kz`` is かん (A->Z),
  ``kk`` きん (I->K), ``kj`` くん (U->J), ``kd`` けん (E->D), ``kl`` こん
  (O->L). ``N`` stands in for ``Z`` on the あ段 (``sn`` さん) — the 撥音互換キー.
- **二重母音拡張** — ``kq`` かい, ``kh`` くう, ``kw`` けい, ``kp`` こう.
- **互換キー** — ``X`` for シャ行 and ``C`` for チャ行 (``xa`` しゃ, ``ca`` ちゃ),
  ``G`` for the 拗音's ``Y`` (``kga`` きゃ), ``;`` for っ, ``:`` for ー, ``Q``
  for a lone ん, ``L`` before a small kana, and the 同指打鍵互換キー ``F``
  (``kf`` き, ``nf`` ぬ).
- **特殊拡張** — 27 hand-picked frequent readings (``kt`` こと, ``mn`` もの,
  ``ds`` です …) that are neither 撥音 nor 二重母音.

This module holds the *rules*, not a copied conversion table: the 400-odd
extension entries fall out of ten suffix keys applied to kana the plain romaji
table already spells, so :func:`build` reads its base kana from the engine's
own table and only writes out what AZIK genuinely reassigns. The kana therefore
stay identical to the engine's, and the ~90 lines here replace a 700-line data
file whose published copies carry no redistribution licence.

Spec: AZIK総合解説書 — http://www1.vecceed.ne.jp/~bemu/azik/azikinfo.htm

:func:`build` returns AZIK's entries alone; :mod:`xefm.migemo_search` overlays
them on the plain table and expands each query under both, so enabling AZIK
only ever adds matches.
"""

from __future__ import annotations

_VOWELS = 'aiueo'

#: Every first stroke that takes the 撥音/二重母音 suffixes. Two-letter entries
#: are the 拗音 and the 特殊な拗音 (``tg`` ティ, ``dc`` ディ, ``ws`` ウォ).
_PREFIXES = (
    'k', 's', 't', 'n', 'h', 'm', 'y', 'r', 'w', 'g', 'z', 'd', 'b', 'p',
    'ky', 'sy', 'ty', 'ny', 'hy', 'my', 'ry', 'gy', 'zy', 'dy', 'by', 'py',
    'kg', 'ng', 'hg', 'mg', 'pg', 'jg',
    'x', 'c', 'j', 'jy', 'tg', 'dc', 'f', 'v', 'fy', 'vy', 'ws',
)

#: Rows whose five kana the plain table already spells under another prefix:
#: the 拗音互換キー (``G`` for ``Y``), ``ZY``/``JG`` for じゃ行, and the 特殊な
#: 拗音 ``TG``/``DC``, which plain romaji types as ``TH``/``DH``.
_BORROWED = {
    'kg': 'ky', 'ng': 'ny', 'hg': 'hy', 'mg': 'my', 'pg': 'py',
    'jg': 'jy', 'zy': 'jy', 'tg': 'th', 'dc': 'dh',
}

#: Rows AZIK spells itself, as (a, i, u, e, o). ``X``/``C`` are the シャ行 /
#: チャ行 互換キー (and their second stroke ``i`` is the bare し / ち, not しぃ);
#: ``W`` types うぃ/うぇ where plain romaji keeps ゐ/ゑ; ``WS``/``DY`` have no
#: plain-table row to borrow from.
_OWN = {
    'x': ('しゃ', 'し', 'しゅ', 'しぇ', 'しょ'),
    'c': ('ちゃ', 'ち', 'ちゅ', 'ちぇ', 'ちょ'),
    'w': ('わ', 'うぃ', 'う', 'うぇ', 'を'),
    'ws': ('うぁ', 'うぃ', 'う', 'うぇ', 'うぉ'),
    'dy': ('ぢゃ', 'ぢぃ', 'ぢゅ', 'ぢぇ', 'ぢょ'),
}

#: (second stroke, which vowel of the row it spells, what it appends). The
#: first six are the 撥音拡張 — the key under each vowel, plus ``N`` for あ段 —
#: and the last four the 二重母音拡張.
_SUFFIXES = (
    ('z', 0, 'ん'), ('n', 0, 'ん'), ('k', 1, 'ん'), ('j', 2, 'ん'),
    ('d', 3, 'ん'), ('l', 4, 'ん'),
    ('q', 0, 'い'), ('h', 2, 'う'), ('w', 3, 'い'), ('p', 4, 'う'),
)

#: What the rules above don't produce, applied last so it wins over them
#: (``mn`` is もの, not まん; ``nn`` is ん, not なん).
_SPECIALS = {
    # 「ん」互換キー, and NN as everywhere else
    'q': 'ん', 'nn': 'ん',
    # っ is always ';' in AZIK; ー has ':' as its 長音互換キー
    ';': 'っ', ':': 'ー',
    # 特殊な拗音: L before a small kana
    'la': 'ぁ', 'li': 'ぃ', 'lu': 'ぅ', 'le': 'ぇ', 'lo': 'ぉ',
    'lya': 'ゃ', 'lyu': 'ゅ', 'lyo': 'ょ',
    'lga': 'ゃ', 'lgu': 'ゅ', 'lgo': 'ょ',
    'ltu': 'っ', 'lwa': 'ゎ',
    # readings only 外来語 have, spelled straight to the 長音記号
    'wp': 'うぉー', 'fp': 'ふぉー',
    # 同指打鍵互換キー F
    'kf': 'き', 'jf': 'じゅ', 'hf': 'ふ', 'yf': 'ゆ', 'mf': 'む',
    'nf': 'ぬ', 'df': 'で', 'cf': 'ちぇ', 'pf': 'ぽん',
    # patterns awkward even under the rules, given a key of their own
    'wf': 'わい', 'sf': 'さい', 'ss': 'せい',
    'zc': 'ざ', 'zv': 'ざい', 'zf': 'ぜ', 'zx': 'ぜい',
    # 特殊拡張
    'kt': 'こと', 'st': 'した', 'tt': 'たち', 'ht': 'ひと',
    'wt': 'わた', 'mn': 'もの', 'ms': 'ます', 'ds': 'です',
    'km': 'かも', 'tm': 'ため', 'dm': 'でも', 'kr': 'から',
    'sr': 'する', 'tr': 'たら', 'nr': 'なる', 'yr': 'よる',
    'rr': 'られ', 'zr': 'ざる', 'mt': 'また', 'tb': 'たび',
    'nb': 'ねば', 'bt': 'びと', 'gr': 'がら', 'gt': 'ごと',
    'nt': 'にち', 'dt': 'だち', 'wr': 'われ',
}


def build(plain: dict[str, str]) -> dict[str, str]:
    """AZIK's romaji -> hiragana entries, with ``plain`` (the engine's own
    romaji table, as a mapping) supplying the base kana every row is built
    from. A prefix the plain table cannot spell is skipped rather than
    guessed, so a future engine table can only ever make this smaller."""
    table: dict[str, str] = {}
    for prefix in _PREFIXES:
        row = _OWN.get(prefix)
        if row is None:
            source = _BORROWED.get(prefix, prefix)
            row = tuple(plain.get(source + vowel) for vowel in _VOWELS)
        for index, vowel in enumerate(_VOWELS):
            if row[index]:
                table[prefix + vowel] = row[index]
        for suffix, index, tail in _SUFFIXES:
            if row[index]:
                table[prefix + suffix] = row[index] + tail
    table.update(_SPECIALS)
    return table
