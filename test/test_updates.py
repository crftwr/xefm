"""The Help menu's links and Check for Updates (xefm/updates.py)."""

import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from xefm import updates


class InstallKind(unittest.TestCase):

    def kind(self, path, platform="darwin", dist=True, cask=False):
        return updates.install_kind(path, platform=platform, has_distribution=dist,
                                    in_caskroom=cask)

    def test_store(self):
        self.assertEqual(self.kind(r"C:\Program Files\WindowsApps\XeFM_1.0\app\xefm",
                                   platform="win32", dist=False), "msix")
        self.assertFalse(updates.offers_update_check("msix"))

    def test_app_bundles(self):
        self.assertEqual(self.kind(r"C:\Users\u\XeFM\Lib\site-packages\xefm",
                                   platform="win32", dist=False), "zip")
        app = "/Applications/XeFM.app/Contents/Resources/lib/xefm"
        self.assertEqual(self.kind(app, dist=False), "dmg")
        self.assertEqual(self.kind(app, dist=False, cask=True), "cask")

    def test_distributions(self):
        self.assertEqual(self.kind("/opt/homebrew/Cellar/xefm/1.17.1/libexec/lib/"
                                   "python3.14/site-packages/xefm"), "formula")
        self.assertEqual(self.kind("/Users/u/.local/pipx/venvs/xefm/lib/"
                                   "python3.14/site-packages/xefm"), "pipx")
        self.assertEqual(self.kind("/Users/u/.local/share/uv/tools/xefm/lib/"
                                   "python3.14/site-packages/xefm"), "uv")
        self.assertEqual(self.kind("/Users/u/venv/lib/python3.14/site-packages/xefm",
                                   platform="linux"), "pip")
        self.assertTrue(updates.offers_update_check("pip"))

    def test_checkout(self):
        root = Path(os.path.realpath(tempfile.mkdtemp()))
        (root / "pyproject.toml").write_text("")
        (root / "xefm").mkdir()
        self.assertEqual(self.kind(str(root / "xefm")), "source")

    def test_this_checkout_is_source(self):
        self.assertEqual(updates.install_kind(), "source")


class Versions(unittest.TestCase):

    def test_order(self):
        key = updates.version_key
        self.assertLess(key("1.18.0rc1"), key("1.18.0"))
        self.assertLess(key("1.18.0b2"), key("1.18.0rc1"))
        self.assertLess(key("1.9.0"), key("1.10.0"))
        self.assertEqual(key("1.18"), key("1.18.0"))
        self.assertIsNone(key("1.18.0.dev1"))

    def test_latest_skips_prereleases_for_a_final_release(self):
        releases = {"1.17.1": [{}], "1.18.0rc1": [{}], "1.17.0": [{}]}
        self.assertIsNone(updates.latest_version(releases, "1.17.1"))
        self.assertEqual(updates.latest_version(releases, "1.17.0"), "1.17.1")

    def test_latest_offers_prereleases_to_a_prerelease(self):
        releases = {"1.18.0rc1": [{}], "1.18.0rc2": [{}], "1.17.1": [{}]}
        self.assertEqual(updates.latest_version(releases, "1.18.0rc1"), "1.18.0rc2")
        releases["1.18.0"] = [{}]
        self.assertEqual(updates.latest_version(releases, "1.18.0rc1"), "1.18.0")

    def test_yanked_and_empty_releases_never_count(self):
        releases = {"1.18.0": [{"yanked": True}], "1.18.1": [], "1.17.1": [{}]}
        self.assertIsNone(updates.latest_version(releases, "1.17.1"))

    def test_check_reads_pypi(self):
        payload = json.dumps({"releases": {"1.17.1": [{}], "2.0.0": [{}]}}).encode()
        asked = []

        def opener(url):
            asked.append(url)
            return payload

        found = updates.check_for_updates("1.17.1", kind="pip", opener=opener)
        self.assertEqual(asked, [updates.PYPI_JSON_URL])
        self.assertTrue(found.available)
        self.assertEqual(found.latest, "2.0.0")
        self.assertFalse(updates.check_for_updates("2.0.0", kind="pip",
                                                   opener=opener).available)


class Instructions(unittest.TestCase):

    def test_each_install_says_what_to_do(self):
        text = updates.upgrade_instructions
        self.assertIn("brew upgrade --cask xefm", text("cask", "2.0.0"))
        self.assertIn("brew upgrade xefm", text("formula", "2.0.0"))
        self.assertIn("pipx upgrade xefm", text("pipx", "2.0.0"))
        self.assertIn("uv tool upgrade xefm", text("uv", "2.0.0"))
        self.assertIn('"/py" -m pip install --upgrade xefm`', text("pip", "2.0.0", "/py"))
        self.assertIn("--pre", text("pip", "2.0.0rc1", "/py"))
        self.assertIn("releases/tag/v2.0.0", text("dmg", "2.0.0"))
        self.assertIn("releases/tag/v2.0.0", text("zip", "2.0.0"))


class Links(unittest.TestCase):

    def test_release_notes(self):
        self.assertEqual(updates.release_notes_url("1.18.0"),
                         "https://github.com/crftwr/xefm/releases/tag/v1.18.0")

    def test_issue_form_is_filled_in(self):
        url = updates.issue_url(version="1.18.0", kind="formula", os_text="macOS 26.1",
                                terminal="iTerm.app 3.6", python="Python 3.15.2 arm64")
        fields = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(fields["template"], ["bug_report.yml"])
        self.assertEqual(fields["version"], ["1.18.0 (Python 3.15.2 arm64)"])
        self.assertEqual(fields["install"], ["Homebrew (terminal app)"])
        self.assertEqual(fields["os"], ["macOS 26.1"])
        self.assertEqual(fields["terminal"], ["iTerm.app 3.6"])

    def test_install_labels_match_the_issue_template(self):
        template = (Path(__file__).resolve().parents[1]
                    / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text()
        for label in set(updates._ISSUE_INSTALL_LABELS.values()):
            self.assertIn(f"- {label}\n", template)

    def test_terminal(self):
        self.assertEqual(updates.terminal_description({"WT_SESSION": "x"}), "Windows Terminal")
        self.assertEqual(updates.terminal_description(
            {"TERM_PROGRAM": "iTerm.app", "TERM_PROGRAM_VERSION": "3.6"}), "iTerm.app 3.6")
        self.assertEqual(updates.terminal_description({"TERM": "xterm-256color"}),
                         "xterm-256color")


if __name__ == "__main__":
    unittest.main()
