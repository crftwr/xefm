"""
Integration test for archive sorting - verifies sorting works in FileManager context

Run with: python -m pytest test/test_archive_sorting_integration.py -v
"""

import tempfile
import zipfile
from pathlib import Path as PathlibPath
from xefm.path import Path
from xefm.config import get_config


def create_test_archive(archive_path):
    """Create a test archive with mixed content"""
    with zipfile.ZipFile(archive_path, 'w') as zf:
        # Add directories
        zf.writestr('aaa_dir/', '')
        zf.writestr('zzz_dir/', '')
        zf.writestr('mmm_dir/', '')
        
        # Add files with different characteristics
        # Large file (newest)
        info = zipfile.ZipInfo('zzz_large.txt')
        info.date_time = (2024, 12, 31, 23, 59, 0)
        zf.writestr(info, 'X' * 10000)
        
        # Small file (oldest)
        info = zipfile.ZipInfo('aaa_small.txt')
        info.date_time = (2023, 1, 1, 0, 0, 0)
        zf.writestr(info, 'A')
        
        # Medium file (middle date)
        info = zipfile.ZipInfo('mmm_medium.txt')
        info.date_time = (2023, 6, 15, 12, 0, 0)
        zf.writestr(info, 'M' * 1000)


def test_pane_sorting_with_archives():
    """Test that pane data structure works correctly with archive sorting"""
    print("\n=== Integration Test: Pane Sorting with Archives ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path)
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Simulate pane data structure
        pane_data = {
            'path': archive_root,
            'files': list(archive_root.iterdir()),
            'selected_index': 0,
            'scroll_offset': 0,
            'selected_files': set(),
            'sort_mode': 'name',
            'sort_reverse': False,
            'filter_pattern': None
        }
        
        print(f"Created pane with {len(pane_data['files'])} archive entries")
        
        # Test sorting with different modes
        from xefm.file_list_manager import FileListManager
        config = get_config()
        file_ops = FileListManager(config)
        
        # Test name sort
        pane_data['sort_mode'] = 'name'
        pane_data['sort_reverse'] = False
        sorted_files = file_ops.sort_entries(
            pane_data['files'],
            pane_data['sort_mode'],
            pane_data['sort_reverse']
        )
        pane_data['files'] = sorted_files
        
        # Verify directories come first
        first_three = pane_data['files'][:3]
        assert all(f.is_dir() for f in first_three), "First three entries should be directories"
        
        # Verify directory names are sorted
        dir_names = [f.name for f in first_three]
        assert dir_names == ['aaa_dir', 'mmm_dir', 'zzz_dir'], f"Directories not sorted: {dir_names}"
        
        print("✓ Name sort works correctly")
        
        # Test size sort
        pane_data['sort_mode'] = 'size'
        pane_data['sort_reverse'] = False
        sorted_files = file_ops.sort_entries(
            pane_data['files'],
            pane_data['sort_mode'],
            pane_data['sort_reverse']
        )
        pane_data['files'] = sorted_files
        
        # Verify directories still come first
        first_three = pane_data['files'][:3]
        assert all(f.is_dir() for f in first_three), "Directories should still be first"
        
        # Verify files are sorted by size
        files = [f for f in pane_data['files'] if f.is_file()]
        file_sizes = [f.stat().st_size for f in files]
        assert file_sizes == sorted(file_sizes), f"Files not sorted by size: {file_sizes}"
        
        print("✓ Size sort works correctly")
        
        # Test date sort
        pane_data['sort_mode'] = 'date'
        pane_data['sort_reverse'] = False
        sorted_files = file_ops.sort_entries(
            pane_data['files'],
            pane_data['sort_mode'],
            pane_data['sort_reverse']
        )
        pane_data['files'] = sorted_files
        
        # Verify directories still come first
        first_three = pane_data['files'][:3]
        assert all(f.is_dir() for f in first_three), "Directories should still be first"
        
        # Verify files are sorted by date
        files = [f for f in pane_data['files'] if f.is_file()]
        file_dates = [f.stat().st_mtime for f in files]
        assert file_dates == sorted(file_dates), f"Files not sorted by date: {file_dates}"
        
        # Verify expected order: aaa_small (oldest), mmm_medium, zzz_large (newest)
        file_names = [f.name for f in files]
        assert file_names == ['aaa_small.txt', 'mmm_medium.txt', 'zzz_large.txt'], f"Files not in expected date order: {file_names}"
        
        print("✓ Date sort works correctly")
        
        # Test reverse sort
        pane_data['sort_mode'] = 'size'
        pane_data['sort_reverse'] = True
        sorted_files = file_ops.sort_entries(
            pane_data['files'],
            pane_data['sort_mode'],
            pane_data['sort_reverse']
        )
        pane_data['files'] = sorted_files
        
        # Verify directories still come first even in reverse
        first_three = pane_data['files'][:3]
        assert all(f.is_dir() for f in first_three), "Directories should be first even in reverse"
        
        # Verify files are sorted by size in reverse
        files = [f for f in pane_data['files'] if f.is_file()]
        file_sizes = [f.stat().st_size for f in files]
        assert file_sizes == sorted(file_sizes, reverse=True), f"Files not sorted by size (reverse): {file_sizes}"
        
        print("✓ Reverse sort works correctly")
        
        print("\n✓ All integration tests passed!")


def test_sort_description():
    """Test that sort description works with archive panes"""
    print("\n=== Integration Test: Sort Description ===")
    
    from xefm.file_list_manager import FileListManager
    config = get_config()
    file_ops = FileListManager(config)
    
    # Test different sort modes
    test_cases = [
        ({'sort_mode': 'name', 'sort_reverse': False}, 'Filename ↑'),
        ({'sort_mode': 'name', 'sort_reverse': True}, 'Filename ↓'),
        ({'sort_mode': 'size', 'sort_reverse': False}, 'Size ↑'),
        ({'sort_mode': 'size', 'sort_reverse': True}, 'Size ↓'),
        ({'sort_mode': 'date', 'sort_reverse': False}, 'Timestamp ↑'),
        ({'sort_mode': 'date', 'sort_reverse': True}, 'Timestamp ↓'),
        ({'sort_mode': 'ext', 'sort_reverse': False}, 'Extension ↑'),
        ({'sort_mode': 'ext', 'sort_reverse': True}, 'Extension ↓'),
        ({'sort_mode': 'type', 'sort_reverse': False}, 'Extension ↑'),
    ]
    
    for pane_data, expected_desc in test_cases:
        desc = file_ops.get_sort_description(pane_data)
        assert desc == expected_desc, f"Expected '{expected_desc}', got '{desc}'"
        print(f"  ✓ {pane_data['sort_mode']} (reverse={pane_data['sort_reverse']}) -> '{desc}'")
    
    print("\n✓ Sort description test passed!")


def run_all_tests():
    """Run all integration tests"""
    print("=" * 70)
    print("Archive Sorting Integration Tests")
    print("=" * 70)
    
    try:
        test_pane_sorting_with_archives()
        test_sort_description()
        
        print("\n" + "=" * 70)
        print("✓ All integration tests passed!")
        print("=" * 70)
        return True
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
