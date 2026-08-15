"""Encoding detection and decoding (issue #289): xefm.text_encoding.

The old decode loop was ``utf-8 → latin-1 → cp1252`` — and latin-1 never
fails, so every Shift-JIS / EUC-JP / ISO-2022-JP file "succeeded" as mojibake.
These tests pin the detector's contract: BOMs win outright, the Japanese
encodings round-trip, CP932 vs EUC-JP is decided by content (both often
strict-decode the same bytes), and the tail still displays anything.

Run with: python -m pytest test/test_text_encoding.py -v
"""

import codecs

import pytest

from xefm.text_encoding import (decode_text, encoding_label, looks_binary_bytes,
                                picker_encodings)

JP = "こんにちは、世界。カタカナも漢字も混ざった日本語の文章です。"


class TestAutoDetection:
    def test_ascii_reads_as_utf8(self):
        assert decode_text(b"plain ascii\n") == ("plain ascii\n", "UTF-8")

    def test_utf8_without_bom(self):
        text, label = decode_text(JP.encode("utf-8"))
        assert (text, label) == (JP, "UTF-8")

    def test_utf8_with_bom_strips_the_bom(self):
        text, label = decode_text(codecs.BOM_UTF8 + JP.encode("utf-8"))
        assert text == JP, "the BOM must not surface as U+FEFF"
        assert label == "UTF-8 BOM"

    @pytest.mark.parametrize("bom,codec,label", [
        (codecs.BOM_UTF16_LE, "utf-16-le", "UTF-16 LE"),
        (codecs.BOM_UTF16_BE, "utf-16-be", "UTF-16 BE"),
        (codecs.BOM_UTF32_LE, "utf-32-le", "UTF-32 LE"),
        (codecs.BOM_UTF32_BE, "utf-32-be", "UTF-32 BE"),
    ])
    def test_utf16_and_utf32_by_bom(self, bom, codec, label):
        text, got = decode_text(bom + JP.encode(codec))
        assert (text, got) == (JP, label)

    def test_cp932_japanese(self):
        text, label = decode_text(JP.encode("cp932"))
        assert (text, label) == (JP, "Shift-JIS")

    def test_euc_jp_japanese(self):
        text, label = decode_text(JP.encode("euc_jp"))
        assert (text, label) == (JP, "EUC-JP")

    def test_iso2022_jp_japanese(self):
        text, label = decode_text(JP.encode("iso2022_jp"))
        assert (text, label) == (JP, "ISO-2022-JP")

    def test_halfwidth_katakana_cp932(self):
        """Half-width katakana is the classic CP932-vs-EUC-JP trap: as single
        bytes 0xA1–0xDF it is exactly what a *misread* EUC-JP file also decodes
        to. A genuine half-width CP932 file must still come back correct."""
        text = "ﾃｽﾄ ﾌｧｲﾙ desu"
        got, label = decode_text(text.encode("cp932"))
        assert (got, label) == (text, "Shift-JIS")

    def test_cp1252_western(self):
        text, label = decode_text("café — “quoted”".encode("cp1252"))
        assert text == "café — “quoted”"
        assert label == "CP1252"

    def test_latin1_is_the_never_fails_tail(self):
        # 0x81 followed by a space: an invalid CP932/EUC-JP sequence (space is
        # not a trail byte), undefined in CP1252, invalid UTF-8 — only the
        # latin-1 tail can represent it.
        text, label = decode_text(b"x\x81 y")
        assert label == "Latin-1"
        assert text == "x\x81 y"

    def test_empty_bytes(self):
        assert decode_text(b"") == ("", "UTF-8")


class TestForcedEncoding:
    def test_forced_codec_is_used_verbatim(self):
        data = JP.encode("cp932")
        text, label = decode_text(data, "cp932")
        assert (text, label) == (JP, "Shift-JIS")

    def test_forcing_the_wrong_codec_replaces_not_raises(self):
        """An explicit choice always produces something — replacement marks,
        not an exception and not a silent fallback to detection."""
        data = JP.encode("cp932")
        text, label = decode_text(data, "euc-jp")
        assert label == "EUC-JP"
        assert text != JP

    def test_forced_utf8_still_strips_a_bom(self):
        text, label = decode_text(codecs.BOM_UTF8 + "abc".encode(), "utf-8")
        assert text == "abc"
        assert label == "UTF-8 BOM"

    def test_unknown_codec_name_falls_back_to_detection(self):
        text, label = decode_text(JP.encode("cp932"), "not-a-codec")
        assert (text, label) == (JP, "Shift-JIS")


class TestLooksBinaryBytes:
    def test_nul_byte_means_binary(self):
        assert looks_binary_bytes(b"abc\x00def")

    def test_utf16_bom_exempts_its_nul_bytes(self):
        assert not looks_binary_bytes("text".encode("utf-16"))

    def test_utf32_bom_exempts_its_nul_bytes(self):
        # UTF-32 BE's BOM itself *starts* with NUL bytes.
        assert not looks_binary_bytes(codecs.BOM_UTF32_BE + "text".encode("utf-32-be"))

    def test_plain_text_is_not_binary(self):
        assert not looks_binary_bytes(JP.encode("euc_jp"))


class TestPickerEncodings:
    def test_valid_names_pass_through_in_order(self):
        names = ["utf-8", "cp932", "euc-jp"]
        assert picker_encodings(names) == names

    def test_unknown_names_are_dropped_not_raised(self):
        assert picker_encodings(["utf-8", "not-a-codec", "cp932"]) == ["utf-8", "cp932"]

    def test_duplicates_collapse_by_canonical_name(self):
        assert picker_encodings(["utf-8", "utf8", "UTF-8"]) == ["utf-8"]

    def test_none_and_empty_are_empty(self):
        assert picker_encodings(None) == []
        assert picker_encodings([]) == []


class TestEncodingLabel:
    @pytest.mark.parametrize("name,label", [
        ("utf-8", "UTF-8"), ("utf8", "UTF-8"), ("cp932", "Shift-JIS"),
        ("shift-jis", "Shift-JIS"), ("euc-jp", "EUC-JP"),
        ("iso-2022-jp", "ISO-2022-JP"), ("latin-1", "Latin-1"),
        ("cp1252", "CP1252"),
    ])
    def test_known_codecs_get_canonical_labels(self, name, label):
        assert encoding_label(name) == label

    def test_unlisted_codec_shows_as_written(self):
        assert encoding_label("koi8-r") == "koi8-r"

    def test_unknown_codec_shows_as_written(self):
        assert encoding_label("not-a-codec") == "not-a-codec"
