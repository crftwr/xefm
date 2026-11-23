"""Take 4 (Pelagic): a saved request on the selection; XeFM confirms the moves."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    "Down", "Down", "Down", "Down", {"hold": 0.4}, "Enter", {"hold": 1.2},
    *menu(SELECT_MENU, SELECT_ALL), {"hold": 1.5},
    *menu(TOOLS_MENU, ASK_AGENT), {"hold": 1.5},
    "Down", {"hold": 1.2}, "Enter",
    {"approve": r"Move", "look": 2.5}, {"hold": 1.5}, {"still": "answered"}, {"hold": 4.0},
    *to_files(), {"hold": 3.0}, {"still": "folders"},
]
