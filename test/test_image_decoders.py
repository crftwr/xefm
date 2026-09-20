"""Which image formats open, and who decodes each one (:mod:`xefm.image_decoders`).

The viewer used to claim one frozen list of extensions, chosen so that a file it
opened always showed a picture. These cover the arrangement that replaces it
while keeping that promise: the claim is *computed* from what the running machine
can actually decode — the backend's own decoder, Pillow with whatever plugins are
installed, and any decoder a config registered — and never from a list written
down in advance.

The half that matters most is the negative one. macOS's ImageIO reads PDFs and
DICOM; Pillow's registry has entries that need Ghostscript before they decode
anything. A claim list built by trusting either wholesale would open the viewer
onto its own "cannot show this" card, which is worse than never having claimed
the file — the file manager's other viewers never got a look at it.

Run with: python -m pytest test/test_image_decoders.py -v
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm import image_decoders  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm.image_viewer import is_image_file  # noqa: E402
from xefm.path import Path  # noqa: E402


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is process-wide; keep it out of every other test."""
    image_decoders.clear()
    image_decoders.set_native_suffixes(())
    yield
    image_decoders.clear()
    image_decoders.set_native_suffixes(())


def load(**table):
    cfg = types.SimpleNamespace(IMAGE_DECODERS=table)
    (warnings, _actions, _hooks, _sorts, _filters,
     count, _schemes) = user_api.load_user_entries(cfg)
    return warnings, count


def _raster(w=2, h=2):
    from puikit.image import RasterImage

    return RasterImage(w, h, b"\xff" * (w * h * 4))


# --------------------------------------------------------------------------- #
# Normalizing a suffix
# --------------------------------------------------------------------------- #

def test_every_spelling_of_a_suffix_is_the_same_suffix():
    for spelling in (".heic", "heic", ".HEIC", "HEIC", " .Heic "):
        assert image_decoders.normalize(spelling) == ".heic"


def test_a_file_with_no_extension_names_no_format():
    assert image_decoders.normalize("") == ""
    assert image_decoders.normalize(None) == ""


# --------------------------------------------------------------------------- #
# What is claimed
# --------------------------------------------------------------------------- #

def test_the_formats_pillow_reads_are_claimed():
    pytest.importorskip("PIL")
    claimed = image_decoders.claimed_suffixes()
    assert {".png", ".jpg", ".gif", ".bmp", ".webp", ".tif"} <= claimed


def test_the_new_formats_arrive_with_a_current_pillow():
    # The half of this change that needs nothing installed: Pillow bundles
    # libavif from 11.3 and openjpeg always, so AVIF and JPEG 2000 are readable
    # on a plain install and therefore claimed.
    Image = pytest.importorskip("PIL.Image")
    Image.init()
    readable = {e.lower() for e, f in Image.registered_extensions().items()
                if f in Image.OPEN}
    claimed = image_decoders.claimed_suffixes()
    for suffix in (".avif", ".jp2", ".psd", ".qoi", ".icns", ".dds", ".pcx"):
        if suffix in readable:
            assert suffix in claimed, suffix


def test_a_format_only_the_backend_reads_is_claimed_once_it_says_so():
    # HEIC on macOS: nothing here decodes it, ImageIO does, and the viewer has
    # to know that before it will offer the file.
    assert ".heic" not in image_decoders.claimed_suffixes()
    image_decoders.set_native_suffixes({".heic", ".heif"})
    assert {".heic", ".heif"} <= image_decoders.claimed_suffixes()


def test_a_backend_reading_a_format_does_not_make_it_a_picture():
    # The curation that keeps the claim honest in the other direction: ImageIO
    # reads PDFs and DICOM, and neither belongs in an image viewer.
    image_decoders.set_native_suffixes({".pdf", ".dcm", ".mov", ".heic"})
    claimed = image_decoders.claimed_suffixes()
    assert ".heic" in claimed
    assert not ({".pdf", ".dcm", ".mov"} & claimed)


def test_a_registered_decoder_is_claimed_whatever_the_curation_says():
    # Registering one *is* the statement that this format should open here, so
    # it outranks the candidate list — which is how DICOM, SVG and RAW arrive
    # without XeFM carrying pydicom, cairosvg or rawpy.
    image_decoders.register(".dcm", lambda data: None)
    assert ".dcm" in image_decoders.claimed_suffixes()
    assert is_image_file(Path("/tmp/scan.dcm"))


def test_dropping_a_registration_drops_the_claim_with_it():
    image_decoders.register(".dcm", lambda data: None)
    image_decoders.clear()
    assert ".dcm" not in image_decoders.claimed_suffixes()


# --------------------------------------------------------------------------- #
# Which route a file takes
# --------------------------------------------------------------------------- #

def test_the_backends_own_formats_take_the_fast_lane():
    image_decoders.set_native_suffixes({".heic"})
    assert image_decoders.is_native(".heic")
    assert image_decoders.is_native("HEIC")       # any spelling
    assert not image_decoders.is_native(".png")


def test_a_registered_decoder_wins_over_the_backends():
    # A config that wrote a decoder for a format the backend also reads meant
    # its own — there would be no other reason to write one.
    mine = lambda data: None                                     # noqa: E731
    image_decoders.set_native_suffixes({".png"})
    image_decoders.register(".png", mine)
    assert not image_decoders.is_native(".png")
    assert image_decoders.decoder_for(".png") is mine


def test_pillow_is_the_decoder_of_last_resort():
    pytest.importorskip("PIL")
    assert image_decoders.decoder_for(".png") is not None
    assert image_decoders.decoder_for(".nosuchformat") is None


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

def test_a_pil_image_comes_back_as_pixels_the_backend_can_draw():
    Image = pytest.importorskip("PIL.Image")

    image_decoders.register(".fake", lambda data: Image.new("RGB", (4, 3), (1, 2, 3)))
    raster = image_decoders.decode(".fake", b"")
    assert raster.size == (4, 3)
    assert raster.data[:4] == bytes((1, 2, 3, 255))


def test_a_decoder_may_hand_over_a_raster_itself():
    # For a decoder that already has pixels, so it need not build a PIL.Image
    # only for XeFM to take it apart again.
    mine = _raster(3, 3)
    image_decoders.register(".fake", lambda data: mine)
    assert image_decoders.decode(".fake", b"") is mine


def test_a_decoder_that_declines_is_not_an_error():
    image_decoders.register(".fake", lambda data: None)
    assert image_decoders.decode(".fake", b"") is None


def test_a_format_with_no_decoder_decodes_to_nothing():
    assert image_decoders.decode(".nosuchformat", b"") is None


def test_the_decoder_sees_the_bytes():
    # Bytes, not a path: the same decoder has to work for a picture inside an
    # archive or on S3, which have no path anything can open.
    seen = []
    image_decoders.register(".fake", lambda data: seen.append(data))
    image_decoders.decode(".fake", b"the file's contents")
    assert seen == [b"the file's contents"]


# --------------------------------------------------------------------------- #
# Loading IMAGE_DECODERS from a config
# --------------------------------------------------------------------------- #

def test_a_plain_function_is_the_simple_form():
    mine = lambda data: None                                     # noqa: E731
    warnings, count = load(**{".heic": mine})
    assert warnings == [] and count == 1
    assert image_decoders.decoder_for(".heic") is mine


def test_the_dict_form_carries_a_label():
    mine = lambda data: None                                     # noqa: E731
    warnings, count = load(**{".heic": {"open": mine, "label": "HEIF photo"}})
    assert warnings == [] and count == 1
    assert image_decoders.decoder_for(".heic") is mine


def test_a_suffix_written_without_its_dot_still_works():
    warnings, count = load(heic=lambda data: None)
    assert warnings == [] and count == 1
    assert ".heic" in image_decoders.claimed_suffixes()


def test_a_key_that_is_not_a_suffix_is_refused():
    warnings, count = load(**{"*.heic": lambda data: None})
    assert count == 0
    assert "not a file suffix" in warnings[0]


def test_an_entry_with_no_function_is_refused():
    warnings, count = load(**{".heic": "cairosvg"})
    assert count == 0
    assert "IMAGE_DECODERS['.heic']" in warnings[0]


def test_one_bad_entry_costs_only_itself():
    warnings, count = load(**{".heic": None, ".dcm": lambda data: None})
    assert count == 1 and len(warnings) == 1
    assert image_decoders.decoder_for(".dcm") is not None


def test_a_table_that_is_not_a_dict_is_refused_whole():
    cfg = types.SimpleNamespace(IMAGE_DECODERS=[".heic"])
    warnings = user_api.load_user_entries(cfg)[0]
    assert "IMAGE_DECODERS must be a dictionary" in warnings[0]


def test_reloading_replaces_the_previous_definitions():
    first = lambda data: None                                    # noqa: E731
    second = lambda data: None                                   # noqa: E731
    load(**{".heic": first})
    load(**{".dcm": second})
    assert image_decoders.decoder_for(".dcm") is second
    assert ".heic" not in image_decoders.claimed_suffixes()


def test_the_preview_notice_counts_them():
    notice = user_api.preview_notice(0, 0, 0, 0, 3, 0)
    assert "3 image decoder(s)" in notice
    assert "Preview" in notice


# --------------------------------------------------------------------------- #
# macOS, where the system decoder can actually be asked
# --------------------------------------------------------------------------- #

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def _heic(tmp_path):
    """A real HEIC, written by ImageIO — the same encoder Photos uses. Skips
    where that is not available rather than testing against a PNG in disguise:
    ImageIO decodes by content, so a mislabelled file would prove nothing."""
    pytest.importorskip("Quartz")
    Image = pytest.importorskip("PIL.Image")
    import Quartz
    from Foundation import NSURL

    png = tmp_path / "seed.png"
    Image.new("RGB", (120, 80), (200, 40, 40)).save(png)
    source = Quartz.CGImageSourceCreateWithURL(
        NSURL.fileURLWithPath_(str(png)), None)
    frame = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    path = tmp_path / "photo.heic"
    dest = Quartz.CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_(str(path)), "public.heic", 1, None)
    if dest is None:
        pytest.skip("no HEIC encoder on this machine")
    Quartz.CGImageDestinationAddImage(dest, frame, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        pytest.skip("HEIC encode failed on this machine")
    return path


@macos
def test_heic_is_claimed_and_handed_straight_to_the_system(tmp_path):
    # The whole arrangement, end to end, on the format that prompted it (#357):
    # nothing installed, nothing decoded here, and the picture is drawn by the
    # same decoder Preview uses.
    from puikit import PROFILE_GUI_DESKTOP, Panel
    from puikit.backends.macos_backend import (_appkit_image_extensions,
                                               _imageio_pixel_size)
    from puikit.backends.memory_backend import MemoryBackend

    from xefm.image_viewer import ImageViewer

    class MacLike(MemoryBackend):
        """A recording backend answering the two image questions the way the
        real macOS backend does — ImageIO is the decoder either way. Standing in
        for it because the real one wants a window and a run loop."""

        def image_formats(self):
            return _appkit_image_extensions()

        def image_size(self, source):
            return _imageio_pixel_size(source) or super().image_size(source)

    photo = _heic(tmp_path)
    backend = MacLike(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    image_decoders.set_native_suffixes(panel.image_formats())

    assert is_image_file(Path(str(photo)))
    assert image_decoders.is_native(".heic")

    viewer = ImageViewer(Path(str(photo)), panel=panel)
    assert viewer._error is None
    assert viewer._size == (120, 80)
    assert viewer._source == str(photo)     # the path, not pixels copied here


@macos
def test_the_system_decoder_does_not_make_a_pdf_an_image(tmp_path):
    # ImageIO reads PDFs. The viewer must not offer them — this is the case the
    # curated candidate list exists for, and the one a naive union would get
    # wrong on every Mac.
    from puikit.backends.macos_backend import _appkit_image_extensions

    image_decoders.set_native_suffixes(_appkit_image_extensions())
    assert ".pdf" in image_decoders.native_suffixes()
    assert not is_image_file(Path(str(tmp_path / "paper.pdf")))


def test_the_ordinary_formats_are_claimed_even_by_a_broken_install(monkeypatch):
    # The deliberate hole in "only claim what something can read". With no
    # Pillow and no backend decoder, every picture is unshowable — so pressing
    # Enter on a .png should still open the viewer, whose card says to install
    # Pillow, rather than quietly hand the file to the binary viewer.
    monkeypatch.setattr(image_decoders, "_pillow_cache", frozenset())
    monkeypatch.setattr(image_decoders, "_claimed_cache", None)
    image_decoders.set_native_suffixes(())

    claimed = image_decoders.claimed_suffixes()
    assert {".png", ".jpg", ".gif"} <= claimed
    assert ".psd" not in claimed        # nothing pretends about the rest


def test_the_backend_is_asked_at_the_first_question_not_at_startup():
    # Handed over uncalled so a backend does not have to build its decoder
    # machinery while it is still starting up — on Windows that means the WIC
    # factory and the COM apartment under it, before the window is even open.
    asked = []

    def formats():
        asked.append(True)
        return {".heic"}

    image_decoders.set_native_suffixes(formats)
    assert asked == []
    assert image_decoders.is_native(".heic")
    assert asked == [True]
    image_decoders.claimed_suffixes()
    assert asked == [True]          # and only once


def test_a_backend_that_raises_costs_the_fast_lane_and_nothing_else():
    def formats():
        raise RuntimeError("no imaging component")

    image_decoders.set_native_suffixes(formats)
    assert image_decoders.native_suffixes() == frozenset()
    assert ".png" in image_decoders.claimed_suffixes()
