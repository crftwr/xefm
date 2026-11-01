"""Open With: the applications that can open a set of files (#634).

Two sources, merged into one list — XeFM's own entries first:

* **XeFM's entries** — the ``open_with`` lists of the FILE_ASSOCIATIONS rules a
  file matches (:func:`xefm.config.get_open_with_for_file`). Commands, so they
  work the same in a terminal, over SSH and in the desktop app.
* **The OS's applications** — what Finder's or Explorer's *Open With* lists:
  ``NSWorkspace`` on macOS, ``SHAssocEnumHandlers`` on Windows, the desktop's
  MIME database through ``gio`` on Linux. Only where those applications can
  reach the user (:func:`os_apps_available`).

For several files only the candidates that fit **every** file are offered —
the strict intersection Finder uses for a mixed selection. A candidate is the
same across files when its :attr:`Candidate.key` is: the entry's name for
XeFM's entries, the bundle ID / handler / desktop ID for the OS's.

Nothing here touches the UI; :meth:`xefm.app.XeFMApp.open_with` owns the picker
and the launch of XeFM's entries.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from xefm.config import get_open_with_for_file
from xefm.log_manager import getLogger

logger = getLogger("OpenWith")

XEFM = "xefm"
OS = "os"


@dataclass(frozen=True)
class Candidate:
    """One row of the Open With list."""

    #: Identity across files: ``"xefm:<name>"`` or ``"os:<app id>"``.
    key: str
    #: What the list shows.
    name: str
    #: :data:`XEFM` or :data:`OS`.
    source: str
    #: The command line or the application's path, for the detail row.
    detail: str = ""
    #: The OS default application for every file in the set.
    default: bool = False
    #: XeFM's entry (``name`` / ``command`` / ``options``), for :data:`XEFM`.
    program: Optional[dict] = field(default=None, compare=False)
    #: What :func:`launch` needs to start an OS application.
    handle: Any = field(default=None, compare=False)


def intersect(per_file: list[list[Candidate]]) -> list[Candidate]:
    """The candidates present for every file, in the first file's order and
    with its entries — so a name that two rules declare differently runs the
    first file's command. ``default`` survives only where it held for all."""
    if not per_file:
        return []
    common = set.intersection(*({c.key for c in cands} for cands in per_file))
    default_everywhere = set.intersection(
        *({c.key for c in cands if c.default} for cands in per_file))
    out = []
    for cand in per_file[0]:
        if cand.key in common:
            if cand.default and cand.key not in default_everywhere:
                cand = Candidate(cand.key, cand.name, cand.source, cand.detail,
                                 False, cand.program, cand.handle)
            out.append(cand)
    return out


def xefm_candidates(names: Iterable[str]) -> list[Candidate]:
    """XeFM's entries that every one of ``names`` (file names) is offered."""
    per_file = []
    for name in names:
        per_file.append([
            Candidate(f"{XEFM}:{prog['name']}", str(prog['name']), XEFM,
                      detail=" ".join(str(a) for a in prog['command']),
                      program=prog)
            for prog in get_open_with_for_file(name)])
    return intersect(per_file)


def os_apps_available(desktop: bool, env: Optional[dict] = None) -> bool:
    """Whether the OS's applications mean anything to the user: always in the
    desktop app; in a terminal only when it runs on the machine the user sits
    at — not over SSH, where the applications are on another machine — and,
    on Linux, only with a graphical session to show them in."""
    if desktop:
        return True
    env = os.environ if env is None else env
    if any(env.get(var) for var in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return False
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def _type_of(path: str) -> str:
    """What the OS's answer depends on — the extension, lowercased — so a
    selection of a hundred photos asks once."""
    return os.path.splitext(path)[1].lower()


def os_candidates(paths: list[str]) -> list[Candidate]:
    """The OS's applications that open every one of ``paths``, asked once per
    file type. Empty — having logged why — when the OS cannot be asked."""
    lister = _PLATFORM_LISTERS.get(sys.platform if sys.platform in _PLATFORM_LISTERS
                                   else "linux")
    by_type: dict[str, list[Candidate]] = {}
    try:
        for path in paths:
            kind = _type_of(path)
            if kind not in by_type:
                by_type[kind] = lister(path)
    except Exception as exc:
        logger.warning(f"Could not ask the OS which apps open {os.path.basename(path)}: {exc}")
        return []
    return intersect(list(by_type.values()))


def launch(candidate: Candidate, paths: list[str]) -> None:
    """Open ``paths`` in the OS application ``candidate``, in one launch,
    without waiting for it. Raises ``OSError`` when it could not be started."""
    if sys.platform == "win32":
        _windows_invoke(candidate.handle, paths)
        return
    if sys.platform == "darwin":
        argv = ["open", "-a", candidate.handle, *paths]
    else:
        argv = ["gio", "launch", candidate.handle, *paths]
    # Detached and silent: in a terminal the child must not write over the
    # screen we own, and nothing here waits for it.
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def remembered_first(candidates: list[Candidate], key: Optional[str]) -> list[Candidate]:
    """``candidates`` with the one last chosen for this file type moved to the
    top, the rest in their order."""
    for i, cand in enumerate(candidates):
        if cand.key == key:
            return [cand, *candidates[:i], *candidates[i + 1:]]
    return candidates


def type_key(paths: Iterable[str]) -> str:
    """The key the last choice is remembered under: the selection's distinct
    extensions, sorted — so ``.jpg`` alone and ``.jpg`` with ``.pdf`` are
    remembered apart, as they offer different lists."""
    return ",".join(sorted({_type_of(p) for p in paths}))


# --- macOS -------------------------------------------------------------------

def _macos_apps(path: str) -> list[Candidate]:
    import AppKit
    import Foundation
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    url = Foundation.NSURL.fileURLWithPath_(path)
    default = workspace.URLForApplicationToOpenURL_(url)
    default_path = str(default.path()) if default is not None else None
    if hasattr(workspace, "URLsForApplicationsToOpenURL_"):   # macOS 12+
        urls = list(workspace.URLsForApplicationsToOpenURL_(url) or [])
    else:
        urls = [default] if default is not None else []
    manager = Foundation.NSFileManager.defaultManager()
    out, seen = [], set()
    for app_url in urls:
        app_path = str(app_url.path())
        bundle = Foundation.NSBundle.bundleWithURL_(app_url)
        ident = (bundle.bundleIdentifier() if bundle is not None else None) or app_path
        # A second copy of one app (Xcode and Xcode-beta's tools, an app in
        # ~/Applications and /Applications) lists once, as Finder does.
        if ident in seen:
            continue
        seen.add(ident)
        out.append(Candidate(f"{OS}:{ident}", str(manager.displayNameAtPath_(app_path)),
                             OS, detail=app_path, default=app_path == default_path,
                             handle=app_path))
    return out


# --- Windows -----------------------------------------------------------------

_ASSOC_FILTER_RECOMMENDED = 0x1
_ASSOCSTR_EXECUTABLE = 2
_win_types: Optional[dict] = None


def _windows_types() -> dict:
    """The COM interfaces Open With needs, declared once. ``comtypes`` has no
    typelib for them: they live in shell32's headers only."""
    global _win_types
    if _win_types is not None:
        return _win_types
    import ctypes
    from ctypes import POINTER, c_int, c_ulong, c_void_p, c_wchar_p

    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IAssocHandler(IUnknown):
        _iid_ = GUID("{F04061AC-1659-4A3F-A954-775AA57FC083}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetName", (["out"], POINTER(c_void_p), "ppsz")),
            COMMETHOD([], HRESULT, "GetUIName", (["out"], POINTER(c_void_p), "ppsz")),
            COMMETHOD([], HRESULT, "GetIconLocation",
                      (["out"], POINTER(c_void_p), "ppszPath"),
                      (["out"], POINTER(c_int), "pIndex")),
            COMMETHOD([], HRESULT, "IsRecommended"),
            COMMETHOD([], HRESULT, "MakeDefault", (["in"], c_wchar_p, "pszDescription")),
            COMMETHOD([], HRESULT, "Invoke", (["in"], POINTER(IUnknown), "pdo")),
            COMMETHOD([], HRESULT, "CreateInvoker",
                      (["in"], POINTER(IUnknown), "pdo"),
                      (["out"], POINTER(POINTER(IUnknown)), "ppInvoker")),
        ]

    class IEnumAssocHandlers(IUnknown):
        _iid_ = GUID("{973810AE-9599-4B88-9E4D-6EE98C9552DA}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Next",
                      (["in"], c_ulong, "celt"),
                      (["out"], POINTER(POINTER(IAssocHandler)), "rgelt"),
                      (["out"], POINTER(c_ulong), "pceltFetched")),
        ]

    class IShellItemArray(IUnknown):
        # Only the first method is ever called, so the rest of the vtable is
        # left undeclared.
        _iid_ = GUID("{B63EA76D-1F85-456F-A19C-48159EFA858B}")
        _methods_ = [
            COMMETHOD([], HRESULT, "BindToHandler",
                      (["in"], c_void_p, "pbc"),
                      (["in"], POINTER(GUID), "bhid"),
                      (["in"], POINTER(GUID), "riid"),
                      (["out"], POINTER(POINTER(IUnknown)), "ppvOut")),
        ]

    shell32, shlwapi, ole32 = ctypes.oledll.shell32, ctypes.oledll.shlwapi, ctypes.windll.ole32
    shell32.SHAssocEnumHandlers.argtypes = [c_wchar_p, c_int,
                                            POINTER(POINTER(IEnumAssocHandlers))]
    shell32.SHParseDisplayName.argtypes = [c_wchar_p, c_void_p, POINTER(c_void_p),
                                           c_ulong, c_void_p]
    shell32.SHCreateShellItemArrayFromIDLists.argtypes = [
        c_ulong, POINTER(c_void_p), POINTER(POINTER(IShellItemArray))]
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    ole32.CoTaskMemFree.restype = None
    _win_types = {
        "ctypes": ctypes, "comtypes": comtypes, "GUID": GUID,
        "IEnumAssocHandlers": IEnumAssocHandlers, "IShellItemArray": IShellItemArray,
        "shell32": shell32, "shlwapi": shlwapi, "ole32": ole32,
    }
    return _win_types


def _windows_com_ready(t: dict) -> None:
    """COM is per thread, and this runs on the UI thread, which ``comtypes``
    initialized only if it was first imported there. Initialized once and left
    so: the handlers live until the picker closes."""
    try:
        t["comtypes"].CoInitialize()
    except OSError:
        pass    # already initialized in another mode — usable as it is


def _windows_take_string(t: dict, ptr) -> str:
    if not ptr:
        return ""
    try:
        return t["ctypes"].wstring_at(ptr)
    finally:
        t["ole32"].CoTaskMemFree(ptr)


def _windows_default_exe(t: dict, ext: str) -> str:
    ctypes = t["ctypes"]
    size = ctypes.c_ulong(1024)
    buf = ctypes.create_unicode_buffer(size.value)
    try:
        t["shlwapi"].AssocQueryStringW(0, _ASSOCSTR_EXECUTABLE, ext, "open",
                                       buf, ctypes.byref(size))
    except OSError:
        return ""
    return buf.value


def _windows_apps(path: str) -> list[Candidate]:
    ext = _type_of(path)
    if not ext:
        return []   # Windows associates by extension; with none there is nothing to ask
    t = _windows_types()
    _windows_com_ready(t)
    ctypes = t["ctypes"]
    enum = ctypes.POINTER(t["IEnumAssocHandlers"])()
    t["shell32"].SHAssocEnumHandlers(ext, _ASSOC_FILTER_RECOMMENDED, ctypes.byref(enum))
    default_exe = _windows_default_exe(t, ext).lower()
    out, seen = [], set()
    while True:
        handler, fetched = enum.Next(1)
        if not fetched or not handler:
            break
        # GetName is the handler's program — the executable's path for a
        # desktop app — which is what makes .jpg's Photos and .png's Photos
        # the same candidate.
        ident = _windows_take_string(t, handler.GetName())
        if not ident or ident.lower() in seen:
            continue
        seen.add(ident.lower())
        name = _windows_take_string(t, handler.GetUIName()) or os.path.basename(ident)
        out.append(Candidate(f"{OS}:{ident.lower()}", name, OS, detail=ident,
                             default=bool(default_exe) and ident.lower() == default_exe,
                             handle=handler))
    return out


def _windows_invoke(handler, paths: list[str]) -> None:
    """Hand every path to ``handler`` at once, as Explorer's Open With does:
    through a data object built from the files' shell items."""
    t = _windows_types()
    ctypes = t["ctypes"]
    GUID = t["GUID"]
    pidls = (ctypes.c_void_p * len(paths))()
    try:
        for i, path in enumerate(paths):
            # An array element reads back as a plain int, so parse into a
            # c_void_p of its own and store its value.
            pidl = ctypes.c_void_p()
            t["shell32"].SHParseDisplayName(path, None, ctypes.byref(pidl), 0, None)
            pidls[i] = pidl.value
        items = ctypes.POINTER(t["IShellItemArray"])()
        t["shell32"].SHCreateShellItemArrayFromIDLists(len(paths), pidls,
                                                       ctypes.byref(items))
        data = items.BindToHandler(None, GUID("{B8C0BD9F-ED24-455C-83E6-D5390C4FE8C4}"),
                                   GUID("{0000010E-0000-0000-C000-000000000046}"))
        handler.Invoke(data)
    finally:
        for pidl in pidls:
            if pidl:
                t["ole32"].CoTaskMemFree(pidl)


# --- Linux and other freedesktop systems -------------------------------------

def _gio(*args: str) -> str:
    # LC_ALL=C: gio translates its headings, which are what is parsed.
    env = dict(os.environ, LC_ALL="C")
    return subprocess.run(["gio", *args], capture_output=True, text=True,
                          env=env, timeout=5, check=True).stdout


def _desktop_dirs() -> list[str]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [os.path.join(d, "applications") for d in [home, *dirs.split(":")] if d]


def _desktop_file(desktop_id: str) -> Optional[str]:
    """Where a desktop ID's file is: ``a-b.desktop`` may also be ``a/b.desktop``."""
    names = [desktop_id]
    if "-" in desktop_id:
        names.append(desktop_id.replace("-", "/", 1))
    for directory in _desktop_dirs():
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _desktop_name(desktop_path: str, fallback: str) -> str:
    try:
        with open(desktop_path, encoding="utf-8", errors="replace") as f:
            in_entry = False
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    in_entry = line == "[Desktop Entry]"
                elif in_entry and line.startswith("Name="):
                    return line[len("Name="):].strip() or fallback
    except OSError:
        pass
    return fallback


def parse_gio_mime(text: str) -> tuple[Optional[str], list[str]]:
    """``gio mime <type>``'s answer as ``(default ID, [registered IDs])``."""
    default, ids, section = None, [], None
    for line in text.splitlines():
        if line.startswith("Default application"):
            value = line.rsplit(":", 1)[-1].strip()
            default = value or None
        elif line.startswith(("Registered applications", "Recommended applications")):
            section = line
        elif line.startswith("\t") and section and line.strip() not in ids:
            ids.append(line.strip())
    if default and default not in ids:
        ids.insert(0, default)
    return default, ids


def _linux_apps(path: str) -> list[Candidate]:
    info = _gio("info", "--attributes=standard::content-type", path)
    mime = next((line.split(":", 3)[-1].strip() for line in info.splitlines()
                 if "standard::content-type:" in line), "")
    if not mime:
        return []
    default, ids = parse_gio_mime(_gio("mime", mime))
    out = []
    for desktop_id in ids:
        desktop_path = _desktop_file(desktop_id)
        if desktop_path is None:
            continue
        fallback = desktop_id[:-len(".desktop")] if desktop_id.endswith(".desktop") else desktop_id
        out.append(Candidate(f"{OS}:{desktop_id}", _desktop_name(desktop_path, fallback),
                             OS, detail=desktop_path, default=desktop_id == default,
                             handle=desktop_path))
    return out


_PLATFORM_LISTERS: dict[str, Callable[[str], list[Candidate]]] = {
    "darwin": _macos_apps,
    "win32": _windows_apps,
    "linux": _linux_apps,
}
