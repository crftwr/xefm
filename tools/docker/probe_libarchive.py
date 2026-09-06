#!/usr/bin/env python3
"""Assert that XeFM finds libarchive here, and say what it found.

Run inside the Linux test containers. The question it answers is not whether the
archive code works — the test suite answers that on glibc — but whether the
shared library is **found at all**, which is a different question on every
platform and one that has already been got wrong once.

musl is why this exists. ``ctypes.util.find_library('archive')``, which
``libarchive-c`` asks, returns None on Alpine with libarchive installed at
``/usr/lib/libarchive.so.13`` and returns None still with the ``-dev`` symlink
beside it: musl's ldconfig has no ``-p`` to read and the fallbacks need a
compiler. XeFM answers by naming the soname itself
(:func:`xefm.archive_libarchive._use_known_soname`); without that this script
fails, which is the regression it is here to catch.

``--expect-absent`` inverts the check, for an image with no libarchive at all:
that path has to be a clean "not available" carrying a reason, not a crash and
not a silent half-registration.

Imports only :mod:`xefm.archive_libarchive`, whose chain needs nothing beyond
``libarchive-c`` — the musl image installs no other dependency.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from xefm.archive_libarchive import (  # noqa: E402
    libarchive_formats, libarchive_info)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-absent", action="store_true",
                        help="require that no libarchive is found, and that "
                             "saying so is all that happens")
    args = parser.parse_args()

    info = libarchive_info()
    formats = [fmt.label for fmt in libarchive_formats()]
    chosen = os.environ.get("LIBARCHIVE") or "(find_library)"

    print(f"platform      : {sys.platform}")
    print(f"available     : {info.available}")
    print(f"named by      : {chosen}")
    print(f"library path  : {info.library_path or '-'}")
    print(f"details       : {info.details or '-'}")
    print(f"codecs        : {' '.join(info.codecs) or '-'}")
    print(f"formats       : {' '.join(formats) or '-'}")
    print(f"error         : {info.error or '-'}")

    if args.expect_absent:
        if info.available:
            print("\nFAIL: expected no libarchive here, but one was found.")
            return 1
        if not info.error:
            print("\nFAIL: no libarchive and no reason given — the absent path "
                  "has to say why.")
            return 1
        if formats:
            print(f"\nFAIL: no libarchive, yet {len(formats)} formats registered.")
            return 1
        print("\nOK: absent, with a reason, and nothing registered.")
        return 0

    if not info.available:
        print(f"\nFAIL: libarchive was not found ({info.error}).")
        return 1
    missing = {"7z", "rar", "iso", "cab", "cpio", "rpm"} - set(formats)
    if missing:
        print(f"\nFAIL: library found but these formats did not register: "
              f"{' '.join(sorted(missing))}")
        return 1
    print("\nOK: found, and every format XeFM offers through it registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
