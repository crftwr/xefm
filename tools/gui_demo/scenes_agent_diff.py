"""Take 2 (Blocks): compare two folders; the agent shows the diff in XeFM."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    ">", {"hold": 2.5},
    {"submit": "What changed between this project and ../aurora-backup? Show me the most important difference in XeFM."},
    {"wait_stop": 300}, {"hold": 1.0}, {"still": "diff"}, {"hold": 5.0},
    "Esc", {"hold": 1.0},
    *back_to_previous_screen(), {"still": "answer"}, {"hold": 6.0},
]
