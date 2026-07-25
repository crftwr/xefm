"""
Tests for xefm/external_programs.py

Run with: python -m pytest test/test_external_programs.py -v
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import os

from xefm.external_programs import ExternalProgramManager, xefm_tool, quote_filenames_with_double_quotes, get_selected_or_cursor_files
from xefm.path import Path


class TestExternalPrograms(unittest.TestCase):
    """Tests for the external programs module"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_config = Mock()
        self.mock_log_manager = Mock()
        self.mock_log_manager.log_messages = []
        self.mock_log_manager.restore_stdio = Mock()
        self.mock_renderer = Mock()
        
        # Create manager with renderer
        self.manager = ExternalProgramManager(
            self.mock_config,
            self.mock_log_manager,
            self.mock_renderer
        )
    
    def test_init_with_renderer(self):
        """Test that ExternalProgramManager initializes with renderer"""
        self.assertEqual(self.manager.config, self.mock_config)
        self.assertEqual(self.manager.log_manager, self.mock_log_manager)
        self.assertEqual(self.manager.renderer, self.mock_renderer)
    
    @patch('builtins.input', return_value='')
    @patch('xefm.external_programs.subprocess.run')
    @patch('xefm.external_programs.os.chdir')
    @patch('xefm.colors.init_colors')
    @patch('xefm.log_manager.LogCapture')
    def test_execute_external_program_uses_renderer(self, mock_log_capture, mock_init_colors, mock_chdir, mock_subprocess, mock_input):
        """Test that execute_external_program uses renderer API"""
        # Set up mock pane manager
        mock_pane_manager = Mock()
        mock_pane_manager.left_pane = {
            'path': Path('/left'),
            'selected_files': [],
            'files': [Path('/left/file1.txt')],
            'focused_index': 0
        }
        mock_pane_manager.right_pane = {
            'path': Path('/right'),
            'selected_files': [],
            'files': [Path('/right/file2.txt')],
            'focused_index': 0
        }
        mock_pane_manager.get_current_pane = Mock(return_value=mock_pane_manager.left_pane)
        mock_pane_manager.get_inactive_pane = Mock(return_value=mock_pane_manager.right_pane)
        
        # Set up program
        program = {
            'name': 'Test Program',
            'command': ['echo', 'test'],
            'options': {'auto_return': True}
        }
        
        # Mock subprocess to return success
        mock_subprocess.return_value = Mock(returncode=0)
        
        # Execute program
        self.manager.execute_external_program(mock_pane_manager, program)
        
        # Verify renderer methods were called
        self.mock_renderer.clear.assert_called_once()
        self.mock_renderer.refresh.assert_called_once()
        self.mock_renderer.suspend.assert_called_once()
        self.mock_renderer.resume.assert_called_once()
        
        # Verify init_colors was called with renderer
        mock_init_colors.assert_called_once_with(self.mock_renderer)
    
    @patch('builtins.input', return_value='')
    @patch('xefm.external_programs.subprocess.run')
    @patch('xefm.external_programs.os.chdir')
    @patch('xefm.colors.init_colors')
    @patch('xefm.log_manager.LogCapture')
    def test_enter_subshell_mode_uses_renderer(self, mock_log_capture, mock_init_colors, mock_chdir, mock_subprocess, mock_input):
        """Test that enter_subshell_mode uses renderer API"""
        # Set up mock pane manager
        mock_pane_manager = Mock()
        mock_pane_manager.left_pane = {
            'path': Path('/left'),
            'selected_files': [],
            'files': [Path('/left/file1.txt')],
            'focused_index': 0
        }
        mock_pane_manager.right_pane = {
            'path': Path('/right'),
            'selected_files': [],
            'files': [Path('/right/file2.txt')],
            'focused_index': 0
        }
        mock_pane_manager.get_current_pane = Mock(return_value=mock_pane_manager.left_pane)
        mock_pane_manager.get_inactive_pane = Mock(return_value=mock_pane_manager.right_pane)
        
        # Mock subprocess to return immediately
        mock_subprocess.return_value = Mock(returncode=0)
        
        # Enter subshell mode
        self.manager.enter_subshell_mode(mock_pane_manager)
        
        # Verify renderer methods were called
        self.mock_renderer.clear.assert_called_once()
        self.mock_renderer.refresh.assert_called_once()
        self.mock_renderer.suspend.assert_called_once()
        self.mock_renderer.resume.assert_called_once()
        
        # Verify init_colors was called with renderer
        mock_init_colors.assert_called_once_with(self.mock_renderer)
    
    def test_no_curses_imports(self):
        """Test that the module doesn't import curses"""
        import xefm.external_programs
        
        # Check that curses is not in the module's namespace
        self.assertNotIn('curses', dir(xefm.external_programs))


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions"""
    
    def test_quote_filenames_with_double_quotes(self):
        """Test filename quoting with double quotes"""
        filenames = ['file1.txt', 'file with spaces.txt', 'file"with"quotes.txt']
        quoted = quote_filenames_with_double_quotes(filenames)
        
        self.assertEqual(quoted[0], '"file1.txt"')
        self.assertEqual(quoted[1], '"file with spaces.txt"')
        self.assertEqual(quoted[2], '"file\\"with\\"quotes.txt"')
    
    def test_get_selected_or_cursor_files_with_selection(self):
        """Test getting files when files are selected"""
        pane_data = {
            'selected_files': [Path('/dir/file1.txt'), Path('/dir/file2.txt')],
            'files': [Path('/dir/file1.txt'), Path('/dir/file2.txt'), Path('/dir/file3.txt')],
            'focused_index': 0
        }
        
        result = get_selected_or_cursor_files(pane_data)
        self.assertEqual(result, ['file1.txt', 'file2.txt'])
    
    def test_get_selected_or_cursor_files_without_selection(self):
        """Test getting files when no files are selected (uses cursor)"""
        pane_data = {
            'selected_files': [],
            'files': [Path('/dir/file1.txt'), Path('/dir/file2.txt'), Path('/dir/file3.txt')],
            'focused_index': 1
        }
        
        result = get_selected_or_cursor_files(pane_data)
        self.assertEqual(result, ['file2.txt'])
    
    def test_xefm_tool_function(self):
        """Test xefm_tool function returns tool path"""
        # This is a basic test - the function will return the tool name if not found
        result = xefm_tool('nonexistent_tool.sh')
        self.assertEqual(result, 'nonexistent_tool.sh')
