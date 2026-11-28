"""Extension packages (#583): the static check, the installed set, install /
uninstall, loading into a config under "config.py wins", key suggestions,
settings classes, and the ``xefm ext`` CLI.

Every test works in a temporary ``~/.xefm`` stand-in (:class:`Layout`), and
each package gets its own uniquely named Python package, since loading one
imports it into this process.

Run with: python -m pytest test/test_extensions.py -v
"""

import io
import itertools
import os
import shutil
import sys
import tempfile
import textwrap
import time
import types
import unittest
import urllib.error
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import extension_cli  # noqa: E402
from xefm import extensions as ext  # noqa: E402

_serial = itertools.count()


def _config(**tables):
    config = types.SimpleNamespace(KEY_BINDINGS={})
    for name, value in tables.items():
        setattr(config, name, value)
    return config


def _no_release_asset(url, payload):
    """A fake GitHub whose tags have no release asset: the asset URL is a 404,
    and anything else returns ``payload``."""
    if "/releases/download/" in url:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return payload


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp()))
        self.layout = ext.Layout(self.home)
        self.src = Path(os.path.realpath(tempfile.mkdtemp()))
        self._path = list(sys.path)

    def tearDown(self):
        sys.path[:] = self._path
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.src, ignore_errors=True)

    def package(self, ext_id=None, *, manifest=None, code=None, where=None,
                module=None):
        """Write a package; returns ``(root, module_name)``. ``manifest`` is
        TOML with ``{id}`` and ``{mod}`` filled in."""
        n = next(_serial)
        ext_id = ext_id or f"t{n}-ext"
        module = module or f"xefm_test_ext_{n}"
        root = (where or self.src) / ext_id
        root.mkdir(parents=True)
        if manifest is None:
            manifest = '''
                [extension]
                id = "{id}"
                version = "0.1.0"
                api_version = 1

                [contributes.actions]
                "{id}.greet" = {{ entry = "{mod}.actions:greet", description = "Say hello" }}
            '''
        (root / ext.MANIFEST).write_text(
            textwrap.dedent(manifest).format(id=ext_id, mod=module), encoding="utf-8")
        if code is None:
            code = {"actions.py": '''
                from xefm.user_api import extension

                calls = []

                def greet(ctx):
                    """Say hello."""
                    calls.append(extension(__name__))
            '''}
        if code:
            pkg = root / module
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            for name, text in code.items():
                (pkg / name).write_text(textwrap.dedent(text), encoding="utf-8")
        return root, module

    def installed_package(self, *args, **kwargs):
        return self.package(*args, where=self.layout.packages, **kwargs)


class Check(_Home):
    def problems(self, root, **kw):
        manifest, problems = ext.check_package(root, **kw)
        return problems

    def test_a_good_package_passes(self):
        root, _ = self.package()
        self.assertEqual(ext.errors(self.problems(root)), [])

    def test_no_manifest(self):
        (problem,) = self.problems(self.src)
        self.assertIn("no xefm-extension.toml", problem.message)

    def test_a_file_is_not_a_package(self):
        """A path to a file is a problem to report, not a traceback (#743)."""
        archive = self.src / "pkg.zip"
        archive.write_bytes(b"PK")
        (problem,) = self.problems(archive)
        self.assertIn("is not a directory", problem.message)

    def test_bad_toml_names_the_problem(self):
        root, _ = self.package(manifest="[extension\n")
        (problem,) = self.problems(root)
        self.assertIn("not valid TOML", problem.message)

    def test_a_reference_is_resolved_without_running_the_module(self):
        root, mod = self.package(code={"actions.py": '''
            raise SystemExit("imported!")

            def greet(ctx):
                pass
        '''})
        self.assertEqual(ext.errors(self.problems(root)), [])
        self.assertNotIn(f"{mod}.actions", sys.modules)

    def test_a_missing_function_is_named_with_its_field(self):
        root, mod = self.package(code={"actions.py": "def hello(ctx): pass\n"})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn(".entry", problem.where)
        self.assertIn(f"module {mod}.actions has no top-level 'greet'", problem.message)

    def test_a_missing_module_says_which_file_was_expected(self):
        root, mod = self.package(code={"other.py": ""})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn(f"{mod}/actions.py", problem.message)

    def test_a_syntax_error_has_its_line(self):
        root, _ = self.package(code={"actions.py": "def greet(ctx):\n    return (\n"})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn("syntax error", problem.message)

    def test_unknown_sections_and_keys_are_errors(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1
            colour = "blue"

            [extras]
            x = 1
        ''', code={})
        wheres = {p.where for p in ext.errors(self.problems(root))}
        self.assertIn("extension.colour", wheres)
        self.assertIn("extras", wheres)

    def test_required_fields(self):
        root, _ = self.package(manifest="[extension]\n", code={})
        wheres = {p.where for p in ext.errors(self.problems(root))}
        self.assertTrue({"extension.id", "extension.version",
                         "extension.api_version"} <= wheres)

    def test_a_newer_api_version_is_refused(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 99
        ''', code={})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn("asks for API version 99", problem.message)

    def test_a_package_written_for_api_0_still_loads_with_a_warning(self):
        """0 was the all-Preview API. A package that says so is not refused —
        what it used may still be there — but it is told the API moved on."""
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 0
        ''', code={})
        problems = self.problems(root)
        self.assertEqual(ext.errors(problems), [])
        self.assertTrue(any("written for API version 0" in p.message
                            for p in problems))

    def test_min_xefm(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1
            min_xefm = "99.0"
        ''', code={})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn("needs XeFM 99.0", problem.message)

    def test_a_built_in_action_name_is_refused(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            rename = "{mod}.actions:greet"
        ''')
        (problem,) = ext.errors(self.problems(root))
        self.assertIn("built-in action", problem.message)

    def test_an_unprefixed_action_name_is_a_warning(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            greet = "{mod}.actions:greet"
        ''')
        problems = self.problems(root)
        self.assertEqual(ext.errors(problems), [])
        self.assertTrue(any("<extension>.greet" in p.message for p in problems))

    def test_key_suggestions_are_parsed_and_must_name_own_actions(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [contributes.key_suggestions]
            "{id}.greet" = ["Hyper-G"]
            "someone.else" = ["Ctrl-G"]
        ''')
        messages = [p.message for p in ext.errors(self.problems(root))]
        self.assertTrue(any("unknown modifier 'Hyper'" in m for m in messages))
        self.assertTrue(any("does not contribute" in m for m in messages))

    def test_menus_must_name_own_actions_and_known_menus(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [contributes.menus]
            "{id}.greet" = {{ menus = ["file", "toolbar"], label = "Greet" }}
            "someone.else" = {{ menus = ["file"], label = "Else" }}
        ''')
        messages = [p.message for p in ext.errors(self.problems(root))]
        self.assertTrue(any("needs menus = a list of file, context" in m for m in messages))
        self.assertTrue(any("does not contribute" in m for m in messages))

    def test_a_good_menu_entry_passes_and_runs_no_code(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [contributes.menus]
            "{id}.greet" = {{ menus = ["file", "context"], label = "Greet: Hi", when = "selection" }}
        ''')
        self.assertEqual(ext.errors(self.problems(root)), [])
        manifest = ext.read_manifest(root)
        self.assertEqual([ref for _, ref in manifest.references()],
                         [f"{manifest.contributes['actions'][f'{root.name}.greet']}"])

    def test_a_menu_entry_needs_a_label_and_a_known_when(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"
            "{id}.wave" = "{mod}.actions:greet"

            [contributes.menus]
            "{id}.greet" = {{ menus = ["file"] }}
            "{id}.wave" = {{ menus = ["file"], label = "Wave", when = "sometimes" }}
        ''')
        messages = [p.message for p in ext.errors(self.problems(root))]
        self.assertTrue(any("needs label" in m for m in messages))
        self.assertTrue(any("when must be one of" in m for m in messages))

    def _with_updates(self, value):
        root, _ = self.package(manifest=f'''
            [extension]
            id = "{{id}}"
            version = "0.1.0"
            api_version = 1
            updates = {value}

            [contributes.actions]
            "{{id}}.greet" = "{{mod}}.actions:greet"
        ''')
        return [p for p in self.problems(root) if p.where == "extension.updates"]

    def test_updates_names_a_github_repository_or_a_package_in_one(self):
        self.assertEqual(self._with_updates('"github:crftwr/xefm-extensions/compute-hash"'), [])
        self.assertEqual(self._with_updates('"github:someone/hello-xefm"'), [])
        for bad in ('"github:crftwr/x@v1"', '"https://example.com/x.zip"', "3"):
            (problem,) = self._with_updates(bad)
            self.assertEqual(problem.severity, "error")
            self.assertIn("with no @ref", problem.message)

    def test_an_unknown_event_is_named(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.event_hooks]
            lunch = "{mod}.hooks:on_lunch"
        ''', code={"hooks.py": "def on_lunch(ctx, event): pass\n"})
        (problem,) = ext.errors(self.problems(root))
        self.assertIn("'lunch' is not an event", problem.message)

    def test_a_callback_must_take_what_xefm_passes(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.code:greet"
            "{id}.fine" = "{mod}.code:fine"

            [contributes.event_hooks]
            directory_changed = ["{mod}.code:old_hook", "{mod}.code:new_hook"]
        ''', code={"code.py": '''
            def greet(ctx, extra):
                pass

            def fine(ctx, *args, flag=False):
                pass

            def old_hook(ctx, pane, old_path, new_path):
                pass

            def new_hook(ctx, event):
                pass
        '''})
        problems = ext.errors(self.problems(root))
        self.assertEqual(sorted(p.message.split(" cannot")[0] for p in problems),
                         ["greet", "old_hook"])
        self.assertTrue(any("cannot be called as fn(ctx, event)" in p.message
                            for p in problems))

    def test_a_data_only_package_needs_no_code(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.themes."Solar Night"]
            base = "dark"
            accent = [255, 160, 0]

            [contributes.filters.pictures]
            globs = ["*.png", "*.jpg"]
        ''', code={})
        manifest, problems = ext.check_package(root)
        self.assertEqual(ext.errors(problems), [])
        self.assertFalse(manifest.runs_code)

    def test_a_module_shadowing_the_standard_library_is_refused(self):
        root, _ = self.package(module="json", code={"actions.py": "def greet(c): pass"})
        messages = [p.message for p in ext.errors(self.problems(root))]
        self.assertTrue(any("shadow the standard library" in m for m in messages))

    def test_two_packages_providing_one_module_collide(self):
        a, mod = self.package()
        b, _ = self.package(module=mod)
        others = [ext.read_manifest(a)]
        messages = [p.message for p in ext.errors(self.problems(b, others=others))]
        self.assertTrue(any(f"'{mod}' is also provided by" in m for m in messages))

    def test_missing_programs_are_warnings(self):
        root, _ = self.package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [requires]
            programs = ["no-such-program-xefm"]
        ''', code={})
        problems = self.problems(root)
        self.assertEqual(ext.errors(problems), [])
        self.assertTrue(any("not on PATH" in p.message for p in problems))


class Load(_Home):
    def test_actions_are_folded_into_the_config(self):
        root, mod = self.installed_package()
        config = _config()
        report = ext.load(config, self.layout)
        self.assertEqual([m.id for m in report.loaded], [root.name])
        spec = config.ACTIONS[f"{root.name}.greet"]
        self.assertEqual(spec["description"], "Say hello")
        from xefm.user_api import ActionContext
        ctx = ActionContext(None)
        spec["func"](ctx)
        handle = sys.modules[f"{mod}.actions"].calls[-1]
        self.assertEqual(handle.id, root.name)

    def test_a_package_finds_itself_from_its_module_name_at_any_time(self):
        """#679: the answer comes from __name__, not from what is running, so
        a prompt callback run after the action returned — or a worker, or a
        sort key — gets the same handle."""
        from xefm.user_api import extension
        root, mod = self.installed_package()
        ext.load(_config(), self.layout)
        handle = extension(f"{mod}.actions")
        self.assertEqual(handle.id, root.name)
        self.assertIs(extension(f"{mod}.deep.inner"), handle)
        self.assertIs(extension(mod), handle)
        self.assertIsNone(extension("config"), "config.py's own code")
        self.assertIsNone(extension("someone_else"))

    def test_a_reload_forgets_packages_that_no_longer_load(self):
        from xefm.user_api import extension
        root, mod = self.installed_package()
        ext.load(_config(), self.layout)
        self.assertIsNotNone(extension(mod))
        ext.set_enabled(root.name, False, self.layout)
        ext.load(_config(), self.layout)
        self.assertIsNone(extension(mod))

    def test_menus_are_folded_into_menu_items(self):
        root, _ = self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [contributes.menus]
            "{id}.greet" = {{ menus = ["context"], label = "Greet" }}
        ''')
        config = _config()
        ext.load(config, self.layout)
        self.assertEqual(config.MENU_ITEMS,
                         {f"{root.name}.greet": {"menus": ["context"], "label": "Greet"}})

    def test_config_py_wins(self):
        root, _ = self.installed_package()
        mine = object()
        config = _config(ACTIONS={f"{root.name}.greet": mine})
        report = ext.load(config, self.layout)
        self.assertIs(config.ACTIONS[f"{root.name}.greet"], mine)
        self.assertTrue(any("config.py wins" in w for w in report.warnings))

    def test_between_two_extensions_the_first_loaded_wins_and_is_named(self):
        manifest = '''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "shared.greet" = "{mod}.actions:greet"
        '''
        first, _ = self.installed_package(manifest=manifest, ext_id="aa-first")
        self.installed_package(manifest=manifest, ext_id="zz-second")
        config = _config()
        report = ext.load(config, self.layout)
        self.assertEqual(len(report.loaded), 2)
        clash = [w for w in report.warnings if "shared.greet" in w]
        self.assertEqual(len(clash), 1, report.warnings)
        self.assertIn("zz-second:", clash[0])
        self.assertIn("aa-first loaded first and wins", clash[0])
        self.assertNotIn("config.py", clash[0])

    def test_a_failing_package_is_skipped_with_its_reason(self):
        root, _ = self.installed_package(code={"actions.py": "def hello(c): pass"})
        config = _config()
        report = ext.load(config, self.layout)
        self.assertEqual(report.loaded, [])
        (label, reason) = report.skipped[0]
        self.assertEqual(label, root.name)
        self.assertIn("no top-level 'greet'", reason)
        self.assertFalse(getattr(config, "ACTIONS", None))

    def test_an_import_failure_leaves_nothing_half_loaded(self):
        root, _ = self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.a" = "{mod}.actions:greet"
            "{id}.b" = "{mod}.broken:greet"
        ''', code={"actions.py": "def greet(c): pass",
                   "broken.py": "import no_such_module_xefm\ndef greet(c): pass"})
        config = _config()
        report = ext.load(config, self.layout)
        self.assertEqual(report.loaded, [])
        self.assertIn("failed to load", report.skipped[0][1])
        self.assertFalse(getattr(config, "ACTIONS", None))

    def test_disabled_packages_are_skipped(self):
        root, _ = self.installed_package()
        ext.set_enabled(root.name, False, self.layout)
        report = ext.load(_config(), self.layout)
        self.assertEqual(report.skipped, [(root.name, "disabled")])

    def test_backend_and_platform_gates(self):
        self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1
            backends = ["desktop"]
        ''', code={})
        with patch.object(ext, "_current_backend", return_value="tui"):
            report = ext.load(_config(), self.layout)
        self.assertIn("tui backend", report.skipped[0][1])

    def test_missing_host_package_skips(self):
        self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [requires]
            host_packages = ["no_such_host_package_xefm"]
        ''', code={})
        report = ext.load(_config(), self.layout)
        self.assertIn("no_such_host_package_xefm", report.skipped[0][1])

    def test_an_action_needing_a_missing_program_refuses_to_run(self):
        root, mod = self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [requires]
            programs = ["no-such-program-xefm"]
        ''')
        config = _config()
        ext.load(config, self.layout)
        config.ACTIONS[f"{root.name}.greet"]["func"](types.SimpleNamespace())
        self.assertEqual(sys.modules[f"{mod}.actions"].calls, [])

    def test_attribute_and_layout_contributions(self):
        """An attribute's provider and a layout's format are references; the
        rest of each is data, as in config.py (#633, #756)."""
        root, mod = self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.attributes."{id}.kind"]
            label = "Kind"
            type = "enum"
            read = "{mod}.attrs:kinds"

            [contributes.layouts."{id}"]
            label = "Kinds"
            columns = ["name", {{ attr = "{id}.kind", format = "{mod}.attrs:mark" }}]
        ''', code={"attrs.py": '''
            def kinds(directory, entries):
                return ["k" for _ in entries]

            def mark(value, entry):
                return value or ""
        '''})
        self.assertEqual(ext.errors(ext.check_package(root)[1]), [])
        config = _config()
        ext.load(config, self.layout)
        attrs = sys.modules[f"{mod}.attrs"]
        spec = config.ATTRIBUTES[f"{root.name}.kind"]
        self.assertEqual(spec["type"], "enum")
        self.assertEqual(spec["read"](None, [1, 2]), ["k", "k"])
        column = config.LAYOUTS[root.name]["columns"][1]
        self.assertIs(column["format"], attrs.mark)

    def test_an_extra_is_overridden_by_config_key_by_key(self):
        """config.py names only what it changes on an extension's extra (#756)."""
        root, mod = self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.layout_extras."{id}"]
            label = "Kinds"
            when = "{mod}.attrs:here"
            markers = [{{ attr = "name", format = "{mod}.attrs:mark", side = "before" }}]
        ''', code={"attrs.py": '''
            def here(path):
                return True

            def mark(value, entry):
                return "k"
        '''})
        self.assertEqual(ext.errors(ext.check_package(root)[1]), [])
        config = _config(LAYOUT_EXTRAS={root.name: {"when": "never"}})
        ext.load(config, self.layout)
        spec = config.LAYOUT_EXTRAS[root.name]
        self.assertEqual(spec["when"], "never")                       # config's
        self.assertEqual(spec["label"], "Kinds")                      # the rest kept
        self.assertIs(spec["markers"][0]["format"], sys.modules[f"{mod}.attrs"].mark)

    def test_data_contributions(self):
        self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.themes."Solar Night"]
            base = "dark"

            [contributes.lexers]
            "*.dclx" = "python"
        ''', code={})
        config = _config(THEMES={"Mine": {"base": "light"}})
        ext.load(config, self.layout)
        self.assertEqual(set(config.THEMES), {"Mine", "Solar Night"})
        self.assertEqual(config.LEXERS, {"*.dclx": "python"})


class KeySuggestions(_Home):
    def _package(self, key):
        return self.installed_package(manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [contributes.key_suggestions]
            "{id}.greet" = ["%s"]
        ''' % key)

    def test_a_free_key_is_bound(self):
        root, _ = self._package("Ctrl-Shift-F12")
        config = _config()
        ext.load(config, self.layout)
        self.assertEqual(config.KEY_BINDINGS[f"{root.name}.greet"], ["Ctrl-Shift-F12"])

    def test_a_taken_key_is_not(self):
        root, _ = self._package("R")   # rename's default key
        config = _config()
        report = ext.load(config, self.layout)
        self.assertNotIn(f"{root.name}.greet", config.KEY_BINDINGS)
        self.assertTrue(any("already in use" in w for w in report.warnings))

    def test_the_user_s_own_binding_wins(self):
        root, _ = self._package("Ctrl-Shift-F12")
        config = _config(KEY_BINDINGS={f"{self.layout.packages.name}": [],
                                       "placeholder": []})
        config.KEY_BINDINGS[f"{root.name}.greet"] = []   # explicitly unbound
        ext.load(config, self.layout)
        self.assertEqual(config.KEY_BINDINGS[f"{root.name}.greet"], [])


class Settings(_Home):
    def _package(self, ext_id="command-palette", extra=""):
        return self.installed_package(ext_id, manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [settings]
            defaults = "{mod}.settings:Settings"
        ''' + extra, code={"settings.py": '''
            class Settings:
                MAX_ITEMS = 20
                SHOW_KEYS = True
        '''})

    def test_the_class_name_is_derived_from_the_id(self):
        root, _ = self._package()
        self.assertEqual(ext.config_class_name(ext.read_manifest(root)),
                         "CommandPaletteConfig")

    def test_the_manifest_can_name_it(self):
        root, _ = self._package("palette-x", extra='config_class = "PaletteConfig"\n')
        self.assertEqual(ext.config_class_name(ext.read_manifest(root)), "PaletteConfig")

    def test_a_plain_class_overrides_defaults(self):
        self._package()

        class CommandPaletteConfig:
            MAX_ITEMS = 30

        ext.load(_config(), self.layout,
                 namespace={"__name__": "user_config",
                            "CommandPaletteConfig": CommandPaletteConfig})
        settings = ext.settings_for("command-palette")
        self.assertEqual(settings.MAX_ITEMS, 30)
        self.assertTrue(settings.SHOW_KEYS, "unset names keep their defaults")

    def test_no_class_means_defaults(self):
        self._package()
        ext.load(_config(), self.layout, namespace={})
        self.assertEqual(ext.settings_for("command-palette").MAX_ITEMS, 20)

    def test_an_unknown_setting_is_a_warning_naming_the_known_ones(self):
        self._package()

        class CommandPaletteConfig:
            MAX_ITEM = 30

        report = ext.load(_config(), self.layout,
                          namespace={"CommandPaletteConfig": CommandPaletteConfig})
        self.assertTrue(any("no setting 'MAX_ITEM'" in w and "MAX_ITEMS" in w
                            for w in report.warnings))
        self.assertEqual(ext.settings_for("command-palette").MAX_ITEMS, 20)

    def test_a_config_class_nobody_claims_is_a_warning(self):
        self._package()

        class CommandPalleteConfig:   # misspelt
            MAX_ITEMS = 30
        CommandPalleteConfig.__module__ = "user_config"

        report = ext.load(_config(), self.layout, namespace={
            "__name__": "user_config", "CommandPalleteConfig": CommandPalleteConfig})
        self.assertTrue(any("CommandPalleteConfig matches no installed" in w
                            for w in report.warnings))

    def test_two_packages_deriving_one_name_collide(self):
        a, _ = self._package("foo-bar")
        b, _ = self._package("foo_bar")
        problems = ext.check_manifest(ext.read_manifest(b),
                                      others=[ext.read_manifest(a)], machine=False)
        self.assertTrue(any(p.where == "settings.config_class" for p in problems))

    def test_the_template_lists_every_default(self):
        root, _ = self._package()
        text = ext.settings_template(ext.read_manifest(root))
        self.assertIn("class CommandPaletteConfig:", text)
        self.assertIn("# MAX_ITEMS = 20", text)

    def test_the_handle_reads_the_settings(self):
        root, _ = self._package()
        ext.load(_config(), self.layout, namespace={})
        handle = ext.ExtensionHandle(ext.read_manifest(root), self.layout)
        self.assertEqual(handle.settings.MAX_ITEMS, 20)


class Install(_Home):
    def test_install_from_a_directory(self):
        root, _ = self.package()
        manifest = ext.install(str(root), self.layout)
        self.assertTrue((self.layout.packages / manifest.id / ext.MANIFEST).is_file())
        entry = ext.read_installed(self.layout)[manifest.id]
        self.assertEqual(entry.version, "0.1.0")
        self.assertEqual(entry.source, str(root))
        self.assertTrue(entry.enabled)

    def _zip(self, root, prefix=""):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for path in root.rglob("*"):
                if path.is_file():
                    z.write(path, prefix + str(path.relative_to(root)))
        return buf.getvalue()

    def test_install_from_a_zip(self):
        root, _ = self.package()
        archive = self.src / "pkg.zip"
        archive.write_bytes(self._zip(root))
        manifest = ext.install(str(archive), self.layout)
        self.assertTrue((self.layout.packages / manifest.id).is_dir())

    def test_install_from_github_unwraps_the_repo_folder(self):
        root, _ = self.package()
        payload = self._zip(root, prefix="repo-main/")
        urls = []

        def opener(url):
            urls.append(url)
            return _no_release_asset(url, payload)

        manifest = ext.install("github:someone/repo@main", self.layout, opener=opener)
        self.assertEqual(urls[-1], "https://codeload.github.com/someone/repo/zip/main")
        self.assertEqual(ext.read_installed(self.layout)[manifest.id].source,
                         "github:someone/repo@main")

    def test_install_from_a_subdirectory_of_a_github_repository(self):
        """One repository, several packages (crftwr/xefm-extensions): the path
        after owner/repo names the package's directory."""
        first, _ = self.package()
        second, _ = self.package()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, root in (("one", first), ("two", second)):
                for path in root.rglob("*"):
                    if path.is_file():
                        z.write(path, f"exts-v1/packages/{name}/{path.relative_to(root)}")
        urls = []

        def opener(url):
            urls.append(url)
            return _no_release_asset(url, buf.getvalue())

        source = "github:crftwr/exts/packages/two@v1"
        manifest = ext.install(source, self.layout, opener=opener)
        self.assertEqual(urls, [
            "https://github.com/crftwr/exts/releases/download/v1/v1.zip",
            "https://codeload.github.com/crftwr/exts/zip/v1"])
        self.assertEqual(manifest.id, second.name)
        self.assertEqual(ext.read_installed(self.layout)[manifest.id].source, source)
        with self.assertRaises(ext.InstallError) as caught:
            ext.install("github:crftwr/exts/packages/three@v1", self.layout,
                        opener=opener)
        self.assertIn("packages/three/", str(caught.exception))

    def test_github_sources_parse(self):
        parse = ext.parse_github_source
        self.assertEqual(parse("github:o/r"), ("o", "r", "", None))
        self.assertEqual(parse("github:o/r@v1.2"), ("o", "r", "", "v1.2"))
        self.assertEqual(parse("github:o/r/a/b@feature/x"), ("o", "r", "a/b", "feature/x"))
        for bad in ("github:o", "github:o/r/../x", "gh:o/r", "github:o/r/"):
            self.assertIsNone(parse(bad), bad)

    def test_a_zip_escaping_its_folder_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "x")
        archive = self.src / "evil.zip"
        archive.write_bytes(buf.getvalue())
        with self.assertRaises(ext.InstallError):
            ext.install(str(archive), self.layout)
        self.assertFalse((self.src.parent / "evil.txt").exists())

    def test_a_failing_package_installs_nothing(self):
        root, _ = self.package(code={"actions.py": "def hello(c): pass"})
        with self.assertRaises(ext.InstallError) as caught:
            ext.install(str(root), self.layout)
        self.assertTrue(caught.exception.problems)
        self.assertFalse(self.layout.packages.exists()
                         and any(self.layout.packages.iterdir()))

    def test_a_local_package_is_never_overwritten(self):
        root, _ = self.package("same-id")
        self.installed_package("same-id")
        with self.assertRaises(ext.InstallError) as caught:
            ext.install(str(root), self.layout)
        self.assertIn("was not installed by XeFM", str(caught.exception))

    def test_reinstall_upgrades_and_keeps_disabled(self):
        root, _ = self.package("up")
        ext.install(str(root), self.layout)
        ext.set_enabled("up", False, self.layout)
        (root / ext.MANIFEST).write_text(
            (root / ext.MANIFEST).read_text().replace('"0.1.0"', '"0.2.0"'))
        ext.install(str(root), self.layout)
        entry = ext.read_installed(self.layout)["up"]
        self.assertEqual(entry.version, "0.2.0")
        self.assertFalse(entry.enabled)

    def test_uninstall_keeps_data_unless_asked(self):
        root, _ = self.package("gone")
        ext.install(str(root), self.layout)
        data = self.layout.data_dir("gone")
        data.mkdir(parents=True)
        ext.uninstall("gone", self.layout)
        self.assertFalse((self.layout.packages / "gone").exists())
        self.assertNotIn("gone", ext.read_installed(self.layout))
        self.assertTrue(data.exists())

    def test_uninstall_with_data(self):
        root, _ = self.package("gone")
        ext.install(str(root), self.layout)
        self.layout.data_dir("gone").mkdir(parents=True)
        ext.uninstall("gone", self.layout, delete_data=True)
        self.assertFalse(self.layout.data_dir("gone").exists())

    def test_sync_rebuilds_missing_directories(self):
        root, _ = self.package("again")
        ext.install(str(root), self.layout)
        shutil.rmtree(self.layout.packages / "again")
        report = ext.sync(self.layout)
        self.assertEqual(report, [f"again: reinstalled from {root}"])
        self.assertTrue((self.layout.packages / "again").is_dir())

    def test_the_installed_set_round_trips_odd_strings(self):
        entries = {"x": ext.InstalledEntry(id="x", version='1"0', source="C:\\a b\\c",
                                           directory="x", enabled=False)}
        ext.write_installed(self.layout, entries)
        self.assertEqual(ext.read_installed(self.layout), entries)

    def test_summary_names_what_runs(self):
        root, mod = self.package()
        lines = ext.summarize(ext.read_manifest(root))
        self.assertIn(f"action: {root.name}.greet  (runs {mod}.actions:greet)", lines)


class Cli(_Home):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), patch("sys.stderr", out):
            code = extension_cli.main(list(argv), layout=self.layout)
        return code, out.getvalue()

    def test_check_exit_status(self):
        good, _ = self.package()
        code, out = self.run_cli("check", str(good))
        self.assertEqual(code, 0, out)
        self.assertIn("ok:", out)
        bad, _ = self.package(code={"actions.py": ""})
        code, out = self.run_cli("check", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("error: xefm-extension.toml: contributes.actions", out)

    def test_check_shows_what_the_package_adds(self):
        """The summary install shows before asking, so a package can be
        reviewed before it is installed (#743) — also when the check fails."""
        good, mod = self.package("adds-ext")
        code, out = self.run_cli("check", str(good))
        self.assertEqual(code, 0, out)
        self.assertIn("adds-ext 0.1.0 (adds-ext) adds:", out)
        self.assertIn(f"  action: adds-ext.greet  (runs {mod}.actions:greet)", out)
        bad, _ = self.package(code={"actions.py": ""})
        code, out = self.run_cli("check", str(bad))
        self.assertEqual(code, 1)
        self.assertIn(f"({bad.name}) adds:", out)

    def test_check_takes_a_zip(self):
        root, _ = self.package("zipped-ext")
        archive = self.src / "zipped.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for path in root.rglob("*"):
                if path.is_file():
                    z.write(path, f"zipped-ext-v1/{path.relative_to(root)}")
        code, out = self.run_cli("check", str(archive))
        self.assertEqual(code, 0, out)
        self.assertIn("ok: zipped-ext 0.1.0", out)

    def test_check_takes_a_github_source(self):
        root, _ = self.package("remote-ext")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for path in root.rglob("*"):
                if path.is_file():
                    z.write(path, f"exts-main/pkgs/remote-ext/{path.relative_to(root)}")
        with patch.object(ext, "_open_url",
                          lambda url: _no_release_asset(url, buf.getvalue())):
            code, out = self.run_cli("check", "github:someone/exts/pkgs/remote-ext@main")
        self.assertEqual(code, 0, out)
        self.assertIn("ok: remote-ext 0.1.0", out)

    def test_check_names_a_source_it_cannot_fetch(self):
        code, out = self.run_cli("check", str(self.src / "nowhere"))
        self.assertEqual(code, 1)
        self.assertIn("is not a directory, a zip", out)
        not_zip = self.src / "notes.txt"
        not_zip.write_text("hello", encoding="utf-8")
        code, out = self.run_cli("check", str(not_zip))
        self.assertEqual(code, 1)
        self.assertIn("is not a zip file", out)

    def test_check_judges_an_upgrade_as_install_does(self):
        """A newer copy of an installed package is an upgrade, not a clash of
        ids; a copy of a *local* package's id is refused, as install refuses it."""
        root, _ = self.package("up-ext")
        ext.install(str(root), self.layout)
        code, out = self.run_cli("check", str(root))
        self.assertEqual(code, 0, out)
        self.installed_package("mine-ext")
        other = self.src / "elsewhere"
        other.mkdir()
        copy, _ = self.package("mine-ext", where=other)
        code, out = self.run_cli("check", str(copy))
        self.assertEqual(code, 1, out)
        self.assertIn("was not installed by XeFM", out)

    def test_install_fetches_once(self):
        """The copy whose summary was shown is the one installed."""
        root, _ = self.package("once-ext")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for path in root.rglob("*"):
                if path.is_file():
                    z.write(path, f"once-main/{path.relative_to(root)}")
        urls = []

        def opener(url):
            urls.append(url)
            return _no_release_asset(url, buf.getvalue())

        with patch.object(ext, "_open_url", opener), \
                patch("builtins.input", return_value="y"):
            code, out = self.run_cli("install", "github:someone/once@main")
        self.assertEqual(code, 0, out)
        self.assertIn("once-ext 0.1.0 (once-ext) adds:", out)
        self.assertEqual(urls.count("https://codeload.github.com/someone/once/zip/main"), 1)

    def test_install_list_disable_uninstall(self):
        root, _ = self.package("cli-ext")
        code, out = self.run_cli("install", "--yes", str(root))
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("list")
        self.assertIn("cli-ext 0.1.0 [enabled]", out)
        self.run_cli("disable", "cli-ext")
        code, out = self.run_cli("list")
        self.assertIn("[disabled]", out)
        code, out = self.run_cli("uninstall", "--keep-data", "cli-ext")
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("list")
        self.assertIn("no extension packages", out)

    def test_settings_prints_the_class(self):
        self.installed_package("pal", manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [settings]
            defaults = "{mod}.settings:Settings"
        ''', code={"settings.py": "class Settings:\n    LIMIT = 3\n"})
        code, out = self.run_cli("settings", "pal")
        self.assertEqual(code, 0, out)
        self.assertIn("class PalConfig:", out)
        self.assertIn("# LIMIT = 3", out)


class ConfigManagerIntegration(_Home):
    """The real loader: config.py runs, the template fills in, packages fold in,
    and a settings class beside Config is found."""

    def test_load_config_folds_packages_in(self):
        from xefm.config import ConfigManager
        root, _ = self.installed_package("palette", manifest='''
            [extension]
            id = "{id}"
            version = "0.1.0"
            api_version = 1

            [contributes.actions]
            "{id}.greet" = "{mod}.actions:greet"

            [settings]
            defaults = "{mod}.settings:Settings"
        ''', code={"actions.py": "def greet(ctx):\n    pass\n",
                   "settings.py": "class Settings:\n    LIMIT = 3\n"})
        (self.home / "config.py").write_text(textwrap.dedent('''
            class PaletteConfig:
                LIMIT = 9

            class Config:
                pass
        '''), encoding="utf-8")
        manager = ConfigManager()
        manager.config_dir = self.home
        manager.config_file = self.home / "config.py"
        manager.user_tools_dir = self.home / "tools"
        manager.user_extensions_dir = self.home / "extensions"
        config = manager.load_config()
        self.assertIn("palette.greet", config.ACTIONS)
        self.assertTrue(hasattr(config, "FONT_SIZE"), "template filled in first")
        self.assertEqual([m.id for m in manager.extension_report.loaded], ["palette"])
        self.assertEqual(ext.settings_for("palette").LIMIT, 9)


if __name__ == "__main__":
    unittest.main()


class AppInstall(_Home):
    """Tools ▸ Advanced ▸ Install Extension on the focused package folder."""

    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm.state_manager import XeFMStateManager
        self.root, _ = self.package("app-ext")
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, str(self.src), str(self.src),
                                    left_provided=True, right_provided=True,
                                    state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app._settle_listings()
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index("app-ext")

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.backend.close()
        except Exception:
            pass
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def _layer(self):
        return self.app.panel._layers[-1].widget

    def _settle(self):
        deadline = time.monotonic() + 5
        while self.app._ext_fetch_done is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.app._pump_extension_fetch())

    def _enter(self, text=None):
        """Install Extension, then Enter in its field (after typing ``text``)."""
        from xefm.input_dialog import InputDialog
        self.app.install_extension()
        dialog = self._layer()
        self.assertIsInstance(dialog, InputDialog)
        if text is not None:
            dialog.edit.text = text
        dialog._accept()
        self._settle()
        return dialog

    def test_shows_what_it_adds_then_installs_and_reloads(self):
        from puikit.widgets.message_box import MessageBox
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home), \
             patch.object(self.app, "reload_config") as reload_config:
            self.app.install_extension()
            # The package under the cursor fills the field.
            self.assertEqual(self._layer().edit.text, str(self.root))
            self._layer()._accept()
            self._settle()
            box = self._layer()
            self.assertIsInstance(box, MessageBox)
            self.assertIn("action: app-ext.greet", box.message)
            self.assertFalse(self.layout.packages.exists(), "nothing before Install")
            box._close(box.buttons.index("Install"))
        self.assertTrue((self.layout.packages / "app-ext" / ext.MANIFEST).is_file())
        reload_config.assert_called_once()

    def test_a_failing_package_lists_its_problems(self):
        from puikit.widgets.message_box import MessageBox
        from xefm.config import config_manager
        (self.root / ext.MANIFEST).write_text("[extension]\n")
        with patch.object(config_manager, "config_dir", self.home):
            self._enter()
        box = self._layer()
        self.assertIsInstance(box, MessageBox)
        self.assertIn("extension.id", box.message)
        self.assertEqual(box.buttons, ["OK"])

    def test_a_github_source_is_downloaded_once(self):
        """Pasted into the field: fetched on the worker to show what it adds,
        and that copy installed — no second download on Install."""
        from xefm.config import config_manager
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for path in self.root.rglob("*"):
                if path.is_file():
                    z.write(path, f"exts-v1/pkgs/app-ext/{path.relative_to(self.root)}")
        urls = []

        def opener(url):
            urls.append(url)
            return _no_release_asset(url, buf.getvalue())

        source = "github:someone/exts/pkgs/app-ext@v1"
        with patch.object(config_manager, "config_dir", self.home), \
             patch.object(ext, "_open_url", opener), \
             patch.object(self.app, "reload_config"):
            self._enter(f"  {source}  ")
            box = self._layer()
            self.assertIn(f"From {source}", box.message)
            box._close(box.buttons.index("Install"))
        self.assertEqual(urls[-1], "https://codeload.github.com/someone/exts/zip/v1")
        self.assertEqual(len(urls), 2)   # the release asset, then the repository
        self.assertEqual(ext.read_installed(self.layout)["app-ext"].source, source)

    def test_a_relative_path_is_the_active_pane_s(self):
        from puikit.widgets.message_box import MessageBox
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home):
            self._enter("app-ext")
        self.assertIsInstance(self._layer(), MessageBox)
        self.assertIn(f"From {self.root}", self._layer().message)

    def test_a_source_that_is_not_there_is_logged(self):
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home), \
             patch.object(self.app, "log_info") as log_info:
            self._enter("no-such-package")
        self.assertIn("not a directory, a zip", log_info.call_args.args[0])
        self.assertFalse(self.app._ext_fetch_busy)


class XefmctlExtAndKeys(AppInstall):
    """``xefmctl ext list|check|install`` and ``xefmctl keys`` against the real
    app: what an agent in a session has when `xefm` is not on PATH (#1017)."""

    def _ask(self, *argv, policy="agent"):
        # The arguments as the shell would pass them: a Windows path through
        # shlex.split would lose its backslashes.
        from xefm import remote_cli, remote_commands, remote_dispatch
        req = remote_cli.parse([str(a) for a in argv])
        req.update(policy=policy, session="3")
        cmd = remote_commands.find(req["cmd"].split())[0]
        return remote_dispatch._answer(self.app, cmd, req)

    def _text(self, answer):
        return "\n".join(i.get("text", "") for i in answer["items"])

    def test_install_asks_in_xefm_and_answers_once_installed(self):
        from puikit.widgets.message_box import MessageBox
        from xefm.config import config_manager
        from xefm.remote_dispatch import Pending
        with patch.object(config_manager, "config_dir", self.home), \
             patch.object(self.app, "reload_config") as reload_config:
            pending = self._ask("ext", "install", self.root, "--wait")
            self.assertIsInstance(pending, Pending)
            self._settle()
            box = self._layer()
            self.assertIsInstance(box, MessageBox)
            self.assertIn("asks to install this package", box.message)
            self.assertIsNone(box.default, "an Enter meant for something else installs nothing")
            self.assertFalse(self.layout.packages.exists(), "nothing before Install")
            box._close(box.buttons.index("Install"))
        answer = pending.wait()
        self.assertEqual(answer["outcome"], "installed")
        self.assertEqual(answer["items"][0]["id"], "app-ext")
        self.assertTrue((self.layout.packages / "app-ext" / ext.MANIFEST).is_file())
        reload_config.assert_called_once()

    def test_install_declined(self):
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home):
            pending = self._ask("ext", "install", self.root, "--wait")
            self._settle()
            box = self._layer()
            box._close(box.buttons.index("Cancel"))
        answer = pending.wait()
        self.assertEqual((answer["outcome"], answer["status"]), ("declined", 1))
        self.assertFalse(self.layout.packages.exists())

    def test_install_of_a_failing_package_answers_its_problems(self):
        from puikit.widgets.message_box import MessageBox
        from xefm.config import config_manager
        (self.root / ext.MANIFEST).write_text("[extension]\n")
        with patch.object(config_manager, "config_dir", self.home):
            pending = self._ask("ext", "install", self.root, "--wait")
            self._settle()
        answer = pending.wait()
        self.assertEqual((answer["outcome"], answer["status"]), ("refused", 1))
        self.assertIn("extension.id", self._text(answer))
        self.assertFalse(self.app.panel._layers and isinstance(self._layer(), MessageBox),
                         "the agent is told, not the user")

    def test_install_without_wait_answers_at_once(self):
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home):
            answer = self._ask("ext", "install", self.root)
            self.assertIn("asks the user", answer["note"])
            self._settle()
            box = self._layer()
            box._close(box.buttons.index("Cancel"))
        missing = self._ask("ext", "install", self.home / "nowhere")
        self.assertFalse(missing["ok"])

    def test_check_and_list(self):
        from xefm.config import config_manager
        with patch.object(config_manager, "config_dir", self.home):
            answer = self._ask("ext", "check", self.root, policy="user")
            self.assertEqual(answer.get("status", 0), 0)
            self.assertIn("ok: app-ext", self._text(answer))
            (self.root / ext.MANIFEST).write_text("[extension]\n")
            bad = self._ask("ext", "check", self.root, policy="user")
            self.assertEqual(bad["status"], 1)
            self.assertIn("extension.id", self._text(bad))
            empty = self._ask("ext", "list")
            self.assertEqual(empty["items"], [])
            self.assertIn("no extension packages", empty["note"])
            root, _ = self.package("listed")
            ext.install(str(root), self.layout)
            [row] = self._ask("ext", "list")["items"]
            self.assertEqual((row["id"], row["state"]), ("listed", "enabled"))

    def test_keys_reads_what_xefm_uses(self):
        text = self._text(self._ask("keys"))
        self.assertTrue(text.startswith("config:  "), text)
        self.assertIn("keymap:  ", text)
        self.assertIn("[filer]", text)
        # One action, by name: its rows alone.
        import re
        first = text.split("[filer]\n", 1)[1].split("\n", 1)[0]
        action = re.split(r"\s{2,}", first.strip())[1]
        only = self._text(self._ask("keys", action, "--context", "filer"))
        rows = [line for line in only.splitlines() if line.startswith("  ")]
        self.assertTrue(rows and all(action in line for line in rows), only)
        self.assertEqual(self._ask("keys", "--context", "nowhere")["code"], 2)
        self.assertEqual(self._ask("keys", "not_an_action_at_all")["code"], 2)
        # A binding that cannot fire is an error, with exit status 1.
        self.app.config._KEY_BINDINGS_BASE = {"reload_config": "Ctrl-Nonsense"}
        bad = self._ask("keys")
        self.assertEqual(bad["status"], 1)
        self.assertIn("error:", self._text(bad))
