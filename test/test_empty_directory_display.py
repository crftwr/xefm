"""
Test empty directory display functionality

Run with: python -m pytest test/test_empty_directory_display.py -v
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock


class MockXeFM:
    """Mock XeFM class to test empty directory display"""
    
    def __init__(self):
        self.stdscr = Mock()
        self.log_height_ratio = 0.3
        self.drawn_text = []
        
    def draw_pane(self, pane_data, start_x, pane_width, is_active):
        """Simplified version of draw_pane method to test empty directory display"""
        # Safety checks to prevent crashes
        if pane_width < 10:  # Minimum viable pane width
            return
        if start_x < 0 or start_x >= 80:  # Mock screen width
            return
            
        height, width = 25, 80  # Mock screen dimensions
        # Allow log pane to be completely hidden (0 height) when ratio is 0
        calculated_height = int(height * self.log_height_ratio)
        log_height = calculated_height if self.log_height_ratio > 0 else 0
        display_height = height - log_height - 3  # Reserve space for header, footer, and status
        
        # Check if there are no files to display
        if not pane_data['files']:
            # Show "no items to show" message in the center of the pane
            message = "No items to show"
            message_y = 1 + display_height // 2  # Center vertically in the pane
            message_x = start_x + (pane_width - len(message)) // 2  # Center horizontally
            
            # Record what would be drawn
            self.drawn_text.append({
                'y': message_y,
                'x': message_x,
                'text': message,
                'color': 'error'
            })
            return
        
        # If there are files, record that files would be drawn
        for i, file_path in enumerate(pane_data['files'][:display_height]):
            self.drawn_text.append({
                'y': i + 1,
                'x': start_x + 1,
                'text': file_path.name,
                'color': 'normal'
            })


def test_empty_directory_display():
    """Test that empty directories show 'No items to show' message"""
    print("Testing empty directory display...")
    
    xefm = MockXeFM()
    
    # Test empty pane data
    empty_pane = {
        'files': [],
        'selected_index': 0,
        'scroll_offset': 0,
        'selected_files': set()
    }
    
    # Draw empty pane
    xefm.draw_pane(empty_pane, 0, 40, True)
    
    # Verify message was drawn
    assert len(xefm.drawn_text) == 1, f"Expected 1 message, got {len(xefm.drawn_text)}"
    
    message = xefm.drawn_text[0]
    assert message['text'] == "No items to show", f"Expected 'No items to show', got '{message['text']}'"
    assert message['color'] == 'error', f"Expected error color, got '{message['color']}'"
    
    # Verify message is centered
    expected_x = 0 + (40 - len("No items to show")) // 2
    assert message['x'] == expected_x, f"Expected x={expected_x}, got x={message['x']}"
    
    print("✅ Empty directory display test passed!")


def test_non_empty_directory_display():
    """Test that non-empty directories show files normally"""
    print("\nTesting non-empty directory display...")
    
    xefm = MockXeFM()
    
    # Create mock file paths
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create some test files
        file1 = temp_path / "file1.txt"
        file2 = temp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        
        # Test non-empty pane data
        non_empty_pane = {
            'files': [file1, file2],
            'selected_index': 0,
            'scroll_offset': 0,
            'selected_files': set()
        }
        
        # Draw non-empty pane
        xefm.draw_pane(non_empty_pane, 0, 40, True)
        
        # Verify files were drawn (not the "no items" message)
        assert len(xefm.drawn_text) == 2, f"Expected 2 files, got {len(xefm.drawn_text)}"
        
        # Verify file names are shown
        file_names = [item['text'] for item in xefm.drawn_text]
        assert "file1.txt" in file_names, "Should show file1.txt"
        assert "file2.txt" in file_names, "Should show file2.txt"
        
        # Verify no error message
        assert "No items to show" not in file_names, "Should not show 'No items to show' when files exist"
    
    print("✅ Non-empty directory display test passed!")


def test_message_positioning():
    """Test that the message is positioned correctly in different pane sizes"""
    print("\nTesting message positioning...")
    
    xefm = MockXeFM()
    
    empty_pane = {
        'files': [],
        'selected_index': 0,
        'scroll_offset': 0,
        'selected_files': set()
    }
    
    # Test different pane widths
    test_cases = [
        {'start_x': 0, 'width': 40},
        {'start_x': 40, 'width': 40},
        {'start_x': 10, 'width': 60},
    ]
    
    for case in test_cases:
        xefm.drawn_text = []  # Reset
        xefm.draw_pane(empty_pane, case['start_x'], case['width'], True)
        
        assert len(xefm.drawn_text) == 1, f"Expected 1 message for case {case}"
        
        message = xefm.drawn_text[0]
        expected_x = case['start_x'] + (case['width'] - len("No items to show")) // 2
        
        assert message['x'] == expected_x, f"For case {case}, expected x={expected_x}, got x={message['x']}"
        assert message['text'] == "No items to show", f"Message text should be consistent"
    
    print("✅ Message positioning test passed!")


def test_narrow_pane_handling():
    """Test that narrow panes are handled gracefully"""
    print("\nTesting narrow pane handling...")
    
    xefm = MockXeFM()
    
    empty_pane = {
        'files': [],
        'selected_index': 0,
        'scroll_offset': 0,
        'selected_files': set()
    }
    
    # Test very narrow pane (should be skipped due to safety check)
    xefm.draw_pane(empty_pane, 0, 5, True)
    
    # Should not draw anything due to safety check
    assert len(xefm.drawn_text) == 0, "Very narrow panes should not draw anything"
    
    # Test minimum viable pane width
    xefm.drawn_text = []
    xefm.draw_pane(empty_pane, 0, 20, True)
    
    # Should draw the message
    assert len(xefm.drawn_text) == 1, "Minimum viable pane should draw message"
    assert xefm.drawn_text[0]['text'] == "No items to show"
    
    print("✅ Narrow pane handling test passed!")
