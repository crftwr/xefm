"""Migemo matching in incremental search (xefm.migemo_search, discussion #332).

Covers the engine loader (the LP64 runtime patch), the activation gates
(length, globs, config), the union semantics ("Migemo only ever adds
matches"), NFC/NFD handling, and the isearch / filter-list integration.
Engine-dependent tests skip when pymigemo isn't installed.

Run with: python -m pytest test/test_migemo_search.py -v
"""

import os
import sys
import unicodedata
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import migemo_search
from xefm import romaji_azik
from xefm.file_list_manager import FileListManager
from xefm.filter_list_dialog import FilterListDialog

HAS_MIGEMO = migemo_search._load_engine() is not None
needs_migemo = pytest.mark.skipif(not HAS_MIGEMO, reason="pymigemo not installed")


@pytest.fixture(autouse=True)
def migemo_config(monkeypatch):
    """Pin the gates to their defaults, independent of ~/.xefm/config.py. Tests
    that vary them mutate the returned namespace."""
    cfg = SimpleNamespace(MIGEMO_SEARCH=True, MIGEMO_MIN_LENGTH=3,
                          MIGEMO_ROMAJI_TABLE="default")
    monkeypatch.setattr(migemo_search, "_config", lambda: cfg)
    return cfg


class FakePath:
    def __init__(self, name):
        self.name = name


NAMES = [
    "検索結果.txt",     # kensaku kekka
    "kensaku_notes.md",
    "無題.png",         # mudai (the cfiler#9 file)
    unicodedata.normalize("NFD", "がっこう.txt"),  # gakkou, decomposed like macOS
    "readme.py",
    "天気予報.csv",     # tenki yohou
    "keyboard.txt",
]


@pytest.fixture
def flm():
    return FileListManager(SimpleNamespace(SHOW_HIDDEN_FILES=True))


@pytest.fixture
def pane():
    return {"files": [FakePath(n) for n in NAMES]}


def isearch(flm, pane, pattern):
    """The names the file-pane isearch would highlight for ``pattern``."""
    idx = flm.find_matches(pane, pattern, match_all=True, return_indices_only=True)
    return [NAMES[i] for i in idx]


# --- gates (no engine required: every gate answers None before loading) ------


def test_short_pattern_is_gated(migemo_config):
    assert migemo_search.get_regex("ke") is None
    assert migemo_search.get_regex("a") is None
    assert migemo_search.get_regex("") is None


def test_glob_patterns_are_gated():
    for pat in ("*.py", "ken*", "a?cdef", "ni[ho"):
        assert migemo_search.get_regex(pat) is None


def test_disabled_by_config(migemo_config):
    migemo_config.MIGEMO_SEARCH = False
    assert migemo_search.get_regex("kensaku") is None


def test_min_length_from_config(migemo_config):
    migemo_config.MIGEMO_MIN_LENGTH = 8
    assert migemo_search.get_regex("kensaku") is None  # 7 chars


def test_gated_helpers_answer_no_extra_match():
    assert migemo_search.match("ke", "検索") is False
    assert migemo_search.find_spans("ke", "検索") is None


@needs_migemo
def test_whitespace_pattern_never_matches_everything():
    # An all-whitespace pattern expands to nothing; without the guard the
    # empty regex would light up every row.
    assert migemo_search.get_regex("   ") is None


# --- engine + expansion ------------------------------------------------------


@needs_migemo
def test_engine_loads_via_runtime_patch():
    # On LP64 platforms (macOS/Linux) this only passes because _Array32
    # replaced the dictionary reader's 'L' arrays; on Windows it exercises
    # the patch being inert.
    regex = migemo_search.get_regex("kensaku")
    assert regex is not None
    assert regex.search("検索")


@needs_migemo
def test_romaji_matches_kanji():
    assert migemo_search.match("kensaku", "検索結果.txt")
    assert migemo_search.match("mudai", "無題.png")
    assert not migemo_search.match("kensaku", "無題.png")


@needs_migemo
def test_capitalization_reaches_the_same_expansion():
    # pymigemo's own query() drops the Japanese expansion for capitalized
    # words (romaji conversion is case-sensitive) — the per-word lowercased
    # expansion restores it. 'Mudai' is cfiler#9's confusion, inverted.
    assert migemo_search.match("Mudai", "無題.png")
    assert migemo_search.match("KENSAKU", "検索結果.txt")
    assert migemo_search.match("TenkiYohou", "天気予報.csv")


@needs_migemo
def test_mixed_case_word_is_not_only_a_camel_split():
    # 'Sa-bisu' camel-splits into ['Sa', '-bisu'], whose literal 'Sa' no
    # Japanese text contains — the whole-pattern-lowercased reading is
    # unioned in, so a word typed with capitals still finds its katakana.
    assert migemo_search.match("Sa-bisu", "サービス")
    assert migemo_search.match("SA-BISU", "サービス")
    assert migemo_search.match("Sa-Bisu", "サービス")
    # The camel reading itself must survive the union.
    assert migemo_search.match("TenkiYohou", "天気予報.csv")


@needs_migemo
def test_uppercase_does_not_flood_match():
    # pymigemo expands 'KENSAKU' to '(ＫＥＮＳＡＫＵ|KE)'; under IGNORECASE
    # that would match every name containing "ke". The lowercased per-word
    # expansion must not inherit that.
    assert not migemo_search.match("KENSAKU", "keyboard.txt")


@needs_migemo
def test_nfd_haystack_matches():
    nfd = unicodedata.normalize("NFD", "がっこう.txt")
    regex = migemo_search.get_regex("gakkou")
    assert migemo_search.search_nfc(regex, nfd)


@needs_migemo
def test_romaji_matches_katakana():
    # pymigemo 0.0.1 expands to hiragana but forgets the katakana forms
    # C/Migemo always adds — _word_expansion unions them back in.
    assert migemo_search.match("memo", "メモ.txt")
    assert migemo_search.match("kensaku", "ケンサク.md")
    assert migemo_search.match("daunro-do", "ダウンロード")


@needs_migemo
def test_romaji_matches_katakana_predictive_prefix():
    # Mid-typing: an incomplete word still matches as a katakana prefix.
    assert migemo_search.match("kensa", "ケンサク.md")


@needs_migemo
def test_hiragana_pattern_matches_katakana():
    assert migemo_search.match("けんさく", "ケンサク.md")


@needs_migemo
def test_romaji_matches_halfwidth_katakana():
    assert migemo_search.match("kensaku", "ｹﾝｻｸ.md")


@needs_migemo
def test_katakana_nfd_haystack():
    assert migemo_search.match(
        "daunro-do", unicodedata.normalize("NFD", "ダウンロード"))


@needs_migemo
def test_find_spans_cover_whole_katakana_hit():
    # Longest-first alternation: the span is the whole ケンサク, not a
    # shorter alternative's prefix.
    assert (0, 4) in migemo_search.find_spans("kensaku", "ケンサクの件")


@needs_migemo
def test_find_spans_on_raw_text():
    line = "今日は検索の日 kensaku day"
    spans = migemo_search.find_spans("kensaku", line)
    assert (3, 5) in spans        # 検索
    # The literal romaji at (8, 15) is NOT a Migemo span: ASCII occurrences
    # are the caller's own literal pass (see has_hit).
    assert (8, 15) not in spans
    assert migemo_search.find_spans("kensaku", "nothing here") == []


@needs_migemo
def test_ascii_only_hits_never_count():
    # pymigemo expands 'x25' to '(ｘ２５|x2)' — a truncated ASCII alternative
    # that would make 'x25' "match" x24. ASCII-only regex hits are discarded:
    # they are either covered by native matching or upstream bugs like this.
    assert not migemo_search.match("x25", "x24")
    assert not migemo_search.match("x25", "x25")   # native matching's job
    assert migemo_search.match("x25", "ｘ２５log")  # the full-width form still hits


@needs_migemo
def test_engine_landmines_are_absorbed():
    # pymigemo 0.0.1 has known IndexError paths (a lone 's' in its bit
    # vector); whatever a pattern triggers must come back as "no extra
    # match", never as an exception.
    for pat in ("sss", "s"):
        migemo_search.get_regex(pat)
        assert migemo_search.match(pat, "検索") in (True, False)


@needs_migemo
def test_camel_pattern_with_short_word_stays_fast():
    # A camel word under the gate ('C' in 'abC') must not reach the engine —
    # 1-char expansion is the seconds-slow path. It becomes a literal instead.
    regex = migemo_search.get_regex("abC")
    assert regex is not None


# --- file-pane isearch (FileListManager.find_matches) ------------------------


@needs_migemo
def test_isearch_union_romaji_and_substring(flm, pane):
    assert isearch(flm, pane, "kensaku") == ["検索結果.txt", "kensaku_notes.md"]
    assert isearch(flm, pane, "mudai") == ["無題.png"]
    assert isearch(flm, pane, "Mudai") == ["無題.png"]


@needs_migemo
def test_isearch_nfd_filename(flm, pane):
    # The match set carries the name as the filesystem serves it — still NFD.
    assert isearch(flm, pane, "gakkou") == [unicodedata.normalize("NFD", "がっこう.txt")]


@needs_migemo
def test_isearch_multi_token_and(flm, pane):
    assert isearch(flm, pane, "tenki yohou") == ["天気予報.csv"]
    assert isearch(flm, pane, "tenki nothere") == []


def test_isearch_glob_semantics_preserved(flm, pane):
    assert isearch(flm, pane, "*.py") == ["readme.py"]
    assert isearch(flm, pane, "*.txt") == [n for n in NAMES if n.endswith(".txt")]


def test_isearch_short_pattern_is_substring_only(flm, pane):
    assert isearch(flm, pane, "ke") == ["kensaku_notes.md", "keyboard.txt"]


def test_isearch_plain_matching_unchanged(flm, pane):
    assert isearch(flm, pane, "readme") == ["readme.py"]
    assert isearch(flm, pane, "zzz") == []


@needs_migemo
def test_isearch_or_mode(flm, pane):
    idx = flm.find_matches(pane, "mudai readme", match_all=False,
                           return_indices_only=True)
    assert [NAMES[i] for i in idx] == ["無題.png", "readme.py"]


@needs_migemo
def test_isearch_disabled_config_is_plain(flm, pane, migemo_config):
    migemo_config.MIGEMO_SEARCH = False
    assert isearch(flm, pane, "kensaku") == ["kensaku_notes.md"]


# --- filter-list dialog (favorites / history / drives ...) -------------------


@needs_migemo
def test_filter_dialog_romaji_filters_japanese_labels():
    d = FilterListDialog(["検索結果.txt", "notes.md", "kensaku.log"])
    d._refilter("kensaku")
    assert d.filtered == ["検索結果.txt", "kensaku.log"]


@needs_migemo
def test_filter_dialog_streamed_rows_pass_migemo_filter():
    d = FilterListDialog(["検索結果.txt"],
                         load_more=lambda cancel: iter(["無題.png", "beta.txt"]))
    d.filter_edit.text = "mudai"
    d._refilter("mudai")
    d._start_load_more()
    assert d.filtered == ["無題.png"]
    assert d.all_items == ["検索結果.txt", "無題.png", "beta.txt"]


def test_filter_dialog_substring_unchanged():
    d = FilterListDialog(["apple", "banana", "apricot"])
    d._refilter("ap")
    assert d.filtered == ["apple", "apricot"]


# --- AZIK romaji table (#346) -----------------------------------------------


PLAIN = {"ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
         "sa": "さ", "si": "し", "su": "す", "se": "せ", "so": "そ",
         "sya": "しゃ", "syi": "しぃ", "syu": "しゅ", "sye": "しぇ", "syo": "しょ",
         "kya": "きゃ", "kyi": "きぃ", "kyu": "きゅ", "kye": "きぇ", "kyo": "きょ"}


def test_azik_table_is_generated_from_the_rules():
    table = romaji_azik.build(PLAIN)
    # 撥音拡張: the key under each vowel spells the kana plus ん, N covers あ段
    assert [table[k] for k in ("kz", "kn", "kk", "kj", "kd", "kl")] == \
        ["かん", "かん", "きん", "くん", "けん", "こん"]
    # 二重母音拡張
    assert [table[k] for k in ("kq", "kh", "kw", "kp")] == \
        ["かい", "くう", "けい", "こう"]
    # 拗音互換キー: G for Y, and the extensions apply to the third stroke too
    assert table["kga"] == "きゃ" and table["kgp"] == "きょう"
    # 互換キー and 特殊拡張
    assert table[";"] == "っ" and table["q"] == "ん"
    assert table["kt"] == "こと" and table["mn"] == "もの"


def test_azik_own_rows_win_over_the_plain_spelling():
    table = romaji_azik.build(PLAIN)
    assert table["xa"] == "しゃ" and table["xi"] == "し"   # plain: ぁ / ぃ
    assert table["ca"] == "ちゃ" and table["ci"] == "ち"   # plain: か / し
    assert table["cz"] == "ちゃん"


def test_azik_skips_rows_the_plain_table_cannot_spell():
    # PLAIN has no ta-row, so nothing is guessed for it.
    table = romaji_azik.build(PLAIN)
    assert "tz" not in table and "ta" not in table


@needs_migemo
def test_azik_table_is_sorted_and_within_the_lookahead():
    keys, values = migemo_search._alternate_table("azik")
    assert keys == sorted(keys)          # the converter prefix-searches by bisect
    assert max(len(k) for k in keys) <= 4  # its lookahead window
    assert len(keys) == len(values)
    assert dict(zip(keys, values))["kz"] == "かん"


@needs_migemo
def test_unknown_table_falls_back_to_plain(migemo_config):
    migemo_config.MIGEMO_ROMAJI_TABLE = "nosuchtable"
    assert migemo_search._alternate_table("nosuchtable") is None
    assert migemo_search.match("kensaku", "検索")   # plain expansion still stands


@needs_migemo
def test_azik_spellings_need_the_table(migemo_config):
    # けんさく as AZIK types it: KD spells けん.
    assert migemo_search.match("kdsaku", "検索結果.txt") is False
    migemo_config.MIGEMO_ROMAJI_TABLE = "azik"
    assert migemo_search.match("kdsaku", "検索結果.txt")
    assert migemo_search.match("kzxa", "感謝.txt")      # かんしゃ: KZ + XA
    assert migemo_search.match("cairo", "茶色.png")     # ちゃいろ: C is チャ行
    assert migemo_search.match("se;kw", "設計書.md")    # せっけい: ; is っ
    assert migemo_search.match("kthazime", "事始め.txt")  # KT is the 特殊拡張 こと


@needs_migemo
def test_azik_only_adds_matches(migemo_config):
    # CA is か in plain romaji and ちゃ in AZIK. Both readings must survive.
    assert migemo_search.match("camoku", "科目.txt")
    migemo_config.MIGEMO_ROMAJI_TABLE = "azik"
    assert migemo_search.match("camoku", "科目.txt")
    assert migemo_search.match("kensaku", "検索")
    assert migemo_search.match("mudai", "無題")


@needs_migemo
def test_table_choice_is_part_of_the_cache_key(migemo_config):
    # Config reloads at runtime, so a cached regex must not outlive its table.
    assert migemo_search.match("kdsaku", "検索結果.txt") is False
    migemo_config.MIGEMO_ROMAJI_TABLE = "azik"
    assert migemo_search.match("kdsaku", "検索結果.txt")
    migemo_config.MIGEMO_ROMAJI_TABLE = "default"
    assert migemo_search.match("kdsaku", "検索結果.txt") is False


@needs_migemo
def test_plain_table_is_restored_after_an_azik_expansion(migemo_config):
    from migemo import romajiconverter

    before = romajiconverter.ROMAJI_KEYS, romajiconverter.ROMAJI_VALUES
    migemo_config.MIGEMO_ROMAJI_TABLE = "azik"
    migemo_search.get_regex("kzsaku")
    assert (romajiconverter.ROMAJI_KEYS, romajiconverter.ROMAJI_VALUES) == before


@needs_migemo
def test_isearch_azik_pattern(flm, pane, migemo_config):
    migemo_config.MIGEMO_ROMAJI_TABLE = "azik"
    # てんき as AZIK types it: TD spells てん.
    assert isearch(flm, pane, "tdki") == ["天気予報.csv"]
    assert isearch(flm, pane, "kensaku") == ["検索結果.txt", "kensaku_notes.md"]
