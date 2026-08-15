"""Binary content detection in the text viewer.

Regression tests for a bug where the binary placeholder was unreachable:
``_read_lines`` decoded before sniffing, and its decode loop included latin-1,
which maps all 256 byte values and therefore never raises UnicodeDecodeError.
The "if nothing decoded" branch could not run, so a PNG opened as ~45,000 lines
of mojibake instead of one placeholder line.

The lesson these tests encode: **sniff before decoding**. Any test that only
checks "a text file reads correctly" would have passed throughout the bug.

Run with: python -m pytest test/test_binary_file_handling.py -v
"""

import pytest

from xefm.path import Path
from xefm.text_viewer import _read_lines, looks_binary

PLACEHOLDER = "[Binary file — cannot display as text]"

#: Real PNG header: signature + the start of the IHDR chunk, whose big-endian
#: length field supplies the NUL bytes that mark it as binary.
PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00"


@pytest.fixture
def tmp_file(tmp_path):
    def make(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return Path(str(p))
    return make


class TestLooksBinary:
    def test_nul_byte_means_binary(self, tmp_file):
        assert looks_binary(tmp_file("a.bin", b"abc\x00def"))

    def test_plain_text_is_not_binary(self, tmp_file):
        assert not looks_binary(tmp_file("a.txt", b"hello world\n"))

    def test_utf8_text_is_not_binary(self, tmp_file):
        assert not looks_binary(tmp_file("a.txt", "héllo — wörld\n".encode()))

    def test_empty_file_is_not_binary(self, tmp_file):
        assert not looks_binary(tmp_file("empty.txt", b""))

    def test_unreadable_file_is_not_reported_as_binary(self, tmp_path):
        """"Cannot read" is not "binary" — the caller's own error path gives a
        better message than a misleading binary verdict."""
        assert not looks_binary(Path(str(tmp_path / "does_not_exist")))

    def test_nul_beyond_the_sample_window_is_not_seen(self, tmp_file):
        # A bounded sniff is a deliberate tradeoff: cheap, and wrong only for
        # files that look textual for their first kilobyte.
        f = tmp_file("late.bin", b"a" * 4096 + b"\x00")
        assert not looks_binary(f, sample_size=1024)
        assert looks_binary(f, sample_size=8192)

    def test_extension_is_irrelevant(self, tmp_file):
        """Detection is by content, so a misleading name changes nothing."""
        assert looks_binary(tmp_file("innocent.txt", PNG_HEADER))
        assert not looks_binary(tmp_file("scary.png", b"actually just text"))


class TestReadLines:
    def test_binary_yields_one_placeholder_line(self, tmp_file):
        lines, is_error, _ = _read_lines(tmp_file("img.png", PNG_HEADER + b"\xff" * 900))
        assert lines == [PLACEHOLDER]
        assert is_error is True

    def test_binary_does_not_produce_mojibake(self, tmp_file):
        """The actual regression: latin-1 decoded the whole file successfully,
        so thousands of garbage lines reached the viewer."""
        data = PNG_HEADER + bytes(range(256)) * 200
        lines, _, _ = _read_lines(tmp_file("big.png", data))
        assert len(lines) == 1, f"expected a placeholder, got {len(lines)} lines"

    def test_text_still_reads_normally(self, tmp_file):
        lines, is_error, _ = _read_lines(tmp_file("a.txt", b"one\ntwo\nthree\n"))
        assert lines == ["one", "two", "three"]
        assert is_error is False

    def test_utf8_text_survives(self, tmp_file):
        lines, is_error, _ = _read_lines(tmp_file("a.txt", "héllo — wörld".encode()))
        assert lines == ["héllo — wörld"]
        assert is_error is False

    def test_latin1_fallback_still_works_for_non_utf8_text(self, tmp_file):
        """Western single-byte text still decodes (via CP1252, with latin-1 as
        the never-fails tail of the chain — see xefm.text_encoding); removing
        that fallback was never the fix. It just must not run first."""
        lines, is_error, _ = _read_lines(tmp_file("a.txt", b"caf\xe9 cr\xe8me"))
        assert is_error is False
        assert len(lines) == 1
        assert "caf" in lines[0]

    def test_empty_file_is_not_an_error(self, tmp_file):
        lines, is_error, _ = _read_lines(tmp_file("empty.txt", b""))
        assert is_error is False
        assert lines == []

    def test_missing_file_reports_an_error_not_a_placeholder(self, tmp_path):
        lines, is_error, _ = _read_lines(Path(str(tmp_path / "nope.txt")))
        assert is_error is True
        assert lines != [PLACEHOLDER]
        assert "Error reading file" in lines[0]
