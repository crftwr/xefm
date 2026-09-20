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

import contextlib
import ctypes
import ctypes.util
import os
import queue
import re
import subprocess
import time

from xefm.log_manager import getLogger
from xefm.netmount import (NETWORK, OTHER, REMOVABLE, DiscoveredServer,
                           MountError, MountInfo, canonical_host, host_label,
                           host_spellings)

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

#: Mount statuses that mean the host was never reached — no such name, or
#: nothing answering at it. These are the failures worth retrying under the
#: mDNS name, and the auth failures are deliberately not among them.
_UNREACHABLE = {2, 51, 60, 61, 64, 65}


#: The two host rules both backends follow, kept in the neutral layer so
#: they cannot drift apart again: what discovery reports, and what a failed
#: name is retried as. See :func:`xefm.netmount.host_spellings`.
_host_label = host_label
_mdns_alternatives = host_spellings


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


def _url_for(target, host: str) -> str:
    """``target``'s URL with the host swapped, for the fallback attempt."""
    if host == target.host:
        return target.url
    port = f":{target.port}" if target.port else ""
    base = f"{target.scheme}://{host}{port}"
    return f"{base}/{target.share}" if target.share else base


def mount(target, user: str = "", password: str = "",
          drive_letter: str = "") -> str:
    """Mount ``target`` through NetFS and return the resulting mount point.

    A single-label host is tried as written and then, if nothing answered at
    that name, as ``<host>.local`` — see :func:`_mdns_alternatives` for why
    that order and not the other. An authentication failure is *not* retried:
    the server was reached, and asking it again under a different name would
    only produce a second rejection and a worse message.

    ``drive_letter`` is accepted and ignored — it is a Windows concept, and
    keeping the signature identical is what lets :mod:`xefm.netmount` call
    either backend without branching.
    """
    last = None
    for host in _mdns_alternatives(target.host):
        try:
            return _mount_once(target, host, user, password)
        except MountError as e:
            if e.auth or not getattr(e, "unreachable", False):
                raise
            last = e
    raise last if last is not None else MountError(
        f"Could not connect to {target.host}.")


def _mount_once(target, host: str, user: str, password: str) -> str:
    """One NetFS attempt against one spelling of the host."""
    ns = _load_netfs()
    if ns is None:
        raise MountError("Connect to Server is not available on this system.")

    from Foundation import NSMutableDictionary, NSURL

    url = NSURL.URLWithString_(_url_for(target, host))
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
        error = MountError(_describe(status, target, guest=guest),
                           auth=status in _AUTH_ERRORS)
        # Only a host that was never reached is worth trying under another
        # name; everything else answered, and the answer stands.
        error.unreachable = status in _UNREACHABLE
        raise error

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
    host = target.canonical_host
    share = target.share.strip("/").lower()
    for info in list_mounts():
        source = info.source.replace("\\", "/").lstrip("/").lower()
        if "@" in source:
            source = source.split("@", 1)[1]
        source_host, _, source_share = source.partition("/")
        if (canonical_host(source_host) == host
                and source_share.strip("/") == share):
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
        proc = _run_tool(argv, timeout=30)
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
    return _run_tool(["/usr/bin/security", *args], input=stdin, timeout=20)


def _run_tool(argv: list[str], *, input: str = "", timeout: float = 20
              ) -> subprocess.CompletedProcess:
    """Run one of the system tools, **with no controlling terminal**.

    ``start_new_session`` is the whole point of this wrapper. Several of these
    tools ask for input by opening ``/dev/tty`` rather than reading stdin —
    ``security -w`` prompts for a password that way — and in the TUI
    ``/dev/tty`` is the terminal XeFM is drawing on. The prompt lands in the
    middle of the file list, the keystrokes meant for it go to XeFM, and the
    tool waits until its timeout. Observed: saving a password took 20 seconds
    and failed, with ``password data for new item:`` written over the pane.

    Detached from the terminal, ``readpassphrase(3)`` cannot open ``/dev/tty``
    and falls back to stdin, which is where the password already is. It is also
    why the password is not passed as an argument: the process list is readable
    by every user on the machine.
    """
    return subprocess.run(argv, input=input, capture_output=True, text=True,
                          timeout=timeout, start_new_session=True)


def _keychain_keys(target, user: str) -> list[str]:
    """The ``security`` arguments that identify one stored password: the account,
    the server and the protocol.

    The share is deliberately *not* part of the key — one password per account
    per server is how the login Keychain already holds these, and it is what
    lets a second share on the same NAS connect without asking again. The host
    is the canonical one, so a password saved for ``synologynas`` is found
    again when Bonjour hands back ``SynologyNas.local``."""
    return ["-a", user or "", "-s", target.canonical_host,
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


def _keychain_servers(target) -> list[str]:
    """The names this server's keychain entry might be filed under, most
    likely first.

    Finder files a Bonjour-discovered server under its **service** name —
    ``SynologyNas._smb._tcp.local``, not ``SynologyNas.local`` and not
    ``synologynas`` — so a lookup by host name finds nothing at all on exactly
    the machines the user has already connected to. XeFM's own entries use the
    canonical host. Both spellings are tried, plus the host as written.
    """
    bare = target.host
    if bare.lower().endswith(".local"):
        bare = bare[:-6]
    names = [f"{bare}._{target.scheme}._tcp.local", target.host,
             target.canonical_host]
    seen, out = set(), []
    for name in names:
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def find_account(target) -> str:
    """The account the login Keychain holds for this server, or ``""``.

    Attributes only — no ``-w`` — so nothing is decrypted and no access prompt
    can appear. Which matters: this runs for a server the user merely
    highlighted, not one they asked to connect to.
    """
    protocol = _KEYCHAIN_PROTOCOLS.get(target.scheme, "smb ")
    for server in _keychain_servers(target):
        proc = _security(["find-internet-password", "-s", server,
                          "-r", protocol])
        if proc.returncode != 0:
            continue
        match = re.search(r'"acct"<blob>="([^"]*)"',
                          (proc.stdout or "") + (proc.stderr or ""))
        if match and match.group(1):
            return match.group(1)
    return ""


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


# --- finding servers ---------------------------------------------------------

#: Bonjour service types browsed for, mapped to the scheme a hit becomes.
#: These are the two Finder's Network view is built on.
_BONJOUR_SERVICES = {"_smb._tcp.": "smb", "_afpovertcp._tcp.": "afp"}

#: Stop browsing after this long even if the picker is still open. Discovery is
#: meant to run for as long as the dialog is up — a NAS that wakes later should
#: still appear — but a dialog left open overnight need not keep a run loop
#: turning until morning.
_DISCOVERY_SECONDS = 300.0

#: How long each turn of the run loop waits before the cancel flag is looked at.
_POLL = 0.2

#: Resolution is a local mDNS query; this is generous for one.
_RESOLVE_SECONDS = 5.0


def _bonjour():
    """The Foundation names discovery needs, or ``None`` where they cannot be
    imported. Imported lazily and behind a guard for the same reason the NetFS
    binding is: a machine that cannot browse should lose the feature, not raise
    at the moment the picker opens."""
    try:
        from Foundation import (NSDate, NSDefaultRunLoopMode,
                                NSNetServiceBrowser, NSObject, NSRunLoop)
    except Exception as e:  # pragma: no cover - a Mac without Foundation
        logger.error(f"Bonjour browsing unavailable: {e}")
        return None
    return NSDate, NSDefaultRunLoopMode, NSNetServiceBrowser, NSObject, NSRunLoop


def _collector_class(NSObject):
    """The browser/resolver delegate, built once and cached.

    Defined inside a function because it subclasses ``NSObject``, which cannot
    be imported at module scope on a machine without PyObjC — and this module
    is imported for :func:`list_mounts` long before anyone browses.

    It does both jobs. A found service is **resolved immediately**, on this
    same run loop, and only reaches the caller once it has a host name. That is
    what keeps the NSNetService objects on one thread: resolving later, from
    whichever worker the user's choice lands on, would mean two threads sharing
    an object Apple does not document as thread-safe.
    """
    global _Collector
    if _Collector is not None:
        return _Collector

    class _ServiceCollector(NSObject):
        def netServiceBrowser_didFindService_moreComing_(self, browser, service,
                                                         more):
            # Held in ``keep``: the browser does not retain the service, and a
            # resolution in flight against a collected object crashes rather
            # than fails.
            self.keep.append(service)
            service.setDelegate_(self)
            service.scheduleInRunLoop_forMode_(self.loop, self.mode)
            service.resolveWithTimeout_(_RESOLVE_SECONDS)

        def netServiceDidResolveAddress_(self, service):
            host = _host_label(service.hostName())
            if host:
                self.out.put((str(service.name()), host, str(service.type())))

        def netService_didNotResolve_(self, service, error):
            # Dropped rather than listed. The advertised name is not a host
            # name (a Mac announces "Anna's MacBook Pro"), so without the
            # resolution there is nothing to connect to, and a row that cannot
            # be connected to is worse than no row.
            logger.debug(f"Could not resolve {service.name()}: {error}")

    _Collector = _ServiceCollector
    return _Collector


#: Cached delegate class (see :func:`_collector_class`).
_Collector = None


def discover_servers(cancel):
    """Browse Bonjour for file servers, yielding each once it has resolved.

    This is the query behind Finder's Network view, and like it, it never
    finishes on its own: a NAS that wakes up ten seconds from now is a new row
    on an already-open list. So the run loop is turned in short slices with the
    cancel flag checked between them, and the browsers are stopped when the
    picker closes.

    ``NSNetServiceBrowser`` rather than ``dns-sd``: the command-line tool
    full-buffers its output when it is talking to a pipe instead of a
    terminal, so its announcements arrive in 4 KB lumps or not at all — the
    first line of a browse and then silence.

    Runs entirely on the calling thread (the picker's loader), including the
    run loop it pumps.
    """
    names = _bonjour()
    if names is None:
        return
    NSDate, mode, NSNetServiceBrowser, NSObject, NSRunLoop = names

    out: queue.Queue = queue.Queue()
    loop = NSRunLoop.currentRunLoop()
    delegate = _collector_class(NSObject).alloc().init()
    delegate.out, delegate.keep, delegate.loop, delegate.mode = out, [], loop, mode

    browsers = []
    for service_type in _BONJOUR_SERVICES:
        browser = NSNetServiceBrowser.alloc().init()
        browser.setDelegate_(delegate)
        browser.scheduleInRunLoop_forMode_(loop, mode)
        browser.searchForServicesOfType_inDomain_(service_type, "local.")
        browsers.append(browser)

    seen = set()
    deadline = time.monotonic() + _DISCOVERY_SECONDS
    try:
        while not cancel.is_set() and time.monotonic() < deadline:
            loop.runMode_beforeDate_(
                mode, NSDate.dateWithTimeIntervalSinceNow_(_POLL))
            while True:
                try:
                    name, host, service_type = out.get_nowait()
                except queue.Empty:
                    break
                scheme = _BONJOUR_SERVICES.get(service_type, "smb")
                if (scheme, host.lower()) in seen:
                    continue
                seen.add((scheme, host.lower()))
                yield DiscoveredServer(name=name, host=host, scheme=scheme)
    finally:
        for browser in browsers:
            browser.stop()


# --- listing shares ----------------------------------------------------------

def list_shares(target, user: str = "", password: str = "") -> list[str]:
    """The disk shares a server offers, via ``smbutil view``.

    Two attempts, because two things work and a third does not:

    - ``-g``, as a guest. Right for an open share, and refused outright by a
      NAS with accounts — a Synology answers ``Authentication error``.
    - ``//user@host``, which authenticates out of the **login Keychain**, or
      out of a session already open to that server.

    A password cannot be handed to ``smbutil`` directly. Its only argument for
    one is on the command line, where the process list carries it to every
    user on the machine, and it does not read one from stdin — measured: an
    unknown account failed in 0.3 s without ever reading the pipe. So a
    password given here is spent on the Keychain, by
    :func:`_lend_to_the_keychain`, which is the one channel left.

    **What is not established** is whether the Keychain alone is enough
    against a server with no session open to it. Every measurement that
    appeared to show it working was made either with a share from that NAS
    still mounted — ``smbutil`` reuses the session and needs no credentials at
    all — or with a password the server had stopped accepting. The two look
    identical from here, and telling them apart needs a password known to be
    current, which this end cannot supply. If the lend turns out not to be
    read, the remaining options are the command line (rejected above) and
    dropping authenticated listing on macOS.
    """
    if target.scheme != "smb":
        raise MountError(f"XeFM cannot list shares over {target.scheme}.")

    attempts = []
    for host in _mdns_alternatives(target.host):
        attempts.append(["-g", f"//{host}"])
        if user:
            attempts.append([f"//{user}@{host}"])
    last = "the server refused the request"
    with _lend_to_the_keychain(target, user, password):
        for args in attempts:
            try:
                proc = _run_tool(["/usr/bin/smbutil", "view", *args])
            except subprocess.TimeoutExpired:
                raise MountError(f"{target.host} did not answer.") from None
            except OSError as e:
                raise MountError(f"Could not run smbutil: {e}") from None
            if proc.returncode == 0:
                return _parse_shares(proc.stdout)
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            if detail:
                last = detail[-1]
    raise MountError(f"{target.host}: {last}", auth=True)


@contextlib.contextmanager
def _lend_to_the_keychain(target, user: str, password: str):
    """Put ``password`` where ``smbutil`` will look, for the listing only.

    **What the user just typed wins.** It is the newest thing anyone knows
    about this account, so it goes in even when the Keychain already holds
    something — and *especially* then, because what it usually holds in that
    case is a password that has stopped working. Standing aside for the stored
    one made a stale entry unfixable: the listing failed on it, the failure
    reopened the form, the password typed there was discarded in favour of the
    same stale entry, and the mount that would have saved a corrected one was
    never reached. Observed on a real NAS.

    **The Keychain is left exactly as it was found.** Whatever was there is
    read first and written back on the way out; where there was nothing, the
    lent entry is removed. Browsing a server neither leaves a credential the
    user did not ask to keep nor destroys one they did. Keeping a password is
    still the mount's job, on success, and still only when asked.
    """
    if not (password and user):
        yield
        return
    try:
        existing = load_password(target, user)
    except Exception as e:  # noqa: BLE001 — a Keychain that will not answer
        logger.warning(f"Could not read the keychain for {target.host}: {e}")
        yield
        return
    if existing == password:
        yield  # already what we would write; touching it changes nothing
        return
    save_password(target, user, password)
    try:
        yield
    finally:
        try:
            if existing:
                save_password(target, user, existing)
            else:
                forget_password(target, user)
        except Exception as e:  # noqa: BLE001
            # Loud: the user's own stored password is what is at stake, and
            # this is the one path that can lose it.
            logger.error(
                f"Could not put the keychain entry for {target.host} back as "
                f"it was: {e}")


def _parse_shares(output: str) -> list[str]:
    """Share names out of ``smbutil view``'s table.

    The columns are fixed-width and the header says where they start, so the
    offsets are read from it rather than hard-coded — and the name is sliced
    rather than split, because a share name may contain spaces while the
    Comments column beside it certainly does.
    """
    lines = output.splitlines()
    head = next((i for i, line in enumerate(lines)
                 if line.startswith("Share") and "Type" in line), -1)
    if head < 0:
        return []
    type_at = lines[head].index("Type")
    shares = []
    for line in lines[head + 1:]:
        if not line.strip() or line.startswith("-"):
            continue
        if line.lstrip()[:1].isdigit() and "shares listed" in line:
            break
        name = line[:type_at].strip()
        kind = line[type_at:].split(None, 1)
        if not name or not kind or kind[0] != "Disk":
            continue
        if name.endswith("$"):
            continue  # administrative share; Finder hides these too
        shares.append(name)
    return shares
