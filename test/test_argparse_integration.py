"""
Integration tests for XeFM command line argument parsing

Run with: python -m pytest test/test_argparse_integration.py -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

class TestArgparseIntegration(unittest.TestCase):
    """Integration tests for command line argument parsing"""

    def setUp(self):
        """Set up test environment"""
        self.repo_root = Path(__file__).parent.parent
        self.assertTrue((self.repo_root / 'xefm' / 'app.py').exists(),
                        "xefm/app.py not found")

    def run_xefm_command(self, args):
        """Helper method to run XeFM with given arguments"""
        # Exercise the real entry point (``python -m xefm`` -> ``xefm.app:main``)
        # from the repo root: ``-m`` puts the working directory on sys.path, so
        # the ``xefm`` package resolves exactly as it does for a normal run.
        cmd = [sys.executable, '-m', 'xefm'] + args
        return subprocess.run(cmd, capture_output=True, text=True,
                              cwd=self.repo_root)

    def test_version_displays_correct_info(self):
        """Test that --version displays the correct version information"""
        result = self.run_xefm_command(['--version'])

        self.assertEqual(result.returncode, 0)
        output = result.stdout.strip()

        # Should contain app name and version
        self.assertIn('XeFM', output)
        self.assertIn('0.99', output)
        
        # Should be a single line
        lines = output.split('\n')
        self.assertEqual(len(lines), 1)
    
    def test_help_contains_all_expected_sections(self):
        """Test that --help contains all expected sections"""
        result = self.run_xefm_command(['--help'])
        
        self.assertEqual(result.returncode, 0)
        help_text = result.stdout
        
        # Check for main sections
        self.assertIn('usage:', help_text)
        self.assertIn('options:', help_text)
        
        # Check for specific options
        self.assertIn('-h, --help', help_text)
        self.assertIn('-v, --version', help_text)
        
        # Check for URL
        self.assertIn('github.com/shimomut/xefm', help_text)
    
    def test_error_handling_for_unknown_args(self):
        """Test error handling for various unknown arguments"""
        test_cases = [
            ['--unknown'],
            ['-x'],
            ['--bad-arg'],
            ['--version=something'],  # --version doesn't take arguments
            ['positional_arg'],  # No positional args expected
        ]
        
        for args in test_cases:
            with self.subTest(args=args):
                result = self.run_xefm_command(args)
                
                # Should exit with error code 2 (argparse error)
                self.assertEqual(result.returncode, 2)
                
                # Should show usage in stderr
                self.assertIn('usage: xefm', result.stderr)
                
                # Should mention the problematic argument
                error_text = result.stderr.lower()
                self.assertTrue(
                    'unrecognized' in error_text or 
                    'invalid' in error_text or
                    'error' in error_text
                )
    
    def test_help_and_version_exit_cleanly(self):
        """Test that help and version options exit cleanly without errors"""
        for args in [['--help'], ['-h'], ['--version'], ['-v']]:
            with self.subTest(args=args):
                result = self.run_xefm_command(args)
                
                # Should exit successfully
                self.assertEqual(result.returncode, 0)
                
                # Should have output in stdout, not stderr
                self.assertTrue(len(result.stdout) > 0)
                self.assertEqual(len(result.stderr), 0)
    
    def test_argument_precedence(self):
        """Test argument precedence when multiple are provided"""
        # When both --help and --version are provided, --help should take precedence
        result = self.run_xefm_command(['--help', '--version'])
        
        self.assertEqual(result.returncode, 0)
        # Should show help, not version
        self.assertIn('usage:', result.stdout)
        self.assertIn('options:', result.stdout)
