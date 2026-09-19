"""Network mounts — the macOS backend.

Mounting goes through **NetFS.framework**, which is the same API Finder's
*Connect to Server* uses: one call covers ``smb:``, ``afp:``, ``http(s):``
(WebDAV), ``nfs:`` and ``ftp:``, and the volume lands in ``/Volumes`` exactly as
Finder would leave it.

PyObjC publishes a NetFS binding (``pyobjc-framework-NetFS``) that XeFM does not
install. The functions are bound from the framework directly with
``objc.loadBundleFunctions``, which needs only ``pyobjc-core`` — already present
on macOS as one of PuiKit's platform requirements. So this file adds **no
dependency**.

Reading the mount table is plain ``ctypes``: ``getmntinfo`` returns every mount
in one syscall, with the filesystem type and the ``MNT_*`` flags needed to tell
a network share from a removable disk. It is called on the UI thread, so it must
stay that cheap — see ``doc/dev/NETWORK_MOUNT_SYSTEM.md``.

Only :mod:`xefm.netmount` imports this module.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess

from xefm.log_manager import getLogger
from xefm.netmount import NETWORK, OTHER, REMOVABLE, MountError, MountInfo

logger = getLogger("NetMountMac")

#: What NetFS can mount here. ``cifs`` is folded into ``smb`` by the parser.
SCHEMES = ("smb", "afp", "nfs", "http", "https", "ftp")

#: Filesystem types that mean "this came over the network". An explicit list,
#: not "anything without MNT_LOCAL": ``autofs`` and ``devfs`` are not local
#: either, and neither is something to offer to disconnect.
_NETWORK_FSTYPES = frozenset({
    "smbfs", "webdav", "afpfs", "nfs", "ftp", "cifs", "exfat_nfs",
})

# sys/mount.h
_MNT_LOCAL = 0x00001000
_MNT_DONTBROWSE = 0x00100000
_MNT_WAIT = 1

_MFSTYPENAMELEN = 16
_MAXPATHLEN = 1024


class _fsid_t(ctypes.Structure):
    _fields_ = [("val", ctypes.c_int32 * 2)]


class _statfs(ctypes.Structure):
    """``struct statfs`` as of the 64-bit-inode ABI (``__DARWIN_STRUCT_STATFS64``
    in ``sys/mount.h``). The whole layout matters, not just the fields read:
    ``getmntinfo`` hands back an array, and ctypes indexes it by
    ``sizeof(_statfs)``. It is 2168 bytes; ``test_netmount`` asserts that, so a
    future SDK growing the struct is caught by a test rather than by garbled
    mount paths."""

    _fields_ = [
        ("f_bsize", ctypes.c_uint32),
        ("f_iosize", ctypes.c_int32),
        ("f_blocks", ctypes.c_uint64),
        ("f_bfree", ctypes.c_uint64),
        ("f_bavail", ctypes.c_uint64),
        ("f_files", ctypes.c_uint64),
        ("f_ffree", ctypes.c_uint64),
        ("f_fsid", _fsid_t),
        ("f_owner", ctypes.c_uint32),
        ("f_type", ctypes.c_uint32),
        ("f_flags", ctypes.c_uint32),
        ("f_fssubtype", ctypes.c_uint32),
        ("f_fstypename", ctypes.c_char * _MFSTYPENAMELEN),
        ("f_mntonname", ctypes.c_char * _MAXPATHLEN),
        ("f_mntfromname", ctypes.c_char * _MAXPATHLEN),
        ("f_flags_ext", ctypes.c_uint32),
        ("f_reserved", ctypes.c_uint32 * 7),
    ]


def _getmntinfo():
    """``getmntinfo``, bound to the 64-bit-inode struct above.

    The symbol name is not the same everywhere. On Apple silicon there is only
    one ``getmntinfo`` and it is the 64-bit-inode one; on x86_64 the plain name
    is the *legacy* (32-bit inode) entry point with a different struct layout,
    and the one we want is ``getmntinfo$INODE64``. Asking for the suffixed
    symbol first is what keeps an Intel Mac from decoding the wrong structure.
    """
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    for name in ("getmntinfo$INODE64", "getmntinfo64", "getmntinfo"):
        try:
            fn = getattr(libc, name)
        except AttributeError:
            continue
        fn.argtypes = [ctypes.POINTER(ctypes.POINTER(_statfs)), ctypes.c_int]
        fn.restype = ctypes.c_int
        return fn
    raise OSError("getmntinfo not found in libc")


# --- NetFS binding -----------------------------------------------------------

#: Bound NetFS functions, or None once loading has been tried and failed.
_netfs: dict | None = None
_netfs_tried = False

#: ``int NetFSMountURLSync(CFURLRef, CFURLRef, CFStringRef, CFStringRef,
#: CFMutableDictionaryRef, CFMutableDictionaryRef, CFArrayRef *)``. The six
#: inputs are toll-free-bridged object types (``@``); the trailing ``o^@`` is
#: what marks the last argument as an **out** pointer, so PyObjC returns the
#: mountpoint array alongside the status instead of demanding a pointer be
#: passed in. Without the ``o`` the call is unusable.
_NETFS_SIG = b"i@@@@@@o^@"


def _load_netfs() -> dict | None:
    """Bind ``NetFSMountURLSync`` out of NetFS.framework, once.

    Returns the namespace it was loaded into, or ``None`` if anything about the
    load failed — a missing framework, a PyObjC that cannot express the
    signature, an OS where the symbol is gone. The caller turns that into
    "Connect to Server is not available", which is a far better outcome than an
    exception at the moment the user presses Enter.
    """
    global _netfs, _netfs_tried
    if _netfs_tried:
        return _netfs
    _netfs_tried = True
    try:
        import objc
        from Foundation import NSBundle

        bundle = NSBundle.bundleWithPath_(
            "/System/Library/Frameworks/NetFS.framework")
        if bundle is None:
            raise OSError("NetFS.framework not found")
        ns: dict = {}
        objc.loadBundleFunctions(bundle, ns, [("NetFSMountURLSync", _NETFS_SIG)])
        if "NetFSMountURLSync" not in ns:
            raise OSError("NetFSMountURLSync not found in NetFS.framework")
        _netfs = ns
    except Exception as e:
        logger.error(f"Could not load NetFS.framework: {e}")
        _netfs = None
    return _netfs


def is_available() -> bool:
    """Whether this machine can mount at all. Checked once at feature-discovery
    time, so a machine without NetFS simply never shows the dialog."""
    return _load_netfs() is not None


# --- mount -------------------------------------------------------------------

#: Mount statuses that mean "the credentials were wrong", so the form should
#: reopen with what the user typed rather than sending them back to the list.
#: Positive values are errno, negative ones OSStatus (see NetFS.h).
_AUTH_ERRORS = {
    1,       # EPERM
    13,      # EACCES
    80,      # EAUTH — what an SMB server actually answers with
    81,      # ENEEDAUTH
    -5045,   # ENETFSPWDNEEDSCHANGE
    -5046,   # ENETFSPWDPOLICY
    -5999,   # ENETFSACCOUNTRESTRICTED
    -5997,   # ENETFSNOAUTHMECHSUPP
    -6004,   # kNetAuthErrorGuestNotSupported
}

_MESSAGES = {
    2: "No such share on the server.",
    13: "The server rejected the user name or password.",
    1: "The server rejected the user name or password.",
    17: "That share is already mounted.",
    80: "The server rejected the user name or password.",
    81: "The server wants a user name and password.",
    51: "The network is unreachable.",
    60: "The server took too long to answer.",
    61: "The server refused the connection.",
    64: "The server is not responding.",
    65: "The server cannot be reached.",
    -128: "Cancelled.",
    -5996: "The server wants a protocol version this Mac will not use.",
    -5997: "The server wants an authentication method this Mac will not use.",
    -5998: "The server offers no shares.",
    -5999: "That account is not allowed to connect.",
    -6003: "The server offers no shares.",
    -6004: "The server does not allow guest access.",
}


def mount(target, user: str = "", password: str = "",
          drive_letter: str = "") -> str:
    """Mount ``target`` through NetFS and return the resulting mount point.

    ``drive_letter`` is accepted and ignored — it is a Windows concept, and
    keeping the signature identical is what lets :mod:`xefm.netmount` call
    either backend without branching.
    """
    ns = _load_netfs()
    if ns is None:
        raise MountError("Connect to Server is not available on this system.")

    from Foundation import NSMutableDictionary, NSURL

    url = NSURL.URLWithString_(target.url)
    if url is None:
        raise MountError(f"{target.url} is not an address macOS understands.")

    # No credentials at all is a request to connect as a guest, which is what
    # Finder's Guest button does — and what most NAS boxes refuse, so the
    # failure message has to distinguish it from a wrong password.
    guest = not user and not password

    open_options = NSMutableDictionary.dictionary()
    # XeFM collects the credentials itself, so the system's own authentication
    # sheet must stay shut: it cannot be driven from the TUI backend at all (no
    # window server session), and one code path for both backends is worth more
    # than the sheet's polish.
    open_options["UIOption"] = "NoUI"
    if guest:
        open_options["Guest"] = True

    mount_options = NSMutableDictionary.dictionary()
    # Lets smb://nas/photo/2026 mount the subdirectory rather than refusing
    # anything below the share point.
    mount_options["AllowSubMounts"] = True
    # Left explicit although it is also the default: I/O against a server that
    # vanishes should fail, not park the process in the kernel forever.
    mount_options["SoftMount"] = True

    status, mountpoints = ns["NetFSMountURLSync"](
        url, None, user or None, password or None,
        open_options, mount_options, None)

    if status != 0:
        # EEXIST is not a failure: the share is already mounted, and where it is
        # mounted is what the caller wants. NetFS does not fill in mountpoints
        # in that case, so the mount table answers instead.
        if status == 17:
            existing = _find_mount(target)
            if existing:
                return existing
        raise MountError(_describe(status, target, guest=guest),
                         auth=status in _AUTH_ERRORS)

    if mountpoints:
        return str(mountpoints[0])
    # A success with no mount point should not happen; the mount table is a
    # better answer than an exception when it does.
    existing = _find_mount(target)
    if existing:
        return existing
    raise MountError("The share was mounted, but macOS did not say where.")


def _describe(status: int, target, *, guest: bool = False) -> str:
    """The sentence shown for a mount status, with the server named where that
    is the useful half of the message."""
    if guest and status in _AUTH_ERRORS:
        # Nothing was typed, so "rejected the user name or password" would be
        # accusing the user of getting wrong something they were never asked
        # for. Name what is actually missing.
        return f"{target.host} needs a user name and password."
    message = _MESSAGES.get(status)
    if message is None:
        return f"Could not connect to {target.host} (error {status})."
    if status in (64, 65, 60, 51, 61):
        return f"{target.host}: {message}"
    return message


def _find_mount(target) -> str:
    """The mount point of ``target`` if it is already mounted, else ``""``.

    ``f_mntfromname`` for an SMB mount reads ``//user@nas/photo``, so the match
    is on host and share with the user part and the case ignored.
    """
    host = target.host.lower()
    share = target.share.strip("/").lower()
    for info in list_mounts():
        source = info.source.replace("\\", "/").lstrip("/").lower()
        if "@" in source:
            source = source.split("@", 1)[1]
        source_host, _, source_share = source.partition("/")
        if source_host == host and source_share.strip("/") == share:
            return info.path
    return ""


# --- the mount table ---------------------------------------------------------

def list_mounts() -> list[MountInfo]:
    """Every mount, classified. One syscall, no subprocesses — this runs on the
    UI thread whenever the Drives dialog opens."""
    fn = _getmntinfo()
    buf = ctypes.POINTER(_statfs)()
    count = fn(ctypes.byref(buf), _MNT_WAIT)
    if count <= 0:
        return []

    mounts = []
    for i in range(count):
        entry = buf[i]
        fstype = entry.f_fstypename.decode("utf-8", "replace")
        path = entry.f_mntonname.decode("utf-8", "replace")
        source = entry.f_mntfromname.decode("utf-8", "replace")
        mounts.append(MountInfo(path=path, kind=_kind(fstype, path, entry.f_flags),
                                source=source, fstype=fstype))
    return mounts


def _kind(fstype: str, path: str, flags: int) -> str:
    """Classify one mount.

    Removability is decided by *where* the volume is mounted rather than by
    ``MNT_REMOVABLE``: an external USB SSD carrying an APFS container does not
    reliably set that flag, yet Finder still offers to eject it, and so should
    XeFM. What is excluded instead is the root volume, the system's own
    ``/System/Volumes`` machinery (never under ``/Volumes``) and anything marked
    ``MNT_DONTBROWSE`` — the Recovery volume is the everyday example.
    """
    if fstype in _NETWORK_FSTYPES:
        return NETWORK
    if not (flags & _MNT_LOCAL):
        return OTHER  # autofs, devfs and friends: nothing to disconnect
    if flags & _MNT_DONTBROWSE:
        return OTHER
    if path.startswith("/Volumes/") and path.count("/") == 2:
        return REMOVABLE
    return OTHER


# --- unmount / eject ---------------------------------------------------------

def unmount(path: str) -> None:
    """Disconnect a network mount with ``umount``."""
    _run(["/sbin/umount", path], path)


def eject(path: str) -> None:
    """Eject a removable volume with ``diskutil``, which also spins the device
    down and powers it off — that last part is what makes it safe to unplug, and
    it is why this is not just another ``umount``."""
    _run(["/usr/sbin/diskutil", "eject", path], path)


def _run(argv: list[str], path: str) -> None:
    """Run one of the small mount-table commands, turning a non-zero exit into a
    :class:`MountError` carrying the command's own words.

    The system's message is kept rather than replaced because it is the useful
    one: ``umount`` names the process still holding the volume, which is exactly
    what the user needs in order to do something about it.
    """
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise MountError(f"{os.path.basename(argv[0])} did not finish.") from None
    except OSError as e:
        raise MountError(f"Could not run {argv[0]}: {e}") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"exit status {proc.returncode}"
        # The tools prefix their own name; it adds nothing to a dialog.
        for prefix in ("umount: ", "diskutil: "):
            if message.startswith(prefix):
                message = message[len(prefix):]
        raise MountError(f"{os.path.basename(path) or path}: {message}")


# --- stored passwords --------------------------------------------------------

#: Keychain protocol codes are exactly four characters (``SecProtocolType``),
#: which is why ``https`` is ``htps`` and the short ones are space-padded.
_KEYCHAIN_PROTOCOLS = {
    "smb": "smb ", "afp": "afp ", "nfs": "nfs ",
    "http": "http", "https": "htps", "ftp": "ftp ",
}


def _security(args: list[str], stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(["/usr/bin/security", *args], input=stdin,
                          capture_output=True, text=True, timeout=20)


def _keychain_keys(target, user: str) -> list[str]:
    """The ``security`` arguments that identify one stored password: the account,
    the server and the protocol. The share is deliberately *not* part of the key
    — one password per account per server is how the login Keychain already
    holds these, and it is what lets a second share on the same NAS connect
    without asking again."""
    return ["-a", user or "", "-s", target.host,
            "-r", _KEYCHAIN_PROTOCOLS.get(target.scheme, "smb ")]


def save_password(target, user: str, password: str) -> None:
    """Add (or replace, via ``-U``) an internet password in the login Keychain.

    The password is written to the command's **stdin**, twice, because
    ``security -w`` with no value prompts for it and then asks again to confirm.
    Passing it as an argument instead would put it in the process list for every
    user on the machine to read, which is why the odd double-write is worth it.
    """
    proc = _security(
        ["add-internet-password", *_keychain_keys(target, user),
         "-l", f"{target.host} (XeFM)", "-U", "-w"],
        stdin=f"{password}\n{password}\n")
    if proc.returncode != 0:
        raise MountError((proc.stderr or "security failed").strip())


def load_password(target, user: str) -> str:
    """The stored password, or ``""`` when there is none (which is the ordinary
    case, not an error)."""
    proc = _security(["find-internet-password", *_keychain_keys(target, user), "-w"])
    if proc.returncode != 0:
        return ""
    return _decode_password(proc.stdout.rstrip("\n"))


def forget_password(target, user: str) -> None:
    """Delete the stored password. A missing item is not an error — forgetting a
    server that never saved one is normal."""
    _security(["delete-internet-password", *_keychain_keys(target, user)])


def _decode_password(raw: str) -> str:
    """``security -w`` prints a password that is not plain ASCII as hex digits
    instead of as text. Undo that, but only when the hex really does decode to
    text with a non-ASCII character in it: a password of ``123456`` is also
    valid hex, and must come back as the six digits the user typed rather than
    as the three control bytes they spell."""
    if not raw or len(raw) % 2 or any(c not in "0123456789ABCDEFabcdef" for c in raw):
        return raw
    try:
        decoded = bytes.fromhex(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return raw
    if decoded.isprintable() and any(ord(c) > 127 for c in decoded):
        return decoded
    return raw
