"""requirements.txt resolves as intended on each platform.

Pillow is wanted wherever it has wheels, and left out elsewhere, where pip
would have to build it and the install would fail. A wrong marker would
silently drop the image viewer on a main platform, so the main ones are
listed here, with the machine names Python reports on them. (similar-files
gates its own Pillow and numpy, and tests that itself.)
"""

import pathlib

import pytest

requirements = pytest.importorskip("packaging.requirements")

_REQUIREMENTS = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"

_WITH_WHEELS = [
    ("darwin", "arm64"), ("darwin", "x86_64"),
    ("linux", "x86_64"), ("linux", "aarch64"),
    ("win32", "AMD64"), ("win32", "ARM64"), ("win32", "x86"),
]
_WITHOUT_WHEELS = [
    *[("linux", m) for m in ("armv7l", "armv6l", "i686", "ppc64le", "s390x", "riscv64")],
    # A machine name with wheels elsewhere, on an OS without them.
    ("cygwin", "x86_64"), ("msys", "x86_64"), ("freebsd14", "arm64"), ("freebsd14", "amd64"),
]


def _applying(sys_platform, machine):
    """The requirements that apply on this platform, by name."""
    env = {"sys_platform": sys_platform, "platform_machine": machine,
           "platform_system": {"darwin": "Darwin", "linux": "Linux", "win32": "Windows"}.get(sys_platform, "")}
    out = {}
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        req = requirements.Requirement(line)
        if req.marker is None or req.marker.evaluate(env):
            assert req.name.lower() not in out, f"two lines apply to {req.name} on {sys_platform}/{machine}"
            out[req.name.lower()] = req
    return out


@pytest.mark.parametrize("sys_platform, machine", _WITH_WHEELS)
def test_pillow_is_installed_where_it_has_wheels(sys_platform, machine):
    assert "pillow" in _applying(sys_platform, machine)


@pytest.mark.parametrize("sys_platform, machine", _WITHOUT_WHEELS)
def test_pillow_is_left_out_where_pip_would_build_it(sys_platform, machine):
    reqs = _applying(sys_platform, machine)
    assert "pillow" not in reqs
    assert "similar-files" in reqs  # it leaves out its own Pillow and numpy there
