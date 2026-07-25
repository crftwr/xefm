"""
Test entry point functionality for XeFM

Run with: python -m pytest test/test_entry_point.py -v
"""

import os
import sys
import unittest

_SRC_DIR = os.path.realpath(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEntryPoint(unittest.TestCase):
    """Test entry point functionality"""

    def setUp(self):
        # Make ``import xefm`` resolve to the package under src/. The sibling
        # ``puikit`` source dir would otherwise shadow the editable puikit
        # install as an empty namespace package when pytest prepends the repo's
        # parent to sys.path, so drop that entry and clear the cached bindings
        # so both re-resolve cleanly. sys.path / sys.modules are process-global,
        # so snapshot and restore in tearDown — otherwise these tweaks would
        # leak into every later test.
        self._saved_path = list(sys.path)
        self._saved_modules = {n: sys.modules.get(n) for n in ("xefm", "puikit")}
        repo_root = os.path.dirname(_SRC_DIR)
        parent = os.path.dirname(repo_root)
        while parent in sys.path:
            sys.path.remove(parent)
        if _SRC_DIR not in sys.path:
            sys.path.insert(0, _SRC_DIR)
        sys.modules.pop("xefm", None)
        sys.modules.pop("puikit", None)

    def tearDown(self):
        sys.path[:] = self._saved_path
        for name, mod in self._saved_modules.items():
            if mod is not None:
                sys.modules[name] = mod
            else:
                sys.modules.pop(name, None)

    def test_import_main_function(self):
        """Test that we can import the main function from xefm.app"""
        try:
            from xefm.app import main
            self.assertTrue(callable(main), "main should be callable")
        except ImportError as e:
            self.fail(f"Failed to import main function: {e}")

    def test_import_parser_function(self):
        """Test that we can import the create_parser function"""
        try:
            from xefm.app import create_parser
            parser = create_parser()
            self.assertIsNotNone(parser, "Parser should not be None")

            # Test that parser has the expected arguments
            help_text = parser.format_help()
            self.assertIn('--version', help_text)
            self.assertIn('--help', help_text)

        except ImportError as e:
            self.fail(f"Failed to import create_parser function: {e}")
