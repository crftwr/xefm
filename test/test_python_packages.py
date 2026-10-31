"""~/.xefm/requirements.txt and the directory synced from it (#664)."""

import base64
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

from xefm import deps_cli
from xefm import python_packages as pp


HOST = {"pillow": "11.3.0", "pygments": "2.19.2"}


def _write_dist(site: Path, name: str, version: str, files: dict[str, str],
                extra_record: tuple = ()) -> None:
    """A minimal installed distribution: its files plus a dist-info that
    lists them in RECORD, as pip leaves it."""
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\n"
                                   f"Version: {version}\n", encoding="utf-8")
    record = [f"{info.name}/METADATA,,", f"{info.name}/RECORD,,"]
    for rel, text in files.items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        record.append(f"{rel},,")
    record += [f"{rel},," for rel in extra_record]
    (info / "RECORD").write_text("\n".join(record) + "\n", encoding="utf-8")


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        self.layout = pp.Layout(self.home)
        self.saved_path = list(sys.path)
        self.addCleanup(self._restore_path)

    def _restore_path(self):
        sys.path[:] = self.saved_path

    def write_requirements(self, text):
        self.layout.requirements.write_text(text, encoding="utf-8")

    def synced(self, text, host=HOST, **override):
        """A target directory as a sync of ``text`` against ``host`` left it."""
        self.write_requirements(text)
        self.layout.target.mkdir(parents=True)
        stamp = {**pp.make_stamp(text, host), **override}
        (self.layout.target / pp.STAMP).write_text(json.dumps(stamp), encoding="utf-8")


class CheckTest(_Fixture):
    def test_unused_without_a_file_or_a_directory(self):
        self.assertEqual(pp.check(self.layout, HOST).state, pp.UNUSED)

    def test_comments_alone_declare_nothing(self):
        self.write_requirements("# pillow-heif\n\n")
        self.assertEqual(pp.check(self.layout, HOST).state, pp.UNUSED)

    def test_a_file_never_synced_needs_a_sync(self):
        self.write_requirements("pillow-heif\n")
        status = pp.check(self.layout, HOST)
        self.assertEqual(status.state, pp.NEEDS_SYNC)
        self.assertFalse(status.loaded)
        self.assertIn("xefm deps sync", status.message)

    def test_in_sync(self):
        self.synced("pillow-heif\n")
        status = pp.check(self.layout, HOST)
        self.assertEqual((status.state, status.loaded), (pp.IN_SYNC, True))
        self.assertEqual(status.message, "")

    def test_an_edited_file_needs_a_sync_but_stays_loaded(self):
        self.synced("pillow-heif\n")
        self.write_requirements("pillow-heif\nrawpy\n")
        status = pp.check(self.layout, HOST)
        self.assertEqual((status.state, status.loaded), (pp.NEEDS_SYNC, True))
        self.assertIn("changed since the last sync", status.reason)

    def test_a_deleted_file_needs_a_sync_to_remove_the_packages(self):
        self.synced("pillow-heif\n")
        self.layout.requirements.unlink()
        self.assertEqual(pp.check(self.layout, HOST).state, pp.NEEDS_SYNC)

    def test_changed_host_packages_need_a_sync(self):
        self.synced("pillow-heif\n")
        status = pp.check(self.layout, {**HOST, "pillow": "12.0.0"})
        self.assertEqual(status.state, pp.NEEDS_SYNC)
        self.assertIn("XeFM's own packages", status.reason)

    def test_another_platform_is_not_loaded(self):
        # No real tag: "cpython-314-win32-amd64" is this one on x64 Windows (#794).
        self.synced("pillow-heif\n", platform="cpython-0-elsewhere")
        status = pp.check(self.layout, HOST)
        self.assertEqual((status.state, status.loaded), (pp.FOREIGN, False))

    def test_a_new_python_minor_version_names_the_old_one(self):
        self.write_requirements("pillow-heif\n")
        (self.layout.root / "3.13").mkdir(parents=True)
        status = pp.check(pp.Layout(self.home, version="3.14"), HOST)
        self.assertEqual(status.state, pp.NEEDS_SYNC)
        self.assertIn("synced for Python 3.13", status.reason)


class ActivateTest(_Fixture):
    def test_appends_the_directory_to_sys_path(self):
        self.synced("x\n")
        pp.activate(self.layout)
        self.assertEqual(sys.path[-1], str(self.layout.target))
        pp.activate(self.layout)
        self.assertEqual(sys.path.count(str(self.layout.target)), 1)

    def test_a_foreign_directory_stays_off_the_path(self):
        self.synced("x\n", platform="elsewhere")
        pp.activate(self.layout)
        self.assertNotIn(str(self.layout.target), sys.path)

    def test_a_staged_sync_is_swapped_in_at_start(self):
        self.synced("old\n")
        (self.layout.target / "old_marker").write_text("")
        self.layout.staging.mkdir()
        (self.layout.staging / pp.STAMP).write_text(json.dumps(pp.make_stamp("x", {})))
        (self.layout.staging / "new_marker").write_text("")
        pp.activate(self.layout)
        self.assertTrue((self.layout.target / "new_marker").exists())
        self.assertFalse(self.layout.staging.exists())
        self.assertFalse(self.layout.retired.exists())

    def test_an_interrupted_sync_is_discarded(self):
        self.synced("old\n")
        self.layout.staging.mkdir()
        (self.layout.staging / "half").write_text("")
        pp.activate(self.layout)
        self.assertFalse(self.layout.staging.exists())
        self.assertTrue((self.layout.target / pp.STAMP).exists())


class PruneTest(_Fixture):
    def test_host_packages_are_removed_and_the_rest_kept(self):
        site = self.home / "site"
        _write_dist(site, "Pillow", "11.3.0",
                    {"PIL/__init__.py": "", "PIL/Image.py": ""},
                    extra_record=("../../bin/outside",))
        _write_dist(site, "pillow_heif", "1.1.0", {"pillow_heif/__init__.py": ""})
        outside = self.home / "bin" / "outside"
        outside.parent.mkdir()
        outside.write_text("keep me")
        pruned = pp._prune(site, HOST)
        self.assertEqual(pruned, ["Pillow"])
        self.assertEqual(sorted(p.name for p in site.iterdir()),
                         ["pillow_heif", "pillow_heif-1.1.0.dist-info"])
        self.assertTrue(outside.exists())


class PipCommandTest(_Fixture):
    def run_fails(self, *a, **k):
        return subprocess.CompletedProcess(a, 1)

    def test_the_interpreters_own_pip_comes_first(self):
        ok = lambda *a, **k: subprocess.CompletedProcess(a, 0)
        self.assertEqual(pp.pip_command("py", self.layout, run=ok), ["py", "-m", "pip"])

    def test_else_the_wheel_ensurepip_carries(self):
        wheel = Path("/lib/ensurepip/_bundled/pip-26.0-py3-none-any.whl")
        with mock.patch.object(pp, "_bundled_pip_wheel", return_value=wheel):
            cmd = pp.pip_command("py", self.layout, run=self.run_fails)
        self.assertEqual(cmd, ["py", os.path.join(str(wheel), "pip")])

    def _pypi(self, payload, digest):
        index = json.dumps({"urls": [
            {"packagetype": "sdist", "filename": "pip-26.0.tar.gz", "url": "sdist"},
            {"packagetype": "bdist_wheel", "filename": "pip-26.0-py3-none-any.whl",
             "url": "wheel", "digests": {"sha256": digest}}]}).encode()
        return lambda url: index if url == pp.PYPI_PIP_JSON else payload

    def test_else_a_wheel_from_pypi_checked_and_cached(self):
        payload = b"wheel bytes"
        opener = self._pypi(payload, hashlib.sha256(payload).hexdigest())
        with mock.patch.object(pp, "_bundled_pip_wheel", return_value=None):
            cmd = pp.pip_command("py", self.layout, run=self.run_fails, opener=opener)
            cached = self.layout.pip_cache / "pip-26.0-py3-none-any.whl"
            self.assertEqual(cmd, ["py", os.path.join(str(cached), "pip")])
            self.assertEqual(cached.read_bytes(), payload)
            # Once cached, nothing is downloaded again.
            again = pp.pip_command("py", self.layout, run=self.run_fails,
                                   opener=lambda url: self.fail("downloaded twice"))
        self.assertEqual(again, cmd)

    def test_a_download_that_does_not_match_its_digest_is_refused(self):
        opener = self._pypi(b"tampered", "0" * 64)
        with mock.patch.object(pp, "_bundled_pip_wheel", return_value=None), \
                self.assertRaises(pp.SyncError):
            pp.pip_command("py", self.layout, run=self.run_fails, opener=opener)
        self.assertFalse(self.layout.pip_cache.exists())


class _FakePip:
    """Stands in for ``subprocess.Popen`` running pip: installs the given
    distributions into ``--target`` and prints, or fails with ``output``."""

    def __init__(self, dists=(), code=0, output=("Successfully installed",)):
        self.dists, self.code, self.output = dists, code, output
        self.argv = None

    def __call__(self, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        self.requirements = Path(argv[argv.index("-r") + 1]).read_text(encoding="utf-8")
        target = Path(argv[argv.index("--target") + 1])
        if self.code == 0:
            for name, version, files in self.dists:
                _write_dist(target, name, version, files)
        proc = mock.Mock()
        proc.stdout = io.StringIO("".join(line + "\n" for line in self.output))
        proc.wait.return_value = self.code
        return proc


class SyncTest(_Fixture):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pp, "host_distributions", return_value=dict(HOST))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_ok = lambda *a, **k: subprocess.CompletedProcess(a, 0)

    def sync(self, popen, **kw):
        lines = []
        result = pp.sync(self.layout, python="py", log=lines.append,
                         run=self.run_ok, popen=popen, **kw)
        return result, lines

    def test_installs_prunes_stamps_and_loads(self):
        self.write_requirements("pillow-heif\n")
        fake = _FakePip(dists=[("pillow_heif", "1.1.0", {"pillow_heif/__init__.py": ""}),
                               ("Pillow", "11.3.0", {"PIL/__init__.py": ""})])
        result, lines = self.sync(fake)
        self.assertEqual(result.installed, ["pillow_heif 1.1.0"])
        self.assertEqual(result.pruned, ["Pillow"])
        self.assertFalse(result.pending_restart)
        self.assertEqual(lines, ["Successfully installed"])
        self.assertEqual(pp.check(self.layout, HOST).state, pp.IN_SYNC)
        self.assertIn(str(self.layout.target), sys.path)
        self.assertFalse((self.layout.target / "PIL").exists())
        # pip ran with the host packages as constraints, from ~/.xefm.
        argv = fake.argv
        self.assertEqual(argv[:4], ["py", "-m", "pip", "install"])
        self.assertEqual(fake.requirements,
                         f"-r {shlex.quote(self.layout.requirements.as_posix())}\n")
        self.assertEqual(fake.kwargs["cwd"], str(self.home))

    def test_the_include_line_survives_pip_s_shlex_split(self):
        # pip reads "-r C:\\Users\\..." as escapes and loses the path (#749).
        for path in (PureWindowsPath(r"C:\Users\John Doe\.xefm\requirements.txt"),
                     PurePosixPath("/home/o'neil/.xefm/requirements.txt")):
            with self.subTest(path=str(path)):
                self.assertEqual(shlex.split(pp._include_line(path)),
                                 ["-r", path.as_posix()])

    def test_constraints_pin_the_host_versions(self):
        self.write_requirements("pillow-heif\n")
        seen = {}

        def popen(argv, **kw):
            seen["constraints"] = Path(argv[argv.index("-c") + 1]).read_text()
            return _FakePip()(argv, **kw)

        self.sync(popen)
        self.assertEqual(seen["constraints"], "pillow==11.3.0\npygments==2.19.2\n")

    def test_a_removed_line_removes_its_package(self):
        self.write_requirements("a\nb\n")
        self.sync(_FakePip(dists=[("a", "1", {"a.py": ""}), ("b", "1", {"b.py": ""})]))
        self.write_requirements("a\n")
        result, _ = self.sync(_FakePip(dists=[("a", "1", {"a.py": ""})]))
        self.assertEqual(result.installed, ["a 1"])
        self.assertFalse((self.layout.target / "b.py").exists())

    def test_an_empty_file_removes_the_directory_without_pip(self):
        self.write_requirements("a\n")
        self.sync(_FakePip(dists=[("a", "1", {"a.py": ""})]))
        self.write_requirements("")
        result, _ = self.sync(lambda *a, **k: self.fail("pip ran"))
        self.assertEqual(result.installed, [])
        self.assertFalse(self.layout.root.exists())
        self.assertEqual(pp.check(self.layout, HOST).state, pp.UNUSED)

    def test_nothing_declared_and_nothing_synced_creates_nothing(self):
        result, _ = self.sync(lambda *a, **k: self.fail("pip ran"))
        self.assertEqual(result.installed, [])
        self.assertFalse(self.layout.root.exists())

    def test_a_conflict_with_a_host_package_names_it_and_changes_nothing(self):
        self.synced("old\n")
        self.write_requirements("pillow>=99\n")
        fake = _FakePip(code=1, output=(
            "ERROR: Cannot install pillow>=99 because these package versions "
            "have conflicting dependencies.",
            "The conflict is caused by:",
            "    The user requested pillow>=99",
            "    The user requested (constraint) pillow==11.3.0",
            "ERROR: ResolutionImpossible"))
        with self.assertRaises(pp.SyncError) as caught:
            self.sync(fake)
        self.assertIn("The user requested pillow>=99; The user requested "
                      "(constraint) pillow==11.3.0", str(caught.exception))
        self.assertFalse(self.layout.staging.exists())
        self.assertEqual(pp.read_stamp(self.layout.target)["requirements"],
                         pp.make_stamp("old\n", HOST)["requirements"])

    def test_a_target_in_use_is_replaced_at_the_next_start(self):
        self.synced("old\n")
        self.write_requirements("a\n")
        real_replace = os.replace

        def replace(src, dst):
            if Path(src) == self.layout.target:
                raise PermissionError("in use")
            return real_replace(src, dst)

        with mock.patch.object(pp.os, "replace", side_effect=replace):
            result, _ = self.sync(_FakePip(dists=[("a", "1", {"a.py": ""})]))
        self.assertTrue(result.pending_restart)
        self.assertTrue(self.layout.staging.is_dir())
        pp.activate(self.layout)
        self.assertTrue((self.layout.target / "a.py").exists())
        self.assertEqual(pp.check(self.layout, HOST).state, pp.IN_SYNC)


def _wheel(directory: Path, name: str, version: str, module: str) -> Path:
    """A real, installable pure-Python wheel — no build backend, no index."""
    path = directory / f"{name}-{version}-py3-none-any.whl"
    info = f"{name}-{version}.dist-info"
    files = {
        f"{module}.py": "VALUE = 42\n",
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
                         "Tag: py3-none-any\n",
    }
    record = []
    for rel, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest())
        record.append(f"{rel},sha256={digest.rstrip(b'=').decode()},{len(text.encode())}")
    record.append(f"{info}/RECORD,,")
    with zipfile.ZipFile(path, "w") as archive:
        for rel, text in files.items():
            archive.writestr(rel, text)
        archive.writestr(f"{info}/RECORD", "\n".join(record) + "\n")
    return path


@unittest.skipIf(subprocess.run([sys.executable, "-m", "pip", "--version"],
                                capture_output=True).returncode != 0, "no pip")
class RealPipTest(_Fixture):
    """The whole sync through the real pip, offline: a local wheel and
    ``--no-index``."""

    def test_sync_installs_an_importable_package(self):
        _wheel(self.home, "xefm_t664_demo", "1.0", "xefm_t664_demo")
        self.write_requirements("--no-index\n./xefm_t664_demo-1.0-py3-none-any.whl\n")
        result = pp.sync(self.layout, python=sys.executable)
        self.assertEqual(result.installed, ["xefm_t664_demo 1.0"])
        self.addCleanup(sys.modules.pop, "xefm_t664_demo", None)
        import xefm_t664_demo
        self.assertEqual(xefm_t664_demo.VALUE, 42)
        self.assertEqual(pp.check(self.layout).state, pp.IN_SYNC)


class DepsCliTest(_Fixture):
    def test_status_exit_codes(self):
        with mock.patch("builtins.print"):
            self.assertEqual(deps_cli.main(["status"], layout=self.layout), 0)
            self.write_requirements("a\n")
            self.assertEqual(deps_cli.main(["status"], layout=self.layout), 1)

    def test_a_failed_sync_exits_nonzero(self):
        with mock.patch.object(pp, "sync", side_effect=pp.SyncError("boom")), \
                mock.patch("builtins.print") as out:
            self.assertEqual(deps_cli.main(["sync"], layout=self.layout), 1)
        out.assert_any_call("sync failed: boom")


if __name__ == "__main__":
    unittest.main()
