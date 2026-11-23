"""Take 5 (Blocks): clean up to the trash with a confirmation; no deleting for good."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    ">", {"hold": 2.5},
    {"submit": "Clean up the build leftovers here: logs, temp files and __pycache__."},
    {"approve": r"Trash|Move", "look": 2.5}, {"hold": 1.5}, {"still": "answered"}, {"hold": 3.0},
    {"submit": "Also delete frames-2026-10.zip permanently."},
    # The agent may refuse, or offer the trash instead: either way XeFM asks.
    {"approve": r"Trash|Move", "look": 2.5}, {"hold": 1.5}, {"still": "answered"}, {"hold": 6.0},
]
