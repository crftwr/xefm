"""XeFM's TUI, started inside a VM over `ssh -tt` - never on the host.

tools/vm_live.py runs this in the guest, the path of a JSON file on the share
as its one argument:

    {"environ": {...}, "path": [...], "cwd": "...", "argv": [...], "pid": "..."}

It sets the environment (HOME and USERPROFILE on the run's home, PYTHONPATH,
LIBARCHIVE, QUALITY_LOOP_EVENTS), enters the directory, writes its pid where
the host can find it - an ssh session that ends does not always end what it
started - and runs `python -m xefm` with the arguments.
"""

import json
import os
import runpy
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    settings = json.load(f)

os.environ.update(settings.get("environ") or {})
sys.path[0:0] = settings.get("path") or []
if settings.get("cwd"):
    os.chdir(settings["cwd"])
with open(settings["pid"], "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))
sys.argv = ["xefm", *settings.get("argv", [])]
runpy.run_module("xefm", run_name="__main__", alter_sys=True)
