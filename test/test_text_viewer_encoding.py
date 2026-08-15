"""The text viewer's encoding handling (issue #289): detection feeding the
viewer, the manual override path (``_apply_encoding``), the picker's row
model, and the in-viewer ``edit_file`` hook that shares the reload path.
Headless — the viewer is constructed directly; nothing here needs a backend.
(The generic picker dialog itself is covered in ``test_choice_dialog.py``.)

Run with: python -m pytest test/test_text_viewer_encoding.py -v
"""

import codecs

import pytest

from xefm.path import Path
from xefm.text_encoding import AUTO_ENCODING
from xefm.text_viewer import TextViewer, _encoding_rows, _read_lines

JP = "こんにちは、世界。"
#: ASCII mixed in on purpose: its UTF-16 code units have NUL high bytes, which
#: is what makes BOM-less UTF-16 trip the binary sniff.
MIXED = "hello, 世界"


@pytest.fixture
def tmp_file(tmp_path):
    def make(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return Path(str(p))
    return make


class TestReadLinesEncoding:
    def test_cp932_reads_correctly(self, tmp_file):
        lines, is_error, label = _read_lines(tmp_file("a.txt", JP.encode("cp932")))
        assert (lines, is_error, label) == ([JP], False, "Shift-JIS")

    def test_utf8_bom_is_stripped(self, tmp_file):
        f = tmp_file("a.txt", codecs.BOM_UTF8 + "abc\ndef".encode())
        lines, _, label = _read_lines(f)
        assert lines == ["abc", "def"]
        assert label == "UTF-8 BOM"

    def test_utf16_with_bom_is_text_not_binary(self, tmp_file):
        """The NUL-byte binary sniff must not eat BOM-tagged UTF-16."""
        lines, is_error, label = _read_lines(tmp_file("a.txt", JP.encode("utf-16")))
        assert (lines, is_error) == ([JP], False)
        assert label.startswith("UTF-16")

    def test_forced_encoding_overrides_detection(self, tmp_file):
        f = tmp_file("a.txt", JP.encode("cp932"))
        lines, _, label = _read_lines(f, "latin-1")
        assert label == "Latin-1"
        assert lines != [JP]

    def test_forced_encoding_bypasses_the_binary_sniff(self, tmp_file):
        """The override exists for a file the sniff got wrong — BOM-less
        UTF-16 being the canonical case: any ASCII character's high byte is a
        NUL, so the sniff calls the file binary."""
        f = tmp_file("a.txt", MIXED.encode("utf-16-le"))  # LE codec emits no BOM
        auto_lines, auto_error, _ = _read_lines(f)
        assert auto_error is True, "sanity: auto still judges this binary"
        lines, is_error, label = _read_lines(f, "utf-16-le")
        assert (lines, is_error, label) == ([MIXED], False, "UTF-16 LE")


class TestViewerEncoding:
    def test_viewer_records_the_detected_encoding(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", JP.encode("euc_jp")))
        assert viewer.encoding == "EUC-JP"
        assert viewer.forced_encoding is None
        assert viewer.lines == [JP]

    def test_apply_encoding_re_decodes(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", JP.encode("cp932")))
        viewer._apply_encoding("latin-1")
        assert viewer.forced_encoding == "latin-1"
        assert viewer.encoding == "Latin-1"
        assert viewer.lines != [JP]
        assert viewer._max_line == max(len(l) for l in viewer.lines)

    def test_apply_encoding_auto_returns_to_detection(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", JP.encode("cp932")))
        viewer._apply_encoding("latin-1")
        viewer._apply_encoding(AUTO_ENCODING)
        assert viewer.forced_encoding is None
        assert (viewer.encoding, viewer.lines) == ("Shift-JIS", [JP])

    def test_apply_encoding_cancel_changes_nothing(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", JP.encode("cp932")))
        before = (viewer.forced_encoding, viewer.encoding, viewer.lines)
        viewer._apply_encoding(None)
        assert (viewer.forced_encoding, viewer.encoding, viewer.lines) == before

    def test_apply_encoding_rebuilds_highlight_and_drops_rich_cache(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", JP.encode("cp932")))
        viewer._rich_widget = object()  # stand-in for a cached rich renderer
        viewer._apply_encoding("latin-1")
        assert viewer._rich_widget is None
        assert len(viewer.highlighted) == len(viewer.lines)

    def test_forcing_an_encoding_on_a_binary_verdict_shows_text(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", MIXED.encode("utf-16-le")))
        assert viewer.is_error is True  # BOM-less UTF-16: sniffed as binary
        viewer._apply_encoding("utf-16-le")
        assert viewer.is_error is False
        assert viewer.lines == [MIXED]


class TestEncodingRows:
    ENCODINGS = ["utf-8", "cp932", "euc-jp"]

    def test_auto_row_is_first_and_names_the_detection(self):
        rows = _encoding_rows(self.ENCODINGS, "Shift-JIS")
        assert rows[0] == (AUTO_ENCODING, "Auto  (Shift-JIS)")
        assert [v for v, _ in rows[1:]] == self.ENCODINGS

    def test_auto_row_without_detection_is_plain(self):
        assert _encoding_rows(self.ENCODINGS, None)[0] == (AUTO_ENCODING, "Auto")

    def test_rows_show_display_labels(self):
        rows = _encoding_rows(self.ENCODINGS, None)
        assert [label for _, label in rows[1:]] == \
            ["UTF-8", "Shift-JIS", "EUC-JP"]


class TestViewerEdit:
    def test_edit_hands_the_viewed_path_to_the_launcher(self, tmp_file):
        f = tmp_file("a.txt", b"before")
        edited = []
        viewer = TextViewer(f, on_edit=edited.append)
        viewer._edit_file()
        assert edited == [f]

    def test_edit_reloads_the_changed_file(self, tmp_path):
        """A terminal editor runs synchronously through on_edit, so the reload
        right after it must show the edited content."""
        p = tmp_path / "a.txt"
        p.write_bytes(b"before")
        viewer = TextViewer(Path(str(p)),
                            on_edit=lambda _p: p.write_bytes(b"after\nlines"))
        viewer._edit_file()
        assert viewer.lines == ["after", "lines"]
        assert viewer._max_line == len("lines")

    def test_edit_reload_keeps_the_encoding_override(self, tmp_file):
        f = tmp_file("a.txt", JP.encode("cp932"))
        viewer = TextViewer(f, on_edit=lambda p: None)
        viewer._apply_encoding("cp932")
        viewer._edit_file()
        assert viewer.forced_encoding == "cp932"
        assert viewer.encoding == "Shift-JIS"

    def test_a_failing_launcher_is_survived(self, tmp_file):
        def boom(_path):
            raise RuntimeError("no editor")
        viewer = TextViewer(tmp_file("a.txt", b"text"), on_edit=boom)
        viewer._edit_file()  # logged, not raised
        assert viewer.lines == ["text"]

    def test_no_launcher_means_no_edit_chrome(self, tmp_file):
        viewer = TextViewer(tmp_file("a.txt", b"text"))
        assert viewer._edit_hint_segment() == ""
