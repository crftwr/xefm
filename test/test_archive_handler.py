"""
Test suite for ArchiveHandler classes

Run with: python -m pytest test/test_archive_handler.py -v
"""

import tempfile
import zipfile
import tarfile
from pathlib import Path as PathlibPath
import pytest

# Add the repo root to path
from xefm.archive import (
    ArchiveHandler, ZipHandler, TarHandler, ArchiveEntry,
    ArchiveError, ArchiveFormatError, ArchiveCorruptedError,
    ArchiveExtractionError, ArchiveNavigationError
)
from xefm.path import Path


class TestZipHandler:
    """Test ZipHandler functionality"""
    
    def setup_method(self):
        """Create a test ZIP archive"""
        self.temp_dir = tempfile.mkdtemp(prefix='xefm_test_')
        self.temp_path = PathlibPath(self.temp_dir)
        
        # Create test ZIP archive
        self.zip_path = self.temp_path / 'test.zip'
        with zipfile.ZipFile(str(self.zip_path), 'w') as zf:
            # Add files at root
            zf.writestr('file1.txt', b'Content of file 1')
            zf.writestr('file2.txt', b'Content of file 2')
            
            # Add directory with files
            zf.writestr('dir1/', b'')
            zf.writestr('dir1/file3.txt', b'Content of file 3')
            zf.writestr('dir1/file4.txt', b'Content of file 4')
            
            # Add nested directory
            zf.writestr('dir1/subdir/', b'')
            zf.writestr('dir1/subdir/file5.txt', b'Content of file 5')
    
    def teardown_method(self):
        """Clean up test files"""
        import shutil
        if self.temp_path.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_open_and_close(self):
        """Test opening and closing ZIP archive"""
        handler = ZipHandler(Path(self.zip_path))
        
        assert not handler._is_open
        handler.open()
        assert handler._is_open
        handler.close()
        assert not handler._is_open
    
    def test_context_manager(self):
        """Test using handler as context manager"""
        with ZipHandler(Path(self.zip_path)) as handler:
            assert handler._is_open
        assert not handler._is_open
    
    def test_list_root_entries(self):
        """Test listing entries at root"""
        with ZipHandler(Path(self.zip_path)) as handler:
            entries = handler.list_entries('')
            
            # Should have 3 items at root: file1.txt, file2.txt, dir1/
            assert len(entries) == 3
            
            names = {entry.name for entry in entries}
            assert 'file1.txt' in names
            assert 'file2.txt' in names
            assert 'dir1' in names
    
    def test_list_directory_entries(self):
        """Test listing entries in a directory"""
        with ZipHandler(Path(self.zip_path)) as handler:
            entries = handler.list_entries('dir1')
            
            # Should have 3 items: file3.txt, file4.txt, subdir/
            assert len(entries) == 3
            
            names = {entry.name for entry in entries}
            assert 'file3.txt' in names
            assert 'file4.txt' in names
            assert 'subdir' in names
    
    def test_list_nested_directory(self):
        """Test listing entries in nested directory"""
        with ZipHandler(Path(self.zip_path)) as handler:
            entries = handler.list_entries('dir1/subdir')
            
            # Should have 1 item: file5.txt
            assert len(entries) == 1
            assert entries[0].name == 'file5.txt'
    
    def test_get_entry_info(self):
        """Test getting entry information"""
        with ZipHandler(Path(self.zip_path)) as handler:
            # Get file entry
            entry = handler.get_entry_info('file1.txt')
            assert entry is not None
            assert entry.name == 'file1.txt'
            assert not entry.is_dir
            assert entry.size > 0
            
            # Get directory entry
            entry = handler.get_entry_info('dir1')
            assert entry is not None
            assert entry.name == 'dir1'
            assert entry.is_dir
            
            # Get non-existent entry
            entry = handler.get_entry_info('nonexistent.txt')
            assert entry is None
    
    def test_extract_to_bytes(self):
        """Test extracting file to bytes"""
        with ZipHandler(Path(self.zip_path)) as handler:
            data = handler.extract_to_bytes('file1.txt')
            assert data == b'Content of file 1'
            
            data = handler.extract_to_bytes('dir1/file3.txt')
            assert data == b'Content of file 3'
    
    def test_extract_to_file(self):
        """Test extracting file to filesystem"""
        with ZipHandler(Path(self.zip_path)) as handler:
            target = self.temp_path / 'extracted.txt'
            handler.extract_to_file('file1.txt', Path(target))
            
            assert target.exists()
            assert target.read_bytes() == b'Content of file 1'
    
    def test_extract_directory_raises_error(self):
        """Test that extracting directory raises error"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(ArchiveExtractionError):
                handler.extract_to_bytes('dir1')
    
    def test_extract_nonexistent_raises_error(self):
        """Test that extracting non-existent file raises error"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(FileNotFoundError):
                handler.extract_to_bytes('nonexistent.txt')
    
    def test_list_nonexistent_path_raises_error(self):
        """Test that listing non-existent path raises error"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(ArchiveNavigationError):
                handler.list_entries('nonexistent_dir')


class TestTarHandler:
    """Test TarHandler functionality"""
    
    def setup_method(self):
        """Create test TAR archives"""
        self.temp_dir = tempfile.mkdtemp(prefix='xefm_test_')
        self.temp_path = PathlibPath(self.temp_dir)
        
        # Create test TAR archive
        self.tar_path = self.temp_path / 'test.tar'
        with tarfile.open(str(self.tar_path), 'w') as tf:
            # Add files at root
            info = tarfile.TarInfo('file1.txt')
            info.size = 17
            tf.addfile(info, fileobj=None if info.size == 0 else 
                      __import__('io').BytesIO(b'Content of file 1'))
            
            info = tarfile.TarInfo('file2.txt')
            info.size = 17
            tf.addfile(info, fileobj=__import__('io').BytesIO(b'Content of file 2'))
            
            # Add directory
            info = tarfile.TarInfo('dir1')
            info.type = tarfile.DIRTYPE
            tf.addfile(info)
            
            # Add files in directory
            info = tarfile.TarInfo('dir1/file3.txt')
            info.size = 17
            tf.addfile(info, fileobj=__import__('io').BytesIO(b'Content of file 3'))
        
        # Create compressed TAR archive
        self.tar_gz_path = self.temp_path / 'test.tar.gz'
        with tarfile.open(str(self.tar_gz_path), 'w:gz') as tf:
            info = tarfile.TarInfo('compressed.txt')
            info.size = 20
            tf.addfile(info, fileobj=__import__('io').BytesIO(b'Compressed content!!'))
    
    def teardown_method(self):
        """Clean up test files"""
        import shutil
        if self.temp_path.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_open_uncompressed_tar(self):
        """Test opening uncompressed TAR archive"""
        handler = TarHandler(Path(self.tar_path), compression=None)
        handler.open()
        assert handler._is_open
        handler.close()
    
    def test_open_compressed_tar(self):
        """Test opening compressed TAR archive"""
        handler = TarHandler(Path(self.tar_gz_path), compression='gz')
        handler.open()
        assert handler._is_open
        handler.close()
    
    def test_list_root_entries(self):
        """Test listing entries at root"""
        with TarHandler(Path(self.tar_path), compression=None) as handler:
            entries = handler.list_entries('')
            
            # Should have 3 items at root
            assert len(entries) == 3
            
            names = {entry.name for entry in entries}
            assert 'file1.txt' in names
            assert 'file2.txt' in names
            assert 'dir1' in names
    
    def test_list_directory_entries(self):
        """Test listing entries in a directory"""
        with TarHandler(Path(self.tar_path), compression=None) as handler:
            entries = handler.list_entries('dir1')
            
            # Should have 1 item
            assert len(entries) == 1
            assert entries[0].name == 'file3.txt'
    
    def test_get_entry_info(self):
        """Test getting entry information"""
        with TarHandler(Path(self.tar_path), compression=None) as handler:
            entry = handler.get_entry_info('file1.txt')
            assert entry is not None
            assert entry.name == 'file1.txt'
            assert not entry.is_dir
    
    def test_extract_to_bytes(self):
        """Test extracting file to bytes"""
        with TarHandler(Path(self.tar_path), compression=None) as handler:
            data = handler.extract_to_bytes('file1.txt')
            assert data == b'Content of file 1'
    
    def test_extract_compressed_to_bytes(self):
        """Test extracting from compressed archive"""
        with TarHandler(Path(self.tar_gz_path), compression='gz') as handler:
            data = handler.extract_to_bytes('compressed.txt')
            assert data == b'Compressed content!!'
    
    def test_extract_to_file(self):
        """Test extracting file to filesystem"""
        with TarHandler(Path(self.tar_path), compression=None) as handler:
            target = self.temp_path / 'extracted.txt'
            handler.extract_to_file('file1.txt', Path(target))
            
            assert target.exists()
            assert target.read_bytes() == b'Content of file 1'


class TestArchiveErrors:
    """Test error handling in archive handlers"""
    
    def setup_method(self):
        """Create test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix='xefm_test_')
        self.temp_path = PathlibPath(self.temp_dir)
    
    def teardown_method(self):
        """Clean up test files"""
        import shutil
        if self.temp_path.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_open_nonexistent_file(self):
        """Test opening non-existent archive"""
        handler = ZipHandler(Path(self.temp_path / 'nonexistent.zip'))
        with pytest.raises(FileNotFoundError):
            handler.open()
    
    def test_open_corrupted_zip(self):
        """Test opening corrupted ZIP archive"""
        # Create corrupted ZIP file
        corrupted_zip = self.temp_path / 'corrupted.zip'
        corrupted_zip.write_bytes(b'This is not a valid ZIP file')
        
        handler = ZipHandler(Path(corrupted_zip))
        with pytest.raises(ArchiveCorruptedError):
            handler.open()
    
    def test_open_corrupted_tar(self):
        """Test opening corrupted TAR archive"""
        # Create corrupted TAR file
        corrupted_tar = self.temp_path / 'corrupted.tar'
        corrupted_tar.write_bytes(b'This is not a valid TAR file')
        
        handler = TarHandler(Path(corrupted_tar), compression=None)
        with pytest.raises(ArchiveCorruptedError):
            handler.open()
