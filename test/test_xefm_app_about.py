"""
About box content for the PuiKit XeFMApp.

The About/Info dialogs were largely already ported — Info's scrollable-panel
role is covered by ``show_text`` (used by help/file-details), and ``show_about``
existed but was a bare message box. This pins the enriched About body (name,
version, project URL) so it stays in sync with the constants.
"""

import os
import platform
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.const import VERSION, GITHUB_URL  # noqa: E402


class AboutText(unittest.TestCase):
    def test_includes_version_and_url(self):
        text = xefm_app.XeFMApp._about_text()
        self.assertIn(VERSION, text)
        self.assertIn(GITHUB_URL, text)

    def test_names_the_app(self):
        self.assertIn("XeFM", xefm_app.XeFMApp._about_text())

    def test_markdown_shape_keeps_rows_and_links_url(self):
        # The body renders as Markdown (show_about passes markdown=True): the
        # first line must end with a hard break (trailing backslash) so name and
        # version keep their own rows, and the URL must sit in its own paragraph
        # so it autolinkifies into a clickable link — the desktop About showed
        # it as inert text while the terminal auto-linked it (issue #307).
        text = xefm_app.XeFMApp._about_text()
        self.assertTrue(text.split("\n")[0].endswith("\\"))
        self.assertIn("\n\n" + GITHUB_URL, text)

    def test_names_the_python_and_its_gil(self):
        # On its own row, so a free-threaded app build can be told by eye.
        text = xefm_app.XeFMApp._about_text()
        line = xefm_app.XeFMApp._python_text()
        self.assertIn("\n" + line + "\n\n", text)
        self.assertTrue(line.startswith("Python " + platform.python_version()))


class PythonText(unittest.TestCase):
    def test_a_free_threaded_build_with_the_gil_off(self):
        self.assertEqual(xefm_app.XeFMApp._python_text("3.15.2", True, False, "arm64"),
                         "Python 3.15.2 arm64 (free-threaded, GIL off)")

    def test_a_free_threaded_build_that_turned_the_gil_back_on(self):
        # An extension module without free-threading support, or PYTHON_GIL=1.
        self.assertEqual(xefm_app.XeFMApp._python_text("3.15.2", True, True, "x64"),
                         "Python 3.15.2 x64 (free-threaded build, GIL on)")

    def test_a_default_build(self):
        self.assertEqual(xefm_app.XeFMApp._python_text("3.14.10", False, True, "x64"),
                         "Python 3.14.10 x64 (GIL on)")

    def test_names_the_running_architecture(self):
        line = xefm_app.XeFMApp._python_text()
        self.assertIn(" " + xefm_app.XeFMApp._python_arch() + " (", line)


class PythonArch(unittest.TestCase):
    def arch(self, tag, machine=None):
        return xefm_app.XeFMApp._python_arch(tag, machine)

    def test_windows_reads_the_interpreter_build_tag(self):
        # Not platform.machine(): an x64 Python emulated on ARM64 says x64.
        self.assertEqual(self.arch("win-amd64", "ARM64"), "x64")
        self.assertEqual(self.arch("win-arm64", "ARM64"), "arm64")
        self.assertEqual(self.arch("win32", "AMD64"), "x86")

    def test_macos_reads_the_process_machine(self):
        # A universal2 build names no one architecture; Rosetta says x86_64.
        self.assertEqual(self.arch("macosx-11.0-universal2", "arm64"), "arm64")
        self.assertEqual(self.arch("macosx-11.0-universal2", "x86_64"), "x64")

    def test_linux(self):
        self.assertEqual(self.arch("linux-x86_64", "x86_64"), "x64")
        self.assertEqual(self.arch("linux-aarch64", "aarch64"), "arm64")

    def test_an_unknown_architecture_keeps_its_own_name(self):
        self.assertEqual(self.arch("linux-riscv64", "riscv64"), "riscv64")


if __name__ == "__main__":
    unittest.main()
