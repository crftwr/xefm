#!/usr/bin/env python3
"""
Timeout utility for macOS - equivalent to GNU timeout command.

Usage:
    python3 tools/timeout.py <seconds> <command> [args...]
    
Example:
    python3 tools/timeout.py 5 python -m xefm
    
Exit codes:
    - Command's exit code if it completes within timeout
    - 124 if timeout is reached
    - 125 if timeout.py itself fails
"""

import sys
import subprocess
import signal
import time


def main():
    if len(sys.argv) < 3:
        print("Usage: timeout.py <seconds> <command> [args...]", file=sys.stderr)
        sys.exit(125)
    
    try:
        timeout_seconds = float(sys.argv[1])
    except ValueError:
        print(f"Error: Invalid timeout value '{sys.argv[1]}'", file=sys.stderr)
        sys.exit(125)
    
    command = sys.argv[2:]
    
    try:
        # Start the process
        process = subprocess.Popen(
            command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            stdin=sys.stdin
        )
        
        # Wait for completion or timeout
        try:
            exit_code = process.wait(timeout=timeout_seconds)
            sys.exit(exit_code)
        except subprocess.TimeoutExpired:
            # Timeout reached - terminate the process
            print(f"\nTimeout: Process killed after {timeout_seconds} seconds", file=sys.stderr)
            
            # Try graceful termination first
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if still running
                process.kill()
                process.wait()
            
            sys.exit(124)
            
    except FileNotFoundError:
        print(f"Error: Command not found: {command[0]}", file=sys.stderr)
        sys.exit(127)
    except KeyboardInterrupt:
        # User interrupted - pass it to the child process
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(125)


if __name__ == "__main__":
    main()
