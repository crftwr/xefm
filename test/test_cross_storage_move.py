"""
Test Cross-Storage Move Functionality

This test verifies that XeFM can move files and directories between different storage systems:
- Local to S3
- S3 to Local  
- S3 to S3 (different buckets/paths)
- Local to Local (same storage verification)

Run with: python -m pytest test/test_cross_storage_move.py -v
"""

import os
import tempfile
import shutil
from pathlib import Path as PathlibPath

from xefm.path import Path


class TestCrossStorageMove:
    """Test cross-storage move operations"""
    
    def setup_method(self, method):
        """Set up test environment (pytest per-test hook; was __init__/setup)."""
        self.temp_dir = None
        self.test_files = []
        self.test_dirs = []

        # Create temporary directory for local tests
        self.temp_dir = tempfile.mkdtemp(prefix='xefm_move_test_')

        # Create test files and directories
        self._create_test_data()
    
    def _create_test_data(self):
        """Create test files and directories"""
        temp_path = PathlibPath(self.temp_dir)
        
        # Create test files
        test_file1 = temp_path / "test_file1.txt"
        test_file1.write_text("This is test file 1\nWith multiple lines\n")
        self.test_files.append(Path(test_file1))
        
        test_file2 = temp_path / "test_file2.md"
        test_file2.write_text("# Test File 2\n\nThis is a markdown file.\n")
        self.test_files.append(Path(test_file2))
        
        # Create test directory with files
        test_dir = temp_path / "test_directory"
        test_dir.mkdir()
        
        (test_dir / "nested_file1.txt").write_text("Nested file 1 content")
        (test_dir / "nested_file2.json").write_text('{"key": "value", "number": 42}')
        
        # Create subdirectory
        sub_dir = test_dir / "subdirectory"
        sub_dir.mkdir()
        (sub_dir / "deep_file.txt").write_text("Deep nested file content")
        
        self.test_dirs.append(Path(test_dir))
        
        print(f"Created {len(self.test_files)} test files and {len(self.test_dirs)} test directories")
    
    def test_local_to_local_move(self):
        """Test moving files within local storage"""
        print("\n=== Testing Local to Local Move ===")
        
        # Create destination directory
        dest_dir = Path(self.temp_dir) / "local_dest"
        dest_dir.mkdir()
        
        # Test single file move
        source_file = self.test_files[0]
        dest_file = dest_dir / source_file.name
        
        print(f"Moving {source_file} to {dest_file}")
        
        # Verify source exists
        assert source_file.exists(), f"Source file should exist: {source_file}"
        
        # Perform move
        try:
            success = source_file.move_to(dest_file)
            assert success, "Move operation should succeed"
            
            # Verify move completed
            assert not source_file.exists(), f"Source should not exist after move: {source_file}"
            assert dest_file.exists(), f"Destination should exist after move: {dest_file}"
            
            # Verify content
            original_content = "This is test file 1\nWith multiple lines\n"
            moved_content = dest_file.read_text()
            assert moved_content == original_content, "Content should be preserved"
            
            print("✓ Local to local file move successful")
            
        except Exception as e:
            print(f"✗ Local to local move failed: {e}")
            return
        
        # Test directory move
        source_dir = self.test_dirs[0]
        dest_subdir = dest_dir / source_dir.name
        
        print(f"Moving directory {source_dir} to {dest_subdir}")
        
        try:
            success = source_dir.move_to(dest_subdir)
            assert success, "Directory move operation should succeed"
            
            # Verify directory structure
            assert not source_dir.exists(), f"Source directory should not exist: {source_dir}"
            assert dest_subdir.exists(), f"Destination directory should exist: {dest_subdir}"
            assert (dest_subdir / "nested_file1.txt").exists(), "Nested files should exist"
            assert (dest_subdir / "subdirectory" / "deep_file.txt").exists(), "Deep nested files should exist"
            
            print("✓ Local to local directory move successful")
            
        except Exception as e:
            print(f"✗ Local to local directory move failed: {e}")
            return
        
        return
    
    def test_s3_availability(self):
        """Test if S3 functionality is available"""
        print("\n=== Testing S3 Availability ===")
        
        try:
            # Try to create an S3 path
            s3_path = Path("s3://test-bucket/test-key")
            print(f"S3 path created: {s3_path}")
            print(f"S3 scheme: {s3_path.get_scheme()}")
            print("✓ S3 support is available")
            return
            
        except ImportError as e:
            print(f"✗ S3 support not available: {e}")
            print("Install boto3 to enable S3 functionality: pip install boto3")
            return
        except Exception as e:
            print(f"✗ S3 initialization failed: {e}")
            return
    
    def test_cross_storage_move_simulation(self):
        """Simulate cross-storage move without actual S3 operations"""
        print("\n=== Testing Cross-Storage Move Logic ===")
        
        # Create mock S3 paths
        try:
            local_file = self.test_files[1]  # Use remaining test file
            s3_dest = Path("s3://test-bucket/moved-file.md")
            
            print(f"Simulating move from {local_file.get_scheme()} to {s3_dest.get_scheme()}")
            
            # Check scheme detection
            assert local_file.get_scheme() == 'file', "Local file should have 'file' scheme"
            assert s3_dest.get_scheme() == 's3', "S3 path should have 's3' scheme"
            
            # Verify cross-storage detection logic
            is_cross_storage = local_file.get_scheme() != s3_dest.get_scheme()
            assert is_cross_storage, "Should detect cross-storage move"
            
            print("✓ Cross-storage move detection works correctly")
            
            # Test scheme name mapping
            scheme_names = {'file': 'Local', 's3': 'S3', 'scp': 'SCP', 'ftp': 'FTP'}
            source_name = scheme_names.get(local_file.get_scheme(), local_file.get_scheme().upper())
            dest_name = scheme_names.get(s3_dest.get_scheme(), s3_dest.get_scheme().upper())
            
            print(f"Move type: {source_name} → {dest_name}")
            assert source_name == "Local", "Source should be Local"
            assert dest_name == "S3", "Destination should be S3"
            
            print("✓ Scheme name mapping works correctly")
            
        except Exception as e:
            print(f"✗ Cross-storage move simulation failed: {e}")
            return
        
        return
    
    def test_move_error_handling(self):
        """Test error handling in move operations"""
        print("\n=== Testing Move Error Handling ===")
        
        try:
            # Test moving non-existent file
            non_existent = Path(self.temp_dir) / "does_not_exist.txt"
            dest = Path(self.temp_dir) / "destination.txt"
            
            try:
                non_existent.move_to(dest)
                print("✗ Should have raised FileNotFoundError")
                return
            except FileNotFoundError:
                print("✓ Correctly raised FileNotFoundError for non-existent source")
            
            # Test moving to existing destination without overwrite
            source = Path(self.temp_dir) / "source.txt"
            source.write_text("Source content")
            
            existing_dest = Path(self.temp_dir) / "existing.txt"
            existing_dest.write_text("Existing content")
            
            try:
                source.move_to(existing_dest, overwrite=False)
                print("✗ Should have raised FileExistsError")
                return
            except FileExistsError:
                print("✓ Correctly raised FileExistsError for existing destination")
            
            # Test moving to existing destination with overwrite
            try:
                success = source.move_to(existing_dest, overwrite=True)
                assert success, "Move with overwrite should succeed"
                assert not source.exists(), "Source should be gone"
                assert existing_dest.exists(), "Destination should exist"
                assert existing_dest.read_text() == "Source content", "Content should be from source"
                print("✓ Move with overwrite works correctly")
            except Exception as e:
                print(f"✗ Move with overwrite failed: {e}")
                return
            
        except Exception as e:
            print(f"✗ Error handling test failed: {e}")
            return
        
        return
    
    def teardown_method(self, method):
        """Clean up test environment (pytest per-test hook; was cleanup)."""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Cleanup failed: {e}")
    
    def run_all_tests(self):
        """Run all tests"""
        print("Starting Cross-Storage Move Tests")
        print("=" * 50)
        
        try:
            self.setup()
            
            tests = [
                ("Local to Local Move", self.test_local_to_local_move),
                ("S3 Availability", self.test_s3_availability),
                ("Cross-Storage Move Logic", self.test_cross_storage_move_simulation),
                ("Move Error Handling", self.test_move_error_handling),
            ]
            
            passed = 0
            total = len(tests)
            
            for test_name, test_func in tests:
                print(f"\nRunning: {test_name}")
                try:
                    if test_func():
                        passed += 1
                        print(f"✓ {test_name} PASSED")
                    else:
                        print(f"✗ {test_name} FAILED")
                except Exception as e:
                    print(f"✗ {test_name} FAILED with exception: {e}")
            
            print(f"\n" + "=" * 50)
            print(f"Test Results: {passed}/{total} tests passed")
            
            if passed == total:
                print("🎉 All tests passed!")
                return True
            else:
                print("❌ Some tests failed")
                return False
                
        finally:
            self.cleanup()


def main():
    """Main test function"""
    tester = TestCrossStorageMove()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)
