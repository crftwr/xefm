"""
Unit tests for text layout system edge cases.

This test module covers edge cases and boundary conditions for the text layout system:
- Empty segment lists
- Zero rendering width
- Single character segments
- All wide character text
- Mixed wide and narrow characters
- Spacer-only layouts

Requirements tested: Comprehensive testing
"""

import pytest
from unittest.mock import Mock, call

from xefm.text_layout import (
    draw_text_segments,
    AbbreviationSegment,
    FilepathSegment,
    AllOrNothingSegment,
    AsIsSegment,
    SpacerSegment
)


class TestEmptySegmentList:
    """Test behavior with empty segment lists."""
    
    def test_empty_list_does_not_crash(self):
        """Empty segment list should not crash and should not call renderer."""
        renderer = Mock()
        
        # Should not raise exception
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=[],
            rendering_width=80
        )
        
        # Renderer should not be called
        renderer.draw_text.assert_not_called()
    
    def test_empty_list_with_zero_width(self):
        """Empty segment list with zero width should not crash."""
        renderer = Mock()
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=[],
            rendering_width=0
        )
        
        renderer.draw_text.assert_not_called()


class TestZeroRenderingWidth:
    """Test behavior with zero rendering width."""
    
    def test_zero_width_with_text_segments(self):
        """Zero rendering width should not render any text."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("Hello"),
            AbbreviationSegment("World")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=0
        )
        
        # Renderer should not be called
        renderer.draw_text.assert_not_called()
    
    def test_zero_width_with_spacers(self):
        """Zero rendering width with spacers should not render."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("Text"),
            SpacerSegment(),
            AbbreviationSegment("More")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=0
        )
        
        renderer.draw_text.assert_not_called()


class TestSingleCharacterSegments:
    """Test behavior with single character segments."""
    
    def test_single_char_abbreviation(self):
        """Single character abbreviation segment should render correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("A")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render the single character
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == "A"  # text argument
    
    def test_single_char_with_width_one(self):
        """Single character with rendering width of 1 should fit."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("X")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=1
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == "X"
    
    def test_multiple_single_chars(self):
        """Multiple single character segments should render correctly."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("A"),
            AbbreviationSegment("B"),
            AbbreviationSegment("C")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render all three characters
        assert renderer.draw_text.call_count == 3
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        assert texts == ["A", "B", "C"]


class TestWideCharacterText:
    """Test behavior with wide character (CJK, emoji) text."""
    
    def test_all_wide_chars_chinese(self):
        """All Chinese characters should be handled correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("你好世界")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=20
        )
        
        # Should render the Chinese text
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "你好世界" in call_args[2]
    
    def test_all_wide_chars_japanese(self):
        """All Japanese characters should be handled correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("こんにちは")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=20
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "こんにちは" in call_args[2]
    
    def test_all_wide_chars_emoji(self):
        """Emoji characters should be handled correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("😀😃😄")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=20
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "😀😃😄" in call_args[2]
    
    def test_wide_chars_with_shortening(self):
        """Wide characters should be shortened correctly."""
        renderer = Mock()
        
        # Chinese text that needs shortening
        segments = [AbbreviationSegment("你好世界朋友")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=6  # Only room for 3 wide chars
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        rendered_text = call_args[2]
        
        # Should be shortened and contain ellipsis
        assert len(rendered_text) < len("你好世界朋友")
        assert "…" in rendered_text or len(rendered_text) <= 3
    
    def test_single_wide_char(self):
        """Single wide character should render correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("你")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == "你"


class TestMixedWideNarrowCharacters:
    """Test behavior with mixed wide and narrow characters."""
    
    def test_mixed_english_chinese(self):
        """Mixed English and Chinese should render correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("Hello 世界 World")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=30
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "Hello" in call_args[2]
        assert "世界" in call_args[2]
        assert "World" in call_args[2]
    
    def test_mixed_with_shortening(self):
        """Mixed text with shortening should handle wide chars correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("File: 文件名.txt")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        rendered_text = call_args[2]
        
        # Should be shortened
        assert len(rendered_text) < len("File: 文件名.txt")
    
    def test_mixed_emoji_text(self):
        """Mixed emoji and text should render correctly."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("Status: ✅ Complete")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=30
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "Status:" in call_args[2]
        assert "✅" in call_args[2]
        assert "Complete" in call_args[2]
    
    def test_alternating_wide_narrow(self):
        """Alternating wide and narrow characters should work."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("a你b好c世d界")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=20
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert "a你b好c世d界" in call_args[2]
    
    def test_filepath_with_wide_chars(self):
        """Filepath with wide characters should abbreviate correctly."""
        renderer = Mock()
        
        segments = [FilepathSegment("/home/用户/文档/项目/文件.txt")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=20
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        rendered_text = call_args[2]
        
        # Should be shortened and preserve filename
        assert "文件.txt" in rendered_text or "…" in rendered_text


class TestSpacerOnlyLayouts:
    """Test behavior with spacer-only layouts."""
    
    def test_single_spacer(self):
        """Single spacer should expand to fill width."""
        renderer = Mock()
        
        segments = [SpacerSegment()]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render 10 spaces
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == " " * 10
    
    def test_multiple_spacers(self):
        """Multiple spacers should distribute space equally."""
        renderer = Mock()
        
        segments = [
            SpacerSegment(),
            SpacerSegment(),
            SpacerSegment()
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=12
        )
        
        # Should render 3 spacers of 4 spaces each
        assert renderer.draw_text.call_count == 3
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        
        # Each spacer should be 4 spaces
        for text in texts:
            assert text == " " * 4
    
    def test_spacers_with_uneven_distribution(self):
        """Spacers with uneven width should distribute remainder correctly."""
        renderer = Mock()
        
        segments = [
            SpacerSegment(),
            SpacerSegment(),
            SpacerSegment()
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # 10 / 3 = 3 remainder 1
        # First spacer gets 4, others get 3
        assert renderer.draw_text.call_count == 3
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        
        # Check total width is 10
        total_width = sum(len(text) for text in texts)
        assert total_width == 10
        
        # First spacer should be longer
        assert len(texts[0]) == 4
        assert len(texts[1]) == 3
        assert len(texts[2]) == 3
    
    def test_spacer_only_with_zero_width(self):
        """Spacer-only layout with zero width should not render."""
        renderer = Mock()
        
        segments = [SpacerSegment()]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=0
        )
        
        renderer.draw_text.assert_not_called()
    
    def test_spacer_only_with_width_one(self):
        """Spacer-only layout with width 1 should render single space."""
        renderer = Mock()
        
        segments = [SpacerSegment()]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=1
        )
        
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == " "


class TestCombinedEdgeCases:
    """Test combinations of edge cases."""
    
    def test_single_char_with_spacer(self):
        """Single character with spacer should work correctly."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("A"),
            SpacerSegment(),
            AbbreviationSegment("B")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render A, spacer, B
        assert renderer.draw_text.call_count == 3
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        assert texts[0] == "A"
        assert texts[1] == " " * 8  # Spacer fills remaining space
        assert texts[2] == "B"
    
    def test_wide_char_with_spacer(self):
        """Wide character with spacer should work correctly."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("你"),
            SpacerSegment(),
            AbbreviationSegment("好")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render both wide chars with spacer
        assert renderer.draw_text.call_count == 3
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        assert texts[0] == "你"
        assert texts[2] == "好"
        # Spacer should fill remaining space (10 - 2 - 2 = 6)
        assert len(texts[1]) == 6
    
    def test_all_or_nothing_with_zero_width(self):
        """AllOrNothingSegment with zero width should return empty."""
        renderer = Mock()
        
        segments = [AllOrNothingSegment("Text")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=0
        )
        
        # Should not render anything
        renderer.draw_text.assert_not_called()
    
    def test_as_is_with_zero_width(self):
        """AsIsSegment with zero width should still try to render."""
        renderer = Mock()
        
        segments = [AsIsSegment("Text")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=0
        )
        
        # AsIsSegment never shortens, but with zero width nothing renders
        renderer.draw_text.assert_not_called()
    
    def test_mixed_segment_types_single_chars(self):
        """Mixed segment types with single characters."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment("A"),
            AsIsSegment("B"),
            AllOrNothingSegment("C"),
            AsIsSegment("D")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # All should render
        assert renderer.draw_text.call_count == 4
        texts = [call[0][2] for call in renderer.draw_text.call_args_list]
        assert texts == ["A", "B", "C", "D"]
    
    def test_empty_text_segments(self):
        """Segments with empty text should not crash."""
        renderer = Mock()
        
        segments = [
            AbbreviationSegment(""),
            SpacerSegment(),
            AbbreviationSegment("")
        ]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Only spacer should render
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[2] == " " * 10


class TestNegativeAndInvalidInputs:
    """Test behavior with negative and invalid inputs."""
    
    def test_negative_rendering_width(self):
        """Negative rendering width should be treated as zero."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("Text")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=0,
            segments=segments,
            rendering_width=-10
        )
        
        # Should not render
        renderer.draw_text.assert_not_called()
    
    def test_negative_row(self):
        """Negative row should be clipped to zero."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("Text")]
        
        draw_text_segments(
            renderer=renderer,
            row=-5,
            col=0,
            segments=segments,
            rendering_width=10
        )
        
        # Should render at row 0
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[0] == 0  # row argument
    
    def test_negative_col(self):
        """Negative col should be clipped to zero."""
        renderer = Mock()
        
        segments = [AbbreviationSegment("Text")]
        
        draw_text_segments(
            renderer=renderer,
            row=0,
            col=-5,
            segments=segments,
            rendering_width=10
        )
        
        # Should render at col 0
        renderer.draw_text.assert_called_once()
        call_args = renderer.draw_text.call_args[0]
        assert call_args[1] == 0  # col argument
    
    def test_none_renderer_raises_error(self):
        """None renderer should raise ValueError."""
        segments = [AbbreviationSegment("Text")]
        
        with pytest.raises(ValueError, match="renderer cannot be None"):
            draw_text_segments(
                renderer=None,
                row=0,
                col=0,
                segments=segments,
                rendering_width=10
            )
    
    def test_none_segments_raises_error(self):
        """None segments should raise ValueError."""
        renderer = Mock()
        
        with pytest.raises(ValueError, match="segments cannot be None"):
            draw_text_segments(
                renderer=renderer,
                row=0,
                col=0,
                segments=None,
                rendering_width=10
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
