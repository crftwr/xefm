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
- `options` (optional):
  - `terminal: True` — hand the terminal over to the program and wait for it
    to exit, for full-screen / interactive programs (`vim`, `less`, a REPL).
    Terminal mode only; in desktop mode there is no terminal to hand over, so
    the launch is refused with an error in the log pane.
  - `auto_return` — deprecated and ignored; launches never block XeFM. A
    config warning names the entries still carrying it.

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
  `XEFM_RIGHT_SELECTED`: The files selected with **Space** in the respective
  pane (space-separated, double-quoted). **Empty when nothing is selected.**
- `XEFM_THIS_FOCUSED` / `XEFM_OTHER_FOCUSED` / `XEFM_LEFT_FOCUSED` /
  `XEFM_RIGHT_FOCUSED`: The single item under that pane's cursor, quoted the
  same way — regardless of the selection, and empty only when the pane is.
- `XEFM_ACTIVE`: Set to `1` while running under XeFM — shell rc files can key
  off it, e.g. to mark the subshell prompt (see the Subshell section of the
  [User Guide](XEFM_USER_GUIDE.md))

Your scripts can use these variables to work with your current selection and location.

### Selection vs. cursor

The two families are reported separately so a program can decide for itself
which one it wants:

```python
targets = selected or focused   # act on the selection, else the cursor
if len(selected) != 2:          # or: require a real selection
    sys.exit("select exactly two files")
```

> **Changed since XeFM 1.1.0.** Up to that release, `*_SELECTED` substituted
> the file under the cursor when nothing was selected, so a program could not
> tell one deliberately selected file from a cursor that happened to sit on it.
> It now reports the selection alone. A tool that wants the old behaviour gets
> it with the `selected or focused` line above.

Note this is the *environment's* contract. The filenames appended to the
program's **command line** still follow the older, single-answer rule — the
selection when there is one, the focused entry otherwise — because one argument
list cannot express both.

## Usage

1. Press **X** to open the programs dialog
2. Use the searchable list to find and select a program
3. Press Enter to launch it

The program runs in the background with the current pane as its working
directory; the selected filenames (or the focused one) are also appended as
command-line arguments. Its output — stdout and stderr — streams into the log
pane, in both terminal and desktop mode, and a nonzero exit code is reported
there too. XeFM stays fully responsive throughout.

By default the program's input is closed at launch, so interactive terminal
programs can't run this way. Give such an entry `'options': {'terminal': True}`
instead: in terminal mode XeFM suspends its own display and hands the program
the terminal — with the same working directory, arguments, and `XEFM_*`
environment — then repaints when it exits, so `vim`, `less`, or a REPL work as
expected:

```python
{'name': 'View with less', 'command': ['less'], 'options': {'terminal': True}},
```

If the program exits with a nonzero code, XeFM waits for Enter before
repainting, so whatever error output it left on the terminal stays readable.

In desktop mode there is no terminal to hand over, so a `terminal: True`
entry is refused with an error in the log pane — as is sub-shell mode
(**Shift-X**), which in terminal mode remains the tool for extended
interactive command-line work.

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

### Beyond Compare (removed)

Earlier releases bundled Beyond Compare helper scripts (`bcompare_files.py`,
`bcompare_dirs.py`) and menu entries driving them. Both are gone: XeFM's
built-in diff viewer compares the two selected files (**=**) and the two pane
directories (**Shift+=**) — see
[Diff Viewer Feature](DIFF_VIEWER_FEATURE.md). A config still referencing the
old scripts will log a launch failure; remove those `PROGRAMS` entries, or —
if you prefer [Beyond Compare](https://www.scootersoftware.com/) — write a
small tool in `~/.xefm/tools/` that runs `bcompare` on `XEFM_LEFT_DIR` /
`XEFM_RIGHT_DIR` (start from `example_tool.py`).

### Visual Studio Code

One entry opens the current directory (and any selected files) in VS Code:

```python
{'name': 'Open in VSCode',
 'command': [xefm_python, xefm_tool('vscode.py')]}
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