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
        'XEFM_THIS_DIR', 'XEFM_THIS_SELECTED',
        'XEFM_OTHER_DIR', 'XEFM_OTHER_SELECTED',
        'XEFM_LEFT_DIR', 'XEFM_LEFT_SELECTED',
        'XEFM_RIGHT_DIR', 'XEFM_RIGHT_SELECTED',
        'XEFM_ACTIVE',
    ]:
        print(f"  {name} = {os.environ.get(name, '')}")

    # The *_SELECTED variables hold space-separated, double-quoted filenames;
    # shlex.split() turns them back into a list. When nothing is selected,
    # XeFM substitutes the file under the cursor.
    this_dir = os.environ.get('XEFM_THIS_DIR', os.getcwd())
    selected = shlex.split(os.environ.get('XEFM_THIS_SELECTED', ''))

    print()
    print(f"Selection in the current pane ({len(selected)} file(s)):")
    for name in selected:
        path = name if os.path.isabs(name) else os.path.join(this_dir, name)
        print(f"  {path}")


if __name__ == '__main__':
    main()
