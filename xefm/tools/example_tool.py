#!/usr/bin/env python3
"""
Example External Program for XeFM

XeFM copies this script to ~/.xefm/tools/ on first launch as a starting
point for your own tools. Edit it freely, or copy it to a new name and add
a matching entry to PROGRAMS in ~/.xefm/config.py:

    {'name': 'My Tool', 'command': [xefm_python, xefm_tool('my_tool.py')]},

External programs are not limited to Python — the "command" list is executed
directly, without a shell, so shell scripts or plain commands like
['git', 'status'] work just as well.

XeFM describes its state to the program through XEFM_* environment
variables. This script prints them all, then resolves the current pane's
selection to absolute paths the way a real tool would. Everything printed
here lands in XeFM's log pane.
"""

import os
import shlex


def main():
    print("XeFM environment variables:")
    print()
    for name in [
        'XEFM_THIS_DIR', 'XEFM_THIS_SELECTED', 'XEFM_THIS_FOCUSED',
        'XEFM_OTHER_DIR', 'XEFM_OTHER_SELECTED', 'XEFM_OTHER_FOCUSED',
        'XEFM_LEFT_DIR', 'XEFM_LEFT_SELECTED', 'XEFM_LEFT_FOCUSED',
        'XEFM_RIGHT_DIR', 'XEFM_RIGHT_SELECTED', 'XEFM_RIGHT_FOCUSED',
        'XEFM_ACTIVE',
    ]:
        print(f"  {name} = {os.environ.get(name, '')}")

    # The *_SELECTED and *_FOCUSED variables hold space-separated,
    # double-quoted filenames; shlex.split() turns them back into a list.
    # *_SELECTED is what Space selected and is EMPTY when nothing is; the file
    # under the cursor is in *_FOCUSED instead. A tool that wants the old
    # "selection, or else the cursor" behaviour writes that fallback itself:
    #
    #     targets = selected or focused
    #
    # while one that requires a real selection -- comparing two files, say --
    # just checks len(selected).
    this_dir = os.environ.get('XEFM_THIS_DIR', os.getcwd())
    selected = shlex.split(os.environ.get('XEFM_THIS_SELECTED', ''))
    focused = shlex.split(os.environ.get('XEFM_THIS_FOCUSED', ''))

    def show(label, names):
        print()
        print(label)
        if not names:
            print("  (none)")
        for name in names:
            path = name if os.path.isabs(name) else os.path.join(this_dir, name)
            print(f"  {path}")

    show(f"Selected in the current pane ({len(selected)} file(s)):", selected)
    show("Under the cursor:", focused)


if __name__ == '__main__':
    main()
