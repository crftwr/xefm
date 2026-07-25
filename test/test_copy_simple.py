"""
Simple test for copy functionality

Run with: python -m pytest test/test_copy_simple.py -v
"""

import tempfile

from xefm.path import Path

def test_copy_method_exists():
    """Test that the copy_to method exists"""
    temp_dir = tempfile.mkdtemp()
    try:
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("test content")
        
        # Check if copy_to method exists
        assert hasattr(test_file, 'copy_to'), "copy_to method should exist"
        assert callable(test_file.copy_to), "copy_to should be callable"
        
        # Test local to local copy
        dest_file = Path(temp_dir) / "dest.txt"
        result = test_file.copy_to(dest_file)
        
        assert result == True, "copy_to should return True on success"
        assert dest_file.exists(), "Destination file should exist"
        assert dest_file.read_text() == "test content", "Content should match"
        
        print("✓ Copy method exists and works for local files")
        
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_s3_path_creation():
    """Test that S3 paths can be created"""
    try:
        s3_path = Path("s3://test-bucket/test-key.txt")
        assert str(s3_path) == "s3://test-bucket/test-key.txt"
        assert s3_path.get_scheme() == "s3"
        assert hasattr(s3_path, 'copy_to'), "S3 path should have copy_to method"
        print("✓ S3 path creation works")
    except ImportError as e:
        print(f"⚠ S3 support not available: {e}")
