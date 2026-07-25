"""
Test color system migration to TTK

Run with: python -m pytest test/test_colors_ttk_migration.py -v
"""

from xefm.colors import (
    init_colors,
    get_file_color,
    get_header_color,
    get_footer_color,
    get_status_color,
    get_error_color,
    get_boundary_color,
    get_log_color,
    get_line_number_color,
    get_syntax_color,
    get_search_color,
    get_search_match_color,
    get_search_current_color,
    get_background_color_pair,
    COLOR_REGULAR_FILE,
    COLOR_DIRECTORIES,
    COLOR_EXECUTABLES,
    COLOR_HEADER,
    COLOR_STATUS,
    TextAttribute,
)


class MockRenderer:
    """Mock TTK renderer for testing"""
    
    def __init__(self):
        self.color_pairs = {}
    
    def init_color_pair(self, pair_id, fg_color, bg_color):
        """Store color pair initialization"""
        self.color_pairs[pair_id] = {
            'fg': fg_color,
            'bg': bg_color
        }


def test_init_colors_dark_scheme():
    """Test color initialization with dark scheme"""
    renderer = MockRenderer()
    
    # Initialize colors with dark scheme
    init_colors(renderer, 'dark')
    
    # Verify color pairs were initialized
    assert len(renderer.color_pairs) > 0
    
    # Check that key color pairs exist
    assert COLOR_REGULAR_FILE in renderer.color_pairs
    assert COLOR_DIRECTORIES in renderer.color_pairs
    assert COLOR_EXECUTABLES in renderer.color_pairs
    assert COLOR_HEADER in renderer.color_pairs
    assert COLOR_STATUS in renderer.color_pairs
    
    # Verify RGB tuples are correct format
    for pair_id, colors in renderer.color_pairs.items():
        fg = colors['fg']
        bg = colors['bg']
        
        # Check that colors are RGB tuples
        assert isinstance(fg, tuple), f"Foreground color for pair {pair_id} is not a tuple"
        assert len(fg) == 3, f"Foreground color for pair {pair_id} doesn't have 3 components"
        assert isinstance(bg, tuple), f"Background color for pair {pair_id} is not a tuple"
        assert len(bg) == 3, f"Background color for pair {pair_id} doesn't have 3 components"
        
        # Check that RGB values are in valid range
        for component in fg + bg:
            assert 0 <= component <= 255, f"RGB component {component} out of range"
    
    print("✓ Dark scheme color initialization test passed")


def test_init_colors_light_scheme():
    """Test color initialization with light scheme"""
    renderer = MockRenderer()
    
    # Initialize colors with light scheme
    init_colors(renderer, 'light')
    
    # Verify color pairs were initialized
    assert len(renderer.color_pairs) > 0
    
    # Check that key color pairs exist
    assert COLOR_REGULAR_FILE in renderer.color_pairs
    assert COLOR_DIRECTORIES in renderer.color_pairs
    
    print("✓ Light scheme color initialization test passed")


def test_color_helper_functions_return_tuples():
    """Test that color helper functions return (color_pair, attributes) tuples"""
    
    # Test file colors
    color_pair, attributes = get_file_color(is_dir=False, is_executable=False, is_focused=False, is_active=True)
    assert isinstance(color_pair, int), "Color pair should be an integer"
    assert isinstance(attributes, int), "Attributes should be an integer"
    assert color_pair == COLOR_REGULAR_FILE
    assert attributes == TextAttribute.NORMAL
    
    # Test directory colors
    color_pair, attributes = get_file_color(is_dir=True, is_executable=False, is_focused=False, is_active=True)
    assert color_pair == COLOR_DIRECTORIES
    assert attributes == TextAttribute.NORMAL
    
    # Test header colors
    color_pair, attributes = get_header_color(is_active=False)
    assert isinstance(color_pair, int)
    assert attributes == TextAttribute.NORMAL
    
    color_pair, attributes = get_header_color(is_active=True)
    assert attributes == TextAttribute.BOLD
    
    # Test footer colors
    color_pair, attributes = get_footer_color(is_active=False)
    assert attributes == TextAttribute.NORMAL
    
    color_pair, attributes = get_footer_color(is_active=True)
    assert attributes == TextAttribute.BOLD
    
    # Test status color
    color_pair, attributes = get_status_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test error color
    color_pair, attributes = get_error_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test boundary color
    color_pair, attributes = get_boundary_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test log colors
    color_pair, attributes = get_log_color("STDOUT")
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    color_pair, attributes = get_log_color("STDERR")
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test line number color
    color_pair, attributes = get_line_number_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test syntax colors (returns a single color id now, not a (pair, attr) tuple)
    color_pair = get_syntax_color("Keyword")
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test search colors
    color_pair, attributes = get_search_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    color_pair, attributes = get_search_match_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    color_pair, attributes = get_search_current_color()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    # Test background color pair
    color_pair, attributes = get_background_color_pair()
    assert isinstance(color_pair, int)
    assert isinstance(attributes, int)
    
    print("✓ Color helper functions return correct tuple format")


def test_selected_file_colors():
    """Test selected file color variations"""
    
    # Active selection
    color_pair, attributes = get_file_color(is_dir=False, is_executable=False, is_focused=True, is_active=True)
    assert isinstance(color_pair, int)
    assert attributes == TextAttribute.NORMAL
    
    # Inactive selection
    color_pair, attributes = get_file_color(is_dir=False, is_executable=False, is_focused=True, is_active=False)
    assert isinstance(color_pair, int)
    assert attributes == TextAttribute.NORMAL
    
    # Directory active selection
    color_pair, attributes = get_file_color(is_dir=True, is_executable=False, is_focused=True, is_active=True)
    assert isinstance(color_pair, int)
    assert attributes == TextAttribute.NORMAL
    
    # Executable active selection
    color_pair, attributes = get_file_color(is_dir=False, is_executable=True, is_focused=True, is_active=True)
    assert isinstance(color_pair, int)
    assert attributes == TextAttribute.NORMAL
    
    print("✓ Selected file colors test passed")


def test_rgb_color_values():
    """Test that RGB color values are properly defined"""
    renderer = MockRenderer()
    init_colors(renderer, 'dark')
    
    # Check a few specific colors to ensure they're reasonable
    # Directory color should be yellowish in dark scheme
    dir_colors = renderer.color_pairs[COLOR_DIRECTORIES]
    dir_fg = dir_colors['fg']
    
    # Yellow-ish color should have high R and G, lower B
    assert dir_fg[0] > 150, "Directory color R component should be high"
    assert dir_fg[1] > 150, "Directory color G component should be high"
    
    print("✓ RGB color values test passed")
