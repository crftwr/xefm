"""Character-encoding detection and decoding for the text / diff viewers
(issue #289).

The viewers historically decoded with ``utf-8 → latin-1 → cp1252`` — and since
latin-1 maps all 256 byte values and never raises, everything non-UTF-8
"succeeded" as latin-1 mojibake: a Shift-JIS file displayed, it just displayed
wrong. This module replaces that loop with a real detector plus an explicit
override path:

- :func:`decode_text` — file bytes → ``(text, label)``, auto-detecting by
  default or forced to a named codec (the viewer's encoding picker).
- :func:`looks_binary_bytes` — the NUL-byte binary sniff, made BOM-aware here
  because UTF-16/32 text is *full* of NULs by construction.

Detection order (each step only fires when it is decisive):

1. **Unicode BOMs** — UTF-8 / UTF-16 / UTF-32, both endiannesses. A BOM is an
   explicit declaration, so it wins outright and later decode errors are
   replaced rather than failing over to a guess.
2. **ISO-2022-JP** — only when its escape sequences are present. It is pure
   7-bit, so it would also strict-decode as UTF-8; the escapes are the tell,
   which is why it is checked first.
3. **UTF-8** strict — multi-byte sequences validate strictly enough that other
   encodings essentially never pass by accident.
4. **CP932 vs EUC-JP** — many byte streams strict-decode "successfully" in
   *both* (EUC-JP kana read as CP932 come out as half-width katakana runs), so
   order alone cannot pick. Each successful decode is scored against Japanese
   Unicode ranges and the higher score wins; a tie falls to CP932 (the Windows
   default, where legacy Japanese files mostly come from).
5. **CP1252** strict, then **latin-1** — the never-fails tail that keeps "any
   file still displays".

Pure bytes → str; no UI, no Path — unit-testable standalone.
"""

from __future__ import annotations

import codecs

from xefm.log_manager import getLogger

logger = getLogger("TextEncoding")

#: The encoding picker's "return to automatic detection" choice value — a real
#: value (not ``None``) so a dialog's cancel stays distinguishable from it.
AUTO_ENCODING = "auto"

#: Unicode BOMs, longest-prefix first: UTF-32 LE's BOM starts with UTF-16 LE's,
#: so it must be tried before it. Each entry is (BOM bytes, codec for the rest
#: of the data, display label).
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le", "UTF-32 LE"),
    (codecs.BOM_UTF32_BE, "utf-32-be", "UTF-32 BE"),
    (codecs.BOM_UTF8, "utf-8", "UTF-8 BOM"),
    (codecs.BOM_UTF16_LE, "utf-16-le", "UTF-16 LE"),
    (codecs.BOM_UTF16_BE, "utf-16-be", "UTF-16 BE"),
)

#: Display label per *canonical* codec name (``codecs.lookup(...).name``), for
#: the well-known encodings; anything else a user configures shows under the
#: name they wrote. cp932 and shift_jis share a label — cp932 is Windows'
#: superset of Shift-JIS and the distinction means nothing to a viewer header.
_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 BOM",
    "utf-16-le": "UTF-16 LE",
    "utf-16-be": "UTF-16 BE",
    "utf-32-le": "UTF-32 LE",
    "utf-32-be": "UTF-32 BE",
    "cp932": "Shift-JIS",
    "shift_jis": "Shift-JIS",
    "euc_jp": "EUC-JP",
    "iso2022_jp": "ISO-2022-JP",
    "cp1252": "CP1252",
    "iso8859-1": "Latin-1",
}

#: Characters scored per candidate in the CP932/EUC-JP disambiguation — enough
#: to judge any real file, keeps a huge one cheap.
_SCORE_SAMPLE = 65536


def encoding_label(name: str) -> str:
    """Display label for codec ``name`` — the canonical spelling for the
    well-known ones, the given name as-is for anything else (including a name
    Python doesn't know, which the picker filters out separately)."""
    try:
        canonical = codecs.lookup(name).name
    except LookupError:
        return name
    return _LABELS.get(canonical, name)


def sniff_bom(data: bytes):
    """The ``(BOM bytes, codec, label)`` entry ``data`` opens with, or ``None``."""
    for entry in _BOMS:
        if data.startswith(entry[0]):
            return entry
    return None


def looks_binary_bytes(data: bytes, sample_size: int = 1024) -> bool:
    """Whether ``data`` holds binary content, judged by a NUL byte in its first
    ``sample_size`` bytes — unless it opens with a Unicode BOM: UTF-16/32 text
    contains NULs by construction, and the BOM already names it text."""
    if sniff_bom(data) is not None:
        return False
    return b"\x00" in data[:sample_size]


def _jp_score(text: str) -> int:
    """How strongly ``text`` reads as Japanese: +2 for kana and kanji, +1 for
    CJK punctuation and full/half-width forms, -2 for private-use and
    replacement characters (misdecode smell).

    This is what disambiguates CP932 from EUC-JP when both strict-decode the
    same bytes: EUC-JP kana misread as CP932 come out as half-width katakana
    (+1) where the correct decode yields kana (+2), and CP932 misread as
    EUC-JP mostly fails strictly (CP932 lead bytes 0x81–0x9F are invalid EUC-JP
    leads), so strictness itself covers that direction."""
    score = 0
    for ch in text[:_SCORE_SAMPLE]:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF:
            score += 2      # hiragana / katakana / kanji
        elif 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
            score += 1      # CJK punctuation, full/half-width forms
        elif 0xE000 <= o <= 0xF8FF or o == 0xFFFD:
            score -= 2      # private use / replacement — a misdecode's residue
    return score


def decode_text(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    """Decode file bytes to text, returning ``(text, label)`` — the label names
    the encoding actually used (the viewer shows it in its header).

    ``encoding=None`` auto-detects per the module docstring. A named
    ``encoding`` forces that codec with ``errors="replace"`` — an explicit
    choice always produces *something*, replacement marks beating a refusal —
    except that a UTF-8 BOM still routes through ``utf-8-sig``, so forcing
    UTF-8 on a BOM file doesn't surface the mark as a stray U+FEFF. An unknown
    codec name (a config typo) logs a warning and falls back to detection."""
    if encoding is not None:
        try:
            canonical = codecs.lookup(encoding).name
        except LookupError:
            logger.warning(f"Unknown encoding {encoding!r}; auto-detecting instead")
        else:
            if canonical == "utf-8" and data.startswith(codecs.BOM_UTF8):
                return data.decode("utf-8-sig", errors="replace"), "UTF-8 BOM"
            return data.decode(encoding, errors="replace"), encoding_label(encoding)

    bom = sniff_bom(data)
    if bom is not None:
        bom_bytes, codec, label = bom
        return data[len(bom_bytes):].decode(codec, errors="replace"), label
    if b"\x1b$" in data or b"\x1b(" in data:
        try:
            return data.decode("iso2022_jp"), "ISO-2022-JP"
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    best = None
    for codec, label in (("cp932", "Shift-JIS"), ("euc_jp", "EUC-JP")):
        try:
            text = data.decode(codec)
        except UnicodeDecodeError:
            continue
        score = _jp_score(text)
        # Strictly greater: on a tie the first candidate (CP932) is kept.
        if best is None or score > best[0]:
            best = (score, text, label)
    # Positive only — a Western single-byte file can strict-decode as CP932 by
    # coincidence, but its "Japanese" then scores ~0; don't let it shadow the
    # CP1252 attempt below.
    if best is not None and best[0] > 0:
        return best[1], best[2]
    try:
        return data.decode("cp1252"), "CP1252"
    except UnicodeDecodeError:
        pass
    return data.decode("latin-1"), "Latin-1"


def picker_encodings(names) -> list[str]:
    """``Config.TEXT_ENCODINGS`` filtered for the encoding picker: unknown
    codec names are logged and dropped (a config typo shouldn't crash the
    dialog), duplicates collapse by canonical name, order is preserved."""
    out: list[str] = []
    seen: set[str] = set()
    for name in names or ():
        try:
            canonical = codecs.lookup(str(name)).name
        except LookupError:
            logger.warning(f"TEXT_ENCODINGS: unknown encoding {name!r} ignored")
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(str(name))
    return out
