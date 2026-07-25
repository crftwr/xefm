"""
Test script to verify help content generation

Run with: python -m pytest test/test_help_content.py -v
"""




# Add the repo root to Python path
from xefm.const import VERSION, GITHUB_URL

def generate_help_content():
    """Generate help content similar to the dialog"""
    help_lines = []
    
    # Title and version info
    help_lines.append(f"XeFM {VERSION} - Terminal File Manager")
    help_lines.append(f"GitHub: {GITHUB_URL}")
    help_lines.append("")
    
    # Navigation section
    help_lines.append("=== NAVIGATION ===")
    help_lines.append("↑↓ / j k         Navigate files")
    help_lines.append("←→ / h l         Switch panes / Navigate directories")
    help_lines.append("Tab              Switch between panes")
    help_lines.append("Enter            Open directory / View file")
    help_lines.append("Backspace        Go to parent directory")
    help_lines.append("Home / End       Go to first / last file")
    help_lines.append("Page Up/Down     Navigate by page")
    help_lines.append("")
    
    # File operations section
    help_lines.append("=== FILE OPERATIONS ===")
    help_lines.append("Space            Select/deselect file")

    help_lines.append("a                Select all files")
    help_lines.append("A                Select all items (files + directories)")
    help_lines.append("m / M            File operations menu (copy/move/delete/rename)")
    help_lines.append("v / V            View text file")
    help_lines.append("e / E            Edit file with text editor")
    help_lines.append("i / I            Show file details")
    help_lines.append("")
    
    # Search and sorting section
    help_lines.append("=== SEARCH & SORTING ===")
    help_lines.append("f / F            Search files")
    help_lines.append("s / S            Sort menu")
    help_lines.append("1                Quick sort by name (toggle reverse if already active)")
    help_lines.append("2                Quick sort by size (toggle reverse if already active)")
    help_lines.append("3                Quick sort by date (toggle reverse if already active)")
    help_lines.append("")
    
    # View options section
    help_lines.append("=== VIEW OPTIONS ===")
    help_lines.append(".                Toggle hidden files")
    help_lines.append("o                Sync current pane to other pane")
    help_lines.append("O                Sync other pane to current pane")
    help_lines.append("-                Reset pane split to 50/50")
    help_lines.append("[/]              Adjust pane boundary")
    help_lines.append("")
    
    # Log pane controls section
    help_lines.append("=== LOG PANE CONTROLS ===")
    help_lines.append("{                Make log pane larger")
    help_lines.append("}                Make log pane smaller")
    help_lines.append("_                Reset log pane height")
    help_lines.append("Shift+Up         Scroll log up (toward older messages)")
    help_lines.append("Shift+Down       Scroll log down (toward newer messages)")
    help_lines.append("Shift+Left       Fast scroll up (toward older messages)")
    help_lines.append("Shift+Right      Fast scroll down (toward newer messages)")
    help_lines.append("l                Scroll log up (alternative)")
    help_lines.append("L                Scroll log down (alternative)")
    help_lines.append("")
    
    # General controls section
    help_lines.append("=== GENERAL ===")
    help_lines.append("? / h            Show this help")
    help_lines.append("q / Q            Quit XeFM")
    help_lines.append("ESC              Cancel current operation")
    help_lines.append("")
    
    # Configuration info
    help_lines.append("=== CONFIGURATION ===")
    help_lines.append("Configuration file: _config.py")
    help_lines.append("Customize key bindings, colors, and behavior")
    help_lines.append("See CONFIGURATION_SYSTEM.md for details")
    help_lines.append("")
    
    # Tips section
    help_lines.append("=== TIPS ===")
    help_lines.append("• Use Space to select/deselect files for batch operations")
    help_lines.append("• Search supports multiple patterns separated by spaces")
    help_lines.append("• Log pane shows operation results and system messages")
    help_lines.append("• File details (i) shows comprehensive file information")
    help_lines.append("• Text viewer (v) supports syntax highlighting")
    
    return help_lines
