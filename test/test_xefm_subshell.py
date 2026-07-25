"""
Test XeFM sub-shell functionality by simulating the environment setup

Run with: python -m pytest test/test_xefm_subshell.py -v
"""

import os
import subprocess
import sys
from pathlib import Path


def simulate_xefm_subshell():
    """Simulate what XeFM does when entering sub-shell mode"""
    
    print("Simulating XeFM sub-shell environment setup...")
    print("=" * 50)
    
    # Simulate XeFM's environment setup
    env = os.environ.copy()
    
    # Set up directory variables (using current directory structure)
    current_dir = Path.cwd()
    home_dir = Path.home()
    
    env['XEFM_LEFT_DIR'] = str(current_dir)
    env['XEFM_RIGHT_DIR'] = str(home_dir)
    env['XEFM_THIS_DIR'] = str(current_dir)
    env['XEFM_OTHER_DIR'] = str(home_dir)
    
    # Set up selected files (simulate some selections)
    env['XEFM_LEFT_SELECTED'] = 'xefm/app.py README.md'
    env['XEFM_RIGHT_SELECTED'] = ''
    env['XEFM_THIS_SELECTED'] = 'xefm/app.py README.md'
    env['XEFM_OTHER_SELECTED'] = ''
    
    # Add prompt modification like XeFM does (both PS1 and PROMPT)
    current_ps1 = env.get('PS1', '')
    current_prompt = env.get('PROMPT', '')
    
    if current_ps1:
        env['PS1'] = f'[XeFM] {current_ps1}'
    else:
        env['PS1'] = '[XeFM] \\u@\\h:\\w\\$ '
    
    if current_prompt:
        env['PROMPT'] = f'[XeFM] {current_prompt}'
    else:
        env['PROMPT'] = '[XeFM] %n@%m:%~%# '
    
    print("Environment variables set:")
    for var in ['XEFM_LEFT_DIR', 'XEFM_RIGHT_DIR', 'XEFM_THIS_DIR', 'XEFM_OTHER_DIR', 
                'XEFM_LEFT_SELECTED', 'XEFM_RIGHT_SELECTED', 'XEFM_THIS_SELECTED', 'XEFM_OTHER_SELECTED']:
        print(f"  {var}: {env[var]}")
    
    print("\n" + "=" * 50)
    print("Testing sub-shell with environment variables...")
    
    # Test running our verification script
    try:
        result = subprocess.run(['bash', 'verify_subshell.sh'], 
                              env=env, 
                              capture_output=True, 
                              text=True,
                              cwd=current_dir)
        
        print("Verification script output:")
        print(result.stdout)
        
        if result.stderr:
            print("Errors:")
            print(result.stderr)
            
        if result.returncode == 0:
            print("✅ Sub-shell environment test PASSED!")
            return True
        else:
            print("❌ Sub-shell environment test FAILED!")
            return False
            
    except Exception as e:
        print(f"❌ Error running test: {e}")
        return False

def test_python_script():
    """Test the Python verification script"""
    
    print("\nTesting Python verification script...")
    print("=" * 50)
    
    # Set up environment
    env = os.environ.copy()
    current_dir = Path.cwd()
    home_dir = Path.home()
    
    env['XEFM_LEFT_DIR'] = str(current_dir)
    env['XEFM_RIGHT_DIR'] = str(home_dir)
    env['XEFM_THIS_DIR'] = str(current_dir)
    env['XEFM_OTHER_DIR'] = str(home_dir)
    env['XEFM_LEFT_SELECTED'] = 'test1.txt test2.txt'
    env['XEFM_RIGHT_SELECTED'] = ''
    env['XEFM_THIS_SELECTED'] = 'test1.txt test2.txt'
    env['XEFM_OTHER_SELECTED'] = ''
    
    # Add prompt modification like XeFM does (both PS1 and PROMPT)
    current_ps1 = env.get('PS1', '')
    current_prompt = env.get('PROMPT', '')
    
    if current_ps1:
        env['PS1'] = f'[XeFM] {current_ps1}'
    else:
        env['PS1'] = '[XeFM] \\u@\\h:\\w\\$ '
    
    if current_prompt:
        env['PROMPT'] = f'[XeFM] {current_prompt}'
    else:
        env['PROMPT'] = '[XeFM] %n@%m:%~%# '
    
    try:
        result = subprocess.run([sys.executable, 'test_subshell.py'], 
                              env=env, 
                              capture_output=True, 
                              text=True,
                              cwd=current_dir)
        
        print("Python test output:")
        print(result.stdout)
        
        if result.stderr:
            print("Errors:")
            print(result.stderr)
            
        return
        
    except Exception as e:
        print(f"❌ Error running Python test: {e}")
        return
