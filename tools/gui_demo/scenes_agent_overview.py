"""Take 1 (Earth): ask about what you are looking at; open code in XeFM."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    ">", {"hold": 2.5},
    {"submit": "What is this project, and how does it score a clear night?"},
    *answered(6.0),
    {"submit": "Open the scoring code in XeFM's viewer."},
    {"wait_stop": 300}, {"hold": 1.0}, {"still": "viewer"}, {"hold": 4.0},
    "Esc", {"hold": 1.2},
    *back_to_previous_screen(), {"hold": 2.5},
]
