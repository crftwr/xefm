"""Shared bits of the AI agent takes (points on the 960x600 screen)."""
SELECT_MENU, SELECT_ALL = [249, 14], [278, 96]
TOOLS_MENU, ASK_AGENT = [354, 14], [382, 131]
SCREENS = "Ctrl-`"


def menu(title, item):
    return [{"click": title}, {"pause": 0.5}, {"move": item}, {"pause": 0.35}, {"click": item}]


def back_to_previous_screen():
    """Screens... opens with the cursor on the screen shown before this one."""
    return [SCREENS, {"hold": 1.4}, "Enter", {"hold": 1.0}]


def answered(read=5.0):
    return [{"wait_stop": 300}, {"hold": 1.5}, {"still": "answered"}, {"hold": read}]


def to_files():
    """Screens..., filtered to the file manager: right whatever screen is on."""
    return [{"move": [600, 360], "duration": 0.3}, SCREENS, {"hold": 1.2},
            {"text": "file"}, {"hold": 0.7}, "Enter", {"hold": 1.0}]
