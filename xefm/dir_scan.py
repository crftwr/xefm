#!/usr/bin/env python3
"""
XeFM Directory Scan - read a whole directory's attributes in one pass.

Listing a pane means answering four questions about every entry: is it a
directory, is it a symlink, how big is it, when was it last modified. Asking the
OS per file costs one round trip per file. On a local disk that is free; on a
network mount it is the whole cost of the listing — a 1,680-entry SMB directory
takes ~21 s at one ``stat`` each, against ~2 s when the same four fields are
read in bulk. The server already sent them along with the directory listing;
per-file ``stat`` throws that away and asks again.

This module answers all four for a whole directory at once:

* **macOS** — ``getattrlistbulk(2)``, the bulk enumeration Finder itself uses.
  Many entries per syscall, no per-file round trips.
* **Windows** — ``os.scandir``, whose ``DirEntry`` already carries what the
  directory enumeration returned; its ``stat()`` costs no syscall at all.
* **Linux and everything else** — ``os.scandir``, which still serves
  ``is_dir``/``is_symlink`` from ``d_type`` and caches its ``stat``, leaving one
  ``stat`` per entry. That is the best a portable API offers there.

Every backend returns the same record, so callers never branch on platform::

    {'is_dir': bool, 'is_link': bool, 'size': int, 'mtime': float, 'ok': bool}

``is_dir``, ``size`` and ``mtime`` describe the **target** of a symlink, and
``is_link`` the link itself — matching what ``stat()``/``is_dir()`` and
``is_symlink()`` reported when callers asked per file. ``ok`` is False when the
target could not be stat'd (a broken symlink); its other fields are then
meaningless and callers should render the entry as unknown.
"""

import os
import stat as stat_mod
import sys

from xefm.log_manager import getLogger

logger = getLogger("DirScan")

__all__ = ["scan_dir", "attrs_for_path", "BROKEN_ATTRS"]

#: What a caller sees for an entry whose target could not be stat'd.
BROKEN_ATTRS = {'is_dir': False, 'is_link': False, 'size': 0, 'mtime': 0.0,
                'ok': False}


def _broken(is_link):
    return {'is_dir': False, 'is_link': is_link, 'size': 0, 'mtime': 0.0,
            'ok': False}


def attrs_for_path(path_str, *, is_link=None):
    """Read one path's attributes with the same record shape :func:`scan_dir`
    returns. Used for the entries bulk enumeration cannot answer (symlinks,
    whose target must be followed) and by callers holding a bare path rather
    than a directory."""
    if is_link is None:
        try:
            is_link = os.path.islink(path_str)
        except OSError:
            is_link = False
    try:
        st = os.stat(path_str)  # follows symlinks
    except (OSError, ValueError):
        return _broken(is_link)
    is_dir = stat_mod.S_ISDIR(st.st_mode)
    return {'is_dir': is_dir, 'is_link': is_link,
            'size': 0 if is_dir else st.st_size,
            'mtime': st.st_mtime, 'ok': True}


# ---------------------------------------------------------------------------
# Portable backend: os.scandir
# ---------------------------------------------------------------------------

def _attrs_from_direntry(entry):
    try:
        is_link = entry.is_symlink()
    except OSError:
        is_link = False
    try:
        # Both follow symlinks, and DirEntry caches the stat it takes.
        st = entry.stat()
        is_dir = entry.is_dir()
    except (OSError, ValueError):
        return _broken(is_link)
    # Directories report size 0 on every backend: the bulk syscall cannot supply
    # a directory's size, and nothing displays or sorts on it (a directory
    # renders as "<DIR>" and sorts as 0).
    return {'is_dir': is_dir, 'is_link': is_link,
            'size': 0 if is_dir else st.st_size,
            'mtime': st.st_mtime, 'ok': True}


def _scan_scandir(path_str):
    out = []
    with os.scandir(path_str) as it:
        for entry in it:
            out.append((entry.name, _attrs_from_direntry(entry)))
    return out


# ---------------------------------------------------------------------------
# macOS backend: getattrlistbulk(2)
# ---------------------------------------------------------------------------

_BULK_READY = False

if sys.platform == "darwin":
    import ctypes
    import ctypes.util
    import struct

    ATTR_BIT_MAP_COUNT = 5

    ATTR_CMN_RETURNED_ATTRS = 0x80000000
    ATTR_CMN_NAME = 0x00000001
    ATTR_CMN_OBJTYPE = 0x00000008
    ATTR_CMN_MODTIME = 0x00000400
    ATTR_FILE_DATALENGTH = 0x00000200

    FSOPT_PACK_INVAL_ATTRS = 0x00000008

    VREG, VDIR, VLNK = 1, 2, 5

    #: Offsets within one packed entry. Attribute buffers are 4-byte packed, not
    #: naturally aligned, so these are fixed rather than struct-derived.
    _OFF_RETURNED = 4     # attribute_set_t, 5 x uint32
    _OFF_NAME = 24        # attrreference_t {int32 offset, uint32 length}
    _OFF_OBJTYPE = 32     # fsobj_type_t
    _OFF_MODTIME = 36     # struct timespec
    _OFF_DATALENGTH = 52  # off_t

    _BULK_BUFSIZE = 256 * 1024

    class _attrlist(ctypes.Structure):
        _fields_ = [
            ("bitmapcount", ctypes.c_ushort),
            ("reserved", ctypes.c_uint16),
            ("commonattr", ctypes.c_uint32),
            ("volattr", ctypes.c_uint32),
            ("dirattr", ctypes.c_uint32),
            ("fileattr", ctypes.c_uint32),
            ("forkattr", ctypes.c_uint32),
        ]

    try:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        _libc.getattrlistbulk.argtypes = [
            ctypes.c_int, ctypes.POINTER(_attrlist), ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_uint64,
        ]
        _libc.getattrlistbulk.restype = ctypes.c_int
        _BULK_READY = True
    except (OSError, AttributeError) as e:  # pragma: no cover - platform quirk
        logger.warning(f"getattrlistbulk unavailable, using scandir: {e}")

    def _scan_bulk(path_str):
        """Enumerate ``path_str`` with getattrlistbulk. Raises OSError if the
        directory cannot be opened or the syscall fails, so the caller can fall
        back to scandir."""
        al = _attrlist()
        al.bitmapcount = ATTR_BIT_MAP_COUNT
        al.commonattr = (ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_NAME |
                         ATTR_CMN_OBJTYPE | ATTR_CMN_MODTIME)
        al.fileattr = ATTR_FILE_DATALENGTH

        buf = ctypes.create_string_buffer(_BULK_BUFSIZE)
        out = []
        fd = os.open(path_str, os.O_RDONLY)
        try:
            while True:
                count = _libc.getattrlistbulk(fd, ctypes.byref(al), buf,
                                              _BULK_BUFSIZE,
                                              FSOPT_PACK_INVAL_ATTRS)
                if count < 0:
                    err = ctypes.get_errno()
                    raise OSError(err, os.strerror(err), path_str)
                if count == 0:
                    break
                mv = memoryview(buf)
                off = 0
                for _ in range(count):
                    rec = mv[off:]
                    length = struct.unpack_from("<I", rec, 0)[0]
                    out.append(_parse_bulk_entry(rec, path_str))
                    off += length
        finally:
            os.close(fd)
        return out

    def _parse_bulk_entry(rec, dir_str):
        ret_common, _ret_vol, _ret_dir, ret_file, _ret_fork = struct.unpack_from(
            "<5I", rec, _OFF_RETURNED)

        name_off, name_len = struct.unpack_from("<iI", rec, _OFF_NAME)
        raw = bytes(rec[_OFF_NAME + name_off:
                        _OFF_NAME + name_off + name_len - 1])  # drop NUL
        name = os.fsdecode(raw)

        objtype = struct.unpack_from("<I", rec, _OFF_OBJTYPE)[0]

        # A symlink's bulk record describes the link, not its target; follow it
        # so is_dir/size/mtime mean what a per-file stat() would have said.
        if objtype == VLNK:
            return name, attrs_for_path(os.path.join(dir_str, name),
                                        is_link=True)

        is_dir = objtype == VDIR

        # A volume that could not supply a field leaves its bit clear; fall back
        # to a stat for just that entry rather than reporting a zero.
        if not ret_common & ATTR_CMN_MODTIME:
            return name, attrs_for_path(os.path.join(dir_str, name),
                                        is_link=False)
        if objtype == VREG and not ret_file & ATTR_FILE_DATALENGTH:
            return name, attrs_for_path(os.path.join(dir_str, name),
                                        is_link=False)

        sec, nsec = struct.unpack_from("<qq", rec, _OFF_MODTIME)
        size = struct.unpack_from("<q", rec, _OFF_DATALENGTH)[0]
        return name, {'is_dir': is_dir, 'is_link': False,
                      'size': 0 if is_dir else size,
                      'mtime': sec + nsec / 1e9, 'ok': True}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scan_dir(path_str):
    """Return ``[(name, attrs), …]`` for every entry in ``path_str``.

    Raises the usual directory errors (``FileNotFoundError``,
    ``PermissionError``, ``NotADirectoryError``) so callers keep their existing
    error handling. A per-entry failure is reported as ``ok: False`` rather than
    raising — one broken symlink must not lose the listing.
    """
    if _BULK_READY:
        try:
            return _scan_bulk(path_str)
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            raise  # a real directory error — the caller reports it
        except OSError as e:
            # A volume that rejects bulk enumeration (some FUSE and network
            # filesystems) still lists fine the portable way.
            logger.debug(f"Bulk scan unavailable for {path_str}: {e}")
            return _scan_scandir(path_str)
    return _scan_scandir(path_str)
