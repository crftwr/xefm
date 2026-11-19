"""Fetch libghostty-vt into an application bundle (discussion #900).

XeFM's terminal is PuiKit's TerminalView, which runs on libghostty-vt. The
desktop bundles ship the library inside their copy of PuiKit, at
``puikit/_bin/``, where ``puikit._ghostty`` looks for it; nothing per-user is
searched, so a bundle without it has no terminal of its own: the subshell and
terminal programs do not start in it.

The library comes from Ghostty's official release on release.files.ghostty.org,
pinned by version and SHA-256 per asset (a Store submission must be
reproducible, and a cached download is checked as strictly as a fresh one):

- ``macos``: the xcframework carries only a static universal
  ``libghostty-vt.a``; it is linked into ``libghostty-vt.dylib`` (both
  slices) with the system clang. The app build thins and signs it with the
  rest of the bundle's Mach-O files.
- ``windows-x64`` / ``windows-arm64``: the ``*-windows-gnu.zip`` carries
  ``ghostty-vt.dll``, which imports only system DLLs and the UCRT.

Linux has no prebuilt library and needs none: XeFM runs in terminal mode there,
where the terminal it was started in runs the subshell.

The license texts the bundle's notices need are in tools/licenses/libghostty/
(:func:`notices` lists them with their display names).

    python tools/fetch_libghostty.py --target macos --dest XeFM.app/.../puikit/_bin
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

#: Must be the release the bundled PuiKit's binding is written for
#: (``LIBGHOSTTY_VERSION`` in puikit/_ghostty.py); :func:`main` refuses to build
#: otherwise. Moving it means new hashes in PINS, and a new look at what is
#: compiled in (tools/licenses/libghostty/README.md).
VERSION = "1.0.1"
BASE = f"https://release.files.ghostty.org/libghostty-vt/{VERSION}"

#: target -> (asset, SHA-256 of the asset, member to take, file it becomes)
PINS = {
    "macos": (
        f"ghostty-vt-{VERSION}.xcframework.zip",
        "c0f9631277f726154c8f521954d17cdc41aac4626fc0df8cf925a19ee58e829b",
        "ghostty-vt.xcframework/macos-arm64_x86_64/libghostty-vt.a",
        "libghostty-vt.dylib",
    ),
    "windows-x64": (
        f"ghostty-vt-{VERSION}-x86_64-windows-gnu.zip",
        "8e2eb9e1822e85d786b456c8beb86f49d09c318c91f0c2913f91e7ffa12cda29",
        f"ghostty-vt-{VERSION}-x86_64-windows-gnu/bin/ghostty-vt.dll",
        "ghostty-vt.dll",
    ),
    "windows-arm64": (
        f"ghostty-vt-{VERSION}-aarch64-windows-gnu.zip",
        "cc61da5f968ea0b08639bdf019c6b7da46bad1d985774fd8a2de57af32862892",
        f"ghostty-vt-{VERSION}-aarch64-windows-gnu/bin/ghostty-vt.dll",
        "ghostty-vt.dll",
    ),
}

LICENSE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "licenses", "libghostty")


def notices() -> list[tuple[str, str]]:
    """(display name, license file) for the bundle's THIRD_PARTY_NOTICES."""
    return [
        (f"libghostty-vt {VERSION} (MIT License)", "ghostty-LICENSE.txt"),
        ("simdutf, compiled into libghostty-vt (MIT License)", "simdutf-LICENSE-MIT.txt"),
        ("Highway, compiled into libghostty-vt (Apache License 2.0 or BSD 3-Clause License)",
         "highway-LICENSE.txt"),
        ("Wuffs, compiled into libghostty-vt (MIT License)", "wuffs-LICENSE-MIT.txt"),
    ]


def puikit_declared_version() -> str:
    """``LIBGHOSTTY_VERSION`` of the PuiKit this Python would bundle, read from
    its source without importing it."""
    spec = importlib.util.find_spec("puikit")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("PuiKit is not importable here; the bundle copies the installed one.")
    path = os.path.join(list(spec.submodule_search_locations)[0], "_ghostty.py")
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except OSError:
        raise SystemExit(f"{path} is missing: this PuiKit has no TerminalView to bundle for.")
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == "LIBGHOSTTY_VERSION"):
            return ast.literal_eval(node.value)
    raise SystemExit(f"{path} declares no LIBGHOSTTY_VERSION: this PuiKit predates "
                     "bundled libghostty and would not look in puikit/_bin/.")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(asset: str, expected: str, cache: str) -> str:
    """The asset in ``cache``, downloaded if absent or not matching its pin."""
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, asset)
    if os.path.exists(path) and sha256(path) != expected:
        print(f"cached {asset} has the wrong hash; downloading again")
        os.remove(path)
    if not os.path.exists(path):
        url = f"{BASE}/{asset}"
        print(f"downloading {url}")
        # The host refuses urllib's default User-Agent.
        req = urllib.request.Request(url, headers={"User-Agent": "fetch-libghostty"})
        with urllib.request.urlopen(req) as resp, open(path + ".part", "wb") as out:
            shutil.copyfileobj(resp, out)
        os.replace(path + ".part", path)
    got = sha256(path)
    if got != expected:
        os.remove(path)
        raise SystemExit(f"SHA-256 mismatch for {asset}\n  expected {expected}\n  got      {got}")
    return path


#: The oldest macOS the xcframework's objects were built for (their
#: LC_BUILD_VERSION). The dylib is linked for the app's floor, which must not be
#: older: linked with no target, clang stamps the host's version on it, and the
#: app would refuse to load it (and raise its own floor to match) on anything
#: older than the build machine.
MACOS_OBJECTS_MIN = "13.0"


def fetch(target: str, dest: str, cache: str, macos_min: str = MACOS_OBJECTS_MIN) -> str:
    """Put the library for ``target`` in ``dest``; return its path."""
    asset, expected, member, name = PINS[target]
    archive = download(asset, expected, cache)
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, name)
    with zipfile.ZipFile(archive) as z, tempfile.TemporaryDirectory() as tmp:
        src = z.extract(member, tmp)
        if target == "macos":
            subprocess.run(["clang", "-dynamiclib", "-arch", "arm64", "-arch", "x86_64",
                            f"-mmacosx-version-min={macos_min}",
                            "-Wl,-all_load", src, "-o", out,
                            "-install_name", "@rpath/libghostty-vt.dylib"], check=True)
        else:
            shutil.copyfile(src, out)
    return out


def loadable_here(target: str) -> bool:
    """Whether this host can load ``target``'s library (same OS and, on
    Windows, the same architecture - a cross build cannot)."""
    if target == "macos":
        return sys.platform == "darwin"
    if sys.platform != "win32":
        return False
    import platform
    arm = platform.machine().lower() in ("arm64", "aarch64")
    return target == ("windows-arm64" if arm else "windows-x64")


def check(path: str) -> None:
    """Load the library and look up the calls PuiKit binds first, so a
    truncated or wrong file stops the build instead of shipping an app whose
    terminal quietly goes missing."""
    import ctypes
    try:
        lib = ctypes.CDLL(path)
        for symbol in ("ghostty_terminal_new", "ghostty_terminal_free",
                       "ghostty_render_state_new", "ghostty_key_encoder_new"):
            getattr(lib, symbol)
        lib.ghostty_version.restype = ctypes.c_char_p
        lib.ghostty_version.argtypes = []
        reported = (lib.ghostty_version() or b"").decode("utf-8", "replace")
    except (OSError, AttributeError) as exc:
        raise SystemExit(f"{path} does not load as libghostty-vt: {exc}")
    if reported != VERSION:
        raise SystemExit(f"{path} reports libghostty-vt {reported!r}, not the pinned {VERSION}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", choices=sorted(PINS))
    ap.add_argument("--dest", help="directory to put the library in")
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "xefm-libghostty"),
                    help="where downloads are kept between builds")
    ap.add_argument("--macos-min", default=MACOS_OBJECTS_MIN,
                    help="deployment target the macOS dylib is linked for (the app's floor)")
    ap.add_argument("--print-notices", action="store_true",
                    help="print 'name=path' per license, one per line, and exit")
    args = ap.parse_args(argv)
    if args.print_notices:
        for name, file in notices():
            print(f"{name}={os.path.join(LICENSE_DIR, file)}")
        return 0
    if not (args.target and args.dest):
        ap.error("--target and --dest are required")
    wanted = puikit_declared_version()
    if wanted != VERSION:
        raise SystemExit(f"The bundled PuiKit is written for libghostty-vt {wanted}, but this "
                         f"tool pins {VERSION}. Pin {wanted} (VERSION and PINS) to bundle it.")
    if tuple(map(int, args.macos_min.split("."))) < tuple(map(int, MACOS_OBJECTS_MIN.split("."))):
        ap.error(f"--macos-min {args.macos_min} is older than the library's objects "
                 f"({MACOS_OBJECTS_MIN})")
    out = fetch(args.target, args.dest, args.cache, args.macos_min)
    if loadable_here(args.target):
        check(out)
        print(f"installed {out} (loads)")
    else:
        print(f"installed {out} (another platform's; not loaded here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
