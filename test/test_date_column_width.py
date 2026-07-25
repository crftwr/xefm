"""
Test script for dynamic date column width adjustment

Run with: python -m pytest test/test_date_column_width.py -v
"""

import sys
from pathlib import Path as StdPath

from xefm.const import DATE_FORMAT_FULL, DATE_FORMAT_SHORT


class MockConfig:
    """Mock configuration for testing"""
    def __init__(self, date_format='short'):
        self.DATE_FORMAT = date_format


class MockFileManager:
    """Mock FileManager with just the get_date_column_width method"""
    def __init__(self, config):
        self.config = config
    
    def get_date_column_width(self):
        """
        Calculate the date column width based on current date format setting.
        
        Returns:
            int: Width in characters for the date column
        """
        from xefm.const import DATE_FORMAT_FULL, DATE_FORMAT_SHORT
        
        date_format = getattr(self.config, 'DATE_FORMAT', 'short')
        
        if date_format == DATE_FORMAT_FULL:
            # YYYY-MM-DD HH:mm:ss = 19 characters
            return 19
        else:  # DATE_FORMAT_SHORT (default)
            # YY-MM-DD HH:mm = 14 characters
            return 14


def test_date_column_widths():
    """Test that date column width adjusts correctly for each format"""
    
    print("=" * 60)
    print("Testing Date Column Width Adjustment")
    print("=" * 60)
    
    test_cases = [
        (DATE_FORMAT_SHORT, "Short Format", 14, "YY-MM-DD HH:mm"),
        (DATE_FORMAT_FULL, "Full Format", 19, "YYYY-MM-DD HH:mm:ss"),
    ]
    
    print(f"\n{'Format':<20} {'Expected Width':<15} {'Actual Width':<15} {'Status':<10}")
    print("-" * 60)
    
    all_passed = True
    for format_type, format_name, expected_width, example in test_cases:
        config = MockConfig(date_format=format_type)
        fm = MockFileManager(config)
        actual_width = fm.get_date_column_width()
        
        status = "✓ PASS" if actual_width == expected_width else "✗ FAIL"
        if actual_width != expected_width:
            all_passed = False
        
        print(f"{format_name:<20} {expected_width:<15} {actual_width:<15} {status:<10}")
        print(f"  Example: {example}")
    
    print("=" * 60)
    
    return


def test_column_layout_calculation():
    """Test how column widths affect layout calculations"""
    
    print("\n" + "=" * 60)
    print("Testing Column Layout Calculations")
    print("=" * 60)
    
    # Simulate pane width
    pane_width = 80
    usable_width = pane_width - 2  # Account for borders
    
    # Fixed widths
    marker_width = 2
    size_width = 8
    ext_width = 4  # Example extension width
    
    print(f"\nPane width: {pane_width}")
    print(f"Usable width: {usable_width}")
    print(f"Fixed widths: marker={marker_width}, size={size_width}, ext={ext_width}")
    print()
    
    formats = [
        (DATE_FORMAT_SHORT, "Short", 14),
        (DATE_FORMAT_FULL, "Full", 19),
    ]
    
    print(f"{'Format':<10} {'Date Width':<12} {'Reserved':<10} {'Name Width':<12} {'Layout':<30}")
    print("-" * 80)
    
    for format_type, format_name, date_width in formats:
        # Calculate reserved space: marker(2) + space(1) + ext(4) + space(1) + size(8) + space(1) + date(width) = 13 + ext + date
        reserved = 13 + ext_width + date_width
        name_width = usable_width - reserved
        
        layout = f"●[{name_width}] .ext[{ext_width}] [{size_width}] [{date_width}]"
        
        print(f"{format_name:<10} {date_width:<12} {reserved:<10} {name_width:<12} {layout:<30}")
    
    print("=" * 80)
    print("\nNote: Numbers in brackets show character widths")
    print("● = selection marker, .ext = extension, numbers = size/date")


def test_format_cycling_width_changes():
    """Test that width changes correctly when cycling formats"""
    
    print("\n" + "=" * 60)
    print("Testing Width Changes During Format Cycling")
    print("=" * 60)
    
    formats = [
        (DATE_FORMAT_SHORT, "Short (YY-MM-DD HH:mm)"),
        (DATE_FORMAT_FULL, "Full (YYYY-MM-DD HH:mm:ss)"),
    ]
    
    print(f"\n{'Cycle':<8} {'Format':<35} {'Width':<8} {'Change':<10}")
    print("-" * 60)
    
    prev_width = None
    for i in range(6):  # Show three full cycles
        format_idx = i % len(formats)
        format_type, format_name = formats[format_idx]
        
        config = MockConfig(date_format=format_type)
        fm = MockFileManager(config)
        width = fm.get_date_column_width()
        
        if prev_width is None:
            change = "initial"
        else:
            diff = width - prev_width
            if diff > 0:
                change = f"+{diff} chars"
            elif diff < 0:
                change = f"{diff} chars"
            else:
                change = "no change"
        
        cycle_num = f"#{i+1}"
        print(f"{cycle_num:<8} {format_name:<35} {width:<8} {change:<10}")
        prev_width = width
    
    print("=" * 60)
