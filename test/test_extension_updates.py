"""Newer versions of installed extension packages (#676).

``[extension] updates`` names where a package's versions are tagged; ``xefm
ext outdated`` / ``upgrade`` and Tools ▸ Advanced ▸ Check for Extension
Updates look there, and only when asked. A fake GitHub stands in for both the
tag list (git's ref advertisement), codeload and release assets here, so nothing reaches the network.

Run with: python -m pytest test/test_extension_updates.py -v
"""

import io
import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import extension_cli  # noqa: E402
from xefm import extensions as ext  # noqa: E402

REPO = "github:someone/exts/packages/upd"
REFS = "https://github.com/someone/exts.git/info/refs?service=git-upload-pack"


def _pkt(text: str) -> bytes:
    data = text.encode()
    return f"{len(data) + 4:04x}".encode() + data


def advertisement(tags) -> bytes:
    """What ``git ls-remote`` reads: a service line, a flush, then the refs —
    the first with capabilities after a NUL, annotated tags also peeled."""
    sha = "0" * 40
    lines = [f"{sha} HEAD\0multi_ack side-band-64k\n", f"{sha} refs/heads/main\n"]
    for tag in tags:
        lines += [f"{sha} refs/tags/{tag}\n", f"{sha} refs/tags/{tag}^{{}}\n"]
    return (_pkt("# service=git-upload-pack\n") + b"0000"
            + b"".join(map(_pkt, lines)) + b"0000")


class FakeGitHub:
    """Tags and zips of one repository holding ``packages/<id>/`` at each tag,
    and the release assets ``<tag>.zip`` of the tags that have one."""

    def __init__(self):
        self.tags: dict[str, bytes] = {}     # tag -> zip of the repository
        self.assets: dict[str, bytes] = {}   # tag -> zip of the package alone
        self.head: bytes = b""               # zip of the default branch
        self.urls: list[str] = []
        self.fail: Exception | None = None

    @staticmethod
    def _zip(package: Path, prefix: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for path in package.rglob("*"):
                if path.is_file():
                    z.write(path, f"{prefix}{path.relative_to(package)}")
        return buf.getvalue()

    def publish(self, tag: str, package: Path, ext_id: str, *, asset=False) -> None:
        self.tags[tag] = self._zip(package, f"exts-{tag}/packages/{ext_id}/")
        if asset:
            self.assets[tag] = self._zip(package, f"{ext_id}/")

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.fail is not None:
            raise self.fail
        if url == REFS:
            return advertisement(self.tags)
        release = "https://github.com/someone/exts/releases/download/"
        if url.startswith(release):
            tag, name = url[len(release):].split("/")
            if tag in self.assets and name == f"{tag}.zip":
                return self.assets[tag]
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        zip_prefix = "https://codeload.github.com/someone/exts/zip/"
        if url.startswith(zip_prefix):
            ref = url[len(zip_prefix):]
            return self.head if ref == "HEAD" else self.tags[ref]
        raise AssertionError(f"unexpected URL {url}")


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp()))
        self.src = Path(os.path.realpath(tempfile.mkdtemp()))
        self.layout = ext.Layout(self.home)
        self.github = FakeGitHub()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.src, ignore_errors=True)

    def package(self, version: str, *, ext_id="upd", updates=REPO, extra="") -> Path:
        root = self.src / f"{ext_id}-{version}"
        root.mkdir()
        updates_line = f'updates = "{updates}"' if updates else ""
        (root / ext.MANIFEST).write_text(textwrap.dedent(f'''
            [extension]
            id = "{ext_id}"
            version = "{version}"
            api_version = 1
            {updates_line}
            {extra}

            [contributes.themes]
            "{ext_id}-theme" = {{ base = "dark" }}
        '''), encoding="utf-8")
        return root

    def release(self, version: str, *, asset=False, **kw) -> Path:
        root = self.package(version, **kw)
        self.github.publish(f"{kw.get('ext_id', 'upd')}-v{version}", root,
                            kw.get("ext_id", "upd"), asset=asset)
        return root

    def installed(self, ext_id="upd") -> ext.InstalledEntry:
        return ext.read_installed(self.layout)[ext_id]


class Versions(_Home):
    def test_tags_are_read_by_the_package_s_prefix(self):
        for version in ("0.1.0", "0.10.0", "0.2.0", "0.3.0-beta"):
            self.release(version)
        self.github.tags["other-v9.0.0"] = b""
        found = ext.published_versions(REPO, "upd", opener=self.github)
        self.assertEqual(found, ["0.1.0", "0.2.0", "0.10.0"])   # numeric, no beta
        self.assertEqual(self.github.urls, [REFS])

    def test_a_package_at_the_root_is_tagged_v(self):
        self.assertEqual(ext.tag_prefix("github:o/r", "x"), "v")
        self.assertEqual(ext.tag_prefix("github:o/r/x", "x"), "x-v")
        self.assertEqual(ext.release_source("github:o/r", "x", "1.0"), "github:o/r@v1.0")

    def test_a_missing_repository_is_named(self):
        """GitHub answers 401, asking for credentials, for a repository that
        does not exist or is private."""
        self.github.fail = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        with self.assertRaises(ext.InstallError) as caught:
            ext.published_versions(REPO, "upd", opener=self.github)
        self.assertIn("github.com/someone/exts", str(caught.exception))

    def test_packages_sharing_a_repository_cost_one_request(self):
        self.release("0.1.0")
        self.release("0.1.0", ext_id="two", updates="github:someone/exts/packages/two")
        ext.install(f"{REPO}@upd-v0.1.0", self.layout, opener=self.github)
        ext.install("github:someone/exts/packages/two@two-v0.1.0", self.layout,
                    opener=self.github)
        self.release("0.2.0")
        self.github.urls.clear()
        checks = ext.check_updates(self.layout, opener=self.github)
        self.assertEqual([(c.id, c.latest) for c in checks], [("two", ""), ("upd", "0.2.0")])
        self.assertEqual(self.github.urls, [REFS])


class Check(_Home):
    def test_install_records_the_update_source(self):
        ext.install(str(self.package("0.1.0")), self.layout)
        self.assertEqual(self.installed().updates, REPO)
        self.assertIn(f'updates = "{REPO}"', self.layout.installed_file.read_text())

    def test_finds_the_newest_release(self):
        ext.install(str(self.release("0.1.0")), self.layout)
        self.release("0.2.0")
        self.release("0.3.0")
        (check,) = ext.check_updates(self.layout, opener=self.github)
        self.assertTrue(check.outdated)
        self.assertEqual(check.latest, "0.3.0")
        self.assertEqual(check.source, f"{REPO}@upd-v0.3.0")

    def test_current(self):
        ext.install(str(self.release("0.2.0")), self.layout)
        self.release("0.1.0")
        (check,) = ext.check_updates(self.layout, opener=self.github)
        self.assertFalse(check.outdated)
        self.assertEqual(check.problem, "")

    def test_no_update_source_is_a_note_not_a_failure(self):
        ext.install(str(self.package("0.1.0", updates="")), self.layout)
        (check,) = ext.check_updates(self.layout, opener=self.github)
        self.assertIn("does not say", check.problem)
        self.assertFalse(check.failed)
        self.assertEqual(self.github.urls, [])

    def test_an_unreachable_source_is_a_failure(self):
        ext.install(str(self.package("0.1.0")), self.layout)
        self.github.fail = OSError("offline")
        (check,) = ext.check_updates(self.layout, opener=self.github)
        self.assertTrue(check.failed)
        self.assertIn("offline", check.problem)

    def test_an_entry_from_before_the_field_reads_the_manifest(self):
        ext.install(str(self.release("0.1.0")), self.layout)
        entries = ext.read_installed(self.layout)
        entries["upd"].updates = ""
        ext.write_installed(self.layout, entries)
        self.release("0.2.0")
        (check,) = ext.check_updates(self.layout, opener=self.github)
        self.assertEqual(check.latest, "0.2.0")

    def test_local_packages_and_unknown_ids(self):
        local = self.layout.packages / "mine"
        local.parent.mkdir(parents=True)
        shutil.copytree(self.package("0.1.0", ext_id="mine"), local)
        ext.set_enabled("mine", True, self.layout)          # listed as (local)
        self.assertEqual(ext.check_updates(self.layout, opener=self.github), [])
        with self.assertRaises(ext.InstallError):
            ext.check_updates(self.layout, ids=["nope"], opener=self.github)


class Upgrade(_Home):
    def test_installs_the_newer_version_and_keeps_it_disabled(self):
        ext.install(str(self.release("0.1.0")), self.layout)
        ext.set_enabled("upd", False, self.layout)
        self.release("0.2.0")
        (check,) = ext.check_updates(self.layout, opener=self.github)
        manifest = ext.upgrade(check, self.layout, opener=self.github)
        self.assertEqual(manifest.version, "0.2.0")
        entry = self.installed()
        self.assertEqual((entry.version, entry.source, entry.enabled),
                         ("0.2.0", f"{REPO}@upd-v0.2.0", False))

    def test_a_version_this_xefm_cannot_run_is_refused_and_the_old_stays(self):
        ext.install(str(self.release("0.1.0")), self.layout)
        self.release("0.2.0", extra='min_xefm = "99.0.0"')
        (check,) = ext.check_updates(self.layout, opener=self.github)
        with self.assertRaises(ext.InstallError) as caught:
            ext.upgrade(check, self.layout, opener=self.github)
        self.assertIn("cannot run on this XeFM", str(caught.exception))
        self.assertIn("99.0.0", str(caught.exception))
        self.assertEqual(self.installed().version, "0.1.0")
        self.assertEqual(ext.read_manifest(self.layout.packages / "upd").version, "0.1.0")


class ReleaseAssets(_Home):
    """A tag's release asset ``<tag>.zip`` holds the package alone, so it is
    downloaded instead of the whole repository; a source with no ``@ref``
    installs the newest release."""

    ASSET = "https://github.com/someone/exts/releases/download/upd-v0.2.0/upd-v0.2.0.zip"

    def test_a_tag_s_asset_is_preferred_to_the_repository_zip(self):
        self.release("0.2.0", asset=True)
        manifest = ext.install(f"{REPO}@upd-v0.2.0", self.layout, opener=self.github)
        self.assertEqual(manifest.version, "0.2.0")
        self.assertEqual(self.github.urls, [self.ASSET])

    def test_a_tag_without_an_asset_falls_back_to_the_repository_zip(self):
        self.release("0.2.0")
        ext.install(f"{REPO}@upd-v0.2.0", self.layout, opener=self.github)
        self.assertEqual(self.github.urls, [
            self.ASSET, "https://codeload.github.com/someone/exts/zip/upd-v0.2.0"])

    def test_no_ref_installs_the_newest_release(self):
        self.release("0.1.0")
        self.release("0.2.0", asset=True)
        manifest = ext.install(REPO, self.layout, opener=self.github)
        self.assertEqual(manifest.version, "0.2.0")
        self.assertEqual(self.github.urls, [REFS, self.ASSET])
        self.assertEqual(self.installed().source, REPO)

    def test_no_ref_and_no_release_installs_the_default_branch(self):
        self.github.head = FakeGitHub._zip(self.package("0.3.0"),
                                           "exts-main/packages/upd/")
        manifest = ext.install(REPO, self.layout, opener=self.github)
        self.assertEqual(manifest.version, "0.3.0")
        self.assertEqual(self.github.urls[-1],
                         "https://codeload.github.com/someone/exts/zip/HEAD")

    def test_no_ref_installs_the_default_branch_when_github_cannot_be_asked(self):
        self.release("0.2.0", asset=True)
        self.github.head = FakeGitHub._zip(self.package("0.3.0"),
                                           "exts-main/packages/upd/")

        def opener(url):
            if url == REFS:
                raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)
            return self.github(url)

        manifest = ext.install(REPO, self.layout, opener=opener)
        self.assertEqual(manifest.version, "0.3.0")

    def test_an_upgrade_downloads_the_asset(self):
        self.release("0.1.0")
        ext.install(f"{REPO}@upd-v0.1.0", self.layout, opener=self.github)
        self.release("0.2.0", asset=True)
        (check,) = ext.check_updates(self.layout, opener=self.github)
        ext.upgrade(check, self.layout, opener=self.github)
        self.assertEqual(self.installed().version, "0.2.0")
        self.assertEqual(self.github.urls[-1], self.ASSET)


class SyncAndStartup(_Home):
    def zip_of(self, root: Path) -> Path:
        archive = self.src / f"{root.name}.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for path in root.rglob("*"):
                if path.is_file():
                    z.write(path, str(path.relative_to(root)))
        return archive

    def test_sync_reinstalls_from_the_update_source_once_the_zip_is_gone(self):
        archive = self.zip_of(self.release("0.1.0"))
        ext.install(str(archive), self.layout)
        archive.unlink()
        shutil.rmtree(self.layout.packages / "upd")
        (line,) = ext.sync(self.layout, opener=self.github)
        self.assertIn(f"{REPO}@upd-v0.1.0", line)
        self.assertTrue((self.layout.packages / "upd" / ext.MANIFEST).is_file())

    def test_stranded_only_without_a_way_back(self):
        lost = self.zip_of(self.package("0.1.0", ext_id="lost", updates=""))
        kept = self.zip_of(self.package("0.1.0", ext_id="kept"))
        here = self.zip_of(self.package("0.1.0", ext_id="here", updates=""))
        for archive in (lost, kept, here):
            ext.install(str(archive), self.layout)
        lost.unlink()
        kept.unlink()
        (line,) = ext.stranded(self.layout)
        self.assertTrue(line.startswith("lost was installed from"), line)

    def test_the_startup_load_reports_it_without_the_network(self):
        archive = self.zip_of(self.package("0.1.0", updates=""))
        ext.install(str(archive), self.layout)
        archive.unlink()
        import types
        config = types.SimpleNamespace(KEY_BINDINGS={}, THEMES={})
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            report = ext.load(config, self.layout)
        self.assertTrue(any("could not reinstall" in w for w in report.warnings))


class Cli(_Home):
    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err, \
                patch.object(ext, "_open_url", self.github):
            code = extension_cli.main(list(argv), layout=self.layout)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        super().setUp()
        ext.install(str(self.release("0.1.0")), self.layout)

    def test_outdated(self):
        code, out, _ = self.run_cli("outdated")
        self.assertEqual((code, out.strip()), (0, "1 package(s) up to date"))
        self.release("0.2.0")
        code, out, _ = self.run_cli("outdated")
        self.assertEqual(code, 1)
        self.assertIn("upd 0.1.0 -> 0.2.0", out)

    def test_upgrade(self):
        self.release("0.2.0")
        code, out, err = self.run_cli("upgrade", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("upgraded upd to 0.2.0", out)
        self.assertEqual(self.installed().version, "0.2.0")
        code, out, _ = self.run_cli("upgrade", "--yes")
        self.assertEqual((code, out.strip()), (0, "nothing to upgrade"))


class AppCheck(_Home):
    """Tools ▸ Advanced ▸ Check for Extension Updates."""

    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm.state_manager import XeFMStateManager
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, str(self.src), str(self.src),
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        ext.install(str(self.release("0.1.0")), self.layout)

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def settle(self):
        deadline = time.monotonic() + 5
        while self.app._ext_updates_done is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.app._pump_extension_updates())

    def box(self):
        from puikit.widgets.message_box import MessageBox
        box = self.app.panel._layers[-1].widget
        self.assertIsInstance(box, MessageBox)
        return box

    def test_offers_the_newer_version_then_upgrades_and_reloads(self):
        from xefm.config import config_manager
        self.release("0.2.0")
        with patch.object(config_manager, "config_dir", self.home), \
                patch.object(ext, "_open_url", self.github), \
                patch.object(self.app, "reload_config") as reload_config:
            self.app.check_extension_updates()
            self.settle()
            box = self.box()
            self.assertIn("upd  0.1.0 → 0.2.0", box.message)
            self.assertEqual(self.installed().version, "0.1.0", "nothing before Upgrade")
            box._close(box.buttons.index("Upgrade"))
            self.settle()
        self.assertEqual(self.installed().version, "0.2.0")
        reload_config.assert_called_once()

    def test_up_to_date(self):
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home), \
                patch.object(ext, "_open_url", self.github):
            self.app.check_extension_updates()
            self.settle()
        box = self.box()
        self.assertIn("up to date (1 checked)", box.message)
        self.assertEqual(box.buttons, ["OK"])


if __name__ == "__main__":
    unittest.main()
