"""
Test comprehensive error handling for archive virtual directory operations.

This test file validates that all archive operations handle errors gracefully
with user-friendly error messages and proper logging.

Run with: python -m pytest test/test_archive_error_handling.py -v
"""

import pytest
import tempfile
import os
import zipfile
import tarfile
from pathlib import Path as PathlibPath

from xefm.archive import (
    ArchiveError, ArchiveFormatError, ArchiveCorruptedError,
    ArchiveExtractionError, ArchiveNavigationError,
    ArchivePermissionError, ArchiveDiskSpaceError,
    ZipHandler, TarHandler, ArchiveCache, ArchivePathImpl
)
from xefm.path import Path


class TestArchiveErrorMessages:
    """Test that archive errors have user-friendly messages"""
    
    def test_archive_error_has_user_message(self):
        """Test that ArchiveError supports user-friendly messages"""
        error = ArchiveError("Technical message", "User-friendly message")
        assert str(error) == "Technical message"
        assert error.user_message == "User-friendly message"
    
    def test_archive_error_defaults_to_technical_message(self):
        """Test that ArchiveError defaults user message to technical message"""
        error = ArchiveError("Technical message")
        assert str(error) == "Technical message"
        assert error.user_message == "Technical message"


class TestCorruptArchiveHandling:
    """Test handling of corrupted archives"""
    
    def test_corrupted_zip_raises_appropriate_error(self):
        """Test that corrupted ZIP files raise ArchiveCorruptedError"""
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
            # Write invalid ZIP data
            f.write(b'This is not a valid ZIP file')
            corrupted_zip = f.name
        
        try:
            handler = ZipHandler(Path(corrupted_zip))
            with pytest.raises(ArchiveCorruptedError) as exc_info:
                handler.open()
            
            # Check that error has user-friendly message
            assert hasattr(exc_info.value, 'user_message')
            assert 'corrupted' in exc_info.value.user_message.lower() or 'invalid' in exc_info.value.user_message.lower()
        finally:
            os.unlink(corrupted_zip)
    
    def test_corrupted_tar_raises_appropriate_error(self):
        """Test that corrupted TAR files raise ArchiveCorruptedError"""
        with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as f:
            # Write invalid TAR data
            f.write(b'This is not a valid TAR file')
            corrupted_tar = f.name
        
        try:
            handler = TarHandler(Path(corrupted_tar), compression=None)
            with pytest.raises(ArchiveCorruptedError) as exc_info:
                handler.open()
            
            # Check that error has user-friendly message
            assert hasattr(exc_info.value, 'user_message')
            assert 'corrupted' in exc_info.value.user_message.lower() or 'invalid' in exc_info.value.user_message.lower()
        finally:
            os.unlink(corrupted_tar)


class TestMissingArchiveHandling:
    """Test handling of missing archive files"""
    
    def test_missing_zip_raises_file_not_found(self):
        """Test that missing ZIP files raise FileNotFoundError"""
        nonexistent_path = Path('/nonexistent/archive.zip')
        handler = ZipHandler(nonexistent_path)
        
        with pytest.raises(FileNotFoundError):
            handler.open()
    
    def test_missing_tar_raises_file_not_found(self):
        """Test that missing TAR files raise FileNotFoundError"""
        nonexistent_path = Path('/nonexistent/archive.tar')
        handler = TarHandler(nonexistent_path, compression=None)
        
        with pytest.raises(FileNotFoundError):
            handler.open()


class TestNavigationErrors:
    """Test error handling for archive navigation"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary ZIP file with some content
        self.temp_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.temp_dir, 'test.zip')
        
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr('file1.txt', 'content1')
            zf.writestr('dir1/file2.txt', 'content2')
    
    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_nonexistent_path_raises_navigation_error(self):
        """Test that navigating to nonexistent path raises ArchiveNavigationError"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(ArchiveNavigationError) as exc_info:
                handler.list_entries('nonexistent_dir')
            
            # Check that error has user-friendly message
            assert hasattr(exc_info.value, 'user_message')
            assert 'not found' in exc_info.value.user_message.lower() or 'does not exist' in exc_info.value.user_message.lower()
    
    def test_nonexistent_file_extraction_raises_file_not_found(self):
        """Test that extracting nonexistent file raises FileNotFoundError"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(FileNotFoundError) as exc_info:
                handler.extract_to_bytes('nonexistent_file.txt')
            
            # Check that error message is informative
            assert 'nonexistent_file.txt' in str(exc_info.value)


class TestExtractionErrors:
    """Test error handling for file extraction"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary ZIP file with some content
        self.temp_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.temp_dir, 'test.zip')
        
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr('file1.txt', 'content1')
            zf.writestr('dir1/', '')  # Directory entry
    
    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_extracting_directory_as_bytes_raises_error(self):
        """Test that extracting directory as bytes raises ArchiveExtractionError"""
        with ZipHandler(Path(self.zip_path)) as handler:
            with pytest.raises(ArchiveExtractionError) as exc_info:
                handler.extract_to_bytes('dir1')
            
            # Check that error has user-friendly message
            assert hasattr(exc_info.value, 'user_message')
            assert 'directory' in exc_info.value.user_message.lower()
    
    def test_extracting_directory_as_file_raises_error(self):
        """Test that extracting directory as file raises ArchiveExtractionError"""
        with ZipHandler(Path(self.zip_path)) as handler:
            target_path = Path(os.path.join(self.temp_dir, 'output.txt'))
            
            with pytest.raises(ArchiveExtractionError) as exc_info:
                handler.extract_to_file('dir1', target_path)
            
            # Check that error has user-friendly message
            assert hasattr(exc_info.value, 'user_message')
            assert 'directory' in exc_info.value.user_message.lower()


class TestArchivePathImplErrorHandling:
    """Test error handling in ArchivePathImpl"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary ZIP file with some content
        self.temp_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.temp_dir, 'test.zip')
        
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr('file1.txt', 'content1')
            zf.writestr('dir1/file2.txt', 'content2')
    
    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_nonexistent_archive_path_exists_returns_false(self):
        """Test that exists() returns False for nonexistent archive"""
        archive_uri = f"archive:///nonexistent/archive.zip#"
        archive_path = Path(archive_uri)
        
        # Should return False, not raise exception
        assert not archive_path.exists()
    
    def test_nonexistent_internal_path_exists_returns_false(self):
        """Test that exists() returns False for nonexistent internal path"""
        archive_uri = f"archive://{self.zip_path}#nonexistent_file.txt"
        archive_path = Path(archive_uri)
        
        # Should return False, not raise exception
        assert not archive_path.exists()
    
    def test_reading_nonexistent_file_raises_error(self):
        """Test that reading nonexistent file raises appropriate error"""
        archive_uri = f"archive://{self.zip_path}#nonexistent_file.txt"
        archive_path = Path(archive_uri)
        
        with pytest.raises(OSError):
            archive_path.read_text()
    
    def test_iterdir_on_nonexistent_path_raises_error(self):
        """Test that iterdir on nonexistent path raises appropriate error"""
        archive_uri = f"archive://{self.zip_path}#nonexistent_dir"
        archive_path = Path(archive_uri)
        
        with pytest.raises(OSError):
            list(archive_path.iterdir())


class TestErrorRecovery:
    """Test error recovery scenarios"""
    
    def test_cache_handles_corrupted_archive_gracefully(self):
        """Test that cache handles corrupted archives without crashing"""
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as f:
            # Write invalid ZIP data
            f.write(b'This is not a valid ZIP file')
            corrupted_zip = f.name
        
        try:
            cache = ArchiveCache(max_open=5, ttl=300)
            
            # Attempting to get handler should raise error, not crash
            with pytest.raises(ArchiveCorruptedError):
                cache.get_handler(Path(corrupted_zip))
            
            # Cache should still be functional after error
            assert cache.get_stats()['open_archives'] == 0
        finally:
            os.unlink(corrupted_zip)
    
    def test_multiple_errors_dont_corrupt_cache(self):
        """Test that multiple errors don't corrupt the cache state"""
        cache = ArchiveCache(max_open=5, ttl=300)
        
        # Try to open multiple nonexistent archives
        for i in range(3):
            nonexistent_path = Path(f'/nonexistent/archive{i}.zip')
            
            with pytest.raises(FileNotFoundError):
                cache.get_handler(nonexistent_path)
        
        # Cache should still be functional
        stats = cache.get_stats()
        assert stats['open_archives'] == 0
        assert stats['max_open'] == 5
