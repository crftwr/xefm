"""
Test archive sorting support - verifies all sort modes work with archive entries

Run with: python -m pytest test/test_archive_sorting.py -v
"""

import tempfile
import zipfile
import tarfile
import time
from pathlib import Path as PathlibPath
from xefm.path import Path
from xefm.file_list_manager import FileListManager
from xefm.config import get_config


def create_test_archive(archive_path, archive_type='zip'):
    """
    Create a test archive with various files and directories for sorting tests.
    
    Creates:
    - Directories: dir_a, dir_b, dir_z
    - Files with different extensions: file1.txt, file2.py, file3.md, file4.log
    - Files with different sizes
    - Files with different modification times
    """
    if archive_type == 'zip':
        with zipfile.ZipFile(archive_path, 'w') as zf:
            # Add directories
            zf.writestr('dir_a/', '')
            zf.writestr('dir_b/', '')
            zf.writestr('dir_z/', '')
            
            # Add files with different sizes and extensions
            # Small file
            info = zipfile.ZipInfo('file1.txt')
            info.date_time = (2024, 1, 1, 10, 0, 0)
            zf.writestr(info, 'Small content')
            
            # Medium file
            info = zipfile.ZipInfo('file2.py')
            info.date_time = (2024, 6, 15, 14, 30, 0)
            zf.writestr(info, 'Medium content ' * 100)
            
            # Large file
            info = zipfile.ZipInfo('file3.md')
            info.date_time = (2024, 12, 31, 23, 59, 0)
            zf.writestr(info, 'Large content ' * 1000)
            
            # Another file
            info = zipfile.ZipInfo('file4.log')
            info.date_time = (2024, 3, 15, 8, 0, 0)
            zf.writestr(info, 'Log content')
            
            # Files in subdirectory
            zf.writestr('dir_a/subfile1.txt', 'Sub content 1')
            zf.writestr('dir_a/subfile2.py', 'Sub content 2')
    
    elif archive_type == 'tar':
        with tarfile.open(archive_path, 'w') as tf:
            # Add directories
            for dirname in ['dir_a', 'dir_b', 'dir_z']:
                info = tarfile.TarInfo(name=dirname)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = time.time()
                tf.addfile(info)
            
            # Add files with different sizes
            import io
            
            # Small file
            content = b'Small content'
            info = tarfile.TarInfo(name='file1.txt')
            info.size = len(content)
            info.mtime = time.mktime((2024, 1, 1, 10, 0, 0, 0, 0, 0))
            tf.addfile(info, io.BytesIO(content))
            
            # Medium file
            content = b'Medium content ' * 100
            info = tarfile.TarInfo(name='file2.py')
            info.size = len(content)
            info.mtime = time.mktime((2024, 6, 15, 14, 30, 0, 0, 0, 0))
            tf.addfile(info, io.BytesIO(content))
            
            # Large file
            content = b'Large content ' * 1000
            info = tarfile.TarInfo(name='file3.md')
            info.size = len(content)
            info.mtime = time.mktime((2024, 12, 31, 23, 59, 0, 0, 0, 0))
            tf.addfile(info, io.BytesIO(content))
            
            # Another file
            content = b'Log content'
            info = tarfile.TarInfo(name='file4.log')
            info.size = len(content)
            info.mtime = time.mktime((2024, 3, 15, 8, 0, 0, 0, 0, 0))
            tf.addfile(info, io.BytesIO(content))


def test_archive_sort_by_name():
    """Test sorting archive entries by name"""
    print("\n=== Test: Sort by Name ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        print(f"Found {len(entries)} entries in archive")
        
        # Sort by name
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'name', reverse=False)
        
        # Verify directories come first
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        print(f"Directories: {len(dirs)}, Files: {len(files)}")
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        # Verify directory names are sorted
        dir_names = [d.name for d in dirs]
        print(f"Directory names: {dir_names}")
        assert dir_names == ['dir_a', 'dir_b', 'dir_z'], f"Directories not sorted correctly: {dir_names}"
        
        # Verify file names are sorted
        file_names = [f.name for f in files]
        print(f"File names: {file_names}")
        assert file_names == ['file1.txt', 'file2.py', 'file3.md', 'file4.log'], f"Files not sorted correctly: {file_names}"
        
        print("✓ Sort by name works correctly")


def test_archive_sort_by_size():
    """Test sorting archive entries by size"""
    print("\n=== Test: Sort by Size ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        
        # Sort by size
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'size', reverse=False)
        
        # Verify directories come first (size 0)
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        # Verify files are sorted by size (smallest to largest)
        file_sizes = [f.stat().st_size for f in files]
        print(f"File sizes: {file_sizes}")
        assert file_sizes == sorted(file_sizes), f"Files not sorted by size: {file_sizes}"
        
        # Test reverse sort
        sorted_entries_rev = file_ops.sort_entries(entries, 'size', reverse=True)
        files_rev = [e for e in sorted_entries_rev if e.is_file()]
        file_sizes_rev = [f.stat().st_size for f in files_rev]
        print(f"File sizes (reverse): {file_sizes_rev}")
        assert file_sizes_rev == sorted(file_sizes_rev, reverse=True), f"Files not sorted by size (reverse): {file_sizes_rev}"
        
        print("✓ Sort by size works correctly")


def test_archive_sort_by_date():
    """Test sorting archive entries by modification date"""
    print("\n=== Test: Sort by Date ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        
        # Sort by date
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'date', reverse=False)
        
        # Verify directories come first
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        # Verify files are sorted by date (oldest to newest)
        file_dates = [f.stat().st_mtime for f in files]
        print(f"File dates: {file_dates}")
        assert file_dates == sorted(file_dates), f"Files not sorted by date: {file_dates}"
        
        # Verify expected order: file1.txt (Jan), file4.log (Mar), file2.py (Jun), file3.md (Dec)
        file_names = [f.name for f in files]
        print(f"File names by date: {file_names}")
        assert file_names == ['file1.txt', 'file4.log', 'file2.py', 'file3.md'], f"Files not in expected date order: {file_names}"
        
        print("✓ Sort by date works correctly")


def test_archive_sort_by_extension():
    """Test sorting archive entries by extension"""
    print("\n=== Test: Sort by Extension ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        
        # Sort by extension
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'ext', reverse=False)
        
        # Verify directories come first (no extension)
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        # Verify files are sorted by extension
        file_exts = [f.suffix.lower() for f in files]
        print(f"File extensions: {file_exts}")
        assert file_exts == sorted(file_exts), f"Files not sorted by extension: {file_exts}"
        
        # Expected order: .log, .md, .py, .txt
        expected_exts = ['.log', '.md', '.py', '.txt']
        assert file_exts == expected_exts, f"Extensions not in expected order: {file_exts}"
        
        print("✓ Sort by extension works correctly")


def test_archive_sort_by_type():
    """Test sorting archive entries by type"""
    print("\n=== Test: Sort by Type ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        
        # Sort by type (same as extension for files)
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'type', reverse=False)
        
        # Verify directories come first
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        print("✓ Sort by type works correctly")


def test_archive_directories_first():
    """Test that directories always come first regardless of sort mode"""
    print("\n=== Test: Directories First ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test archive
        archive_path = PathlibPath(tmpdir) / 'test.zip'
        create_test_archive(archive_path, 'zip')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        
        config = get_config()
        file_ops = FileListManager(config)
        
        # Test all sort modes
        for sort_mode in ['name', 'size', 'date', 'ext', 'type']:
            sorted_entries = file_ops.sort_entries(entries, sort_mode, reverse=False)
            
            # Find first file index
            first_file_idx = None
            for i, entry in enumerate(sorted_entries):
                if entry.is_file():
                    first_file_idx = i
                    break
            
            # Verify all entries before first file are directories
            if first_file_idx is not None:
                for i in range(first_file_idx):
                    assert sorted_entries[i].is_dir(), f"Entry at index {i} is not a directory in {sort_mode} sort"
            
            print(f"  ✓ Directories first in {sort_mode} sort")
        
        print("✓ Directories always come first")


def test_archive_sort_with_tar():
    """Test sorting works with tar archives"""
    print("\n=== Test: Sort with TAR Archive ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test tar archive
        archive_path = PathlibPath(tmpdir) / 'test.tar'
        create_test_archive(archive_path, 'tar')
        
        # Create archive path
        archive_uri = f"archive://{archive_path}#"
        archive_root = Path(archive_uri)
        
        # Get entries
        entries = list(archive_root.iterdir())
        print(f"Found {len(entries)} entries in tar archive")
        
        # Sort by name
        config = get_config()
        file_ops = FileListManager(config)
        sorted_entries = file_ops.sort_entries(entries, 'name', reverse=False)
        
        # Verify directories come first
        dirs = [e for e in sorted_entries if e.is_dir()]
        files = [e for e in sorted_entries if e.is_file()]
        
        print(f"Directories: {len(dirs)}, Files: {len(files)}")
        assert len(dirs) == 3, f"Expected 3 directories, got {len(dirs)}"
        assert len(files) == 4, f"Expected 4 files, got {len(files)}"
        
        # Verify sorting works
        dir_names = [d.name for d in dirs]
        print(f"Directory names: {dir_names}")
        assert dir_names == ['dir_a', 'dir_b', 'dir_z'], f"Directories not sorted correctly: {dir_names}"
        
        print("✓ Sort works with tar archives")


def run_all_tests():
    """Run all archive sorting tests"""
    print("=" * 60)
    print("Archive Sorting Tests")
    print("=" * 60)
    
    try:
        test_archive_sort_by_name()
        test_archive_sort_by_size()
        test_archive_sort_by_date()
        test_archive_sort_by_extension()
        test_archive_sort_by_type()
        test_archive_directories_first()
        test_archive_sort_with_tar()
        
        print("\n" + "=" * 60)
        print("✓ All archive sorting tests passed!")
        print("=" * 60)
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
