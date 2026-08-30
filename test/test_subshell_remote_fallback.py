"""
Test for subshell remote directory fallback functionality.

This test verifies that when subshell is opened while browsing a remote directory
(like S3), XeFM falls back to using XeFM's working directory instead of failing.

Run with: python -m pytest test/test_subshell_remote_fallback.py -v
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path as PathlibPath

# Add src directory to path for imports
src_dir = PathlibPath(__file__).parent.parent
from xefm.external_programs import ExternalProgramManager
from xefm.path import Path


class MockRemotePath:
    """Mock remote path that simulates S3 or other remote storage"""
    
    def __init__(self, path_str):
        self.path_str = path_str
    
    def __str__(self):
        return self.path_str
    
    def is_remote(self):
        return True
    
    def get_scheme(self):
        return 's3'


class MockLocalPath:
    """Mock local path for comparison"""
    
    def __init__(self, path_str):
        self.path_str = path_str
    
    def __str__(self):
        return self.path_str
    
    def is_remote(self):
        return False
    
    def get_scheme(self):
        return 'file'


class TestSubshellRemoteFallback(unittest.TestCase):
    """Test subshell behavior with remote directories"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = Mock()
        self.log_manager = Mock()
        self.log_manager.restore_stdio = Mock()
        
        self.external_program_manager = ExternalProgramManager(
            self.config, self.log_manager
        )
        
        # Mock pane manager with remote path
        self.pane_manager = Mock()
        self.pane_manager.left_pane = {
            'path': MockLocalPath('/home/user/local'),
            'selected_files': [],
            'files': [],
            'focused_index': 0
        }
        self.pane_manager.right_pane = {
            'path': MockRemotePath('s3://my-bucket/folder/'),
            'selected_files': [],
            'files': [],
            'focused_index': 0
        }
        
        # Mock stdscr / renderer. enter_subshell_mode now uses self.renderer
        # (set on the manager) rather than a stdscr passed to the method.
        self.stdscr = Mock()
        self.stdscr.clear = Mock()
        self.stdscr.refresh = Mock()
        self.external_program_manager.renderer = self.stdscr
    
    @patch('curses.curs_set')
    @patch('curses.endwin')
    @patch('curses.initscr')
    @patch('subprocess.run')
    @patch('os.chdir')
    @patch('os.getcwd')
    def test_subshell_remote_directory_fallback(self, mock_getcwd, mock_chdir, 
                                               mock_subprocess, mock_initscr, mock_endwin, mock_curs_set):
        """Test that subshell falls back to XeFM working directory when browsing remote directory"""
        
        # Set up mocks
        xefm_working_dir = '/home/user/xefm'
        mock_getcwd.return_value = xefm_working_dir
        
        # Set current pane to remote directory
        self.pane_manager.get_current_pane = Mock(return_value=self.pane_manager.right_pane)
        self.pane_manager.get_inactive_pane = Mock(return_value=self.pane_manager.left_pane)
        
        # Mock environment and imports
        with patch.dict(os.environ, {'SHELL': '/bin/bash'}, clear=False), \
             patch('xefm.colors.init_colors'), \
             patch('xefm.log_manager.LogCapture'):
            # Call enter_subshell_mode
            result = self.external_program_manager.enter_subshell_mode(self.pane_manager)
        
        # Verify that os.chdir was called with XeFM's working directory, not the remote path
        mock_chdir.assert_called_once_with(xefm_working_dir)
        
        # Verify subprocess was called with shell
        mock_subprocess.assert_called_once()
        args, kwargs = mock_subprocess.call_args
        self.assertEqual(args[0], ['/bin/bash'])
        
        # Verify environment variables are set correctly
        env = kwargs['env']
        self.assertEqual(env['XEFM_THIS_DIR'], 's3://my-bucket/folder/')
        self.assertEqual(env['XEFM_OTHER_DIR'], '/home/user/local')
        self.assertEqual(env['XEFM_ACTIVE'], '1')
    
    @patch('curses.curs_set')
    @patch('curses.endwin')
    @patch('curses.initscr')
    @patch('subprocess.run')
    @patch('os.chdir')
    @patch('os.getcwd')
    def test_subshell_local_directory_normal_behavior(self, mock_getcwd, mock_chdir, 
                                                     mock_subprocess, mock_initscr, mock_endwin, mock_curs_set):
        """Test that subshell works normally when browsing local directory"""
        
        # Set up mocks
        xefm_working_dir = '/home/user/xefm'
        mock_getcwd.return_value = xefm_working_dir
        
        # Set current pane to local directory
        self.pane_manager.get_current_pane = Mock(return_value=self.pane_manager.left_pane)
        self.pane_manager.get_inactive_pane = Mock(return_value=self.pane_manager.right_pane)
        
        # Mock environment and imports
        with patch.dict(os.environ, {'SHELL': '/bin/bash'}, clear=False), \
             patch('xefm.colors.init_colors'), \
             patch('xefm.log_manager.LogCapture'):
            # Call enter_subshell_mode
            result = self.external_program_manager.enter_subshell_mode(self.pane_manager)
        
        # Verify that os.chdir was called with the local directory, not XeFM's working directory
        mock_chdir.assert_called_once_with('/home/user/local')
        
        # Verify subprocess was called with shell
        mock_subprocess.assert_called_once()
        args, kwargs = mock_subprocess.call_args
        self.assertEqual(args[0], ['/bin/bash'])
        
        # Verify environment variables are set correctly
        env = kwargs['env']
        self.assertEqual(env['XEFM_THIS_DIR'], '/home/user/local')
        self.assertEqual(env['XEFM_OTHER_DIR'], 's3://my-bucket/folder/')
        self.assertEqual(env['XEFM_ACTIVE'], '1')
    
    @patch('curses.curs_set')
    @patch('curses.endwin')
    @patch('curses.initscr')
    @patch('subprocess.run')
    @patch('os.chdir')
    @patch('os.getcwd')
    def test_external_program_remote_directory_fallback(self, mock_getcwd, mock_chdir, 
                                                       mock_subprocess, mock_initscr, mock_endwin, mock_curs_set):
        """Test that external programs fall back to XeFM working directory when browsing remote directory"""
        
        # Set up mocks
        xefm_working_dir = '/home/user/xefm'
        mock_getcwd.return_value = xefm_working_dir
        
        # Set current pane to remote directory
        self.pane_manager.get_current_pane = Mock(return_value=self.pane_manager.right_pane)
        self.pane_manager.get_inactive_pane = Mock(return_value=self.pane_manager.left_pane)
        
        # Mock program
        program = {
            'name': 'Test Program',
            'command': ['echo', 'test'],
            'options': {'auto_return': True}
        }
        
        # Mock imports and call execute_external_program
        with patch('xefm.colors.init_colors'), \
             patch('xefm.log_manager.LogCapture'), \
             patch('builtins.input', return_value=''):
            result = self.external_program_manager.execute_external_program(self.pane_manager, program)
        
        # Verify that os.chdir was called with XeFM's working directory, not the remote path
        mock_chdir.assert_called_once_with(xefm_working_dir)
        
        # Verify subprocess was called with the program command
        mock_subprocess.assert_called_once()
        args, kwargs = mock_subprocess.call_args
        self.assertEqual(args[0], ['echo', 'test'])
        
        # Verify environment variables are set correctly
        env = kwargs['env']
        self.assertEqual(env['XEFM_THIS_DIR'], 's3://my-bucket/folder/')
        self.assertEqual(env['XEFM_OTHER_DIR'], '/home/user/local')
        self.assertEqual(env['XEFM_ACTIVE'], '1')
    
    @patch('curses.curs_set')
    @patch('curses.endwin')
    @patch('curses.initscr')
    @patch('subprocess.run')
    @patch('os.chdir')
    @patch('os.getcwd')
    def test_external_program_local_directory_normal_behavior(self, mock_getcwd, mock_chdir, 
                                                             mock_subprocess, mock_initscr, mock_endwin, mock_curs_set):
        """Test that external programs work normally when browsing local directory"""
        
        # Set up mocks
        xefm_working_dir = '/home/user/xefm'
        mock_getcwd.return_value = xefm_working_dir
        
        # Set current pane to local directory
        self.pane_manager.get_current_pane = Mock(return_value=self.pane_manager.left_pane)
        self.pane_manager.get_inactive_pane = Mock(return_value=self.pane_manager.right_pane)
        
        # Mock program
        program = {
            'name': 'Test Program',
            'command': ['echo', 'test'],
            'options': {'auto_return': True}
        }
        
        # Mock imports and call execute_external_program
        with patch('xefm.colors.init_colors'), \
             patch('xefm.log_manager.LogCapture'), \
             patch('builtins.input', return_value=''):
            result = self.external_program_manager.execute_external_program(self.pane_manager, program)
        
        # Verify that os.chdir was called with the local directory, not XeFM's working directory
        mock_chdir.assert_called_once_with('/home/user/local')
        
        # Verify subprocess was called with the program command
        mock_subprocess.assert_called_once()
        args, kwargs = mock_subprocess.call_args
        self.assertEqual(args[0], ['echo', 'test'])
        
        # Verify environment variables are set correctly
        env = kwargs['env']
        self.assertEqual(env['XEFM_THIS_DIR'], '/home/user/local')
        self.assertEqual(env['XEFM_OTHER_DIR'], 's3://my-bucket/folder/')
        self.assertEqual(env['XEFM_ACTIVE'], '1')
