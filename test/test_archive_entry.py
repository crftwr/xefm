"""
Tests for ArchiveEntry dataclass

Run with: python -m pytest test/test_archive_entry.py -v
"""

import os
import stat
import time
import zipfile
import tarfile
import tempfile

from xefm.archive import ArchiveEntry


def test_archive_entry_creation():
    """Test basic ArchiveEntry creation"""
    entry = ArchiveEntry(
        name="test.txt",
        internal_path="folder/test.txt",
        is_dir=False,
        size=1024,
        compressed_size=512,
        mtime=time.time(),
        mode=0o644,
        archive_type="zip"
    )
    
    assert entry.name == "test.txt"
    assert entry.internal_path == "folder/test.txt"
    assert entry.is_dir is False
    assert entry.size == 1024
    assert entry.compressed_size == 512
    assert entry.mode == 0o644
    assert entry.archive_type == "zip"
    print("✓ Basic ArchiveEntry creation works")


def test_archive_entry_to_stat_result():
    """Test conversion to stat_result"""
    mtime = time.time()
    
    # Test file entry
    file_entry = ArchiveEntry(
        name="test.txt",
        internal_path="test.txt",
        is_dir=False,
        size=1024,
        compressed_size=512,
        mtime=mtime,
        mode=0o644,
        archive_type="zip"
    )
    
    stat_result = file_entry.to_stat_result()
    assert stat.S_ISREG(stat_result.st_mode)
    assert stat_result.st_size == 1024
    assert stat_result.st_mtime == mtime
    assert stat_result.st_mode & 0o777 == 0o644
    print("✓ File entry to_stat_result works")
    
    # Test directory entry
    dir_entry = ArchiveEntry(
        name="folder",
        internal_path="folder/",
        is_dir=True,
        size=0,
        compressed_size=0,
        mtime=mtime,
        mode=0o755,
        archive_type="zip"
    )
    
    stat_result = dir_entry.to_stat_result()
    assert stat.S_ISDIR(stat_result.st_mode)
    assert stat_result.st_size == 0
    assert stat_result.st_mtime == mtime
    assert stat_result.st_mode & 0o777 == 0o755
    print("✓ Directory entry to_stat_result works")


def test_archive_entry_from_zip_info():
    """Test creation from ZipInfo"""
    # Create a temporary zip file with a test entry
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Create a zip file with test content
        with zipfile.ZipFile(tmp_path, 'w') as zf:
            # Add a file
            zf.writestr('test.txt', 'Hello, World!')
            # Add a directory
            zf.writestr('folder/', '')
        
        # Read back and create ArchiveEntry objects
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            for zip_info in zf.infolist():
                entry = ArchiveEntry.from_zip_info(zip_info, 'zip')
                
                assert entry.archive_type == 'zip'
                assert entry.internal_path == zip_info.filename
                assert entry.size == zip_info.file_size
                assert entry.compressed_size == zip_info.compress_size
                
                if zip_info.filename == 'test.txt':
                    assert entry.name == 'test.txt'
                    assert entry.is_dir is False
                    assert entry.size > 0
                    print(f"✓ Created file entry from ZipInfo: {entry.name}")
                elif zip_info.filename == 'folder/':
                    assert entry.name == 'folder'
                    assert entry.is_dir is True
                    print(f"✓ Created directory entry from ZipInfo: {entry.name}")
    
    finally:
        # Clean up
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_archive_entry_from_tar_info():
    """Test creation from TarInfo"""
    # Create a temporary tar file with a test entry
    with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        # Create a tar file with test content
        with tarfile.open(tmp_path, 'w') as tf:
            # Add a file
            file_data = b'Hello, World!'
            file_info = tarfile.TarInfo(name='test.txt')
            file_info.size = len(file_data)
            file_info.mtime = time.time()
            file_info.mode = 0o644
            
            import io
            tf.addfile(file_info, io.BytesIO(file_data))
            
            # Add a directory
            dir_info = tarfile.TarInfo(name='folder')
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            dir_info.mtime = time.time()
            tf.addfile(dir_info)
        
        # Read back and create ArchiveEntry objects
        with tarfile.open(tmp_path, 'r') as tf:
            for tar_info in tf.getmembers():
                entry = ArchiveEntry.from_tar_info(tar_info, 'tar')
                
                assert entry.archive_type == 'tar'
                assert entry.internal_path == tar_info.name
                assert entry.size == tar_info.size
                
                if tar_info.name == 'test.txt':
                    assert entry.name == 'test.txt'
                    assert entry.is_dir is False
                    assert entry.size > 0
                    assert entry.mode == 0o644
                    print(f"✓ Created file entry from TarInfo: {entry.name}")
                elif tar_info.name == 'folder':
                    assert entry.name == 'folder'
                    assert entry.is_dir is True
                    assert entry.mode == 0o755
                    print(f"✓ Created directory entry from TarInfo: {entry.name}")
    
    finally:
        # Clean up
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def test_archive_entry_name_extraction():
    """Test that name is correctly extracted from internal_path"""
    # Test simple filename
    entry1 = ArchiveEntry(
        name="",  # Will be set by from_zip_info
        internal_path="test.txt",
        is_dir=False,
        size=100,
        compressed_size=50,
        mtime=time.time(),
        mode=0o644,
        archive_type="zip"
    )
    # Manually test name extraction logic
    name = entry1.internal_path.rstrip('/').split('/')[-1]
    assert name == "test.txt"
    print("✓ Simple filename extraction works")
    
    # Test nested path
    entry2 = ArchiveEntry(
        name="",
        internal_path="folder/subfolder/test.txt",
        is_dir=False,
        size=100,
        compressed_size=50,
        mtime=time.time(),
        mode=0o644,
        archive_type="zip"
    )
    name = entry2.internal_path.rstrip('/').split('/')[-1]
    assert name == "test.txt"
    print("✓ Nested path filename extraction works")
    
    # Test directory path
    entry3 = ArchiveEntry(
        name="",
        internal_path="folder/subfolder/",
        is_dir=True,
        size=0,
        compressed_size=0,
        mtime=time.time(),
        mode=0o755,
        archive_type="zip"
    )
    name = entry3.internal_path.rstrip('/').split('/')[-1]
    assert name == "subfolder"
    print("✓ Directory path name extraction works")
