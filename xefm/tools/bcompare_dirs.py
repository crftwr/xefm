#!/usr/bin/env python3
"""
BeyondCompare wrapper script for XeFM
This script launches BeyondCompare with the left and right pane directories
"""

import os
import sys
import subprocess
import shutil


def main():
    """Launch BeyondCompare with XeFM directory environment variables."""
    # Check if BeyondCompare is available
    if not shutil.which('bcompare'):
        print("Error: BeyondCompare (bcompare) is not installed or not in PATH")
        print("Please install BeyondCompare and ensure 'bcompare' command is available")
        sys.exit(1)

    # Check if XeFM environment variables are set
    left_dir = os.environ.get('XEFM_LEFT_DIR')
    right_dir = os.environ.get('XEFM_RIGHT_DIR')
    
    if not left_dir or not right_dir:
        print("Error: XeFM environment variables not set")
        print("This script should be run from within XeFM")
        sys.exit(1)

    # Launch BeyondCompare with the directories
    print("Launching BeyondCompare...")
    print(f"Left directory: {left_dir}")
    print(f"Right directory: {right_dir}")

    # Store the directories before unsetting environment variables
    dirs_to_compare = [left_dir, right_dir]

    # Unset XeFM environment variables before launching GUI app
    # These variables are not needed for BeyondCompare and can sometimes cause issues
    xefm_vars = [
        'XEFM_THIS_DIR', 'XEFM_THIS_SELECTED', 'XEFM_OTHER_DIR', 'XEFM_OTHER_SELECTED',
        'XEFM_LEFT_DIR', 'XEFM_LEFT_SELECTED', 'XEFM_RIGHT_DIR', 'XEFM_RIGHT_SELECTED', 'XEFM_ACTIVE'
    ]
    
    for var in xefm_vars:
        os.environ.pop(var, None)

    try:
        subprocess.run(['bcompare'] + dirs_to_compare, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error launching BeyondCompare: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: BeyondCompare executable not found")
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Unexpected error occurred: {e}")
        sys.exit(1)