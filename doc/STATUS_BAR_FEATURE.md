# XeFM Text Viewer Status Bar

## Overview
The XeFM text viewer includes a comprehensive status bar at the bottom of the screen that provides real-time information about the current file and viewer state.

## Status Bar Layout

```
Line 45/127 (35%) | 2.3K                           PY | NUM | SYNTAX
└─── Position Info ───┘ └─ File Size ─┘             └──── File Type & Options ────┘
```

## Information Displayed

### Left Side: Position & File Info
- **Current Line**: Shows current line number (1-based)
- **Total Lines**: Total number of lines in the file
- **Scroll Percentage**: How far through the file you've scrolled (0-100%)
- **Column Position**: When horizontally scrolled, shows current column
- **File Size**: Displays file size in appropriate units (B, K, M, G)

### Archive Creation Progress
When creating archives, the status bar displays real-time progress:
- **Format**: `Creating archive... 45/120 (37%) - filename.txt`
- **File Counter**: Shows processed/total files
- **Percentage**: Completion percentage
- **Current File**: Name of file being processed (truncated if too long)

### Right Side: File Type & Active Options
- **File Format**: File extension in uppercase (PY, JSON, MD, etc.)
- **NUM**: Displayed when line numbers are enabled
- **WRAP**: Displayed when line wrapping is enabled  
- **SYNTAX**: Displayed when syntax highlighting is active

## Examples

### Python File with Line Numbers and Syntax Highlighting
```
Line 1/50 (2%) | 1.2K                               PY | NUM | SYNTAX
```

### JSON File, Scrolled to Middle, with Horizontal Scroll
```
Line 25/50 (50%) | Col 15 | 856B                    JSON | NUM | SYNTAX
```

### Text File with Line Wrapping, No Syntax Highlighting
```
Line 10/20 (50%) | 3.4K                             TXT | NUM | WRAP
```

### Large Markdown File at End
```
Line 500/500 (100%) | 45.2K                         MD | NUM | SYNTAX
```

### Archive Creation in Progress
```
Creating archive... 45/120 (37%) - long_filename_that_gets_truncated.txt
```

## Dynamic Updates
The status bar updates in real-time as you:
- **Scroll vertically**: Line number and percentage change
- **Scroll horizontally**: Column position appears/updates
- **Toggle options**: NUM, WRAP, SYNTAX indicators appear/disappear
- **Switch files**: All information updates for the new file

## Benefits

### ✅ Navigation Awareness
- **Know your position** in large files instantly
- **Track progress** when reading through documents
- **Understand file structure** with line count information

### ✅ File Information
- **Quick file size reference** without leaving the viewer
- **File type confirmation** shows detected format
- **Encoding awareness** (UTF-8 assumed for text files)

### ✅ Option Status
- **Visual confirmation** of active settings
- **No guessing** about current viewer configuration
- **Consistent feedback** for all toggle operations

## Technical Implementation

### Efficient Updates
- **Calculated on demand** during each screen refresh
- **Minimal performance impact** with cached file information
- **Responsive display** that adapts to terminal width

### Robust Information
- **Safe file size calculation** with error handling
- **Accurate position tracking** even with large files
- **Proper percentage calculation** avoiding division by zero

### Terminal Compatibility
- **Handles narrow terminals** by truncating information gracefully
- **Right-aligned layout** that adapts to available space

## Integration with XeFM
The status bar uses the same color scheme and design language as the main XeFM interface, providing a cohesive user experience throughout the file management workflow.

---

The status bar transforms the text viewer from a simple file display into an informative, professional text editing environment that keeps users oriented and informed while browsing code, configuration files, and documentation.