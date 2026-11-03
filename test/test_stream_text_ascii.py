"""What XeFM writes to stdout/stderr is ASCII, and the rest cannot crash it (#829).

Redirected to a file or a pipe on Windows, stdout takes the ANSI code page -
cp932 in Japan - and an em dash in a warning raised UnicodeEncodeError out of
``xefm keys > keys.txt``. Two guards, pinned here:

- XeFM's own message text is ASCII: every string literal (docstrings aside)
  in the modules whose messages reach a stream, the text ``app.py`` prints
  itself, and every ``print()`` under ``xefm/``. A literal that is only ever
  drawn on screen says so with a ``# non-ASCII: <why>`` comment on the line
  before its statement.
- What XeFM does not write - a config's own names, a path, an extension's
  text - is replaced with "?" instead of raising: ``main()`` reconfigures
  stdout with ``errors="replace"``.

Run with: python -m pytest test/test_stream_text_ascii.py -v
"""

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PKG = _ROOT / "xefm"

# The modules whose messages reach stdout/stderr: the CLI subcommands, and
# the config, extension and table checks whose warnings and errors they print.
STREAM_MODULES = (
    "keys_cli", "deps_cli", "extension_cli", "try_cli", "trial",
    "python_packages", "extensions", "user_api", "config", "keymap_presets",
    "layouts", "sort_keys", "attributes",
)

# What app.py itself writes to a stream: the --help text and the startup notices.
APP_STREAM_NAMES = ("_CLI_DESCRIPTION", "_CLI_EPILOG", "create_parser",
                    "_web_access_message", "_curses_backend_notice", "main")

EXEMPT_MARK = "# non-ASCII:"


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _non_ascii(path: Path, pick=None) -> list[str]:
    """``file:line: text`` for each non-ASCII string literal under the nodes
    ``pick(tree)`` returns (the whole module when None), docstrings and exempt
    statements aside."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    skip = _docstrings(tree)
    exempt = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno > 1 \
                and EXEMPT_MARK in lines[node.lineno - 2]:
            exempt.update(range(node.lineno, node.end_lineno + 1))
    found = []
    for root in pick(tree) if pick is not None else [tree]:
        for node in ast.walk(root):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip and node.lineno not in exempt
                    and not node.value.isascii()):
                found.append(f"{path.relative_to(_ROOT)}:{node.lineno}: {node.value!r}")
    return found


class StreamTextIsAscii(unittest.TestCase):
    def test_stream_modules(self):
        found = []
        for name in STREAM_MODULES:
            found += _non_ascii(_PKG / f"{name}.py")
        self.assertEqual(found, [], "use ASCII (' - ', '...', '->', '>') or mark "
                                    f"a screen-only literal with '{EXEMPT_MARK}'")

    def test_what_app_py_writes(self):
        def named(tree):
            roots = []
            for node in tree.body:
                name = getattr(node, "name", None)
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                    name = node.targets[0].id
                if name in APP_STREAM_NAMES:
                    roots.append(node)
            self.assertEqual(len(roots), len(APP_STREAM_NAMES), "a name moved")
            return roots
        self.assertEqual(_non_ascii(_PKG / "app.py", named), [])

    def test_every_print(self):
        found = []
        for path in sorted(_PKG.rglob("*.py")):
            found += _non_ascii(path, lambda tree: [
                n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "print"])
        self.assertEqual(found, [])


class RedirectedToCp932(unittest.TestCase):
    """``xefm keys`` with stdout a pipe in cp932, echoing a name cp932 lacks."""

    def test_unencodable_text_is_replaced_not_raised(self):
        home = Path(os.path.realpath(tempfile.mkdtemp(prefix="xefm-cp932-")))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        (home / ".xefm").mkdir()
        template = (_PKG / "_config.py").read_text(encoding="utf-8")
        anchor = "    KEY_BINDINGS = {\n"
        (home / ".xefm" / "config.py").write_text(
            template.replace(anchor, anchor + "        'relod—config': ['F12'],\n", 1),
            encoding="utf-8")
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        env.update(HOME=str(home), USERPROFILE=str(home),
                   PYTHONIOENCODING="cp932", PYTHONUTF8="0")
        result = subprocess.run([sys.executable, "-m", "xefm", "keys", "F12"],
                                cwd=_ROOT, env=env, capture_output=True, timeout=120)
        stderr = result.stderr.decode("cp932", errors="replace")
        self.assertNotIn("Traceback", stderr)
        self.assertIn(b"no action is called 'relod?config'", result.stdout)


if __name__ == "__main__":
    unittest.main()
