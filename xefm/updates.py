"""The Help menu's ways out of XeFM: the documentation, the release notes, a
bug report already filled in, and Check for Updates.

Everything here is a pure function of what it is handed, so tests can stand in
for the running install; the app opens the URLs and shows the dialogs.

**How XeFM was installed** decides what "update" means, and it is read from
where the ``xefm`` package sits, never asked of the user:

- ``msix`` - the Microsoft Store keeps it current, so Check for Updates is not
  offered at all.
- ``zip`` / ``dmg`` - the Windows and macOS app bundles copy the package in
  with no ``.dist-info``; the new version is a download.
- ``cask`` - the macOS app bundle, put there by ``brew install --cask``.
- ``formula`` / ``pipx`` / ``uv`` / ``pip`` - an installed distribution; the
  new version is one command.
- ``source`` - a checkout (the package's parent holds ``pyproject.toml``).

**Check for Updates** reads PyPI's JSON for ``xefm`` - every channel publishes
the same version there first - on a worker thread, and only when the user asks:
XeFM never looks on its own (PRIVACY.md). A final release is compared with
final releases only; a pre-release also with later pre-releases, since whoever
runs one asked for them.
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from typing import Callable

from xefm.const import GITHUB_URL, VERSION

DOCS_URL = "https://crftwr.github.io/xefm/"
PYPI_JSON_URL = "https://pypi.org/pypi/xefm/json"
RELEASES_URL = f"{GITHUB_URL}/releases"

#: The bug report form's ``install`` dropdown, by install kind. The labels
#: must match .github/ISSUE_TEMPLATE/bug_report.yml word for word - GitHub
#: selects a dropdown option only on an exact match.
_ISSUE_INSTALL_LABELS = {
    "msix": "Microsoft Store (Windows desktop app)",
    "zip": "Portable zip (Windows desktop app)",
    "dmg": "DMG (macOS desktop app)",
    "cask": "DMG (macOS desktop app)",
    "pip": "pip / pipx / uv (terminal app)",
    "pipx": "pip / pipx / uv (terminal app)",
    "uv": "pip / pipx / uv (terminal app)",
    "formula": "Homebrew (terminal app)",
    "source": "From source",
}

_CASKROOMS = ("/opt/homebrew/Caskroom/xefm", "/usr/local/Caskroom/xefm")


def _has_distribution() -> bool:
    try:
        metadata.distribution("xefm")
    except metadata.PackageNotFoundError:
        return False
    return True


def install_kind(package_dir: str | None = None, platform: str | None = None,
                 has_distribution: bool | None = None,
                 in_caskroom: bool | None = None) -> str:
    """How this XeFM was installed (see the module docstring). The arguments
    stand in for the running install in tests."""
    if package_dir is None:
        package_dir = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    if platform is None:
        platform = sys.platform
    path = package_dir.replace("\\", "/")
    if "/WindowsApps/" in path:
        return "msix"
    if os.path.isfile(path.rstrip("/").rsplit("/", 1)[0] + "/pyproject.toml"):
        return "source"
    if has_distribution is None:
        has_distribution = _has_distribution()
    if not has_distribution:
        if platform == "win32":
            return "zip"
        if ".app/Contents/" in path:
            if in_caskroom is None:
                in_caskroom = any(os.path.isdir(p) for p in _CASKROOMS)
            return "cask" if in_caskroom else "dmg"
        return "source"
    if "/Cellar/xefm/" in path:
        return "formula"
    if "/pipx/venvs/" in path:
        return "pipx"
    if "/uv/tools/" in path:
        return "uv"
    return "pip"


def offers_update_check(kind: str | None = None) -> bool:
    """Whether Help offers Check for Updates: not where the Store updates XeFM."""
    return (kind or install_kind()) != "msix"


# --- versions ---------------------------------------------------------------

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?$")
_PRE_RANK = {"a": 0, "b": 1, "rc": 2}


def version_key(text: str) -> tuple | None:
    """A sort key for the release versions XeFM publishes (``1.18.0``,
    ``1.18.0rc1``), or None for anything else (dev and post releases are
    never published, so they are not ranked)."""
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    nums = [int(n) for n in match.group(1).split(".")]
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    pre = (_PRE_RANK[match.group(2)], int(match.group(3))) if match.group(2) else (3, 0)
    return (tuple(nums), pre)


def is_prerelease(text: str) -> bool:
    key = version_key(text)
    return key is not None and key[1][0] < 3


def latest_version(releases: dict, current: str) -> str | None:
    """The newest version in PyPI's ``releases`` table that is newer than
    ``current``, or None. Yanked releases and ones with no files never count;
    pre-releases count only when ``current`` is one."""
    current_key = version_key(current)
    allow_pre = is_prerelease(current)
    best, best_key = None, current_key
    for version, files in releases.items():
        key = version_key(version)
        if key is None or not files or all(f.get("yanked") for f in files):
            continue
        if key[1][0] < 3 and not allow_pre:
            continue
        if best_key is None or key > best_key:
            best, best_key = version, key
    return best


Opener = Callable[[str], bytes]


def _urlopen(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"XeFM/{VERSION}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read()


@dataclass
class UpdateCheck:
    current: str
    latest: str | None          # newer than current, or None when up to date
    kind: str

    @property
    def available(self) -> bool:
        return self.latest is not None


def check_for_updates(current: str = VERSION, kind: str | None = None,
                      opener: Opener | None = None) -> UpdateCheck:
    """Ask PyPI for the newest XeFM. Raises on a network or format error; the
    caller reports it."""
    data = json.loads((opener or _urlopen)(PYPI_JSON_URL))
    return UpdateCheck(current=current,
                       latest=latest_version(data.get("releases") or {}, current),
                       kind=kind or install_kind())


def upgrade_instructions(kind: str, version: str, python: str | None = None) -> str:
    """How to get ``version`` for this install, as Markdown."""
    page = release_notes_url(version)
    if kind in ("dmg", "zip"):
        what = "DMG" if kind == "dmg" else "zip for your Windows (x64 or arm64)"
        return f"Download the {what} from the [release page]({page})."
    commands = {
        "cask": "brew upgrade --cask xefm",
        "formula": "brew upgrade xefm",
        "pipx": "pipx upgrade xefm",
        "uv": "uv tool upgrade xefm",
        "pip": f"\"{python or sys.executable}\" -m pip install --upgrade xefm",
        "source": "git pull",
    }
    command = commands.get(kind)
    if command is None:
        return f"See the [release page]({page})."
    if kind == "pip" and is_prerelease(version):
        command += " --pre"
    lines = [f"Run `{command}` in a terminal, then restart XeFM."]
    if kind in ("cask", "formula"):
        lines.append("Homebrew can take a day to pick up a new version.")
    return " ".join(lines)


# --- links ------------------------------------------------------------------

def release_notes_url(version: str = VERSION) -> str:
    return f"{RELEASES_URL}/tag/v{version}"


def os_description(platform: str | None = None) -> str:
    """The OS for a bug report, the way a person names it."""
    platform = platform or sys.platform
    if platform == "darwin":
        version = _platform.mac_ver()[0]
        return f"macOS {version}".strip()
    if platform == "win32":
        release, version = _platform.release(), _platform.version()
        return f"Windows {release} ({version})"
    try:
        return _platform.freedesktop_os_release().get("PRETTY_NAME") or _platform.platform()
    except OSError:
        return _platform.platform()


def terminal_description(environ: dict | None = None) -> str:
    """The terminal a TUI runs in, from what it says about itself."""
    environ = os.environ if environ is None else environ
    if environ.get("WT_SESSION"):
        return "Windows Terminal"
    name = environ.get("TERM_PROGRAM", "")
    version = environ.get("TERM_PROGRAM_VERSION", "")
    return f"{name} {version}".strip() or environ.get("TERM", "")


def issue_url(*, version: str = VERSION, kind: str | None = None,
              os_text: str | None = None, terminal: str = "",
              python: str = "") -> str:
    """The bug report form with what XeFM knows about itself filled in. The
    user sees every field before anything is sent: this only builds a link."""
    kind = kind or install_kind()
    version_text = f"{version} ({python})" if python else version
    fields = {
        "template": "bug_report.yml",
        "version": version_text,
        "install": _ISSUE_INSTALL_LABELS.get(kind, ""),
        "os": os_text if os_text is not None else os_description(),
    }
    if terminal:
        fields["terminal"] = terminal
    query = urllib.parse.urlencode({k: v for k, v in fields.items() if v})
    return f"{GITHUB_URL}/issues/new?{query}"
