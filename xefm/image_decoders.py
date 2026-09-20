#!/usr/bin/env python3
"""Which files the image viewer opens, and who decodes each one.

The viewer used to answer both questions with one frozen set of extensions, and
the set had to be small for a reason worth keeping: **a file that opens in the
viewer should show a picture.** Claiming a format nothing on the machine can read
means the viewer opens onto its metadata card — a worse outcome than never
having claimed it, because the file manager's other viewers never got a look.

What changes here is that the answer stops being frozen. Two things can decode a
picture, and both are properties of the machine rather than of the format:

* **The backend's own decoder**, which PuiKit reports through
  ``Backend.image_formats()``. On macOS that is ImageIO — HEIC, JPEG XL and
  camera RAW out of the box. On Windows it is whatever WIC codecs are installed,
  so HEIC appears only where the user has the Store extension. In a terminal it
  is Pillow, plugins included. A format it names travels as a **path**: XeFM
  reads nothing, decodes nothing, copies no pixels.
* **A decoder registered here**, which turns bytes into pixels XeFM hands over
  as a :class:`~puikit.image.RasterImage`. Pillow is registered as the built-in
  one, for every format it can open; a config adds its own.

:func:`claimed_suffixes` is the intersection of what XeFM considers a *picture*
(:data:`CANDIDATE_SUFFIXES` — curated, because ImageIO will happily also read a
PDF) with what one of those two can actually decode, plus the registered
suffixes and :data:`BASELINE_SUFFIXES`. So the old guarantee survives while the
list stops being a guess: an old Pillow without AVIF simply does not claim
``.avif`` on Linux, and the same machine's macOS sibling claims it because
ImageIO reads it.

Registering a decoder
---------------------

```python
def open_dicom(data):
    import io, numpy, pydicom
    from PIL import Image
    frame = pydicom.dcmread(io.BytesIO(data)).pixel_array
    return Image.fromarray(frame)

IMAGE_DECODERS = {'.dcm': open_dicom}
```

**The contract.**

* The function takes one argument, the file's ``bytes``, and returns a
  ``PIL.Image``, a :class:`~puikit.image.RasterImage`, or ``None`` for "I cannot
  read this one". Bytes rather than a path because the viewer opens files inside
  archives and on S3 and SFTP too, and a decoder that took a path would send
  every one of those through a temporary file for no reason.
* **It may run off the UI thread**, so it must not touch the UI — the same rule
  :mod:`xefm.sort_keys` and :mod:`xefm.filters` set, and for the same reason:
  this is the slow work. A RAW decode takes seconds.
* A decoder that raises loses *that picture*, not the viewer: the metadata card
  says what went wrong and the log carries the traceback. Failing to a card is
  the safe direction here — the opposite of a filter, which fails open, because
  a picture that cannot be decoded has no honest stand-in.
* A registration **replaces** the built-in route for that suffix, which is how
  you override Pillow's reading of a format with your own.

The suffixes a config registers are claimed whether or not anything else can
read them — that is the point of registering one — so this is also how SVG, RAW
and DICOM reach the viewer without XeFM carrying cairosvg, rawpy or pydicom.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from xefm.log_manager import getLogger

logger = getLogger("ImageDecode")

#: Every suffix XeFM is willing to treat as a picture — the question "is this a
#: file the image viewer should open?", kept separate from "can anything decode
#: it?" and answered here by hand.
#:
#: Curation is the whole value. macOS's ImageIO reports sixty-odd readable types
#: and several of them have no business opening in an image viewer: ``.pdf`` is a
#: document, ``.dcm`` wants window/level controls this viewer does not have, and
#: ``.svg`` is text a user may well want to *read*. A config that disagrees
#: registers a decoder for one and gets it (see the module docstring).
CANDIDATE_SUFFIXES = frozenset({
    # --- what the viewer has always claimed ------------------------------
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".bmp", ".webp",
    ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".tga",
    # --- the formats a photo actually arrives in now ----------------------
    # AVIF: what a phone or a web page hands you today. Pillow 11.3+ bundles
    # libavif, so this needs nothing installed on most machines.
    ".avif", ".avifs",
    # HEIC and friends: an iPhone's own format. Decoded by ImageIO on macOS and
    # by WIC on a Windows machine with the Store extension, so on those it costs
    # nothing; elsewhere ``pip install pillow-heif`` is what turns it on.
    ".heic", ".heif", ".heics", ".hif", ".avci",
    # JPEG XL: same story, read natively on macOS and by a Pillow plugin
    # (pillow-jxl-plugin) anywhere.
    ".jxl",
    # --- the rest of the curated set -------------------------------------
    ".jp2", ".j2k", ".j2c", ".jpc", ".jpf", ".jpx",   # JPEG 2000
    ".psd",                                            # Photoshop (composite)
    ".qoi",
    ".icns",                                           # macOS icon
    ".dds",                                            # texture
    ".cur",                                            # Windows cursor
    ".apng",                                           # animated PNG, 1st frame
    ".pcx",
})

#: Claimed even when nothing on the machine can decode them.
#:
#: The one deliberate hole in "only claim what something can read", and it is
#: there to keep a *diagnostic*. Reaching it takes a broken install — no Pillow
#: and a backend that draws no pictures either — and in that state every picture
#: is unshowable, not just these. What the exception buys is that pressing Enter
#: on a ``.png`` still opens the viewer, whose card then says "Install pillow to
#: view images", instead of silently handing the file to the binary viewer and
#: leaving the user to work out why images stopped working.
BASELINE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp"})

#: Optional Pillow plugins, as ``(module, opener function)``. Each is registered
#: when it happens to be importable and ignored when it is not, which is what
#: makes ``pip install pillow-heif`` the whole of "turn HEIC on" — there is no
#: XeFM-side switch, and no entry in ``requirements.txt`` either. Bundling one
#: would carry its LGPL codecs into the DMG and the MSIX to serve a format the
#: two platforms that ship those installers already read natively.
_OPTIONAL_PILLOW_PLUGINS = (
    ("pillow_heif", "register_heif_opener"),
    ("pillow_avif", None),          # import alone registers the plugin
    ("pillow_jxl", None),
)

#: ``suffix -> {'open': callable, 'label': str | None}``, in registration order.
#: Rebuilt wholesale on a config reload, exactly as ``FILTERS`` is.
_user: dict[str, dict[str, Any]] = {}

#: Where to find out what the running backend draws from a path: the suffixes
#: themselves, or — the usual case — ``Panel.image_formats`` left uncalled, so
#: the backend is asked the first time the answer is wanted rather than while it
#: is still starting up. ``None`` claims nothing, which is the safe direction.
_native_source: Any = None

#: Memoized answers. All of them depend only on the registrations and the
#: backend, which change at known moments (:func:`register`, :func:`clear`,
#: :func:`set_native_suffixes`), and ``is_image_file`` is asked once per entry
#: for every directory listed.
_native_cache: frozenset[str] | None = None
_claimed_cache: frozenset[str] | None = None
_pillow_cache: frozenset[str] | None = None


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def clear() -> None:
    """Drop every registration. A config reload rebuilds from scratch, so a
    decoder removed from the config stops being used — and the format stops
    being claimed with it, unless something else can read it."""
    _user.clear()
    _invalidate()


def register(suffix: str, opener: Callable[[bytes], Any],
             label: str | None = None) -> None:
    """Add or replace the decoder for one suffix. Later registration wins, as in
    :mod:`xefm.sort_keys` and :mod:`xefm.filters`.

    ``suffix`` is normalized to lowercase with a leading dot, so ``'PNG'``,
    ``'.png'`` and ``'.PNG'`` all name the same format."""
    _user[normalize(suffix)] = {"open": opener, "label": label}
    _invalidate()


def set_native_suffixes(source: "Iterable[str] | Callable[[], Iterable[str]] | None") -> None:
    """Record where to learn what the running backend decodes from a path.

    A fact about the machine — the installed WIC codecs, the OS's ImageIO, the
    Pillow plugins a terminal has — so it is read from the backend rather than
    assumed, and it decides both which formats are claimed and which take the
    fast lane.

    ``source`` may be the suffixes, or a **callable** returning them. The app
    passes ``Panel.image_formats`` uncalled, and the difference matters: asking
    at startup would have a backend build its decoder machinery (on Windows, the
    WIC factory, and the COM apartment under it) before its window is even open.
    Deferring it means the backend is asked once, at the first question anyone
    actually has — the first directory listing — by which time it is running."""
    global _native_source, _native_cache
    _native_source = source
    _native_cache = None
    _invalidate()


def _invalidate() -> None:
    global _claimed_cache
    _claimed_cache = None


def normalize(suffix: Any) -> str:
    """``'.png'`` from any spelling of it. A suffix with no dot gets one; the
    empty string stays empty (a file with no extension names no format)."""
    text = str(suffix or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith(".") else "." + text


# --------------------------------------------------------------------------- #
# What can be shown, and by whom
# --------------------------------------------------------------------------- #

def native_suffixes() -> frozenset[str]:
    """What the backend reads from a path, resolving the source on first ask.

    A backend that raises here is treated as answering nothing: the set is an
    optimization and a widening, never a prerequisite, so losing it costs the
    fast lane and a few formats — not the viewer."""
    global _native_cache
    if _native_cache is None:
        source = _native_source
        if callable(source):
            try:
                source = source()
            except Exception as e:
                logger.error(f"Could not ask the backend which image formats "
                             f"it reads: {e}")
                source = ()
        _native_cache = frozenset(normalize(s) for s in (source or ()))
    return _native_cache


def claimed_suffixes() -> frozenset[str]:
    """Every suffix the image viewer claims on this machine.

    A candidate is claimed when something can decode it — the backend, Pillow, or
    a registered decoder — and a registered suffix is claimed whether or not it
    is a candidate, because registering one *is* the statement that it should
    open here. :data:`BASELINE_SUFFIXES` is the one exception, and says why."""
    global _claimed_cache
    if _claimed_cache is None:
        decodable = native_suffixes() | _pillow_suffixes()
        _claimed_cache = frozenset(
            (CANDIDATE_SUFFIXES & decodable) | BASELINE_SUFFIXES | set(_user))
    return _claimed_cache


def is_native(suffix: str) -> bool:
    """Whether the backend reads this format from a path itself — the fast lane,
    where XeFM neither reads the file nor decodes anything.

    A registered decoder takes precedence: a config that wrote one for a format
    the backend also reads meant its own."""
    suffix = normalize(suffix)
    return suffix not in _user and suffix in native_suffixes()


def decoder_for(suffix: str) -> Callable[[bytes], Any] | None:
    """The function that turns this format's bytes into pixels, or ``None`` when
    nothing here can — a registered decoder first, then Pillow."""
    suffix = normalize(suffix)
    entry = _user.get(suffix)
    if entry is not None:
        return entry["open"]
    if suffix in _pillow_suffixes():
        return _pillow_open
    return None


def user_suffixes() -> list[str]:
    """The suffixes a config registered, in registration order."""
    return list(_user)


# --------------------------------------------------------------------------- #
# The built-in decoder
# --------------------------------------------------------------------------- #

def _pillow_suffixes() -> frozenset[str]:
    """Every extension Pillow can *open* on this machine, plugins included.

    Resolved once. ``Image.init()`` is what pulls the plugins in — without it the
    registry holds only whatever happened to be imported already — and the
    optional openers are registered first so a ``pillow-heif`` the user installed
    shows up in the same answer, with no separate list to keep in step."""
    global _pillow_cache
    if _pillow_cache is not None:
        return _pillow_cache
    try:
        from PIL import Image
    except ImportError:
        _pillow_cache = frozenset()
        return _pillow_cache
    _register_optional_plugins()
    try:
        Image.init()
        _pillow_cache = frozenset(
            ext.lower() for ext, fmt in Image.registered_extensions().items()
            if fmt in Image.OPEN)
    except Exception as e:
        logger.error(f"Could not read Pillow's format registry: {e}")
        _pillow_cache = frozenset()
    return _pillow_cache


def _register_optional_plugins() -> None:
    """Hook up whichever Pillow plugins are installed. Each is a plain import
    away from working, and each is absent on a normal install, so every failure
    here is expected and silent — nothing is wrong with a machine that has no
    HEIC decoder, it simply will not claim HEIC."""
    for module_name, entry_point in _OPTIONAL_PILLOW_PLUGINS:
        try:
            module = __import__(module_name)
        except Exception:
            continue
        if entry_point is None:
            logger.info(f"Pillow plugin {module_name} registered")
            continue
        try:
            getattr(module, entry_point)()
            logger.info(f"Pillow plugin {module_name} registered")
        except Exception as e:
            logger.warning(f"Pillow plugin {module_name} failed to register: {e}")


def _pillow_open(data: bytes):
    """The built-in decoder: Pillow, over the file's bytes.

    ``load()`` is forced here rather than left lazy so a truncated or corrupt
    file raises *now*, inside the caller's error handling, instead of part-way
    through a draw."""
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image.load()
    return image


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

def decode(suffix: str, data: bytes):
    """``data`` as a :class:`~puikit.image.RasterImage`, or ``None`` when no
    decoder claims this format.

    Raises whatever the decoder raises. The caller — one modal viewer, which has
    somewhere to show the reason — is better placed to say what went wrong than
    a swallowed exception here would be.
    """
    from puikit.image import RasterImage, is_raster

    opener = decoder_for(suffix)
    if opener is None:
        return None
    result = opener(data)
    if result is None:
        return None
    if is_raster(result):
        return result
    # Anything else is taken to be a PIL.Image, which is what the contract asks
    # for and what every plausible decoder produces.
    return RasterImage.from_pillow(result)
