"""
The in-process customization API (Preview) and the action registry under it.

Three layers, tested from the bottom up:

1. :mod:`xefm.actions` — per-context action tables, override and restore.
2. :class:`xefm.config.KeyBindings` context resolution — which keys a surface
   sees, where their defaults come from, and the guarantee that the file list
   resolves exactly as it did before contexts existed.
3. :mod:`xefm.user_api` — ``ACTIONS`` / ``EVENT_HOOKS`` loaded from a config and
   driven through a live :class:`~xefm.app.XeFMApp`.
"""

import os
import shutil
import sys
import tempfile

import pytest
from puikit import Event, EventType
from puikit.backends import create_backend

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import actions as xa  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm._config import Config as DefaultConfig  # noqa: E402
from xefm.config import KeyBindings, config_manager  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402


def key(name, char=None, mods=()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))


# --------------------------------------------------------------------------- #
# 1. The registry
# --------------------------------------------------------------------------- #

def test_builtin_actions_are_registered_per_context():
    r = xa._new_registry()
    assert r.resolve(xa.FILER, "cursor_up").context == xa.FILER
    assert r.resolve(xa.TEXT_VIEWER, "toggle_wrap").context == xa.TEXT_VIEWER
    # A viewer action is invisible to the file list and vice versa — the whole
    # point of contexts.
    assert r.resolve(xa.FILER, "toggle_wrap") is None
    assert r.resolve(xa.TEXT_VIEWER, "cursor_up") is None


def test_common_actions_are_inherited_by_every_context():
    r = xa._new_registry()
    for context in (xa.FILER, xa.TEXT_VIEWER, xa.IMAGE_VIEWER,
                    xa.FILE_DIFF, xa.DIR_DIFF):
        assert r.resolve(context, "quit").context == xa.COMMON, context
        assert r.resolve(context, "help") is not None, context


def test_defaults_for_pre_registry_actions_come_from_the_template():
    # 'copy_files' keeps its keys and its selection requirement in one place —
    # the shipped _config.py — so the registry can never drift from it.
    action = xa._new_registry().resolve(xa.FILER, "copy_files")
    assert action.resolved_default_keys() == ("C",)
    assert action.resolved_selection() == "required"


def test_new_dotted_actions_declare_their_own_defaults():
    r = xa._new_registry()
    assert r.resolve(xa.FILE_DIFF, "file_diff.next_block").resolved_default_keys() == ("n",)
    assert r.resolve(xa.TEXT_VIEWER, "text_viewer.page_down").resolved_default_keys() == ("PAGE_DOWN",)


def test_register_refuses_a_collision_without_override():
    r = xa._new_registry()
    mine = xa.Action(name="cursor_up", context=xa.FILER, func=lambda ctx: None,
                     source="user")
    assert r.register(mine) is False
    assert r.resolve(xa.FILER, "cursor_up").source == "builtin"
    assert r.register(mine, override=True) is True
    assert r.resolve(xa.FILER, "cursor_up").source == "user"


def test_dropping_user_actions_restores_the_builtin_they_shadowed():
    r = xa._new_registry()
    r.register(xa.Action(name="cursor_up", context=xa.FILER,
                         func=lambda ctx: None, source="user"), override=True)
    # The built-in stays reachable while shadowed — that is what makes wrapping
    # one possible instead of replacing it outright.
    assert r.builtin(xa.FILER, "cursor_up").source == "builtin"
    assert r.unregister_source("user") == 1
    assert r.resolve(xa.FILER, "cursor_up").source == "builtin"


def test_generation_bumps_on_every_mutation():
    r = xa._new_registry()
    before = r.generation
    r.register(xa.Action(name="mine", context=xa.FILER, func=lambda ctx: None,
                         source="user"))
    assert r.generation > before
    after = r.generation
    r.unregister_source("user")
    assert r.generation > after


# --------------------------------------------------------------------------- #
# 2. Context key resolution
# --------------------------------------------------------------------------- #

@pytest.fixture
def kb():
    return KeyBindings(DefaultConfig.KEY_BINDINGS)


def test_filer_resolves_every_default_key_exactly_as_the_flat_table_did(kb):
    """The compatibility guarantee for the registry refactor: for the shipped
    keymap, resolving in the ``filer`` context gives the same answer the old
    context-free lookup gave, for every key it binds and both selection states."""
    def event_for(parsed):
        identity, mods, mode = parsed
        if mode == "char":
            return key(identity, identity, mods)
        char = identity if len(identity) == 1 else None
        if char and "shift" in mods:
            char = char.upper()
        return key(identity, char, mods)

    seen = set()
    for parsed, _name, _sel in kb._context_entries(xa.FILER):
        if parsed in seen:
            continue
        seen.add(parsed)
        event = event_for(parsed)
        for has_sel in (False, True):
            assert (kb.find_action_for_event(event, has_sel)
                    == kb.find_action_for_event(event, has_sel, xa.FILER)), parsed
    assert len(seen) > 50  # the keymap really was walked


def test_viewer_local_keys_resolve_without_any_config_entry(kb):
    """Nothing in KEY_BINDINGS mentions these, and they still work — the
    defaults come off the action itself."""
    assert "file_diff.next_block" not in DefaultConfig.KEY_BINDINGS
    assert kb.find_action_for_event(key("n", "n"), False,
                                    xa.FILE_DIFF) == "file_diff.next_block"
    assert kb.find_action_for_event(key("pagedown"), False,
                                    xa.TEXT_VIEWER) == "text_viewer.page_down"
    assert kb.find_action_for_event(key("tab"), False,
                                    xa.DIR_DIFF) == "dir_diff.switch_side"


def test_the_same_key_means_different_things_in_different_contexts(kb):
    """``-`` is the file list's pane reset and the image viewer's zoom out; the
    arrows are the file list's cursor and the diff viewer's scroll. Under the
    flat table which one won came down to dict order."""
    assert kb.find_action_for_event(key("-", "-"), False, xa.FILER) == "reset_pane_boundary"
    assert kb.find_action_for_event(key("-", "-"), False, xa.IMAGE_VIEWER) == "image_viewer.zoom_out"
    assert kb.find_action_for_event(key("down"), False, xa.FILER) == "cursor_down"
    assert kb.find_action_for_event(key("down"), False, xa.FILE_DIFF) == "file_diff.scroll_down"
    assert kb.find_action_for_event(key("down"), False, xa.IMAGE_VIEWER) == "image_viewer.next"


def test_a_rebound_viewer_action_wins_over_its_default():
    bindings = dict(DefaultConfig.KEY_BINDINGS)
    bindings["file_diff.next_block"] = ["j"]
    kb = KeyBindings(bindings)
    assert kb.find_action_for_event(key("j", "j"), False, xa.FILE_DIFF) == "file_diff.next_block"
    assert kb.find_action_for_event(key("n", "n"), False, xa.FILE_DIFF) is None
    # ...and the sibling default it did not touch is unaffected.
    assert kb.find_action_for_event(key("n", "N", {"shift"}), False,
                                    xa.FILE_DIFF) == "file_diff.prev_block"


def test_a_dotted_prefix_scopes_a_shared_action_to_one_context():
    """``'file_diff.quit'`` rebinds quit inside the file diff viewer only."""
    bindings = dict(DefaultConfig.KEY_BINDINGS)
    bindings["file_diff.quit"] = ["X"]
    kb = KeyBindings(bindings)
    assert kb.find_action_for_event(key("x", "x"), False, xa.FILE_DIFF) == "quit"
    # The scoped entry replaces the inherited one in that context...
    assert kb.find_action_for_event(key("q", "q"), False, xa.FILE_DIFF) is None
    # ...and leaves every other surface alone.
    assert kb.find_action_for_event(key("q", "q"), False, xa.FILER) == "quit"
    assert kb.find_action_for_event(key("q", "q"), False, xa.TEXT_VIEWER) == "quit"


@pytest.mark.parametrize("context", [xa.FILER, xa.TEXT_VIEWER, xa.IMAGE_VIEWER,
                                     xa.FILE_DIFF, xa.DIR_DIFF])
def test_no_two_actions_in_a_context_fight_over_a_key(context, kb):
    """Within one surface a key must mean one thing — the exception being a pair
    whose selection requirements are disjoint ('M' is move-files with a
    selection and create-directory without one), which is deliberate."""
    from collections import defaultdict
    by_key = defaultdict(list)
    for parsed, name, selection in kb._context_entries(context):
        by_key[parsed].append((name, selection))
    for parsed, bound in by_key.items():
        if len(bound) == 1:
            continue
        requirements = {selection for _name, selection in bound}
        assert requirements == {"required", "none"}, (context, parsed, bound)


def test_get_keys_for_action_reports_what_the_context_will_use(kb):
    assert kb.get_keys_for_action("file_diff.next_block", xa.FILE_DIFF) == (["n"], "any")
    # Without a context the flat dict alone answers, and it has no such entry.
    assert kb.get_keys_for_action("file_diff.next_block") == ([], "any")


def test_a_config_missing_an_action_still_gets_its_keys():
    """``_copy_missing_fields`` can add a missing config *field* but never a
    missing key inside ``KEY_BINDINGS``, so an action added after a user wrote
    their config would otherwise be unreachable forever."""
    bindings = dict(DefaultConfig.KEY_BINDINGS)
    del bindings["image_viewer.zoom_in"]
    kb = KeyBindings(bindings)
    assert kb.find_action_for_event(key("+", "+"), False,
                                    xa.IMAGE_VIEWER) == "image_viewer.zoom_in"


def test_the_context_table_is_rebuilt_when_the_registry_changes(kb):
    assert kb.find_action_for_event(key("y", "y"), False, xa.FILER) is None
    kb._bindings = dict(kb._bindings, mine=["Y"])
    xa.registry.register(xa.Action(name="mine", context=xa.FILER,
                                   func=lambda ctx: None, source="user"))
    try:
        assert kb.find_action_for_event(key("y", "y"), False, xa.FILER) == "mine"
    finally:
        xa.registry.unregister_source("user")
    assert kb.find_action_for_event(key("y", "y"), False, xa.FILER) is None


# --------------------------------------------------------------------------- #
# 2b. Renamed actions and their aliases
# --------------------------------------------------------------------------- #

# Every rename that has shipped, as (old name, current name, context). An entry
# here may never be deleted: the alias is the only thing keeping a config that
# predates the rename working.
SHIPPED_RENAMES = [
    ("search", "isearch", xa.FILER),
    ("search_dialog", "find_files", xa.FILER),
    ("search_content", "find_in_files", xa.FILER),
    ("sort_menu", "sort", xa.FILER),
    ("drives_dialog", "drives", xa.FILER),
    ("rename_file", "rename", xa.FILER),
    ("select_file", "toggle_select_down", xa.FILER),
    ("select_file_up", "toggle_select_up", xa.FILER),
    ("select_all_files", "toggle_select_files", xa.FILER),
    ("select_all_items", "toggle_select_items", xa.FILER),
    ("image_zoom_in", "image_viewer.zoom_in", xa.IMAGE_VIEWER),
    ("image_zoom_out", "image_viewer.zoom_out", xa.IMAGE_VIEWER),
    ("image_zoom_reset", "image_viewer.zoom_reset", xa.IMAGE_VIEWER),
    ("image_next", "image_viewer.next", xa.IMAGE_VIEWER),
    ("image_prev", "image_viewer.prev", xa.IMAGE_VIEWER),
    ("image_scroll_up", "image_viewer.pan_up", xa.IMAGE_VIEWER),
    ("image_scroll_down", "image_viewer.pan_down", xa.IMAGE_VIEWER),
    ("image_scroll_left", "image_viewer.pan_left", xa.IMAGE_VIEWER),
    ("image_scroll_right", "image_viewer.pan_right", xa.IMAGE_VIEWER),
]


@pytest.mark.parametrize("old, current, context", SHIPPED_RENAMES)
def test_every_shipped_rename_keeps_its_alias(old, current, context):
    r = xa._new_registry()
    assert r.resolve(context, current) is not None, f"{current} is not registered"
    assert r.canonical(context, old) == current, f"{old} lost its alias"


def test_a_config_binding_an_old_name_still_works():
    """The whole point of aliases: a config written before a rename keeps
    working, key for key."""
    bindings = {old: ["Y"] for old, _c, _x in SHIPPED_RENAMES if _x == xa.FILER}
    kb = KeyBindings(bindings)
    for old, current, context in SHIPPED_RENAMES:
        if context is not xa.FILER:
            continue
        assert kb.find_action_for_event(key("y", "y"), True, context) is not None
        assert kb.get_keys_for_action(current, context)[0] == ["Y"], current


def test_an_old_viewer_name_still_reaches_its_viewer():
    # A config from before the rename: the old spelling, and only the old one.
    bindings = dict(DefaultConfig.KEY_BINDINGS)
    del bindings["image_viewer.zoom_in"]
    bindings["image_zoom_in"] = ["Y"]
    kb = KeyBindings(bindings)
    assert kb.find_action_for_event(key("y", "y"), False,
                                    xa.IMAGE_VIEWER) == "image_viewer.zoom_in"
    assert kb.get_keys_for_action("image_viewer.zoom_in",
                                  xa.IMAGE_VIEWER)[0] == ["Y"]


def test_the_current_name_wins_when_a_config_has_both():
    """A config half-migrated — the new name added, the old one left behind —
    must not depend on which the dict happens to list first."""
    for order in (("image_zoom_in", "image_viewer.zoom_in"),
                  ("image_viewer.zoom_in", "image_zoom_in")):
        bindings = {}
        for name in order:
            bindings[name] = ["Y"] if name == "image_zoom_in" else ["Z"]
        kb = KeyBindings(bindings)
        assert kb.get_keys_for_action("image_viewer.zoom_in",
                                      xa.IMAGE_VIEWER)[0] == ["Z"], order
        assert kb.find_action_for_event(key("z", "z"), False,
                                        xa.IMAGE_VIEWER) == "image_viewer.zoom_in"
        assert kb.find_action_for_event(key("y", "y"), False,
                                        xa.IMAGE_VIEWER) is None


def test_the_shipped_template_uses_only_current_names():
    from xefm.config import deprecated_binding_names
    assert deprecated_binding_names(DefaultConfig.KEY_BINDINGS) == []


def test_an_old_name_is_reported_once_as_a_single_line():
    from xefm.config import deprecated_binding_names, deprecated_names_notice
    bindings = dict(DefaultConfig.KEY_BINDINGS)
    for name in ("image_viewer.zoom_in", "image_viewer.pan_up", "sort"):
        del bindings[name]
    bindings.update({"image_zoom_in": ["+"], "image_scroll_up": ["Shift-UP"],
                     "sort_menu": ["S"]})

    pairs = dict(deprecated_binding_names(bindings))
    assert pairs == {"image_zoom_in": "image_viewer.zoom_in",
                     "image_scroll_up": "image_viewer.pan_up",
                     "sort_menu": "sort"}
    notice = deprecated_names_notice(bindings)
    assert notice.count("\n") == 0 and "3 old action name(s)" in notice


def test_a_name_spelled_both_ways_is_not_reported():
    from xefm.config import deprecated_binding_names
    bindings = dict(DefaultConfig.KEY_BINDINGS, image_zoom_in=["+"])
    assert "image_viewer.zoom_in" in bindings   # the current spelling is there
    assert deprecated_binding_names(bindings) == []


def test_no_alias_collides_with_a_current_name():
    """An alias that is also somebody's current name would make resolution
    depend on lookup order — and would mean a rename had quietly reused a
    retired name for a different action."""
    r = xa._new_registry()
    for context in xa.CONTEXTS:
        current = {a.name for a in r.actions(context)}
        for old in r.aliases_in(context):
            assert old not in current, (context, old)


# --------------------------------------------------------------------------- #
# 3. Loading ACTIONS / EVENT_HOOKS
# --------------------------------------------------------------------------- #

@pytest.fixture
def clean_registry():
    """Keep the process-wide registry and hook table out of other tests."""
    yield
    xa.registry.unregister_source("user")
    user_api.hooks.clear()


def config_with(**attrs):
    cfg = DefaultConfig()
    for name, value in attrs.items():
        setattr(cfg, name, value)
    return cfg


def test_a_bare_callable_is_the_simple_form(clean_registry):
    def mine(ctx):
        pass

    warnings, actions_n, hooks_n, _ = user_api.load_user_entries(config_with(ACTIONS={"mine": mine}))
    assert warnings == []
    assert (actions_n, hooks_n) == (1, 0)
    loaded = xa.registry.resolve(xa.FILER, "mine")
    assert loaded.func is mine and loaded.is_user


def test_shadowing_a_builtin_needs_an_explicit_override(clean_registry):
    def mine(ctx):
        pass

    warnings, actions_n, _, _ = user_api.load_user_entries(config_with(ACTIONS={"quit": mine}))
    assert actions_n == 0
    assert len(warnings) == 1 and "override" in warnings[0]
    assert xa.registry.resolve(xa.FILER, "quit").source == "builtin"

    warnings, actions_n, _, _ = user_api.load_user_entries(
        config_with(ACTIONS={"quit": {"func": mine, "override": True}}))
    assert warnings == [] and actions_n == 1
    assert xa.registry.resolve(xa.FILER, "quit").func is mine


def test_reloading_replaces_every_previous_user_entry(clean_registry):
    user_api.load_user_entries(config_with(ACTIONS={"first": lambda ctx: None}))
    user_api.load_user_entries(config_with(ACTIONS={"second": lambda ctx: None}))
    assert xa.registry.resolve(xa.FILER, "first") is None
    assert xa.registry.resolve(xa.FILER, "second") is not None


@pytest.mark.parametrize("spec, fragment", [
    (42, "must be a function or a dict"),
    ({"description": "no func here"}, "no callable 'func'"),
    ({"func": lambda ctx: None, "context": "nope"}, "unknown context"),
    ({"func": lambda ctx: None, "context": "text_viewer"}, "accepted only in"),
])
def test_a_malformed_action_is_one_warning_not_a_failure(spec, fragment, clean_registry):
    warnings, actions_n, _, _ = user_api.load_user_entries(
        config_with(ACTIONS={"mine": spec, "fine": lambda ctx: None}))
    assert actions_n == 1  # the good one still loaded
    assert len(warnings) == 1 and fragment in warnings[0]


def test_hooks_load_and_unknown_events_warn(clean_registry):
    def hook(ctx):
        pass

    warnings, _, hooks_n, _ = user_api.load_user_entries(config_with(
        EVENT_HOOKS={"startup": [hook], "quit": hook, "nope": [hook]}))
    assert hooks_n == 2  # a bare callable is accepted alongside a list
    assert len(warnings) == 1 and "not a known event" in warnings[0]
    assert user_api.hooks.get("startup") == [hook]
    assert user_api.hooks.get("quit") == [hook]


def test_validation_reports_without_loading(clean_registry):
    cfg = config_with(ACTIONS={"quit": lambda ctx: None})
    assert len(user_api.validate_user_entries(cfg)) == 1
    assert xa.registry.user_actions() == []          # nothing was installed
    assert config_manager.validate_config(cfg)       # and it reaches validate_config


def test_the_preview_notice_only_appears_when_the_api_is_used():
    assert user_api.preview_notice(0, 0) is None
    notice = user_api.preview_notice(2, 1)
    assert "Preview" in notice and "2 action(s)" in notice and "1 event hook(s)" in notice


def test_a_hook_that_raises_is_logged_not_propagated(clean_registry):
    ran = []

    def boom(ctx):
        raise RuntimeError("nope")

    def after(ctx):
        ran.append("after")

    user_api.load_user_entries(config_with(EVENT_HOOKS={"startup": [boom, after]}))
    # The bad hook does not abort the ones behind it.
    assert user_api.hooks.fire("startup", None) is False
    assert ran == ["after"]


# --------------------------------------------------------------------------- #
# 4. The façade, against a live app
# --------------------------------------------------------------------------- #

@pytest.fixture
def app_with(request):
    """Build a real XeFMApp over a memory backend, with a config of the test's
    choosing, and restore the shared singletons afterwards."""
    made = []

    def build(**config_attrs):
        tmp = tempfile.mkdtemp()
        cfgdir = tempfile.mkdtemp()
        for name in ("a.txt", "b.docx", "c.docx", "d.pdf"):
            with open(os.path.join(tmp, name), "w") as fh:
                fh.write("x")
        os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)

        cfg = config_with(**config_attrs)
        saved = (config_manager.config, config_manager._key_bindings)
        config_manager.config = cfg
        config_manager._key_bindings = None

        sm = XeFMStateManager(db_path=os.path.join(cfgdir, "state.db"))
        backend = create_backend("memory")
        backend.open()
        app = xefm_app.XeFMApp(backend, tmp, tmp, left_provided=True,
                               right_provided=True, state_manager=sm)
        app._settle_listings()
        made.append((app, backend, sm, tmp, cfgdir, saved))
        return app, tmp

    yield build

    for app, backend, sm, tmp, cfgdir, saved in made:
        try:
            app._restore_streams()
            app.file_monitor.stop_monitoring()
            backend.close()
            if hasattr(sm, "close"):
                sm.close()
        except Exception:
            pass
        config_manager.config, config_manager._key_bindings = saved
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(cfgdir, ignore_errors=True)
    xa.registry.unregister_source("user")
    user_api.hooks.clear()


def test_a_user_action_runs_from_the_key_it_is_bound_to(app_with):
    def select_docs(ctx):
        ctx.pane.select(lambda e: e.suffix == ".docx")

    bindings = dict(DefaultConfig.KEY_BINDINGS, **{"select-docs": ["Shift-D"]})
    app, tmp = app_with(ACTIONS={"select-docs": select_docs}, KEY_BINDINGS=bindings)

    app.on_event(key("d", "D", {"shift"}))
    chosen = sorted(os.path.basename(p) for p in app.active_pane()["selected_files"])
    assert chosen == ["b.docx", "c.docx"]


def test_invoke_from_an_overriding_action_reaches_the_builtin(app_with):
    seen = []

    def loud_quit(ctx):
        seen.append("user")
        ctx.invoke("quit")

    app, _ = app_with(ACTIONS={"quit": {"func": loud_quit, "override": True}})
    app.confirm_quit = lambda: seen.append("builtin")
    app.dispatch("quit")
    assert seen == ["user", "builtin"]


def test_invoke_runs_a_builtin_by_name(app_with):
    def to_the_end(ctx):
        ctx.invoke("select_all")

    app, _ = app_with(ACTIONS={"pick-all": to_the_end})
    app.dispatch("pick-all")
    assert len(app.active_pane()["selected_files"]) == 5


def test_an_action_that_raises_leaves_the_app_running(app_with):
    def boom(ctx):
        raise ValueError("bad action")

    app, _ = app_with(ACTIONS={"boom": boom})
    assert app.dispatch("boom") is True   # handled, screen repainted
    assert app.dispatch("cursor_down") is True   # and the app still works


def test_pane_api_reads_and_moves_the_cursor(app_with):
    captured = {}

    def probe(ctx):
        captured["names"] = [e.name for e in ctx.pane.entries]
        captured["dirs"] = [e.name for e in ctx.pane.entries if e.is_dir]
        ctx.pane.cursor = 999                      # clamped, not an error
        captured["cursor"] = ctx.pane.cursor
        captured["focused"] = ctx.pane.focused.name
        captured["other_is_other"] = ctx.other.name != ctx.pane.name
        captured["size"] = ctx.pane.entries[0].size

    app, _ = app_with(ACTIONS={"probe": probe})
    app.dispatch("probe")
    assert captured["dirs"] == ["sub"]
    assert captured["cursor"] == len(captured["names"]) - 1
    assert captured["focused"] == captured["names"][-1]
    assert captured["other_is_other"] is True
    assert captured["size"] >= 0


def test_pane_api_select_and_unselect_are_additive(app_with):
    counts = {}

    def probe(ctx):
        counts["added"] = ctx.pane.select(lambda e: e.suffix == ".docx")
        counts["again"] = ctx.pane.select(lambda e: e.suffix == ".docx")
        counts["selected"] = len(ctx.pane.selected())
        counts["removed"] = ctx.pane.unselect(lambda e: e.name == "b.docx")
        counts["left"] = [e.name for e in ctx.pane.selected()]
        ctx.pane.unselect()
        counts["cleared"] = len(ctx.pane.selected())

    app, _ = app_with(ACTIONS={"probe": probe})
    app.dispatch("probe")
    assert counts["added"] == 2
    assert counts["again"] == 0        # already selected, not double counted
    assert counts["selected"] == 2
    assert counts["removed"] == 1
    assert counts["left"] == ["c.docx"]
    assert counts["cleared"] == 0


def test_a_predicate_that_raises_matches_nothing(app_with):
    result = {}

    def probe(ctx):
        result["n"] = ctx.pane.select(lambda e: 1 / 0)

    app, _ = app_with(ACTIONS={"probe": probe})
    app.dispatch("probe")
    assert result["n"] == 0


def test_pane_api_cd_navigates(app_with):
    def go(ctx):
        ctx.pane.cd(ctx.pane.path / "sub")

    app, tmp = app_with(ACTIONS={"go": go})
    app.dispatch("go")
    app._settle_listings()
    assert app.active_pane()["path"].name == "sub"


# --- events ---------------------------------------------------------------- #

def test_startup_and_quit_hooks_fire(app_with):
    seen = []
    app, _ = app_with(EVENT_HOOKS={"startup": [lambda ctx: seen.append("startup")],
                                   "quit": [lambda ctx: seen.append("quit")]})
    app.backend.run_event_loop = lambda cb: None
    app.run()
    assert seen == ["startup"]
    app.backend.quit = lambda: None
    app._quit()
    assert seen == ["startup", "quit"]


def test_directory_changed_fires_once_per_real_change(app_with):
    seen = []

    def hook(ctx, pane, old, new):
        seen.append((pane.name, os.path.basename(str(old)), os.path.basename(str(new))))

    app, tmp = app_with(EVENT_HOOKS={"directory_changed": [hook]})
    assert seen == []                      # the startup listings are not a change

    pane = app.active_pane()
    app._go_to_dir(pane, Path(os.path.join(tmp, "sub")), None)
    app._settle_listings()
    assert len(seen) == 1
    assert seen[0][0] == "left" and seen[0][2] == "sub"

    # A re-list of the same directory is not a directory change.
    app._relist(pane)
    app._settle_listings()
    assert len(seen) == 1


def test_file_open_can_claim_the_open(app_with):
    seen = []

    def route(ctx, path):
        seen.append(path.name)
        return path.suffix == ".pdf"

    app, _ = app_with(EVENT_HOOKS={"file_open": [route]})
    opened = []
    app._open_viewer = lambda *a, **k: opened.append("viewer")

    pane = app.active_pane()
    names = [f.name for f in pane["files"]]

    pane["focused_index"] = names.index("d.pdf")
    app._open(pane)
    assert seen == ["d.pdf"] and opened == []       # claimed

    pane["focused_index"] = names.index("a.txt")
    app._open(pane)
    assert seen == ["d.pdf", "a.txt"] and opened == ["viewer"]   # fell through


def test_file_open_does_not_fire_for_directories(app_with):
    seen = []
    app, _ = app_with(EVENT_HOOKS={"file_open": [lambda ctx, p: seen.append(p.name)]})
    pane = app.active_pane()
    pane["focused_index"] = [f.name for f in pane["files"]].index("sub")
    app._open(pane)
    app._settle_listings()
    assert seen == []
    assert app.active_pane()["path"].name == "sub"


def test_the_help_dialog_lists_the_config_s_own_actions(app_with):
    shown = {}

    def mine(ctx):
        pass

    app, _ = app_with(
        ACTIONS={"select-docs": {"func": mine, "description": "Select documents"}},
        KEY_BINDINGS=dict(DefaultConfig.KEY_BINDINGS, **{"select-docs": ["Shift-D"]}))
    app.panel.render = lambda *a, **k: None
    import xefm.app as module
    original = module.show_markdown
    module.show_markdown = lambda panel, text, **kw: shown.setdefault("text", text)
    try:
        app.show_help()
    finally:
        module.show_markdown = original
    assert "Your Actions (config.py)" in shown["text"]
    assert "Select documents" in shown["text"]
    assert "Shift-D" in shown["text"]


def test_the_help_dialog_has_no_user_section_without_user_actions(app_with):
    shown = {}
    app, _ = app_with()
    app.panel.render = lambda *a, **k: None
    import xefm.app as module
    original = module.show_markdown
    module.show_markdown = lambda panel, text, **kw: shown.setdefault("text", text)
    try:
        app.show_help()
    finally:
        module.show_markdown = original
    assert "Your Actions" not in shown["text"]


# --- reload ----------------------------------------------------------------- #

def test_reload_config_installs_the_edited_actions_and_hooks(app_with, tmp_path):
    """Iterating on an action is edit-then-reload: the whole user layer is
    dropped and rebuilt from the file just read, with no restart."""
    import textwrap

    app, _ = app_with()
    saved_file = config_manager.config_file

    def write(body):
        path = tmp_path / "config.py"
        path.write_text(textwrap.dedent(body))
        config_manager.config_file = Path(str(path))

    try:
        write("""
            def first(ctx):
                ctx.message("first")

            class Config:
                ACTIONS = {'first': first}
                EVENT_HOOKS = {'startup': [lambda ctx: None]}
        """)
        app.reload_config()
        assert xa.registry.resolve(xa.FILER, "first") is not None
        assert len(user_api.hooks.get("startup")) == 1

        write("""
            def second(ctx):
                ctx.message("second")

            class Config:
                ACTIONS = {'second': second}
        """)
        app.reload_config()
        assert xa.registry.resolve(xa.FILER, "first") is None
        assert xa.registry.resolve(xa.FILER, "second") is not None
        assert user_api.hooks.get("startup") == []
    finally:
        config_manager.config_file = saved_file


def test_the_preview_notice_reaches_the_log_pane(app_with):
    lines = []
    app, _ = app_with(ACTIONS={"mine": lambda ctx: None})
    app.log_info = lines.append          # replaced after startup logged its own
    app._load_user_entries(app.config)
    assert any("Preview" in line and "API_VERSION" in line for line in lines)


def test_a_config_that_uses_none_of_it_says_nothing(app_with):
    lines = []
    app, _ = app_with()
    app.log_info = lines.append
    app._load_user_entries(app.config)
    assert lines == []


# --- the dispatch table ----------------------------------------------------- #

def test_every_registered_filer_action_has_a_handler(app_with):
    """The registry and the app must agree on what the file list can do — a name
    in one and not the other is a key that resolves to nothing."""
    app, _ = app_with()
    handlers = set(app._filer_handlers())
    registered = {a.name for a in xa.registry.actions(xa.FILER)}
    assert registered - handlers == set()
    assert handlers - registered == set()
