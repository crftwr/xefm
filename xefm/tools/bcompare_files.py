#!/usr/bin/env python3
"""
BeyondCompare file comparison wrapper script for XeFM
This script launches BeyondCompare to compare selected files from left and right panes
"""

import os
import sys
import subprocess
import shutil
import shlex


def main():
    """Launch BeyondCompare to compare selected files from left and right panes."""
    # Check if BeyondCompare is available
    if not shutil.which('bcompare'):
        print("Error: BeyondCompare (bcompare) is not installed or not in PATH")
        print("Please install BeyondCompare and ensure 'bcompare' command is available")
        sys.exit(1)

    # Check if XeFM environment variables are set
    left_selected = os.environ.get('XEFM_LEFT_SELECTED')
    right_selected = os.environ.get('XEFM_RIGHT_SELECTED')
    left_dir = os.environ.get('XEFM_LEFT_DIR')
    right_dir = os.environ.get('XEFM_RIGHT_DIR')
    
    if not left_selected or not right_selected:
        print("Error: XeFM file selection environment variables not set")
        print("This script should be run from within XeFM with files selected in both panes")
        sys.exit(1)

    if not left_dir or not right_dir:
        print("Error: XeFM directory environment variables not set")
        print("This script should be run from within XeFM")
        sys.exit(1)

    # Parse selected files (properly handle quoted filenames)
    try:
        left_files = shlex.split(left_selected)
        right_files = shlex.split(right_selected)
    except ValueError as e:
        print(f"Error parsing selected files: {e}")
        sys.exit(1)

    # Get first file from each pane
    if not left_files or not right_files:
        print("Error: No files selected in one or both panes")
        sys.exit(1)
        
    left_file = left_files[0]
    right_file = right_files[0]

    # Build full paths
    left_path = os.path.join(left_dir, left_file)
    right_path = os.path.join(right_dir, right_file)

    # Check if files exist
    if not os.path.isfile(left_path):
        print(f"Error: Left file does not exist: {left_path}")
        sys.exit(1)

    if not os.path.isfile(right_path):
        print(f"Error: Right file does not exist: {right_path}")
        sys.exit(1)

    # Launch BeyondCompare with the files
    print("Launching BeyondCompare for file comparison...")
    print(f"Left file:  {left_path}")
    print(f"Right file: {right_path}")
    print()

    # Store the file paths before unsetting environment variables
    files_to_compare = [left_path, right_path]

    # Unset XeFM environment variables before launching GUI app
    # These variables are not needed for BeyondCompare and can sometimes cause issues
    xefm_vars = [
        'XEFM_THIS_DIR', 'XEFM_THIS_SELECTED', 'XEFM_OTHER_DIR', 'XEFM_OTHER_SELECTED',
        'XEFM_LEFT_DIR', 'XEFM_LEFT_SELECTED', 'XEFM_RIGHT_DIR', 'XEFM_RIGHT_SELECTED', 'XEFM_ACTIVE'
    ]
    
    for var in xefm_vars:
        os.environ.pop(var, None)

    try:
        subprocess.run(['bcompare'] + files_to_compare, check=True)
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