# File Extension Associations Feature

## Overview

The File Extension Associations feature allows you to configure which programs XeFM uses to open, view, and edit different types of files based on their extensions. This provides a flexible way to customize how XeFM handles various file types.

## Quick Start

### What is it?

File associations let you configure which programs XeFM uses to open, view, and edit different file types. For example, you can use Preview for viewing images but Photoshop for editing them.

### Basic Example

Add this to your `~/.xefm/config.py`:

```python
FILE_ASSOCIATIONS = [
    # Images: Multiple patterns, Preview for viewing, Photoshop for editing
    {
        'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
        'open|view': ['open', '-a', 'Preview'],  # Same for open and view
        'edit': ['open', '-a', 'Photoshop']
    },
    
    # Videos: QuickTime for viewing, Final Cut for editing
    {
        'pattern': ['*.mp4', '*.mov'],
        'open|view': ['open', '-a', 'QuickTime Player'],
        'edit': ['open', '-a', 'Final Cut Pro']
    },
    
    # PDFs: Preview for viewing, Acrobat for editing
    {
        'pattern': '*.pdf',
        'open|view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Adobe Acrobat']
    }
]
```

## Configuration

File associations are configured in your `~/.xefm/config.py` file using the `FILE_ASSOCIATIONS` list.

### Compact Format Structure

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': '*.ext' or ['*.ext1', '*.ext2'],  # Single or multiple
        'open|view': ['command', 'args'],  # Combined actions
        'edit': ['command', 'args']        # Separate action
    }
]
```

### Key Features

1. **Multiple patterns**: Group related patterns in a list
2. **Combined actions**: Use `|` to assign same command to multiple actions
3. **Flexible format**: Single pattern as string, multiple as list

### Actions

Each file pattern can configure up to four actions:

| Action | Key | What it does | Value |
|---|---|---|---|
| **enter** | `Enter` | Casual open — handled **inside XeFM** | A built-in handler name |
| **open** | `Cmd/Ctrl-Enter` | Deliberate open — hands off to another app | A command |
| **view** | `V` | View the file | A command |
| **edit** | `E` | Edit the file | A command |

#### Two tiers of "open"

`Enter` and `Cmd/Ctrl-Enter` are deliberately different gestures:

- **`Enter` never leaves XeFM.** It enters directories, browses archives, and
  opens files in the built-in viewer. It is safe to lean on — it will not
  launch an application or steal focus.
- **`Cmd/Ctrl-Enter` hands the file to a real application.** Use it when you
  actually want Preview, an IDE, or the OS default app.

Because the `enter` tier stays inside XeFM, its value names a **built-in
handler** rather than a program to launch:

| Value | Effect |
|---|---|
| `'viewer'` | Open in the built-in text/markdown viewer |
| `'navigate'` | Browse the file as an archive (useful for `*.jar`, `*.whl`) |
| `None` | Do nothing |
| *(no rule)* | XeFM's default: enter directories and archives, view files |

```python
{
    'pattern': '*.csv',
    'enter': 'viewer',                    # Enter -> built-in viewer
    'open':  ['open', '-a', 'Numbers'],   # Cmd-Enter -> Numbers
}
```

### Command Formats

Programs can be specified in two formats:

1. **Command list** (recommended):
   ```python
   'open': ['open', '-a', 'Preview']
   ```

2. **Command string** (automatically converted to list):
   ```python
   'open': 'open -a Preview'
   ```

3. **None** (action not available):
   ```python
   'edit': None  # No editor configured for this file type
   ```

   For `view`, `None` means something more specific: **use the built-in
   viewer**. See [Text Files](#text-files---built-in-viewer-for-view-action).

### Terminal Programs

**You do not declare this.** Whether XeFM hands over the display is a property of
the backend you are running, not of the program you configured:

| Mode | What happens when a program launches |
|---|---|
| Terminal (`--backend tui`) | XeFM suspends, the program owns the terminal, XeFM restores and repaints when it exits |
| Desktop mode | There is no terminal to hand over, so the program is detached and XeFM stays responsive |

So `'view': ['less']` simply works in terminal mode — no flag needed:

```python
{
    'pattern': '*.log',
    'view': ['less'],      # terminal mode hands the display over and waits
    'edit': ['code'],      # a GUI editor in the same entry is fine
}
```

The practical consequence is the same one that governs `TEXT_EDITOR`: **pick
programs that suit the mode you run in.** A terminal program configured while
running in desktop mode has no terminal to draw on and will not appear; a GUI
launcher used in terminal mode works, with a brief repaint as XeFM resumes.

> Earlier drafts of this feature had a per-entry `'terminal': True` flag. It was
> removed: it duplicated a decision XeFM can already make, could not express one
> entry mixing a terminal viewer with a GUI editor, and failed unsafely —
> forgetting it on `less` corrupted the terminal. A leftover `terminal` key in a
> hand-written config is ignored.

### Compact Format Features

#### 1. Multiple Patterns

Group related file patterns together:

```python
{
    'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif']
}
```

Instead of repeating the same configuration for each extension.

#### 2. Combined Actions

Use the pipe `|` operator to assign the same command to multiple actions:

```python
{
    'open|view': ['open', '-a', 'Preview']
}
```

This clearly shows that open and view use the same program, making the intent explicit.

#### 3. Flexible Pattern Format

Single pattern as string:
```python
'pattern': '*.pdf'
```

Multiple patterns as list:
```python
'pattern': ['*.mp4', '*.mov', '*.avi']
```

### Format Comparison

**Old Format (Verbose)**:
```python
FILE_ASSOCIATIONS = {
    '*.jpg': {
        'open': ['open', '-a', 'Preview'],
        'view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Photoshop']
    },
    '*.jpeg': {
        'open': ['open', '-a', 'Preview'],
        'view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Photoshop']
    },
    # ... repeat for each extension
}
```

**New Format (Compact)**:
```python
FILE_ASSOCIATIONS = [
    {
        'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
        'open|view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Photoshop']
    }
]
```

**Reduction**: 75% fewer lines!

## Priority Matching

FILE_ASSOCIATIONS entries are checked in order from top to bottom. This allows you to define specific rules before general rules, giving you fine-grained control over file handling.

### How It Works

When XeFM needs to find a program for a file and action:

1. **Check each entry** in FILE_ASSOCIATIONS from top to bottom
2. **For each entry**:
   - Check if the filename matches the pattern
   - If pattern matches, check if the action exists in that entry
   - If action exists, use that command (even if None)
   - If action doesn't exist, continue to next entry
3. **Stop at first match** where both pattern and action are found

### Key Principle

**First matching entry wins** - but only if the action is present in that entry.

### Priority Examples

#### Example 1: Specific Before General

```python
FILE_ASSOCIATIONS = [
    # Specific: Test files
    {
        'pattern': 'test_*.py',
        'open': ['pytest', '-v'],
        'edit': ['vim']
    },
    # General: All Python files
    {
        'pattern': '*.py',
        'open': ['python3'],
        'view': ['less'],
        'edit': ['vim']
    }
]
```

**Behavior**:
- `test_main.py` + open → `pytest -v` (matches first entry)
- `test_main.py` + view → `less` (first entry has no 'view', uses second entry)
- `script.py` + open → `python3` (doesn't match first pattern, uses second entry)

#### Example 2: README Files

```python
FILE_ASSOCIATIONS = [
    # Specific: README files with special viewer
    {
        'pattern': 'README*',
        'view': ['glow']  # Markdown renderer
    },
    # General: All markdown files
    {
        'pattern': '*.md',
        'open': ['typora'],
        'view': ['less'],
        'edit': ['vim']
    }
]
```

**Behavior**:
- `README.md` + view → `glow` (matches first entry)
- `README.md` + open → `typora` (first entry has no 'open', uses second entry)
- `notes.md` + view → `less` (doesn't match first pattern, uses second entry)

### Best Practices for Priority

1. **Specific Patterns First**: Always put more specific patterns before general ones
2. **Document Your Intent**: Add comments to explain why entries are ordered
3. **Test Your Configuration**: Verify that files match the expected patterns

## Usage in XeFM

Once configured, XeFM will use these associations when you:

1. Select a file and choose an action (open, view, or edit)
2. Use keyboard shortcuts for file operations
3. Use the file context menu

### Key Bindings

#### Enter - Open Inside XeFM
Enter uses the **enter** action. It never launches an external program.

**Behavior**:
1. Directories are entered and recognized archives are browsed — always, and
   not configurable; this is what Enter means structurally
2. For a plain file, checks associations for an 'enter' handler
3. `'viewer'` opens the built-in viewer; `'navigate'` browses the file as an
   archive; `None` does nothing
4. With no rule, opens the built-in viewer
5. Unless XeFM has no built-in way to show the file — a PNG, say — in which case
   it logs a warning naming the key bound to `open_with_os`, rather than
   opening a viewer on content it cannot render

Step 5 is why images currently report *"No built-in viewer for photo.png —
press Command-ENTER to open it in an external program"*. Setting
`'enter': 'viewer'` on such a pattern overrides this and opens the viewer
anyway, which shows a binary placeholder.

#### Cmd/Ctrl-Enter - Open Externally
Cmd-Enter (Ctrl-Enter on Windows) uses the **open** action.

**Behavior**:
1. Checks associations for an 'open' command
2. If found, launches it — handing over the display first in terminal mode,
   detaching it in desktop mode (see [Terminal Programs](#terminal-programs))
3. If explicitly `None`, nothing is launched (this is how you stop a file type
   from ever being handed to the OS)
4. Otherwise falls back to the OS default app (`open` / `xdg-open` / `start`)

#### V Key - View File
When you press V on a file, XeFM uses the **view** action from file associations.

**Behavior**:
1. Checks file associations for 'view' action
2. If found, launches the configured viewer
3. If explicitly `None`, opens the built-in text viewer
4. If not found, opens the built-in text viewer (binaries show a placeholder)

Remote and in-archive files always use the built-in viewer — an external
program has no path on disk it could open.

#### E Key - Edit File
When you press E on a file, XeFM uses the **edit** action from file associations.

**Behavior**:
1. Checks file associations for 'edit' action
2. If found, launches the configured editor
3. If explicitly `None`, reports that no editor is configured and stops
4. If not found, falls back to the `TEXT_EDITOR` config setting

Local files only; remote and in-archive paths are skipped.

### Usage Examples

#### Images - Same Viewer, Different Editor

```python
{
    'pattern': ['*.jpg', '*.png'],
    'open|view': ['open', '-a', 'Preview'],  # Same for both
    'edit': ['open', '-a', 'Photoshop']      # Different editor
}
```

**Usage**:
- Press Enter on `photo.jpg` → Opens in Preview
- Press V on `photo.jpg` → Opens in Preview (same as Enter)
- Press E on `photo.jpg` → Opens in Photoshop

#### Videos - Viewer Only

```python
{
    'pattern': '*.avi',
    'open|view': ['open', '-a', 'VLC'],
    'edit': None  # No editor configured
}
```

**Usage**:
- Press Enter on `movie.avi` → Opens in VLC
- Press V on `movie.avi` → Opens in VLC
- Press E on `movie.avi` → Shows "No editor configured" message

#### Text Files - Built-in Viewer for View Action

```python
{
    'pattern': '*.txt',
    'open': ['open', '-e'],      # TextEdit
    'edit': ['vim']              # Terminal editor
    # 'view' omitted - will use built-in text viewer
}
```

**Usage**:
- Press Enter on `readme.txt` → Opens in TextEdit
- Press V on `readme.txt` → Opens in built-in text viewer (with syntax highlighting)
- Press E on `readme.txt` → Opens in vim

**Note**: Omitting the `view` action allows XeFM to use the built-in text viewer for text files, which provides syntax highlighting and is optimized for viewing code and text files.

### Fallback Behavior

If a file has no configured association:

1. **Enter key**: Falls back to the built-in viewer for text files; for a file
   XeFM has no built-in way to render (an image, say) it logs a warning naming
   the key that opens the file externally, rather than showing garbage
2. **V key**: Opens the built-in text viewer, which reads the bytes — text is
   shown with syntax highlighting, a binary shows a placeholder
3. **E key**: Falls back to the `TEXT_EDITOR` config setting

### How XeFM decides a file is text

**XeFM detects text by reading the bytes, not by looking at the extension.**
There is deliberately no list of "text extensions" anywhere in XeFM: such a list
is wrong for files with no extension (`Makefile`, `README`), an unknown one, or
a misleading one — and inspecting the content gets all three right for free.

The built-in viewer decides like this:

1. **Try to decode** the file as `utf-8`, then `latin-1`, then `cp1252`
2. **If none decode**, read the raw bytes and look for a NUL byte in the first
   1024 — a NUL means binary, and `[Binary file — cannot display as text]` is
   shown
3. **Otherwise** fall back to `latin-1` with replacement characters

The rule of thumb across XeFM is **detect capability from the bytes; configure
preference by extension.** Extensions decide *which application you prefer* —
never whether a file is readable as text.

### View action: command, None, or no rule

For the **view** action there are three cases, and two of them land in the same
place:

| `view` value | Effect |
|---|---|
| a command, e.g. `['less']` | Launch that external viewer |
| `None` | Use the built-in viewer (text shown, binary → placeholder) |
| *(no rule matches)* | Same as `None` — the built-in viewer, via fallback |

So for `view`, `None` and "no rule at all" are equivalent. The distinction only
matters for **open** and **edit**, where `None` means "this action is
unavailable for this file type" and stops the fallback. Set `'view': None`
explicitly only when you want to *guarantee* the built-in viewer even though a
later, more general entry might otherwise supply a command.

### Action fallback at a glance

| Action | With association | No association — text | No association — binary |
|---|---|---|---|
| **Enter** | Built-in handler or configured open | Built-in viewer | Warns to use the open-externally key |
| **V (View)** | Configured viewer (or built-in if `None`) | Built-in viewer | Built-in viewer shows placeholder |
| **E (Edit)** | Configured editor | `TEXT_EDITOR` config | `TEXT_EDITOR` config |

## Open Externally and Reveal in File Manager

Beyond the configurable actions above, XeFM has two fixed gestures that hand a
file to the operating system.

### Open externally — the OS default app

**Key**: `Cmd-Enter` (macOS) / `Ctrl-Enter` (Linux/Windows) — the same key as
the **open** action.

This is the deliberate-open tier described under
[Cmd/Ctrl-Enter](#cmdctrl-enter---open-externally): XeFM first looks for an
`open` command in your associations, and if there is none (and it is not
explicitly `None`) it falls back to the OS default application — `open` on
macOS, `xdg-open` on Linux, `start` on Windows. Selected files are opened; if
nothing is selected, the focused file is used. This handoff is *not*
configurable per file the way the `open` command is — it is whatever the OS
has registered for that type.

### Reveal in File Manager

**Key**: `Alt-Enter` (macOS/Linux) / `Ctrl-Shift-E` (Windows).

Opens the OS file manager with the item selected:

- **macOS**: Finder, via `open -R`
- **Windows**: Explorer, via `explorer`
- **Linux**: the default file manager (nautilus, nemo, dolphin, …)

This action always uses the **focused** item, not the selection. When a
directory is focused it is revealed *in its parent* (shown as a selected item),
not opened to show its contents — useful for jumping out to the OS to
drag-and-drop or reach a native context menu.

To run one of your own configured tools instead of the OS default, open the
external programs menu with **X** (see
[External Programs](EXTERNAL_PROGRAMS_FEATURE.md)).

## Examples

### Image Files

Group multiple image extensions and use the same program for opening and viewing:

```python
{
    'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
    'open|view': ['open', '-a', 'Preview'],
    'edit': ['open', '-a', 'Photoshop']
}
```

### Video Files

```python
{
    'pattern': ['*.mp4', '*.mov'],
    'open|view': ['open', '-a', 'QuickTime Player'],
    'edit': ['open', '-a', 'Final Cut Pro']
},
{
    'pattern': '*.avi',
    'open|view': ['open', '-a', 'VLC'],
    'edit': None  # No editor configured
}
```

### PDF Files

```python
{
    'pattern': '*.pdf',
    'open|view': ['open', '-a', 'Preview'],
    'edit': ['open', '-a', 'Adobe Acrobat']
}
```

### Text and Code Files

```python
{
    'pattern': '*.txt',
    'open': ['open', '-e'],  # TextEdit on macOS
    'edit': ['vim']
    # 'view' omitted - uses built-in text viewer
},
{
    'pattern': ['*.py', '*.js'],
    'open': ['open', '-a', 'Visual Studio Code'],
    'edit': ['vim']
    # 'view' omitted - uses built-in text viewer with syntax highlighting
}
```

## Pattern Matching

File associations use wildcard pattern matching:

- `*.pdf` - matches all PDF files
- `*.jpg` - matches all JPG files
- `*.tar.gz` - matches compressed tar archives

Pattern matching is case-insensitive, so `*.PDF` and `*.pdf` are treated the same.

## Platform-Specific Configuration

You can configure different programs for different platforms:

```python
import platform

FILE_ASSOCIATIONS = []

if platform.system() == 'Darwin':  # macOS
    FILE_ASSOCIATIONS.append({
        'pattern': ['*.jpg', '*.png'],
        'open|view': ['open', '-a', 'Preview'],
        'edit': ['open', '-a', 'Photoshop']
    })
elif platform.system() == 'Linux':
    FILE_ASSOCIATIONS.append({
        'pattern': ['*.jpg', '*.png'],
        'open': ['xdg-open'],
        'view': ['eog'],  # Eye of GNOME
        'edit': ['gimp']
    })
```

## Default Associations

XeFM comes with default file associations for common file types:

- **Images**: JPG, JPEG, PNG, GIF
- **Videos**: MP4, MOV, AVI
- **Audio**: MP3, WAV
- **Documents**: PDF, TXT, MD
- **Code**: PY, JS

You can override any of these defaults in your configuration file.

## Tips and Best Practices

1. **Same program for multiple actions**: It's common to use the same program for both 'open' and 'view' actions, especially for media files.

2. **Specialized editors**: Use the 'edit' action for specialized editing software that's different from your viewing application.

3. **No action available**: Set an action to `None` if you don't want that action available for a file type.

4. **Test your commands**: Make sure the commands work from your terminal before adding them to the configuration.

5. **Use absolute paths**: If a program isn't in your PATH, use the absolute path to the executable.

6. **Specific patterns first**: Always put more specific patterns before general ones in your configuration.

7. **Document your intent**: Add comments to explain why entries are ordered a certain way.

## Troubleshooting

### Program not found

If XeFM can't find the program:
- Check that the program is installed
- Verify the command name is correct
- Use the full path to the executable if needed

### Wrong program opens

If the wrong program opens:
- Check your pattern matches the file extension correctly
- Verify the pattern is case-insensitive
- Make sure there are no conflicting patterns
- Check the order of entries (specific before general)

### Action not available

If an action doesn't appear:
- Check that the action is configured (not set to `None`)
- Verify the file extension matches a configured pattern
- Check for typos in the configuration

### Pattern Not Matching

If a file doesn't match the expected pattern:
- Remember patterns are checked in order from top to bottom
- More specific patterns should come before general patterns
- Check that the pattern syntax is correct (use `*.ext` format)

## Testing Your Configuration

Run the test to verify everything works:

```bash
python3 test/test_file_associations.py
```

## Related Documentation

- Implementation details: `doc/dev/FILE_ASSOCIATIONS_IMPLEMENTATION.md`
- XeFM User Guide: `doc/XEFM_USER_GUIDE.md`
