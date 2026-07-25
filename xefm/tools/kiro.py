#!/usr/bin/env python3
"""
Kiro Wrapper Script for XeFM
Opens Kiro with the focused directory and selected files
Intelligently detects git repositories and opens the repo root instead
"""

import os
import sys
import subprocess
import shutil
import shlex


def find_git_root(directory):
    """Find git repository root starting from the given directory."""
    current_dir = os.path.abspath(directory)
    
    while current_dir != os.path.dirname(current_dir):  # Not at filesystem root
        if os.path.isdir(os.path.join(current_dir, '.git')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    
    return None


def main():
    """Main function to open Kiro with XeFM context."""
    # Check if Kiro is available
    if not shutil.which('kiro'):
        print("Error: Kiro (kiro) is not installed or not in PATH")
        print("Please install Kiro and ensure 'kiro' command is available")
        sys.exit(1)

    # Get the current directory from XeFM environment variables
    # XeFM sets XEFM_THIS_DIR to the current pane's directory
    current_dir = os.environ.get('XEFM_THIS_DIR', os.getcwd())
    selected_files = os.environ.get('XEFM_THIS_SELECTED', '')

    # Verify the current directory exists
    try:
        dir_exists = os.path.isdir(current_dir)
    except (OSError, PermissionError) as e:
        print(f"Error accessing current directory: {e}")
        sys.exit(1)
        
    if not dir_exists:
        print(f"Error: Current directory does not exist: {current_dir}")
        sys.exit(1)

    # Check if we're in a git repository
    git_root = find_git_root(current_dir)
    if git_root:
        # Open git repository root
        target_dir = git_root
        print(f"Opening git repository root: {target_dir}")
    else:
        # Open the current directory
        target_dir = current_dir
        print(f"Opening directory: {target_dir}")

    # Build Kiro command
    kiro_args = [target_dir]

    # Add selected files if any
    if selected_files:
        print(f"Opening selected files: {selected_files}")
        
        try:
            # XEFM_THIS_SELECTED contains space-separated quoted filenames
            # We need to parse them to remove quotes and handle spaces properly
            selected_array = shlex.split(selected_files)
        except ValueError as e:
            print(f"Error parsing selected files: {e}")
            selected_array = []
        
        for file in selected_array:
            if file:
                # Convert relative paths to absolute paths
                if not os.path.isabs(file):
                    file_path = os.path.join(current_dir, file)
                else:
                    file_path = file
                
                # Only add regular files, skip directories
                try:
                    is_file = os.path.isfile(file_path)
                    is_dir = os.path.isdir(file_path)
                    exists = os.path.exists(file_path)
                except (OSError, PermissionError) as e:
                    print(f"Warning: Cannot access '{file}': {e}")
                    continue
                    
                if is_file:
                    kiro_args.append(file_path)
                elif is_dir:
                    print(f"Skipping directory: '{file}' (only files are opened)")
                else:
                    print(f"Warning: '{file}' does not exist, skipping")

    # Unset XeFM environment variables before launching GUI app
    # These variables are not needed for Kiro and can sometimes cause issues
    xefm_vars = [
        'XEFM_THIS_DIR', 'XEFM_THIS_SELECTED', 'XEFM_OTHER_DIR', 'XEFM_OTHER_SELECTED',
        'XEFM_LEFT_DIR', 'XEFM_LEFT_SELECTED', 'XEFM_RIGHT_DIR', 'XEFM_RIGHT_SELECTED', 'XEFM_ACTIVE'
    ]
    
    for var in xefm_vars:
        os.environ.pop(var, None)

    # Execute Kiro
    print(f"Executing: kiro {' '.join(kiro_args)}")
    
    try:
        subprocess.run(['kiro'] + kiro_args, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error launching Kiro: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: Kiro executable not found")
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Unexpected error occurred: {e}")
        sys.exit(1)
