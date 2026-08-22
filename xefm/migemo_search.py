"""Migemo matching for incremental search — romaji finds Japanese (#302).

Migemo expands a romaji query into a regex matching the Japanese it could
spell: ``kensaku`` becomes ``(検索|けんさく|…|kensaku)``, so isearch can find
Japanese names without switching to an IME. The design was worked out in
discussion #332; the load-bearing choices:

- **Engine: oguna's pymigemo** — pure Python with a BSD-3 dictionary bundled
  in the wheel, so the same artifact ships through PyPI, the dmg, and the
  Store with no native library, separate dictionary, or GPL entanglement.
- **Runtime patch, pinned.** pymigemo 0.0.1 cannot load its dictionary on
  LP64 platforms (macOS / Linux): the reader builds ``array.array('L')`` for
  a 32-bit on-disk format, and ``'L'`` is 8 bytes there. :class:`_Array32`
  swaps the ``array`` binding inside the dictionary module before the engine
  is constructed — inert on Windows (where ``'L'`` is 4 bytes) and once
  upstream reads ``'I'`` itself. The dependency stays pinned to 0.0.1 so a
  new upstream release can't silently move the internals the patch touches.
- **Always on, no mode.** The generated regex keeps the typed romaji as one
  of its alternatives, so it never *loses* matches plain search would find
  (cfiler's mixed-case activation heuristic taught otherwise — cfiler#9).
  Callers still keep their native matching and union Migemo on top, so an
  engine quirk can only ever add matches, never remove them.
- **A minimum-length gate instead of a mode.** Regex generation for 1–2 char
  queries can take seconds (measured: 2s for ``c``) while 3+ chars sits at
  ~5ms — and two romaji chars are barely one kana, so nothing useful is
  gated away. ``MIGEMO_MIN_LENGTH``, default 3.
- **Globs bypass Migemo.** A pattern containing ``* ? [`` keeps its exact
  fnmatch semantics; Migemo's regex would collide with them.
- **Everything degrades to plain matching.** Package missing, dictionary
  unreadable, an engine landmine (a lone ``s`` raises IndexError in its bit
  vector), a regex the stdlib rejects: the answer is always ``None`` /
  ``False`` and the caller's native match stands alone.

macOS serves NFD filenames while Migemo emits NFC kana, so membership tests
(:func:`search_nfc`, :func:`match`) normalize the haystack. Span extraction
(:func:`find_spans`) deliberately does not: normalization shifts character
offsets, and the spans index into the text as drawn.
"""

from __future__ import annotations

import array
import re
import unicodedata
from functools import lru_cache

from xefm.log_manager import getLogger

logger = getLogger("Migemo")

#: fnmatch metacharacters: a pattern using any of these keeps its glob
#: semantics and never reaches Migemo (#332 §3.2).
_GLOB_CHARS = ('*', '?', '[')

#: None: not tried yet. False: tried and unavailable (missing package, wrong
#: package under the ``migemo`` name, broken dictionary). Else the engine.
_engine = None


class _Array32:
    """Drop-in for the ``array`` module inside pymigemo's dictionary reader:
    typecode ``'L'`` (32-bit in the file format, but 64-bit on LP64 platforms)
    is served as the always-32-bit ``'I'``. Every other typecode passes
    through, so the patch is inert wherever the bug isn't."""

    @staticmethod
    def array(typecode, *args):
        if typecode == 'L' and array.array('L').itemsize != 4:
            typecode = 'I'
        return array.array(typecode, *args)


#: hiragana -> katakana, for str.translate: the blocks are parallel
#: (ぁ..ゖ at U+3041 -> ァ..ヶ at U+30A1), plus the iteration marks ゝゞ.
_HIRA2KATA = {c: c + 0x60 for c in range(0x3041, 0x3097)}
_HIRA2KATA.update({0x309D: 0x30FD, 0x309E: 0x30FE})


def _config():
    """The live config, or ``None`` (early startup, tests) — the gates in
    :func:`get_regex` then fall back to their defaults."""
    try:
        from xefm.config import get_config
        return get_config()
    except Exception:
        return None


def _load_engine():
    """Import, patch, and construct the pymigemo engine on first use — the
    ~50ms dictionary read happens on the first gated query, not at startup.
    Failure is cached as ``False``: one warning, then permanent silence."""
    global _engine
    if _engine is None:
        try:
            # pymigemo imports as plain ``migemo`` — the same name atzm's
            # C/Migemo binding claims. Reaching for the pure-Python dictionary
            # module first doubles as the identity check: on any other package
            # this import raises and Migemo simply stays off.
            from migemo import migemocompactdictionary as _dict_module
            _dict_module.array = _Array32
            import migemo
            _engine = migemo.Migemo()
            logger.info("Migemo dictionary loaded")
        except Exception as e:
            logger.warning(f"Migemo unavailable ({type(e).__name__}: {e}); "
                           "incremental search uses plain matching only")
            _engine = False
    return _engine if _engine else None


def _word_expansion(engine, word: str) -> str:
    """pymigemo's regex for one lowercased word, plus the katakana it
    forgets: C/Migemo unions hiragana->katakana (and half-width katakana)
    forms into every expansion, while pymigemo 0.0.1 stops at hiragana — so
    romaji could never find ダウンロード, nor typed hiragana find ケンサク.
    Each hiragana reading (the word's predictive romaji conversions, and the
    word itself when it is hiragana) comes back as its katakana and
    half-width-katakana literals, longest first so a span covers the whole
    hit rather than a shorter alternative's prefix."""
    base = engine.query(word)
    forms = set()
    try:
        from migemo import characterconverter, romajiconverter
        readings = list(
            romajiconverter.convert_romaji_to_hiragana_predictively(word))
        readings.append(word)
        for hira in readings:
            kata = hira.translate(_HIRA2KATA)
            if kata == hira:
                continue
            forms.add(kata)
            han = characterconverter.zen2han(kata)
            if han != kata:
                forms.add(han)
    except Exception as e:
        # The base expansion still stands; only the katakana forms are lost.
        logger.warning(f"Migemo katakana forms failed for {word!r} "
                       f"({type(e).__name__}: {e})")
    if not forms:
        return base
    alts = ([base] if base else []) + [
        re.escape(f) for f in sorted(forms, key=lambda s: (-len(s), s))]
    return '(?:' + '|'.join(alts) + ')'


@lru_cache(maxsize=256)
def _compiled(pattern: str, min_length: int) -> re.Pattern | None:
    """The compiled Migemo regex for ``pattern``, or ``None``. Cached per
    (pattern, gate): generation is the expensive step; matching with the
    result is cheap (#332 §3.3).

    The pattern is split into words with pymigemo's own parser (camel case
    and whitespace are word breaks) but each word is expanded *lowercased*,
    unlike pymigemo's built-in query: its romaji conversion is case-sensitive,
    so ``Mudai`` would expand without 無題 (the cfiler#9 confusion) and an
    all-caps word can expand to a degenerate alternative (``KENSAKU`` ->
    ``(ＫＥＮＳＡＫＵ|KE)``) that, under IGNORECASE, floods the result with
    every name containing "ke". Words shorter than the gate stay escaped
    literals — expanding 1-2 char words is the seconds-slow path, and inside
    a camel pattern (``abC``) they'd dodge the whole-pattern gate.
    ``IGNORECASE`` keeps the regex as forgiving as the callers' lowercased
    native matching."""
    engine = _load_engine()
    if engine is None:
        return None
    try:
        words = engine.parse_query(pattern)
        expansion = ''.join(
            _word_expansion(engine, w.lower()) if len(w) >= min_length
            else re.escape(w)
            for w in words
        )
        if not expansion:
            # e.g. an all-whitespace pattern: re.compile('') matches
            # everything, which would light up every row.
            return None
        return re.compile(expansion, re.IGNORECASE)
    except Exception as e:
        logger.warning(f"Migemo query failed for {pattern!r} "
                       f"({type(e).__name__}: {e}); matching it plainly")
        return None


def get_regex(pattern: str) -> re.Pattern | None:
    """The Migemo regex for one search pattern, or ``None`` when Migemo does
    not apply: disabled by config, shorter than the length gate, a glob, or
    the engine failed. Callers union a non-``None`` regex with their native
    matching — never replace it."""
    if not pattern:
        return None
    config = _config()
    if not getattr(config, 'MIGEMO_SEARCH', True):
        return None
    min_length = getattr(config, 'MIGEMO_MIN_LENGTH', 3)
    if len(pattern) < min_length:
        return None
    if any(c in pattern for c in _GLOB_CHARS):
        return None
    return _compiled(pattern, min_length)


def has_hit(regex: re.Pattern, text: str) -> bool:
    """Whether ``regex`` (from :func:`get_regex`) adds a match anywhere in the
    raw ``text``. A hit only counts when the matched span contains a non-ASCII
    character: ASCII hits are already every caller's native matching (the
    regex keeps the typed romaji as an alternative), and pymigemo's expansion
    of an ASCII word can be buggy-broad (``x25`` -> ``(ｘ２５|x2)``, which
    would make ``x25`` "match" ``x24``) — so an ASCII-only hit is at best
    redundant and at worst wrong. For viewer lines, whose offsets elsewhere
    index the raw text; filenames go through :func:`search_nfc`."""
    try:
        return any(m.end() > m.start() and not m.group().isascii()
                   for m in regex.finditer(text))
    except Exception:
        return False


def search_nfc(regex: re.Pattern, text: str) -> bool:
    """:func:`has_hit` against ``text``'s NFC form — macOS serves NFD
    filenames while Migemo emits NFC kana/kanji. For membership tests
    (row-level highlights), where character offsets don't matter."""
    try:
        return has_hit(regex, unicodedata.normalize('NFC', text))
    except Exception:
        return False


def match(pattern: str, text: str) -> bool:
    """One-shot union helper: ``True`` only when Migemo applies to ``pattern``
    and its regex hits ``text`` (NFC). ``False`` means "no *extra* match" —
    the caller's native matching still stands on its own."""
    regex = get_regex(pattern)
    return regex is not None and search_nfc(regex, text)


def find_spans(pattern: str, text: str) -> list[tuple[int, int]] | None:
    """``(start, end)`` character spans of every Migemo hit in ``text``, for
    span-level highlight drawing — or ``None`` when Migemo doesn't apply to
    ``pattern`` (the caller draws its literal occurrences only). Only spans
    containing a non-ASCII character count, same as :func:`has_hit` — the
    caller's own literal pass draws the ASCII occurrences. Matches the *raw*
    text: NFC-normalizing would shift the offsets the spans index into, so a
    decomposed haystack (rare inside file content) is missed here by design.
    Also the ``search_matcher`` PuiKit's rich viewers accept."""
    regex = get_regex(pattern)
    if regex is None:
        return None
    try:
        return [m.span() for m in regex.finditer(text)
                if m.end() > m.start() and not m.group().isascii()]
    except Exception:
        return None
