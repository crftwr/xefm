"""Take 3 (Cyber): search, and get the results as a list in the pane."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    ">", {"hold": 2.5},
    {"submit": "Find every TODO and FIXME in this project and list those files in the left pane."},
    *answered(3.0),
    *to_files(), {"hold": 2.0}, {"still": "list"},
    "Down", {"hold": 0.6}, "Enter", {"hold": 3.0}, {"still": "view"},
    "Esc", {"hold": 1.5},
]
