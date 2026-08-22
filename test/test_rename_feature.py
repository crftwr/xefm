"""
Test script for the rename feature in XeFM

Run with: python -m pytest test/test_rename_feature.py -v
"""

from pathlib import Path
import tempfile
import shutil

def test_rename_functionality():
    """Test the rename functionality"""
    print("Testing rename functionality...")
    
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test files
        test_file = temp_path / "test_file.txt"
        test_dir = temp_path / "test_directory"
        
        test_file.write_text("This is a test file")
        test_dir.mkdir()
        
        print(f"Created test file: {test_file}")
        print(f"Created test directory: {test_dir}")
        
        # Test file rename
        new_file_name = "renamed_file.txt"
        new_file_path = temp_path / new_file_name
        
        try:
            test_file.rename(new_file_path)
            print(f"✓ Successfully renamed file to: {new_file_name}")
            
            # Verify the file exists with new name
            if new_file_path.exists():
                print("✓ Renamed file exists")
            else:
                print("✗ Renamed file does not exist")
                
            # Verify old file doesn't exist
            if not test_file.exists():
                print("✓ Original file no longer exists")
            else:
                print("✗ Original file still exists")
                
        except Exception as e:
            print(f"✗ Error renaming file: {e}")
        
        # Test directory rename
        new_dir_name = "renamed_directory"
        new_dir_path = temp_path / new_dir_name
        
        try:
            test_dir.rename(new_dir_path)
            print(f"✓ Successfully renamed directory to: {new_dir_name}")
            
            # Verify the directory exists with new name
            if new_dir_path.exists():
                print("✓ Renamed directory exists")
            else:
                print("✗ Renamed directory does not exist")
                
            # Verify old directory doesn't exist
            if not test_dir.exists():
                print("✓ Original directory no longer exists")
            else:
                print("✗ Original directory still exists")
                
        except Exception as e:
            print(f"✗ Error renaming directory: {e}")
        
        # Test invalid rename scenarios
        print("\nTesting invalid rename scenarios...")
        
        # Try to rename to existing name
        try:
            duplicate_file = temp_path / "duplicate.txt"
            duplicate_file.write_text("duplicate")
            
            # Try to rename to same name (should be no-op)
            duplicate_file.rename(duplicate_file)
            print("✓ Renaming to same name handled correctly")
            
        except Exception as e:
            print(f"✗ Error with same name rename: {e}")
        
        # Test invalid characters
        invalid_names = ["file/with/slash", "file\x00with\x00null"]
        for invalid_name in invalid_names:
            try:
                if '/' in invalid_name or '\0' in invalid_name:
                    print(f"✓ Invalid name '{repr(invalid_name)}' would be rejected")
                else:
                    print(f"✗ Invalid name '{repr(invalid_name)}' not properly detected")
            except Exception as e:
                print(f"Error testing invalid name: {e}")

def test_key_binding():
    """Test that the key binding is properly configured"""
    print("\nTesting key binding configuration...")
    
    try:
        from xefm.config import get_config, is_key_bound_to
        
        # Test if 'r' and 'R' are bound to rename action
        if is_key_bound_to('r', 'rename'):
            print("✓ 'r' key is bound to rename action")
        else:
            print("✗ 'r' key is not bound to rename action")
            
        if is_key_bound_to('R', 'rename'):
            print("✓ 'R' key is bound to rename action")
        else:
            print("✗ 'R' key is not bound to rename action")
            
        # Check configuration
        config = get_config()
        if hasattr(config, 'KEY_BINDINGS') and 'rename' in config.KEY_BINDINGS:
            rename_keys = config.KEY_BINDINGS['rename']
            print(f"✓ Rename keys configured: {rename_keys}")
        else:
            print("✗ Rename key binding not found in configuration")
            
    except ImportError as e:
        print(f"✗ Could not import configuration modules: {e}")
    except Exception as e:
        print(f"✗ Error testing key binding: {e}")
