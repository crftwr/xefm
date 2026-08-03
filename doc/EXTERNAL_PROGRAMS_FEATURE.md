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
- `options` (optional): accepted for compatibility with older configs
  (`auto_return`), but the current launcher never blocks XeFM, so it has no
  effect

### Basic Configuration Example

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Git Log', 'command': ['git', 'log', '--oneline', '-10']},
    {'name': 'Disk Usage', 'command': ['du', '-sh', '.']},
]
```

## Environment Variables

When you run external programs, XeFM provides information about your current state through environment variables:

- `XEFM_THIS_DIR` / `XEFM_OTHER_DIR`: Current / other pane directory
- `XEFM_LEFT_DIR` / `XEFM_RIGHT_DIR`: Left / right pane directory
- `XEFM_THIS_SELECTED` / `XEFM_OTHER_SELECTED` / `XEFM_LEFT_SELECTED` /
  `XEFM_RIGHT_SELECTED`: Selected files in the respective pane
  (space-separated, double-quoted; the focused file when nothing is selected)
- `XEFM_ACTIVE`: Set to `1` while running under XeFM

Your scripts can use these variables to work with your current selection and location.

## Usage

1. Press **X** to open the programs dialog
2. Use the searchable list to find and select a program
3. Press Enter to launch it

The program runs in the background with the current pane as its working
directory; the selected filenames (or the focused one) are also appended as
command-line arguments. Its output — stdout and stderr — streams into the log
pane, in both terminal and desktop mode, and a nonzero exit code is reported
there too. XeFM stays fully responsive throughout.

Because the program's input is closed at launch, interactive terminal programs
(a REPL, `vim`, `less`) can't run from this menu — use sub-shell mode
(**Shift-X**) for those.

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

On first launch XeFM creates a personal tools directory, `~/.xefm/tools/`, and
places an example in it: `example_tool.py`, which prints every `XEFM_*`
variable and resolves the current selection to absolute paths. It is wired
into the default `PROGRAMS` as **Example Tool (show XeFM environment)**, so
pressing **X** and running it shows exactly what your own scripts receive.
(The directory is seeded once — if you delete the example, it stays deleted.)

To add a tool of your own:

1. Drop a script into `~/.xefm/tools/` — copying `example_tool.py` is a good
   starting point.
2. Add an entry to `PROGRAMS` in `~/.xefm/config.py`:

```python
{'name': 'My Tool', 'command': [xefm_python, xefm_tool('my_tool.py')]},
```

Tools are not limited to Python. The `command` field is an argument list
passed straight to the operating system, so shell scripts and plain commands
work the same way:

```bash
#!/bin/bash
# Simple script that processes selected files
echo "Working in: $XEFM_THIS_DIR"
echo "Selected files: $XEFM_THIS_SELECTED"
```

```python
{'name': 'My Shell Script', 'command': ['bash', xefm_tool('my_script.sh')]},
```

## Example integrations

XeFM ships with a few ready-made `PROGRAMS` entries that show how to wire a real
external tool into the menu. Each is a single recipe pointing at a small helper
script that reads the `XEFM_*` environment variables above. The helpers live in
XeFM's bundled tools directory (`xefm/tools/`) and are located at run time by
`xefm_tool('name')`, which searches `~/.xefm/tools/` first and then that bundled
directory. `xefm_python` is the interpreter XeFM is running under.

### Beyond Compare

XeFM's built-in diff viewer already compares the two selected files (**=**)
and the two pane directories (**Shift+=**) — see
[Diff Viewer Feature](DIFF_VIEWER_FEATURE.md) — so the Beyond Compare entries
are no longer part of the default configuration. The helper scripts stay
bundled for configs that still reference them; if you prefer
[Beyond Compare](https://www.scootersoftware.com/), add the entries yourself:

```python
PROGRAMS = [
    {'name': 'Compare Files (BeyondCompare)',
     'command': [xefm_python, xefm_tool('bcompare_files.py')]},
    {'name': 'Compare Directories (BeyondCompare)',
     'command': [xefm_python, xefm_tool('bcompare_dirs.py')]},
]
```

- `bcompare_dirs.py` launches Beyond Compare on `XEFM_LEFT_DIR` and
  `XEFM_RIGHT_DIR` (the left and right pane directories).
- `bcompare_files.py` compares the first selected file in each pane, building
  full paths from `XEFM_LEFT_SELECTED` / `XEFM_RIGHT_SELECTED` and the pane
  directories. If nothing is explicitly selected, the file under each cursor is
  used.

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