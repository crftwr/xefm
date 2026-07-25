"""
Test script for flexible date-time formatting in file list panes

Run with: python -m pytest test/test_date_format.py -v
"""

from datetime import datetime, timedelta
from pathlib import Path as StdPath

from xefm.file_list_manager import FileListManager
from xefm.const import DATE_FORMAT_FULL, DATE_FORMAT_SHORT


class MockConfig:
    """Mock configuration for testing"""
    def __init__(self, date_format='short'):
        self.DATE_FORMAT = date_format
        self.SHOW_HIDDEN_FILES = False


def test_date_formats():
    """Test both date format variations"""
    
    print("=" * 60)
    print("Testing Date Format Variations")
    print("=" * 60)
    
    # Create timestamps for testing
    now = datetime.now()
    today_morning = now.replace(hour=9, minute=30, second=15)
    yesterday = now - timedelta(days=1)
    last_week = now - timedelta(days=7)
    last_year = now - timedelta(days=365)
    
    timestamps = [
        ("Today (morning)", today_morning.timestamp()),
        ("Yesterday", yesterday.timestamp()),
        ("Last week", last_week.timestamp()),
        ("Last year", last_year.timestamp()),
    ]
    
    # Test each format
    formats = [
        (DATE_FORMAT_SHORT, "Short Format (YY-MM-DD HH:mm)"),
        (DATE_FORMAT_FULL, "Full Format (YYYY-MM-DD HH:mm:ss)"),
    ]
    
    for format_type, format_name in formats:
        print(f"\n{format_name}")
        print("-" * 60)
        
        config = MockConfig(date_format=format_type)
        file_ops = FileListManager(config)
        
        for label, timestamp in timestamps:
            formatted = file_ops._format_date(timestamp)
            dt = datetime.fromtimestamp(timestamp)
            print(f"  {label:20} -> {formatted:20} ({dt.strftime('%Y-%m-%d %H:%M:%S')})")
    
    print("\n" + "=" * 60)
    print("Format Specifications:")
    print("=" * 60)
    print("1. Short: YY-MM-DD HH:mm       (e.g., 24-12-17 09:30) - Default")
    print("2. Full:  YYYY-MM-DD HH:mm:ss  (e.g., 2024-12-17 09:30:15)")
    print("=" * 60)


def test_format_cycling():
    """Test cycling through date formats"""
    
    print("\n" + "=" * 60)
    print("Testing Format Cycling")
    print("=" * 60)
    
    formats = [DATE_FORMAT_SHORT, DATE_FORMAT_FULL]
    format_names = {
        DATE_FORMAT_FULL: "Full (YYYY-MM-DD HH:mm:ss)",
        DATE_FORMAT_SHORT: "Short (YY-MM-DD HH:mm)",
    }
    
    print("\nCycle order: Short <-> Full")
    print("-" * 60)
    
    current_idx = 0
    for i in range(6):  # Show three full cycles
        current_format = formats[current_idx]
        next_idx = (current_idx + 1) % len(formats)
        next_format = formats[next_idx]
        
        print(f"Step {i+1}: {format_names[current_format]:30} -> {format_names[next_format]}")
        current_idx = next_idx
    
    print("=" * 60)


def test_edge_cases():
    """Test edge cases for date formatting"""
    
    print("\n" + "=" * 60)
    print("Testing Edge Cases")
    print("=" * 60)
    
    now = datetime.now()
    
    # Test midnight
    midnight = now.replace(hour=0, minute=0, second=0)
    
    # Test with short format
    config_short = MockConfig(date_format=DATE_FORMAT_SHORT)
    file_ops_short = FileListManager(config_short)
    formatted_short = file_ops_short._format_date(midnight.timestamp())
    print(f"Midnight (short):   {formatted_short:20} (YY-MM-DD HH:mm)")
    
    # Test with full format
    config_full = MockConfig(date_format=DATE_FORMAT_FULL)
    file_ops_full = FileListManager(config_full)
    formatted_full = file_ops_full._format_date(midnight.timestamp())
    print(f"Midnight (full):    {formatted_full:20} (YYYY-MM-DD HH:mm:ss)")
    
    # Test noon
    noon = now.replace(hour=12, minute=0, second=0)
    formatted_short = file_ops_short._format_date(noon.timestamp())
    formatted_full = file_ops_full._format_date(noon.timestamp())
    print(f"Noon (short):       {formatted_short:20} (YY-MM-DD HH:mm)")
    print(f"Noon (full):        {formatted_full:20} (YYYY-MM-DD HH:mm:ss)")
    
    print("=" * 60)
