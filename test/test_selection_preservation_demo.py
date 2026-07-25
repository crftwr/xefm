"""
Demo: Selection Preservation in Jump Dialog
Demonstrates that user selection is preserved during filtering and scanning

Run with: python -m pytest test/test_selection_preservation_demo.py -v
"""

import tempfile
import time

from xefm._config import Config

def create_test_directories():
    """Create a test directory structure"""
    temp_dir = tempfile.mkdtemp(prefix="selection_demo_")
    temp_path = Path(temp_dir)
    
    # Create directories with predictable names
    directories = [
        "alpha_project/src",
        "alpha_project/docs",
        "beta_project/src", 
        "beta_project/tests",
        "gamma_shared/utils",
        "gamma_shared/config",
        "delta_tools/scripts",
        "delta_tools/bin"
    ]
    
    for dir_path in directories:
        (temp_path / dir_path).mkdir(parents=True, exist_ok=True)
    
    return temp_path

def demo_selection_preservation():
    """Demonstrate selection preservation during filtering"""
    print("Selection Preservation Demo")
    print("=" * 50)
    
    # Create test structure
    test_path = create_test_directories()
    print(f"Created test directory: {test_path}")
    
    # Initialize jump dialog
    config = Config()
    jump_dialog = JumpDialog(config)
    
    try:
        # Show dialog and wait for scanning
        print("\n1. Starting directory scan...")
        jump_dialog.show(test_path)
        
        # Wait for scanning to complete
        max_wait = 5.0
        start_time = time.time()
        
        while jump_dialog.searching and (time.time() - start_time) < max_wait:
            time.sleep(0.1)
        
        print(f"   Scan completed. Found {len(jump_dialog.directories)} directories.")
        
        # Show all directories
        print("\n2. All directories found:")
        with jump_dialog.scan_lock:
            for i, directory in enumerate(jump_dialog.filtered_directories):
                print(f"   [{i}] {directory.relative_to(test_path)}")
        
        # Select a specific directory (beta_project)
        print("\n3. Selecting 'beta_project' directory...")
        with jump_dialog.scan_lock:
            target_dir = None
            for i, directory in enumerate(jump_dialog.filtered_directories):
                if "beta_project" in str(directory) and directory.name == "beta_project":
                    target_dir = directory
                    jump_dialog.selected = i
                    print(f"   Selected index {i}: {directory.relative_to(test_path)}")
                    break
        
        if not target_dir:
            print("   ERROR: Could not find beta_project directory")
            return
        
        # Apply filter that includes the selected directory
        print("\n4. Applying filter 'beta' (should preserve selection)...")
        jump_dialog.text_editor.text = "beta"
        jump_dialog._filter_directories()
        
        with jump_dialog.scan_lock:
            print(f"   Filtered results ({len(jump_dialog.filtered_directories)} directories):")
            for i, directory in enumerate(jump_dialog.filtered_directories):
                marker = " ← SELECTED" if i == jump_dialog.selected else ""
                print(f"   [{i}] {directory.relative_to(test_path)}{marker}")
            
            # Verify selection is preserved
            if jump_dialog.filtered_directories and jump_dialog.selected < len(jump_dialog.filtered_directories):
                selected_dir = jump_dialog.filtered_directories[jump_dialog.selected]
                if selected_dir == target_dir:
                    print("   ✅ SUCCESS: Selection preserved on same directory!")
                else:
                    print(f"   ❌ FAIL: Selection changed to {selected_dir.relative_to(test_path)}")
            else:
                print("   ❌ FAIL: Invalid selection index")
        
        # Apply filter that excludes the selected directory
        print("\n5. Applying filter 'gamma' (should reset selection)...")
        jump_dialog.text_editor.text = "gamma"
        jump_dialog._filter_directories()
        
        with jump_dialog.scan_lock:
            print(f"   Filtered results ({len(jump_dialog.filtered_directories)} directories):")
            for i, directory in enumerate(jump_dialog.filtered_directories):
                marker = " ← SELECTED" if i == jump_dialog.selected else ""
                print(f"   [{i}] {directory.relative_to(test_path)}{marker}")
            
            # Verify selection reset to 0
            if jump_dialog.selected == 0:
                print("   ✅ SUCCESS: Selection properly reset to top!")
            else:
                print(f"   ❌ FAIL: Selection is {jump_dialog.selected}, expected 0")
        
        # Clear filter to show all directories again
        print("\n6. Clearing filter (should show all directories)...")
        jump_dialog.text_editor.text = ""
        jump_dialog._filter_directories()
        
        with jump_dialog.scan_lock:
            print(f"   All directories restored ({len(jump_dialog.filtered_directories)} total)")
            if jump_dialog.selected < len(jump_dialog.filtered_directories):
                selected_dir = jump_dialog.filtered_directories[jump_dialog.selected]
                print(f"   Current selection: [{jump_dialog.selected}] {selected_dir.relative_to(test_path)}")
        
        print("\n✅ Demo completed successfully!")
        
    finally:
        # Clean up
        jump_dialog.exit()
        
        # Remove test directory
        import shutil
        try:
            shutil.rmtree(test_path)
            print(f"\nCleaned up test directory: {test_path}")
        except:
            print(f"\nWarning: Could not clean up {test_path}")
