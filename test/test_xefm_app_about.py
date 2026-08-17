"""
About box content for the PuiKit XeFMApp.

The About/Info dialogs were largely already ported — Info's scrollable-panel
role is covered by ``show_text`` (used by help/file-details), and ``show_about``
existed but was a bare message box. This pins the enriched About body (name,
version, project URL) so it stays in sync with the constants.
"""

import os
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


if __name__ == "__main__":
    unittest.main()
