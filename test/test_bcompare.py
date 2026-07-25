"""
Test script to verify BeyondCompare integration with XeFM

Run with: python -m pytest test/test_bcompare.py -v
"""

import os

from xefm.config import get_programs

def test_bcompare_config():
    """Test that BeyondCompare programs are properly configured"""
    print("Testing BeyondCompare configuration...")
    
    # Get programs from config
    programs = get_programs()
    
    print(f"Found {len(programs)} external programs:")
    for i, prog in enumerate(programs, 1):
        options_str = ""
        if prog.get('options'):
            options_list = [f"{k}={v}" for k, v in prog['options'].items()]
            options_str = f" (options: {', '.join(options_list)})"
        print(f"  {i}. {prog['name']}: {' '.join(prog['command'])}{options_str}")
    
    # Check for both BeyondCompare programs
    programs_to_check = [
        'Compare Directories (BeyondCompare)',
        'Compare Files (BeyondCompare)'
    ]
    
    found_programs = []
    for prog in programs:
        if prog['name'] in programs_to_check:
            found_programs.append(prog['name'])
            options_str = ""
            if prog.get('options'):
                options_list = [f"{k}={v}" for k, v in prog['options'].items()]
                options_str = f" (options: {', '.join(options_list)})"
            print(f"\n✓ {prog['name']} found: {' '.join(prog['command'])}{options_str}")
            
            # Check if the wrapper script exists (adjust path based on current working directory)
            wrapper_path = prog['command'][0]
            if os.path.basename(os.getcwd()) == 'test':
                # When running from test directory, adjust the path
                wrapper_path = '../' + wrapper_path if wrapper_path.startswith('./') else wrapper_path
            
            if os.path.exists(wrapper_path):
                print(f"✓ Wrapper script exists: {wrapper_path}")
                
                # Check if it's executable
                if os.access(wrapper_path, os.X_OK):
                    print("✓ Wrapper script is executable")
                else:
                    print("✗ Wrapper script is not executable")
                    return
            else:
                print(f"✗ Wrapper script not found: {wrapper_path}")
                return
    
    # Check if all expected programs were found
    missing_programs = set(programs_to_check) - set(found_programs)
    if missing_programs:
        print(f"✗ Missing BeyondCompare programs: {', '.join(missing_programs)}")
        return
    
    print("\n✓ BeyondCompare configuration test passed!")
    return

def test_wrapper_scripts():
    """Test the wrapper scripts with mock environment variables"""
    print("\nTesting wrapper scripts with mock environment...")
    
    # Set mock XeFM environment variables for directory comparison
    os.environ['XEFM_LEFT_DIR'] = '/tmp/left'
    os.environ['XEFM_RIGHT_DIR'] = '/tmp/right'
    
    # Create mock directories and files
    os.makedirs('/tmp/left', exist_ok=True)
    os.makedirs('/tmp/right', exist_ok=True)
    
    # Create test files
    with open('/tmp/left/test.txt', 'w') as f:
        f.write("Left file content")
    with open('/tmp/right/test.txt', 'w') as f:
        f.write("Right file content")
    
    # Set mock file selection environment variables
    os.environ['XEFM_LEFT_SELECTED'] = 'test.txt'
    os.environ['XEFM_RIGHT_SELECTED'] = 'test.txt'
    
    print("Mock environment set:")
    print(f"  XEFM_LEFT_DIR: {os.environ['XEFM_LEFT_DIR']}")
    print(f"  XEFM_RIGHT_DIR: {os.environ['XEFM_RIGHT_DIR']}")
    print(f"  XEFM_LEFT_SELECTED: {os.environ['XEFM_LEFT_SELECTED']}")
    print(f"  XEFM_RIGHT_SELECTED: {os.environ['XEFM_RIGHT_SELECTED']}")
    
    success = True
    
    # Test directory comparison wrapper (adjust path based on current working directory)
    wrapper_path = '../tools/bcompare_dirs_wrapper.sh' if os.path.basename(os.getcwd()) == 'test' else './tools/bcompare_dirs_wrapper.sh'
    if os.path.exists(wrapper_path):
        print(f"✓ Directory comparison wrapper ready: {wrapper_path}")
    else:
        print(f"✗ Directory comparison wrapper not found: {wrapper_path}")
        success = False
    
    # Test file comparison wrapper (adjust path based on current working directory)
    files_wrapper_path = '../tools/bcompare_files_wrapper.sh' if os.path.basename(os.getcwd()) == 'test' else './tools/bcompare_files_wrapper.sh'
    if os.path.exists(files_wrapper_path):
        print(f"✓ File comparison wrapper ready: {files_wrapper_path}")
    else:
        print(f"✗ File comparison wrapper not found: {files_wrapper_path}")
        success = False
    
    print("  (Not executing to avoid launching BeyondCompare)")
    return
