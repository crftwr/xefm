"""
Tests for ArchivePathImpl class

Run with: python -m pytest test/test_archive_path_impl.py -v
"""

import tempfile
import zipfile
import tarfile
from pathlib import Path as PathlibPath

from xefm.path import Path
from xefm.archive import ArchivePathImpl


class TestArchivePathImpl:
    """Test ArchivePathImpl functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary directory for test files
        self.temp_dir = tempfile.mkdtemp(prefix='xefm_test_archive_path_')
        self.temp_path = PathlibPath(self.temp_dir)
        
        # Create a test ZIP archive
        self.zip_path = self.temp_path / 'test.zip'
        with zipfile.ZipFile(str(self.zip_path), 'w') as zf:
            # Add files
            zf.writestr('file1.txt', 'Content of file1')
            zf.writestr('file2.txt', 'Content of file2')
            
            # Add directory with files
            zf.writestr('dir1/', '')
            zf.writestr('dir1/file3.txt', 'Content of file3')
            zf.writestr('dir1/file4.txt', 'Content of file4')
            
            # Add nested directory
            zf.writestr('dir1/subdir/', '')
            zf.writestr('dir1/subdir/file5.txt', 'Content of file5')
    
    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        if self.temp_path.exists():
            shutil.rmtree(str(self.temp_path))
    
    def test_archive_path_creation(self):
        """Test creating an archive path"""
        archive_uri = f"archive://{self.zip_path}#"
        path = Path(archive_uri)
        
        assert isinstance(path._impl, ArchivePathImpl)
        assert str(path) == archive_uri
    
    def test_archive_path_parsing(self):
        """Test URI parsing"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        impl = path._impl
        assert impl._archive_path == Path(str(self.zip_path))
        assert impl._internal_path == 'dir1/file3.txt'
    
    def test_archive_root_exists(self):
        """Test that archive root exists"""
        archive_uri = f"archive://{self.zip_path}#"
        path = Path(archive_uri)
        
        assert path.exists()
        assert path.is_dir()
        assert not path.is_file()
    
    def test_archive_file_exists(self):
        """Test checking if file exists in archive"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        assert path.exists()
        assert path.is_file()
        assert not path.is_dir()
    
    def test_archive_directory_exists(self):
        """Test checking if directory exists in archive"""
        archive_uri = f"archive://{self.zip_path}#dir1"
        path = Path(archive_uri)
        
        assert path.exists()
        assert path.is_dir()
        assert not path.is_file()
    
    def test_archive_nonexistent_path(self):
        """Test checking nonexistent path"""
        archive_uri = f"archive://{self.zip_path}#nonexistent.txt"
        path = Path(archive_uri)
        
        assert not path.exists()
        assert not path.is_file()
        assert not path.is_dir()
    
    def test_archive_path_name(self):
        """Test getting path name"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        assert path.name == 'file3.txt'
    
    def test_archive_path_stem_and_suffix(self):
        """Test getting stem and suffix"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        assert path.stem == 'file3'
        assert path.suffix == '.txt'
    
    def test_archive_path_parent(self):
        """Test getting parent path"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        parent = path.parent
        assert isinstance(parent._impl, ArchivePathImpl)
        assert parent._impl._internal_path == 'dir1'
    
    def test_archive_root_parent(self):
        """Test getting parent of archive root"""
        archive_uri = f"archive://{self.zip_path}#"
        path = Path(archive_uri)
        
        parent = path.parent
        # Parent of archive root should be the directory containing the archive
        assert parent == Path(str(self.zip_path)).parent
    
    def test_archive_iterdir(self):
        """Test iterating directory contents"""
        archive_uri = f"archive://{self.zip_path}#"
        path = Path(archive_uri)
        
        entries = list(path.iterdir())
        entry_names = {e.name for e in entries}
        
        # Should have file1.txt, file2.txt, and dir1
        assert 'file1.txt' in entry_names
        assert 'file2.txt' in entry_names
        assert 'dir1' in entry_names
    
    def test_archive_iterdir_subdirectory(self):
        """Test iterating subdirectory contents"""
        archive_uri = f"archive://{self.zip_path}#dir1"
        path = Path(archive_uri)
        
        entries = list(path.iterdir())
        entry_names = {e.name for e in entries}
        
        # Should have file3.txt, file4.txt, and subdir
        assert 'file3.txt' in entry_names
        assert 'file4.txt' in entry_names
        assert 'subdir' in entry_names
    
    def test_archive_read_text(self):
        """Test reading text file from archive"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        content = path.read_text()
        assert content == 'Content of file1'
    
    def test_archive_read_bytes(self):
        """Test reading bytes from archive"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        content = path.read_bytes()
        assert content == b'Content of file1'
    
    def test_archive_open_text(self):
        """Test opening file in text mode"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        with path.open('r') as f:
            content = f.read()
        
        assert content == 'Content of file1'
    
    def test_archive_open_binary(self):
        """Test opening file in binary mode"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        with path.open('rb') as f:
            content = f.read()
        
        assert content == b'Content of file1'
    
    def test_archive_stat(self):
        """Test getting file stats"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        stat_result = path.stat()
        assert stat_result.st_size == len('Content of file1')
    
    def test_archive_joinpath(self):
        """Test joining paths"""
        archive_uri = f"archive://{self.zip_path}#dir1"
        path = Path(archive_uri)
        
        file_path = path / 'file3.txt'
        assert isinstance(file_path._impl, ArchivePathImpl)
        assert file_path._impl._internal_path == 'dir1/file3.txt'
        assert file_path.exists()
    
    def test_archive_with_name(self):
        """Test changing file name"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        new_path = path.with_name('file4.txt')
        assert new_path._impl._internal_path == 'dir1/file4.txt'
        assert new_path.exists()
    
    def test_archive_with_suffix(self):
        """Test changing file suffix"""
        archive_uri = f"archive://{self.zip_path}#dir1/file3.txt"
        path = Path(archive_uri)
        
        new_path = path.with_suffix('.md')
        assert new_path._impl._internal_path == 'dir1/file3.md'
        assert new_path.suffix == '.md'
    
    def test_archive_glob(self):
        """Test glob pattern matching"""
        archive_uri = f"archive://{self.zip_path}#"
        path = Path(archive_uri)
        
        txt_files = list(path.glob('*.txt'))
        txt_names = {f.name for f in txt_files}
        
        assert 'file1.txt' in txt_names
        assert 'file2.txt' in txt_names
    
    def test_archive_is_remote(self):
        """Test is_remote method"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        # Archive on local filesystem should not be remote
        assert not path.is_remote()
    
    def test_archive_get_scheme(self):
        """Test get_scheme method"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        assert path.get_scheme() == 'archive'
    
    def test_archive_readonly_operations(self):
        """Test that write operations raise errors"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        # All write operations should raise OSError
        try:
            path.write_text('new content')
            assert False, "Should have raised OSError"
        except OSError:
            pass
        
        try:
            path.write_bytes(b'new content')
            assert False, "Should have raised OSError"
        except OSError:
            pass
        
        try:
            path.unlink()
            assert False, "Should have raised OSError"
        except OSError:
            pass
    
    def test_archive_supports_methods(self):
        """Test supports_* methods"""
        archive_uri = f"archive://{self.zip_path}#file1.txt"
        path = Path(archive_uri)
        
        assert not path.supports_directory_rename()
        assert not path.supports_file_editing()
