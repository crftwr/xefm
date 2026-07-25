"""
Test archive extraction progress tracking

Run with: python -m pytest test/test_archive_extraction_progress.py -v
"""

import tempfile
import zipfile
import tarfile
from pathlib import Path
from unittest.mock import Mock, MagicMock

from xefm.progress_manager import ProgressManager, OperationType


class MockFileManager:
    """Mock FileManager class to test archive extraction progress"""
    
    def __init__(self):
        self.progress_manager = ProgressManager()
        self.stdscr = Mock()
        
    def _progress_callback(self, progress_data):
        """Mock progress callback"""
        pass
        
    def draw_status(self):
        """Mock draw_status method"""
        pass
    
    def extract_zip_archive(self, archive_file, extract_dir):
        """Extract a ZIP archive with progress tracking"""
        import zipfile
        from pathlib import Path
        
        with zipfile.ZipFile(archive_file, 'r') as zipf:
            # Get list of files to extract
            file_list = zipf.namelist()
            total_files = len(file_list)
            
            # Start progress tracking if there are multiple files
            if total_files > 1:
                self.progress_manager.start_operation(
                    OperationType.ARCHIVE_EXTRACT,
                    total_files,
                    f"ZIP: {archive_file.name}",
                    self._progress_callback
                )
            
            try:
                # Extract files one by one to track progress
                for i, file_info in enumerate(file_list):
                    if total_files > 1:
                        # Update progress with current file
                        filename = Path(file_info).name if file_info else f"file_{i+1}"
                        self.progress_manager.update_progress(filename, i)
                    
                    try:
                        # Extract individual file
                        zipf.extract(file_info, extract_dir)
                    except Exception as e:
                        print(f"Error extracting {file_info}: {e}")
                        if total_files > 1:
                            self.progress_manager.increment_errors()
                        
            finally:
                # Finish progress tracking
                if total_files > 1:
                    self.progress_manager.finish_operation()
    
    def extract_tar_archive(self, archive_file, extract_dir):
        """Extract a TAR.GZ archive with progress tracking"""
        import tarfile
        from pathlib import Path
        
        with tarfile.open(archive_file, 'r:gz') as tarf:
            # Get list of members to extract
            members = tarf.getmembers()
            # Count only files (not directories) for progress
            file_members = [m for m in members if m.isfile()]
            total_files = len(file_members)
            
            # Start progress tracking if there are multiple files
            if total_files > 1:
                self.progress_manager.start_operation(
                    OperationType.ARCHIVE_EXTRACT,
                    total_files,
                    f"TAR.GZ: {archive_file.name}",
                    self._progress_callback
                )
            
            try:
                # Extract members one by one to track progress
                processed_files = 0
                for member in members:
                    if member.isfile():
                        processed_files += 1
                        if total_files > 1:
                            # Update progress with current file
                            filename = Path(member.name).name if member.name else f"file_{processed_files}"
                            self.progress_manager.update_progress(filename, processed_files)
                    
                    try:
                        # Extract individual member
                        tarf.extract(member, extract_dir)
                    except Exception as e:
                        print(f"Error extracting {member.name}: {e}")
                        if total_files > 1 and member.isfile():
                            self.progress_manager.increment_errors()
                        
            finally:
                # Finish progress tracking
                if total_files > 1:
                    self.progress_manager.finish_operation()


def create_test_zip_archive(archive_path, num_files=5):
    """Create a test ZIP archive with multiple files"""
    with zipfile.ZipFile(archive_path, 'w') as zipf:
        for i in range(num_files):
            filename = f"test_file_{i+1}.txt"
            content = f"This is test file {i+1}\nWith some content for testing.\n"
            zipf.writestr(filename, content)


def create_test_tar_archive(archive_path, num_files=5):
    """Create a test TAR.GZ archive with multiple files"""
    with tarfile.open(archive_path, 'w:gz') as tarf:
        for i in range(num_files):
            filename = f"test_file_{i+1}.txt"
            content = f"This is test file {i+1}\nWith some content for testing.\n"
            
            # Create tarinfo for the file
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(content.encode())
            
            # Add file to archive
            import io
            tarf.addfile(tarinfo, io.BytesIO(content.encode()))


def test_zip_extraction_progress():
    """Test ZIP archive extraction with progress tracking"""
    print("Testing ZIP extraction progress...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test archive
        archive_path = temp_path / "test_archive.zip"
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()
        
        create_test_zip_archive(archive_path, 5)
        
        # Test extraction with progress
        fm = MockFileManager()
        
        # Verify no operation is active initially
        assert not fm.progress_manager.is_operation_active()
        
        # Extract archive
        fm.extract_zip_archive(archive_path, extract_dir)
        
        # Verify operation completed and is no longer active
        assert not fm.progress_manager.is_operation_active()
        
        # Verify files were extracted
        extracted_files = list(extract_dir.glob("*.txt"))
        assert len(extracted_files) == 5
        
        for i in range(5):
            expected_file = extract_dir / f"test_file_{i+1}.txt"
            assert expected_file.exists()
            content = expected_file.read_text()
            assert f"This is test file {i+1}" in content
    
    print("✅ ZIP extraction progress test passed!")


def test_tar_extraction_progress():
    """Test TAR.GZ archive extraction with progress tracking"""
    print("Testing TAR.GZ extraction progress...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test archive
        archive_path = temp_path / "test_archive.tar.gz"
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()
        
        create_test_tar_archive(archive_path, 4)
        
        # Test extraction with progress
        fm = MockFileManager()
        
        # Verify no operation is active initially
        assert not fm.progress_manager.is_operation_active()
        
        # Extract archive
        fm.extract_tar_archive(archive_path, extract_dir)
        
        # Verify operation completed and is no longer active
        assert not fm.progress_manager.is_operation_active()
        
        # Verify files were extracted
        extracted_files = list(extract_dir.glob("*.txt"))
        assert len(extracted_files) == 4
        
        for i in range(4):
            expected_file = extract_dir / f"test_file_{i+1}.txt"
            assert expected_file.exists()
            content = expected_file.read_text()
            assert f"This is test file {i+1}" in content
    
    print("✅ TAR.GZ extraction progress test passed!")


def test_single_file_extraction():
    """Test that single file archives don't show progress"""
    print("Testing single file extraction (no progress)...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create single-file archive
        archive_path = temp_path / "single_file.zip"
        extract_dir = temp_path / "extracted"
        extract_dir.mkdir()
        
        create_test_zip_archive(archive_path, 1)
        
        # Test extraction
        fm = MockFileManager()
        
        # Extract archive
        fm.extract_zip_archive(archive_path, extract_dir)
        
        # Verify no progress was shown (single file)
        assert not fm.progress_manager.is_operation_active()
        
        # Verify file was extracted
        extracted_files = list(extract_dir.glob("*.txt"))
        assert len(extracted_files) == 1
    
    print("✅ Single file extraction test passed!")


def test_progress_text_formatting():
    """Test progress text formatting for extraction operations"""
    print("Testing extraction progress text formatting...")
    
    fm = MockFileManager()
    
    # Start extraction operation
    fm.progress_manager.start_operation(
        OperationType.ARCHIVE_EXTRACT,
        10,
        "ZIP: large_archive.zip",
        fm._progress_callback
    )
    
    # Update progress
    fm.progress_manager.update_progress("document.pdf", 3)
    
    # Test progress text
    progress_text = fm.progress_manager.get_progress_text(80)
    assert "Extracting archive" in progress_text
    assert "3/10" in progress_text
    assert "document.pdf" in progress_text
    assert "ZIP: large_archive.zip" in progress_text
    
    # Finish operation
    fm.progress_manager.finish_operation()
    
    print("✅ Progress text formatting test passed!")
