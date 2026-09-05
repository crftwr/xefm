# Batch Rename Feature

## Overview
The batch rename feature allows you to rename multiple files at once using regex patterns and destination templates with special macros.

## How to Use

1. **Select Multiple Files**: Use the space bar to select multiple files in the file manager
2. **Trigger Batch Rename**: Press 'R' key when multiple files are selected
3. **Enter Patterns**: The batch rename dialog will appear with two input fields:
   - **Regex Pattern**: A regular expression to match parts of the original filenames
   - **Destination Pattern**: A template for the new filenames using special macros

## Special Macros

The destination pattern supports the following macros:

- `\0` - The entire original filename
- `\1` to `\9` - Regex capture groups from the pattern match
- `\d` - Index number (1, 2, 3, etc.)

## Examples

### Example 1: Add Prefix
- **Files**: `file1.txt`, `file2.txt`, `file3.txt`
- **Regex Pattern**: `(.*)`
- **Destination Pattern**: `backup_\1`
- **Result**: `backup_file1.txt`, `backup_file2.txt`, `backup_file3.txt`

### Example 2: Change Extension
- **Files**: `document.txt`, `readme.txt`, `notes.txt`
- **Regex Pattern**: `(.*)\.txt`
- **Destination Pattern**: `\1.md`
- **Result**: `document.md`, `readme.md`, `notes.md`

### Example 3: Add Sequential Numbers
- **Files**: `photo.jpg`, `image.jpg`, `picture.jpg`
- **Regex Pattern**: `(.*)\.(jpg)`
- **Destination Pattern**: `\1_\d.\2`
- **Result**: `photo_1.jpg`, `image_2.jpg`, `picture_3.jpg`

### Example 4: Extract and Reorder Parts
- **Files**: `2023-01-15_report.pdf`, `2023-02-20_summary.pdf`
- **Regex Pattern**: `(\d{4})-(\d{2})-(\d{2})_(.*)`
- **Destination Pattern**: `\4_\1\2\3`
- **Result**: `report_20230115.pdf`, `summary_20230220.pdf`

## Dialog Controls

- **Tab**: Switch between regex pattern and destination pattern input fields
- **Enter**: Execute the batch rename operation
- **ESC**: Cancel and exit batch rename mode
- **↑/↓**: Scroll through the preview list
- **←/→**: Move text cursor left/right within the current input field
- **Home/End**: Move cursor to beginning/end of the current input field
- **Backspace**: Delete character before cursor
- **Delete**: Delete character at cursor position

## Preview

The dialog shows a real-time preview of the rename operation:
- **Original Name**: The current filename
- **New Name**: The proposed new filename
- **Status**: 
  - `OK` - Rename will succeed
  - `UNCHANGED` - No change needed
  - `CONFLICT!` - Target filename already exists
  - `INVALID!` - Invalid filename (contains illegal characters)

## Safety Features

- **Conflict Detection**: The system checks for existing files and prevents overwrites
- **Validation**: Filenames are validated for illegal characters
- **Preview**: See all changes before executing
- **Selective Rename**: Only files that actually change are renamed

## Notes

- Only regular files are included in batch rename (directories are excluded for safety)
- The regex pattern must match the filename for the rename to occur
- If no match is found, the original filename is preserved

## Accented and Japanese names

Some characters can be written two ways that look identical on screen — `が` as
one character, or as `か` plus a voiced-sound mark. Files written the second way
come from HFS+ disks, network shares, archives, and from Finder itself.

XeFM treats the two spellings as the same text, so a search pattern typed at an
IME finds a file however it happens to be stored, and two files whose new names
differ only in spelling are reported as a conflict instead of one silently
replacing the other.

A renamed file is written back in the single-character spelling. Finder uses the
other one, so on macOS a name XeFM renames may end up spelled differently from
the same name renamed in Finder. The file is the same file either way and both
spellings open it; the difference matters only on disks and cloud storage that
compare names byte for byte, which is why XeFM keeps one spelling everywhere.
Files the rename does not touch are left exactly as they are.
- Empty or invalid destination patterns will prevent the operation