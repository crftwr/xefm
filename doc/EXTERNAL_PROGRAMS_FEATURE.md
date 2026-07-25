# External Programs Feature

## Overview

The External Programs feature allows you to execute custom external programs directly from XeFM with access to the current file manager state through environment variables. This extends XeFM's functionality by integrating with external tools and scripts.

## Key Bindings

- **X**: Open the external programs dialog
- **Shift-X**: Enter sub-shell (command line) mode — a separate feature

The programs menu and the sub-shell are two different tools: **X** runs one of
your configured `PROGRAMS` and returns to XeFM, while **Shift-X** drops you into
an interactive shell in the current pane's directory.

## Configuration

External programs are configured in the `PROGRAMS` list in your `config.py` file. Each program entry needs:

- `name`: Display name for the program
- `command`: List of command arguments
- `options` (optional): Program-specific options like `auto_return`

### Basic Configuration Example

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Git Log', 'command': ['git', 'log', '--oneline', '-10']},
    {'name': 'Disk Usage', 'command': ['du', '-sh', '*']},
    {'name': 'Python REPL', 'command': ['python3']},
    {'name': 'Quick Git Status', 'command': ['git', 'status', '--short'], 'options': {'auto_return': True}},
]
```

## Environment Variables

When you run external programs, XeFM provides information about your current state through environment variables:

- `XEFM_THIS_DIR`: Current pane directory
- `XEFM_OTHER_DIR`: Other pane directory
- `XEFM_THIS_SELECTED`: Selected files in current pane
- `XEFM_OTHER_SELECTED`: Selected files in other pane

Your scripts can use these variables to work with your current selection and location.

## Usage

1. Press **X** to open the programs dialog
2. Use the searchable list to find and select a program
3. Press Enter to execute the selected program
4. The program runs in the current pane's directory
5. Press Enter after the program completes to return to XeFM

## Example Use Cases

### Git Operations
- Check repository status
- View recent commits
- Add files to staging

### File Operations
- View file permissions
- Check disk usage
- Find large files

### Development Tools
- Open Python or Node.js REPL
- Run test suites
- Execute build scripts

### System Information
- View system information
- Check memory usage
- List running processes

## Creating Custom Scripts

You can create custom scripts that work with XeFM's environment variables. For example:

```bash
#!/bin/bash
# Simple script that processes selected files
echo "Working in: $XEFM_THIS_DIR"
echo "Selected files: $XEFM_THIS_SELECTED"
```

## Example integrations

XeFM ships with a few ready-made `PROGRAMS` entries that show how to wire a real
external tool into the menu. Each is a single recipe pointing at a small helper
script that reads the `XEFM_*` environment variables above. The helpers live in
XeFM's bundled tools directory (`xefm/tools/`) and are located at run time by
`xefm_tool('name')`, which searches `~/.xefm/tools/` first and then that bundled
directory. `xefm_python` is the interpreter XeFM is running under.

### Beyond Compare

Two entries drive [Beyond Compare](https://www.scootersoftware.com/) — one
compares the two pane *directories*, the other the two selected *files*:

```python
PROGRAMS = [
    {'name': 'Compare Files (BeyondCompare)',
     'command': [xefm_python, xefm_tool('bcompare_files.py')],
     'options': {'auto_return': True}},
    {'name': 'Compare Directories (BeyondCompare)',
     'command': [xefm_python, xefm_tool('bcompare_dirs.py')],
     'options': {'auto_return': True}},
]
```

- `bcompare_dirs.py` launches Beyond Compare on `XEFM_LEFT_DIR` and
  `XEFM_RIGHT_DIR` (the left and right pane directories).
- `bcompare_files.py` compares the first selected file in each pane, building
  full paths from `XEFM_LEFT_SELECTED` / `XEFM_RIGHT_SELECTED` and the pane
  directories. If nothing is explicitly selected, the file under each cursor is
  used.
- `auto_return: True` returns to XeFM as soon as Beyond Compare launches, without
  waiting for you to press Enter.

Requires the `bcompare` command on your `PATH` (install Beyond Compare — e.g.
`brew install --cask beyond-compare` on macOS).

### Visual Studio Code

One entry opens the current directory (and any selected files) in VS Code:

```python
{'name': 'Open in VSCode',
 'command': [xefm_python, xefm_tool('vscode.py')],
 'options': {'auto_return': True}}
```

`vscode.py` reads `XEFM_THIS_DIR` and `XEFM_THIS_SELECTED`. If the current
directory is inside a git repository it walks up to the repository root and
opens that instead of the subdirectory, then adds any selected regular files
(directories are skipped; filenames with spaces are handled). Requires the
`code` command on your `PATH` — in VS Code, run *Shell Command: Install 'code'
command in PATH* from the command palette.

## Troubleshooting

### Program Not Found
- Make sure the command exists in your PATH
- Use absolute paths for custom scripts

### Permission Denied
- Check that scripts have execute permissions
- Verify file/directory access rights

### No Output
- Some programs may run silently
- Check that the program completed successfully

## Quick Reference

- **X**: Open external programs dialog
- **Shift-X**: Open sub-shell mode (different feature)
- Use external programs for quick, specific tasks
- Use sub-shell mode for interactive command-line work