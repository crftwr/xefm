"""Network mounts — the platform-neutral layer.

XeFM connects to a NAS or file server by asking the **operating system** to
mount the share, not by speaking SMB itself. What comes back is an ordinary
local path (``/Volumes/photo``, ``\\\\nas\\photo``), so every other part of XeFM
— viewers, archives, file operations, external programs, the file monitor —
keeps working on it with no new cases. See ``doc/dev/NETWORK_MOUNT_SYSTEM.md``
for why this was chosen over a fourth :class:`~xefm.path.PathImpl`.

This module is the whole API the rest of XeFM uses:

- :func:`is_supported` — whether this platform can mount at all (macOS and
  Windows can; Linux cannot, and the UI hides the feature there)
- :func:`parse_address` — text -> :class:`MountTarget`, or ``None``
- :func:`list_mounts` — what is mounted now, classified
- :func:`mount` / :func:`unmount` / :func:`eject`

Platform selection is the one lazy import in :func:`_backend`. Nothing else in
XeFM branches on ``platform.system()`` for this feature.

**The Path facade is deliberately not involved.** ``Path("smb://…")`` must stay
free of side effects — the favorites picker builds a Path per row and is
required to touch nothing (issue #430) — and mounting means a network round trip
and a password prompt. Resolution happens in the dialog that asked for it, and
what reaches the rest of XeFM is the local path :func:`mount` returns.
"""

from __future__ import annotations

import platform
import re
import threading
from dataclasses import dataclass
from typing import Optional

from xefm.log_manager import getLogger

logger = getLogger("NetMount")

#: ``MountInfo.kind`` values. The Drives picker switches on these to decide
#: between disconnecting a share, ejecting a device, and doing nothing.
NETWORK = "network"
REMOVABLE = "removable"
OTHER = "other"

#: URL schemes :func:`parse_address` recognises, mapped to the canonical name.
#: A scheme being here does not mean every platform can mount it —
#: :func:`mount` reports that, with the platform named.
_SCHEME_ALIASES = {
    "smb": "smb", "cifs": "smb",
    "afp": "afp",
    "nfs": "nfs",
    "http": "http", "https": "https",
    "ftp": "ftp",
}

#: Schemes that need a share/export name before anything can be *mounted*.
#: An address without one still parses — ``smb://nas`` is a server to browse,
#: which is what :func:`list_shares` is for — but :func:`mount` refuses it.
_SHARE_REQUIRED = frozenset({"smb", "afp", "nfs"})

_URL_RE = re.compile(
    r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://"
    r"(?:(?P<user>[^/@:]+)(?::(?P<password>[^/@]*))?@)?"
    r"(?P<host>\[[0-9A-Fa-f:]+\]|[^/@:]+)"
    r"(?::(?P<port>\d+))?"
    r"(?P<path>/.*)?$"
)


class MountError(Exception):
    """A mount, unmount or eject that did not happen.

    ``auth`` marks the failures worth reopening the credential form for (a
    rejected user name or password) as opposed to the ones where retyping the
    password cannot help (no such host, no such share).
    """

    def __init__(self, message: str, *, auth: bool = False):
        super().__init__(message)
        self.auth = auth


@dataclass(frozen=True)
class MountTarget:
    """A parsed server address."""

    scheme: str
    host: str
    #: Everything after the host: the share, plus any subdirectory below it.
    #: Leading slash stripped; may be empty for WebDAV.
    share: str
    #: User name taken from the address (``smb://me@nas/photo``), if any. The
    #: form field wins over this when both are given.
    user: str = ""
    port: int = 0

    @property
    def url(self) -> str:
        """The address as the user wrote it, minus any credentials and trailing
        slash. **This is for showing and for saving**, so it keeps the case that
        was typed: a row that reads ``smb://synologynas/Videos`` when the user
        typed ``SynologyNAS`` is XeFM's bookkeeping leaking into their screen.
        Use :attr:`key` to compare two addresses."""
        host = f"{self.host}:{self.port}" if self.port else self.host
        base = f"{self.scheme}://{host}"
        return f"{base}/{self.share}" if self.share else base

    @property
    def canonical_host(self) -> str:
        """The host as an identity: lower case, and without a trailing
        ``.local``.

        Both foldings are about one machine wearing several names. DNS, mDNS
        and NetBIOS all ignore case, so ``SynologyNAS`` and ``synologynas``
        are the same host. And Bonjour answers with the mDNS name —
        ``SynologyNas.local`` — where a hand-typed address and the mount table
        both say ``synologynas``. Left unfolded, the same NAS reached two ways
        gets two rows in the list, two entries in the keychain, and a mounted
        share that the list does not recognise as mounted.
        """
        host = self.host.lower()
        return host[:-6] if host.endswith(".local") else host

    @property
    def key(self) -> str:
        """The address as an **identity**, for deduplicating saved servers, for
        naming a stored password, and for recognising a share in the mount
        table. Built on :attr:`canonical_host`; the share is left alone, since
        SMB share names preserve case and the mount path is built from them."""
        host = self.canonical_host
        host = f"{host}:{self.port}" if self.port else host
        base = f"{self.scheme}://{host}"
        return f"{base}/{self.share}" if self.share else base

    @property
    def unc(self) -> str:
        """The Windows UNC form (``\\\\nas\\photo``) of an SMB address."""
        return "\\\\" + self.host + "".join(
            "\\" + part for part in self.share.split("/") if part)


def canonical_host(host: str) -> str:
    """:attr:`MountTarget.canonical_host` for a bare host string — what the
    mount table and the discovery rows hand over."""
    host = (host or "").strip().rstrip(".").lower()
    return host[:-6] if host.endswith(".local") else host


@dataclass(frozen=True)
class MountInfo:
    """One entry of the machine's mount table, classified."""

    #: Where it is mounted — the local path a pane can be sent to.
    path: str
    #: One of :data:`NETWORK`, :data:`REMOVABLE`, :data:`OTHER`.
    kind: str
    #: What it was mounted from, as the OS reports it (``//me@nas/photo``).
    source: str = ""
    #: Filesystem type (``smbfs``, ``webdav``, …); informational.
    fstype: str = ""


# --- platform selection ------------------------------------------------------

_backend_lock = threading.Lock()
_backend_cache: list = []  # one slot; [] = not resolved yet


def _backend():
    """The platform module, or ``None`` where there is no mounting to do.

    Resolved once, lazily: importing it pulls in ``ctypes``/``pyobjc`` and
    probes system libraries, which should not happen at XeFM startup for a
    feature the user may never open.
    """
    with _backend_lock:
        if _backend_cache:
            return _backend_cache[0]
        module = None
        system = platform.system()
        try:
            if system == "Darwin":
                from xefm import netmount_macos as module  # noqa: F401
            elif system == "Windows":
                from xefm import netmount_windows as module  # noqa: F401
        except Exception as e:
            logger.error(f"Network mount support unavailable: {e}")
            module = None
        if module is not None and not module.is_available():
            logger.info(f"Network mount support unavailable on {system}")
            module = None
        _backend_cache.append(module)
        return module


def is_supported() -> bool:
    """Whether this machine can mount network shares from XeFM. False on Linux,
    and on a macOS/Windows where the system library could not be loaded — the
    UI hides the feature rather than failing at the point of use."""
    return _backend() is not None


def supported_schemes() -> tuple[str, ...]:
    """The URL schemes this platform can actually mount, for the form's help
    line. Empty where mounting is unsupported."""
    backend = _backend()
    return backend.SCHEMES if backend is not None else ()


# --- addresses ---------------------------------------------------------------

def parse_address(text: str) -> Optional[MountTarget]:
    """Parse a server address, or return ``None`` if it is not one.

    Accepts a URL (``smb://me@nas/photo``) and a UNC path (``\\\\nas\\photo``,
    or ``//nas/photo``). The share may be missing (``smb://nas``): that is a
    *server*, which the picker browses for its shares rather than mounts.

    Returning ``None`` for everything else is load-bearing, not defensive: the
    Connect picker hands its filter text here to decide whether **Enter** on an
    unmatched query means "connect to this" or "nothing matched". A bare word, a
    local path and a half-typed URL must all be rejected.

    A password written into the address is parsed and **dropped** — it is not
    carried into :class:`MountTarget`, so it cannot reach a saved server entry
    or a log line. The user retypes it in the form's masked field.
    """
    if not text:
        return None
    text = text.strip()
    if not text:
        return None

    if text.startswith("\\\\") or text.startswith("//"):
        rest = text[2:].replace("\\", "/")
        parts = [p for p in rest.split("/") if p]
        if not parts:
            return None
        host, share = parts[0], "/".join(parts[1:])
        user = ""
        if "@" in host:  # //me@nas/photo, as macOS writes it
            user, _, host = host.rpartition("@")
        if not host or not share:
            return None
        return MountTarget(scheme="smb", host=host, share=share, user=user)

    m = _URL_RE.match(text)
    if m is None:
        return None
    scheme = _SCHEME_ALIASES.get(m.group("scheme").lower())
    if scheme is None:
        return None
    host = m.group("host")
    if not host:
        return None
    share = (m.group("path") or "").strip("/")
    port = int(m.group("port")) if m.group("port") else 0
    # The host keeps the case it was typed in; see MountTarget.key for where
    # it is folded and why that is not the same place.
    return MountTarget(scheme=scheme, host=host, share=share,
                       user=m.group("user") or "", port=port)


def looks_like_address(text: str) -> bool:
    """Whether ``text`` should be treated as a server address rather than as
    filter text. Thin wrapper over :func:`parse_address`, named for the one
    place that asks the question."""
    return parse_address(text) is not None


# --- the mount table ---------------------------------------------------------

def list_mounts() -> list[MountInfo]:
    """Everything mounted right now, classified.

    **Called on the UI thread** — when the Drives dialog opens, and again when a
    row is acted on. It must stay cheap: one syscall on macOS, the mount table
    on Windows. No ``diskutil``, no ``net use``, nothing per row.
    """
    backend = _backend()
    if backend is None:
        return []
    try:
        return backend.list_mounts()
    except Exception as e:
        logger.error(f"Could not read the mount table: {e}")
        return []


def classify(path: str) -> Optional[MountInfo]:
    """The :class:`MountInfo` for ``path``, or ``None`` if it is not a mount
    point. Matching is exact: a directory *inside* a volume is not the volume,
    and disconnecting it would be wrong."""
    if not path:
        return None
    wanted = path.rstrip("/\\").lower() or path
    for info in list_mounts():
        if (info.path.rstrip("/\\").lower() or info.path) == wanted:
            return info
    return None


# --- finding servers and shares ----------------------------------------------

@dataclass(frozen=True)
class DiscoveredServer:
    """A file server the machine can see on the local network.

    ``name`` is what the server advertises itself as, and is what the picker
    shows — the string Finder's Network view puts on screen. ``host`` is what
    XeFM connects to, and the two are often **not** the same: a Mac announces
    "Anna's MacBook Pro" while answering to ``Annas-MacBook-Pro.local``. A
    server is only reported once the second one is known, so every row in the
    list is a row that can be opened.
    """

    name: str
    host: str
    scheme: str = "smb"

    @property
    def target(self) -> "MountTarget":
        """The server as a share-less address, ready to be browsed."""
        return MountTarget(scheme=self.scheme, host=self.host, share="")


def can_discover() -> bool:
    """Whether this platform can look for servers at all.

    Discovery is the part that degrades: macOS browses Bonjour, Windows asks
    the network provider and may well get nothing back (modern Windows dropped
    the browser service in favour of WS-Discovery). The UI treats an empty
    answer as "found none" either way.
    """
    backend = _backend()
    return backend is not None and hasattr(backend, "discover_servers")


def discover_servers(cancel: threading.Event):
    """Yield :class:`DiscoveredServer` s as they are found, until ``cancel``.

    Runs on the picker's background loader thread, exactly like the S3 bucket
    scan: the dialog is already open and rows arrive underneath it. Discovery
    has no natural end — a NAS that wakes up ten seconds later is a new row —
    so this runs until the dialog closes and sets ``cancel``.

    Best effort in every direction: no discovery support, a missing framework
    or a silent network all end the scan with whatever was found by then.
    """
    backend = _backend()
    if backend is None or not hasattr(backend, "discover_servers"):
        return
    try:
        yield from backend.discover_servers(cancel)
    except Exception as e:
        logger.warning(f"Looking for servers stopped: {e}")


def list_shares(target: MountTarget, user: str = "") -> list[str]:
    """The shares ``target``'s server offers, for the picker that follows
    choosing a server.

    Tried as a **guest** first, and then — where an account is known — as that
    account. There is no password parameter on purpose: neither platform's tool
    will take one safely (see the system doc), and neither needs to. macOS
    looks the account up in the login Keychain, Windows uses the session's own
    credentials. So what makes an authenticated listing possible is XeFM
    knowing *which account*, not knowing the password.

    A server that answers neither way raises :class:`MountError`, and the
    caller falls back to letting the user type the share name. Administrative
    shares (``C$``, ``IPC$``) are left out, as they are in Finder and Explorer.

    Blocks on the network; call it from a worker.
    """
    backend = _backend()
    if backend is None:
        raise MountError("Listing shares is not available on this system.")
    return backend.list_shares(target, user)


# --- operations --------------------------------------------------------------

def mount(target: MountTarget, user: str = "", password: str = "", *,
          drive_letter: str = "", cancel: Optional[threading.Event] = None) -> str:
    """Mount ``target`` and return **the path it actually landed on**.

    The returned path is not always derivable from the address: macOS appends a
    suffix when the name is taken (a second ``photo`` share becomes
    ``/Volumes/photo-1``). Callers navigate to what this returns, never to a
    path they built themselves.

    ``drive_letter`` is Windows-only and empty by default — a connection is
    deviceless (the UNC path works, no letter consumed) unless one is asked for.

    ``cancel`` is checked around the blocking call. Neither platform's mount can
    be interrupted once it is in flight (see the system doc), so a cancelled
    request that nevertheless succeeds is **undone**: the share is unmounted
    again and :class:`MountError` is raised. The user never ends up holding a
    mount they cancelled.

    Blocks for as long as the network takes. Never call it on the UI thread.
    """
    backend = _backend()
    if backend is None:
        raise MountError("Connecting to a server is not available on this system.")
    if target.scheme not in backend.SCHEMES:
        raise MountError(
            f"{target.scheme}:// cannot be mounted on {platform.system()}.")
    if target.scheme in _SHARE_REQUIRED and not target.share:
        # The flow browses a share-less address instead of mounting it; this is
        # the guard for anything that reaches here another way.
        raise MountError(f"Choose a share on {target.host}.")

    path = backend.mount(target, user=user, password=password,
                         drive_letter=drive_letter)

    if cancel is not None and cancel.is_set():
        # It landed after the user gave up on it. Undo it rather than leaving a
        # mount nobody asked for; a failure to undo is logged, not raised over
        # the cancellation the caller is already reporting.
        try:
            backend.unmount(path)
        except Exception as e:
            logger.warning(f"Could not undo the cancelled mount at {path}: {e}")
        raise MountError("Cancelled.")
    logger.info(f"Mounted {target.url} at {path}")
    return path


def unmount(path: str) -> None:
    """Disconnect the volume mounted at ``path``. Raises :class:`MountError`
    with the operating system's own words when something is still using it."""
    backend = _backend()
    if backend is None:
        raise MountError("Disconnecting is not available on this system.")
    backend.unmount(path)
    logger.info(f"Disconnected {path}")


def eject(path: str) -> None:
    """Eject the removable volume mounted at ``path``, so the device is safe to
    unplug. Raises :class:`MountError` if something is still using it."""
    backend = _backend()
    if backend is None:
        raise MountError("Ejecting is not available on this system.")
    backend.eject(path)
    logger.info(f"Ejected {path}")


# --- stored passwords --------------------------------------------------------

def save_password(target: MountTarget, user: str, password: str) -> bool:
    """Store ``password`` in the operating system's credential store — the login
    Keychain on macOS, Credential Manager on Windows. Never in the config file,
    and never in XeFM's own state.

    Returns whether it was stored. A failure here is not worth failing a
    successful connection over, so it is reported by the return value and
    logged, not raised.
    """
    backend = _backend()
    if backend is None or not password:
        return False
    try:
        backend.save_password(target, user, password)
        return True
    except Exception as e:
        logger.warning(f"Could not save the password for {target.url}: {e}")
        return False


def load_password(target: MountTarget, user: str) -> str:
    """The stored password for this server and account, or ``""``. Used to
    prefill the form, so a saved server reconnects without retyping."""
    backend = _backend()
    if backend is None:
        return ""
    try:
        return backend.load_password(target, user)
    except Exception as e:
        logger.warning(f"Could not read the password for {target.url}: {e}")
        return ""


def forget_password(target: MountTarget, user: str) -> None:
    """Delete the stored password, if there is one. Called when a saved server
    is forgotten; a failure is logged and does not block the removal."""
    backend = _backend()
    if backend is None:
        return
    try:
        backend.forget_password(target, user)
    except Exception as e:
        logger.warning(f"Could not delete the password for {target.url}: {e}")


def reset_backend_cache() -> None:
    """Forget the resolved platform module. Tests only — nothing in the app
    changes platform mid-run."""
    with _backend_lock:
        _backend_cache.clear()
