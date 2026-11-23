"""Build the demo VM's home for the AI agent demo under OUT: the sample
project (with TODOs, build leftovers and photos across three months), and a
~/.xefm whose AGENTS entry runs the VM's Claude Code.

    PYTHONPATH=. python tools/gui_demo/prep_home_agent.py temp/gui-demo/home-agent [THEME]
"""
import re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_demo_gif as tui
from xefm.state_manager import StateManager

out = Path(sys.argv[1])
theme = sys.argv[2] if len(sys.argv) > 2 else "Earth"
shutil.rmtree(out, ignore_errors=True)
projects = out / "projects"
aurora = projects / "aurora"
tui._project(aurora)
tui._project(projects / "aurora-backup", backup=True)

# Work left in the code, for "find every TODO".
edits = {
    "src/aurora/forecast.py": [
        ("    def next_nights(self, count: int):\n",
         "    def next_nights(self, count: int):\n"
         "        # TODO: skip nights when the moon is above the horizon all night\n"),
        ("        moon = abs(",
         "        # FIXME: the moon phase ignores the observer's time zone\n        moon = abs("),
    ],
    "src/aurora/storage.py": [
        ("        frames = sorted(",
         "        # TODO: read frames from S3 as well as the local disk\n        frames = sorted("),
    ],
    "src/aurora/models/cloud_cover.py": [
        ("# Cloud cover from a frame.\n",
         "# Cloud cover from a frame.\n# TODO: replace the threshold with forecast_ml\n"),
    ],
    "scripts/fetch_frames.sh": [
        ("rsync -a", "# FIXME: hard-coded host name\nrsync -a"),
    ],
}
for name, pairs in edits.items():
    p = aurora / name
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert old in text, (name, old)
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")

# Leftovers for "clean up".
junk = {
    "build/aurora.log": "2026-10-31 23:59:01 frames: 480\n" * 40,
    "build/tmp-frames-0412.tmp": "x" * 5000,
    "debug.log": "DEBUG cloud=0.42\n" * 200,
    "src/aurora/__pycache__/forecast.cpython-314.pyc": "\0" * 2400,
    "src/aurora/__pycache__/storage.cpython-314.pyc": "\0" * 1800,
}
for name, text in junk.items():
    p = aurora / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

# Photos across three months, for "sort by month".
import ast  # noqa: E402
_src = (Path(__file__).resolve().parent / "prep_home.py").read_text(encoding="utf-8")
_sky = next(n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name == "sky")
_ns = {}
exec("import math, random\nfrom PIL import Image, ImageChops, ImageDraw, ImageFilter\n"
     + ast.get_source_segment(_src, _sky), _ns)
photos = aurora / "photos"
photos.mkdir(parents=True)
dates = ["2026-08-11", "2026-08-12", "2026-08-27", "2026-09-05", "2026-09-19",
         "2026-09-22", "2026-10-03", "2026-10-09", "2026-10-21"]
for i, d in enumerate(dates):
    _ns["sky"](photos / f"night-{d}.jpg", i)

xefm = out / ".xefm"
xefm.mkdir()
config = (Path("xefm") / "_config.py").read_text(encoding="utf-8")
config = config.replace("    CONFIRM_COPY = True", "    CONFIRM_COPY = False")
config, n = re.subn(
    r"    AGENTS = \[\n(?:        .*\n)+?    \]\n",
    "    AGENTS = [\n"
    "        {'name': 'Claude Code', 'preset': 'claude-code',\n"
    "         'command': ['/Users/admin/.local/bin/claude', '--model', 'sonnet']},\n"
    "    ]\n", config)
assert n == 1
config = config.replace('    AGENT_RULES = ""',
                        '    AGENT_RULES = "Answer in English, in a few short lines."')
config, n = re.subn(
    r"    AGENT_PROMPTS = \{\n(?:        .*\n)*?    \}\n",
    "    AGENT_PROMPTS = {\n"
    "        'Summarize': 'Summarize these files, a few lines each.',\n"
    "        'Sort photos by month':\n"
    "            'Move these photos into folders named YYYY-MM, by the date in their names.',\n"
    "        'Explain this folder': 'What is this folder for? Look around and tell me.',\n"
    "    }\n", config)
assert n == 1
(xefm / "config.py").write_text(config, encoding="utf-8")
(xefm / "tools").mkdir()

st = StateManager(xefm / "state.db")
st.set_state("tips.enabled", False)
st.set_state("keymap.preset", "afx")
st.set_state("theme", theme)
st.set_state("pane.left", {"path": "/Users/admin/projects/aurora", "sort_mode": "name"})
st.set_state("pane.right", {"path": "/Users/admin/projects/aurora-backup", "sort_mode": "name"})
st.close() if hasattr(st, "close") else None
print("ok", out, theme)
