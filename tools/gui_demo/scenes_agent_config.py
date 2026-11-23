"""Take 6 (Pelagic): the agent changes XeFM's own configuration."""
from agent_common import *  # noqa: F403
SCENES = [
    {"hold": 2.0},
    ">", {"hold": 2.5},
    {"submit": "Add ~/projects/aurora/photos to my XeFM favorites."},
    *answered(4.0),
    *to_files(), {"hold": 1.0},
    "J", {"hold": 2.0}, {"still": "favorites"}, {"text": "pho"}, {"hold": 1.2}, "Enter", {"hold": 2.5}, {"still": "photos"},
]
