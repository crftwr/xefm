#!/usr/bin/env python3
"""
Test that SSH list_directory correctly filters out . and .. entries

This test verifies the fix for the bug where . and .. entries were not being
filtered out, causing rglob to enter infinite loops and return incorrect results.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from xefm.path import Path
import fnmatch

import pytest
pytest.skip("Requires live SSH host 'Ec2-Dev-Ubuntu24' (developer integration test)", allow_module_level=True)



def test_iterdir_excludes_dot_entries():
    """Test that iterdir does not return . or .. entries"""
    ssh_path = Path("ssh://Ec2-Dev-Ubuntu24/home/ubuntu/projects/xefm")
    
    # Get all entries
    entries = list(ssh_path.iterdir())
    
    # Check that . and .. are not in the results
    entry_names = [entry.name for entry in entries]
    
    assert '.' not in entry_names, "iterdir should not return . entry"
    assert '..' not in entry_names, "iterdir should not return .. entry"
    
    # Verify we got some actual entries
    assert len(entries) > 0, "Should have some entries"
    
    print(f"✓ iterdir correctly excludes . and .. entries")
    print(f"  Found {len(entries)} valid entries")


def test_rglob_returns_actual_files():
    """Test that rglob returns actual files, not just dots"""
    ssh_path = Path("ssh://Ec2-Dev-Ubuntu24/home/ubuntu/projects/xefm")
    
    # Get first 10 items from rglob
    items = []
    for item in ssh_path.rglob('*'):
        items.append(item)
        if len(items) >= 10:
            break
    
    # Check that we got actual files, not all dots
    item_names = [item.name for item in items]
    
    # Should not have all items named '.'
    dot_count = sum(1 for name in item_names if name == '.')
    assert dot_count == 0, f"rglob should not return . entries, but got {dot_count}"
    
    # Should have variety of names
    unique_names = set(item_names)
    assert len(unique_names) > 1, "rglob should return files with different names"
    
    print(f"✓ rglob returns actual files")
    print(f"  First 10 items: {item_names[:10]}")


def test_search_for_py_files():
    """Test that searching for *.py files returns results"""
    ssh_path = Path("ssh://Ec2-Dev-Ubuntu24/home/ubuntu/projects/xefm")
    
    # Simulate search dialog behavior
    pattern = "*.py"
    matches = []
    
    for file_path in ssh_path.rglob('*'):
        if fnmatch.fnmatch(file_path.name.lower(), pattern.lower()):
            matches.append(file_path)
            if len(matches) >= 10:
                break
    
    # Should find some .py files
    assert len(matches) > 0, "Should find at least one .py file"
    
    # All matches should end with .py
    for match in matches:
        assert match.name.lower().endswith('.py'), f"Match {match.name} should end with .py"
    
    print(f"✓ Search for *.py files works correctly")
    print(f"  Found {len(matches)} .py files")
    print(f"  Examples: {[m.name for m in matches[:5]]}")


def test_rglob_no_infinite_loop():
    """Test that rglob doesn't enter infinite loop with . entries"""
    ssh_path = Path("ssh://Ec2-Dev-Ubuntu24/home/ubuntu/projects/xefm")
    
    # Try to get 100 items - should complete quickly without infinite loop
    items = []
    for item in ssh_path.rglob('*'):
        items.append(item)
        if len(items) >= 100:
            break
    
    # Should have gotten 100 different items
    assert len(items) == 100, "Should be able to iterate through 100 items"
    
    # Should have variety of names (not all the same)
    unique_names = set(item.name for item in items)
    assert len(unique_names) > 10, f"Should have variety of names, got {len(unique_names)} unique"
    
    print(f"✓ rglob completes without infinite loop")
    print(f"  Iterated through {len(items)} items")
    print(f"  Found {len(unique_names)} unique names")


if __name__ == '__main__':
    print("=" * 60)
    print("SSH Dot Entries Fix Verification")
    print("=" * 60)
    print()
    
    try:
        test_iterdir_excludes_dot_entries()
        print()
        test_rglob_returns_actual_files()
        print()
        test_search_for_py_files()
        print()
        test_rglob_no_infinite_loop()
        print()
        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
