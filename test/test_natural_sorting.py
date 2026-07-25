"""
Test natural sorting of filenames with numeric parts.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock
from xefm.file_list_manager import FileListManager


class TestNaturalSorting:
    """Test natural sorting functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = Mock()
        self.config.MAX_EXTENSION_LENGTH = 5
        self.file_list_manager = FileListManager(self.config)
    
    def test_natural_sort_key_basic(self):
        """Test natural sort key generation for basic cases"""
        # Test simple numeric sorting
        assert self.file_list_manager._natural_sort_key("Test1.txt") < \
               self.file_list_manager._natural_sort_key("Test2.txt")
        assert self.file_list_manager._natural_sort_key("Test2.txt") < \
               self.file_list_manager._natural_sort_key("Test10.txt")
        assert self.file_list_manager._natural_sort_key("Test10.txt") < \
               self.file_list_manager._natural_sort_key("Test100.txt")
    
    def test_natural_sort_key_mixed(self):
        """Test natural sort key with mixed text and numbers"""
        # Test multiple numeric parts
        assert self.file_list_manager._natural_sort_key("file1-part2.txt") < \
               self.file_list_manager._natural_sort_key("file1-part10.txt")
        assert self.file_list_manager._natural_sort_key("file2-part1.txt") > \
               self.file_list_manager._natural_sort_key("file1-part10.txt")
    
    def test_natural_sort_key_case_insensitive(self):
        """Test that natural sorting is case-insensitive for text parts"""
        key1 = self.file_list_manager._natural_sort_key("Test1.txt")
        key2 = self.file_list_manager._natural_sort_key("test1.txt")
        # Text parts should be lowercase, so they should be equal
        assert key1 == key2
    
    def test_natural_sort_key_no_numbers(self):
        """Test natural sort key with no numbers"""
        assert self.file_list_manager._natural_sort_key("abc.txt") < \
               self.file_list_manager._natural_sort_key("def.txt")
    
    def test_natural_sort_key_only_numbers(self):
        """Test natural sort key with only numbers"""
        assert self.file_list_manager._natural_sort_key("1") < \
               self.file_list_manager._natural_sort_key("2")
        assert self.file_list_manager._natural_sort_key("2") < \
               self.file_list_manager._natural_sort_key("10")
    
    def test_sort_entries_natural_order(self):
        """Test that sort_entries uses natural sorting for filenames"""
        # Create mock Path objects
        def create_mock_path(name, is_dir=False):
            mock_path = MagicMock(spec=Path)
            mock_path.name = name
            mock_path.is_dir.return_value = is_dir
            mock_path.is_file.return_value = not is_dir
            return mock_path
        
        # Create test files in non-natural order
        entries = [
            create_mock_path("Test10.txt"),
            create_mock_path("Test2.txt"),
            create_mock_path("Test1.txt"),
            create_mock_path("Test100.txt"),
            create_mock_path("Test11.txt"),
            create_mock_path("Test3.txt"),
        ]
        
        # Sort by name
        sorted_entries = self.file_list_manager.sort_entries(entries, 'name', reverse=False)
        
        # Extract names
        sorted_names = [entry.name for entry in sorted_entries]
        
        # Verify natural order
        expected_order = ["Test1.txt", "Test2.txt", "Test3.txt", "Test10.txt", "Test11.txt", "Test100.txt"]
        assert sorted_names == expected_order
    
    def test_sort_entries_directories_first(self):
        """Test that directories are always sorted before files"""
        def create_mock_path(name, is_dir=False):
            mock_path = MagicMock(spec=Path)
            mock_path.name = name
            mock_path.is_dir.return_value = is_dir
            mock_path.is_file.return_value = not is_dir
            return mock_path
        
        entries = [
            create_mock_path("file10.txt", is_dir=False),
            create_mock_path("dir2", is_dir=True),
            create_mock_path("file1.txt", is_dir=False),
            create_mock_path("dir10", is_dir=True),
            create_mock_path("dir1", is_dir=True),
        ]
        
        sorted_entries = self.file_list_manager.sort_entries(entries, 'name', reverse=False)
        sorted_names = [entry.name for entry in sorted_entries]
        
        # Directories should come first, both groups naturally sorted
        expected_order = ["dir1", "dir2", "dir10", "file1.txt", "file10.txt"]
        assert sorted_names == expected_order
    
    def test_sort_entries_reverse_natural_order(self):
        """Test reverse natural sorting"""
        def create_mock_path(name, is_dir=False):
            mock_path = MagicMock(spec=Path)
            mock_path.name = name
            mock_path.is_dir.return_value = is_dir
            mock_path.is_file.return_value = not is_dir
            return mock_path
        
        entries = [
            create_mock_path("Test1.txt"),
            create_mock_path("Test2.txt"),
            create_mock_path("Test10.txt"),
        ]
        
        sorted_entries = self.file_list_manager.sort_entries(entries, 'name', reverse=True)
        sorted_names = [entry.name for entry in sorted_entries]
        
        # Reverse natural order
        expected_order = ["Test10.txt", "Test2.txt", "Test1.txt"]
        assert sorted_names == expected_order
    
    def test_natural_sort_leading_zeros(self):
        """Test natural sorting with leading zeros"""
        # Leading zeros should be treated as part of the number
        assert self.file_list_manager._natural_sort_key("file001.txt") < \
               self.file_list_manager._natural_sort_key("file002.txt")
        assert self.file_list_manager._natural_sort_key("file002.txt") < \
               self.file_list_manager._natural_sort_key("file010.txt")
        assert self.file_list_manager._natural_sort_key("file010.txt") < \
               self.file_list_manager._natural_sort_key("file100.txt")
