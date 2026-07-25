# Wide Character Support Feature

## Overview

XeFM now includes comprehensive support for wide characters, particularly Japanese Zenkaku characters and other Unicode characters that occupy multiple display columns in terminal output. This feature ensures that filenames containing international characters are displayed correctly without breaking the layout.

## What Are Wide Characters?

Wide characters are Unicode characters that take up 2 display columns in terminal output, as opposed to regular ASCII characters that take up 1 column. Examples include:

- **Japanese characters**: あいうえお, 日本語, ひらがな, カタカナ
- **Chinese characters**: 中文, 汉字, 繁體字
- **Korean characters**: 한글, 한국어
- **Full-width symbols**: ！＠＃＄％
- **Some emoji**: 📁📂📄 (depending on terminal support)

## Features

### Automatic Layout Correction

XeFM automatically detects and handles wide characters in:

- **File and directory names** in the main panes
- **Text content** in the built-in text viewer
- **Dialog input fields** for creating files and directories
- **Search results** and other text displays

### Proper Column Alignment

- File lists maintain proper column alignment regardless of character types
- Extension columns align correctly even with mixed character widths
- Cursor positioning works accurately with wide character filenames

### Terminal Compatibility

- Automatic detection of terminal Unicode capabilities
- Graceful fallback for terminals with limited Unicode support

## Configuration

Wide-character handling is **automatic** — XeFM measures each glyph's display width
and aligns columns accordingly, with no configuration required. There are no
`UNICODE_*` settings to tune.

## Supported Character Types

### Fully Supported

- **East Asian characters** (Chinese, Japanese, Korean)
- **Full-width punctuation and symbols**
- **Combining characters** (accents, diacritics)
- **Zero-width characters**

### Terminal-Dependent

- **Emoji and pictographs** (support varies by terminal)
- **Complex Unicode sequences** (may require modern terminals)

## Terminal Compatibility

### Recommended Terminals

These terminals provide excellent wide character support:

- **macOS**: iTerm2, Terminal.app
- **Linux**: GNOME Terminal, Konsole, Alacritty, Kitty
- **Windows**: Windows Terminal, ConEmu
- **Cross-platform**: Alacritty, Kitty

### Limited Support Terminals

These terminals may have limited wide character support:

- **Basic terminals**: xterm (older versions)
- **SSH sessions** to systems with limited locale support
- **Embedded terminals** in some IDEs

## Troubleshooting

### Display Issues

**Problem**: Filenames with Japanese characters appear misaligned or corrupted.

**Solutions**:
1. Check your terminal's Unicode support
2. Verify your locale settings include UTF-8 encoding
3. Ensure the terminal uses a font with good Unicode coverage

**Check locale settings**:
```bash
echo $LANG
echo $LC_ALL
locale
```

**Recommended locale settings**:
```bash
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

### Performance Issues

**Problem**: XeFM feels slow when displaying directories with many Unicode filenames.

**Solutions**:
1. Display-width calculations are already cached internally — there is nothing to tune
2. Very large directories are inherently slower to render; narrow the view with a filter

### Terminal Compatibility Issues

**Problem**: Wide characters don't display correctly in your terminal.

**Solutions**:
1. Update to a modern terminal application
2. Check your terminal's Unicode / font settings
3. Ensure the terminal uses a font with good Unicode coverage

### SSH and Remote Sessions

**Problem**: Wide characters work locally but not over SSH.

**Solutions**:
1. Ensure remote system has UTF-8 locale installed
2. Forward locale settings through SSH:
   ```bash
   ssh -o SendEnv=LANG,LC_ALL user@host
   ```
3. Set locale on remote system:
   ```bash
   export LANG=en_US.UTF-8
   export LC_ALL=en_US.UTF-8
   ```

## Testing Your Setup

### Quick Test

1. Create a test directory with wide character names:
   ```bash
   mkdir "テスト"
   mkdir "测试"
   mkdir "테스트"
   touch "日本語ファイル.txt"
   touch "中文文件.txt"
   ```

2. Navigate to the directory in XeFM
3. Check that:
   - Filenames display correctly
   - Columns are properly aligned
   - Cursor positioning works accurately
   - Text selection covers the entire filename

### Locale Test

Check if your system supports the required locales:
```bash
locale -a | grep -i utf
```

If UTF-8 locales are missing, install them:
```bash
# Ubuntu/Debian
sudo apt-get install locales
sudo locale-gen en_US.UTF-8

# CentOS/RHEL
sudo yum install glibc-locale-source glibc-langpack-en
```

## Known Limitations

### Terminal-Specific Issues

- Some terminals may not support all Unicode characters
- Emoji support varies significantly between terminals
- Complex Unicode sequences may not render correctly in all environments

### Performance Considerations

- Very large directories with many Unicode filenames may be slower to display
- Display-width caching helps but uses additional memory

### Font Requirements

- Terminal must use a font that includes the required Unicode characters
- Monospace fonts work best for proper alignment
- Some fonts may not have consistent width for wide characters

## Getting Help

If you encounter issues with wide character support:

1. Check the troubleshooting section above
2. Verify your terminal and locale settings
3. Test with a known Unicode-capable terminal
4. Check XeFM's log output for Unicode-related warnings

For additional support, include the following information when reporting issues:

- Terminal application and version
- Operating system and version
- Locale settings (`locale` command output)
- Example filenames that cause problems
- Screenshots if display issues are visual