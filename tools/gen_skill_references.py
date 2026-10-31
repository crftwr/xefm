"""Generate the agent skill's reference files from XeFM itself.

    PYTHONPATH=. python tools/gen_skill_references.py           # write them
    PYTHONPATH=. python tools/gen_skill_references.py --check   # exit 1 if stale

The clean room (#639) found that an agent editing config.py had no way to
learn an action's name, which keys a preset already uses, or what a setting
is called and holds, other than the comments in the user's own file — which
the user may have deleted, and which date from whatever XeFM they first
installed. So the skill carries both, generated, and cannot drift from XeFM:
test/test_extension_skill.py runs the --check.

- references/actions.md: every action, from the registry, with each preset's
  default keys (the terminal table every backend shares; the desktop app's
  few additions are listed per platform after it).
- references/config-template.md: xefm/_config.py verbatim — every setting,
  its default and its explanation, which is what XeFM fills a missing
  setting from.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCES = ROOT / "xefm" / "skills" / "xefm" / "references"
TEMPLATE = ROOT / "xefm" / "_config.py"

PRESETS = (("afx", "AFX style"), ("orthodox", "Orthodox"), ("native", "OS native"),
           ("vim", "Vim style"))
DESKTOPS = (("darwin", "macOS desktop app"), ("win32", "Windows desktop app"))


@contextmanager
def _as(backend: str, platform: str | None = None):
    from xefm import backend_detector
    saved = os.environ.get("XEFM_BACKEND"), sys.platform
    os.environ["XEFM_BACKEND"] = backend
    backend_detector._cached_backend = None      # it caches the first answer
    if platform:
        sys.platform = platform
    try:
        yield
    finally:
        if saved[0] is None:
            os.environ.pop("XEFM_BACKEND", None)
        else:
            os.environ["XEFM_BACKEND"] = saved[0]
        sys.platform = saved[1]
        backend_detector._cached_backend = None


def _keys(binding) -> str:
    if binding is None:
        return ""
    keys = binding.get("keys", []) if isinstance(binding, dict) else binding
    text = ", ".join(f"`{k}`" for k in keys) if keys else "—"
    if isinstance(binding, dict) and binding.get("selection", "any") != "any":
        text += f" (selection: {binding['selection']})"
    return text


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render() -> str:
    from xefm import actions, keymap_presets

    with _as("tui"):
        tables = {name: keymap_presets.table(name) for name, _ in PRESETS}
    desktop = {}
    for platform, _ in DESKTOPS:
        with _as("gui", platform):
            desktop[platform] = {name: keymap_presets.table(name) for name, _ in PRESETS}

    out = [
        "# XeFM actions and their default keys",
        "",
        "Generated from XeFM {XEFM_VERSION}'s action registry and keymap presets",
        "by `tools/gen_skill_references.py` — do not edit by hand.",
        "",
        "Use these names exactly in `KEY_BINDINGS` (and with `ctx.invoke`). The",
        "key columns are each preset's defaults *before* the user's",
        "`KEY_BINDINGS` is laid over them: to know whether a key is free, look",
        "for it in the column of the preset in force (`KEY_PRESET`, or the one",
        "the user picked in **Tools ▸ Advanced ▸ Keymap…**; ask which if `KEY_PRESET` is",
        "`None` and you cannot tell) *and* in the user's own `KEY_BINDINGS`.",
        "— means the action has no key by default.",
        "",
        "## File list",
        "",
        "| Action | What it does | " + " | ".join(label for _, label in PRESETS) + " |",
        "|---|---|" + "---|" * len(PRESETS),
    ]
    for action in actions.registry.actions(actions.FILER):
        if action.source != "builtin":
            continue
        row = [f"`{action.name}`", _cell(action.description)]
        row += [_keys(tables[name].get(action.name)) or "—" for name, _ in PRESETS]
        out.append("| " + " | ".join(row) + " |")

    out += ["", "### Desktop app additions", "",
            "The desktop app adds platform keys to a few actions (a terminal cannot",
            "send them). These replace the row above in that app:", ""]
    for platform, label in DESKTOPS:
        changed = []
        for name, preset_label in PRESETS:
            for action, binding in desktop[platform][name].items():
                if "." in action or binding == tables[name].get(action):
                    continue
                changed.append(f"- `{action}` ({preset_label}): {_keys(binding)}")
        out.append(f"**{label}:**")
        out.append("")
        out += sorted(set(changed)) or ["- none"]
        out.append("")

    out += ["## Inside viewers and dialogs", "",
            "These keys are the same under every preset. Bind one with its full",
            "dotted name (`'text_viewer.page_down': ['SPACE']`). A file-list action",
            "name with a viewer prefix (`'file_diff.quit'`) rebinds it inside that",
            "viewer only.", ""]
    for context in actions.CONTEXTS:
        if context == actions.FILER:
            continue
        rows = [a for a in actions.registry.actions(context) if a.source == "builtin"]
        if not rows:
            continue
        out += [f"### `{context}`", "", "| Action | What it does | Keys |", "|---|---|---|"]
        for action in rows:
            binding = tables["afx"].get(action.name)
            if binding is None and action.default_keys is not None:
                binding = list(action.default_keys)
            out.append(f"| `{action.name}` | {_cell(action.description)} | "
                       f"{_keys(binding) or '—'} |")
        out.append("")

    out += ["## Old names", "",
            "Names actions used to have. XeFM still accepts each one in",
            "`KEY_BINDINGS`, as the action it now names, so an older `config.py`",
            "may use them. Edit such an entry under the name it has (or rename",
            "it); never add the current name beside it — two entries for one",
            "action leave it unclear which keys win.", "",
            "| Old name | Now |", "|---|---|"]
    seen = set()
    for context in actions.CONTEXTS:
        # A shared action is listed under every context that inherits it;
        # its old names are one row each, not one per context.
        for action in actions.registry.actions(context):
            for alias in action.aliases:
                if (alias, action.name) not in seen:
                    seen.add((alias, action.name))
                    out.append(f"| `{alias}` | `{action.name}` |")
    return "\n".join(out).rstrip() + "\n"


def render_template() -> str:
    """The config template, as the reference an agent reads it from."""
    return "\n".join([
        "# XeFM's configuration template",
        "",
        "Generated from XeFM {XEFM_VERSION}'s `xefm/_config.py` by",
        "`tools/gen_skill_references.py` — do not edit by hand.",
        "",
        "This is the file XeFM copies to `~/.xefm/config.py` on first launch, and",
        "the one it fills every setting the user's file leaves out from. It is the",
        "authority on what each setting is called, what it holds by default, and",
        "what it does. Read it here rather than in the user's own file: theirs may",
        "have had its comments deleted, or date from an older XeFM.",
        "",
        "A setting the user's file does not have keeps the value shown here. Adding",
        "it to their file **replaces** that value whole: to extend a default list",
        "or table (FILE_ASSOCIATIONS, PROGRAMS, FAVORITES, THEMES…), copy its",
        "default entries from here and add to them.",
        "",
        "```python",
        TEMPLATE.read_text(encoding="utf-8").rstrip("\n"),
        "```",
        "",
    ])


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    outputs = {REFERENCES / "actions.md": render(),
               REFERENCES / "config-template.md": render_template()}
    if "--check" in argv:
        stale = [p for p, text in outputs.items()
                 if not p.exists() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"{path.relative_to(ROOT)} is stale: run `make skill-references`",
                  file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
