"""
Text Layout System for XeFM.

This module provides a comprehensive API for rendering text segments with intelligent
width management, color attributes, and flexible shortening strategies. It handles
the complete text layout and rendering pipeline, including:

- Layout calculation with priority-based shortening
- Multiple shortening strategies (abbreviation, filepath, truncate, all-or-nothing, as-is)
- Spacer support for expandable whitespace
- Wide character support (CJK, emoji)
- Color and attribute management per segment
- Integration with TTK rendering backend

This system has replaced the legacy xefm_string_width.py module.

Basic Usage:
    from xefm.text_layout import draw_text_segments, AbbreviationSegment, SpacerSegment
    
    segments = [
        AbbreviationSegment("Long filename.txt", priority=1, min_length=10),
        SpacerSegment(),
        AbbreviationSegment("Status", priority=0, min_length=3)
    ]
    
    draw_text_segments(renderer, row=0, col=0, segments=segments, 
                      rendering_width=80, default_color=1)

Segment Types:
    - AbbreviationSegment: Shortens with ellipsis (left/middle/right position)
    - FilepathSegment: Intelligently abbreviates filesystem paths
    - TruncateSegment: Removes characters from end without ellipsis
    - AllOrNothingSegment: Either keeps full text or removes entirely
    - AsIsSegment: Never shortens regardless of width constraints
    - SpacerSegment: Expands with whitespace when space available

Priority-Based Shortening:
    Segments with higher priority values are shortened first. When space becomes
    available, segments are restored in reverse priority order (lower values first).
    
    Example:
        segments = [
            AbbreviationSegment("Important", priority=0, min_length=5),
            SpacerSegment(),
            AbbreviationSegment("Less important", priority=1, min_length=3)
        ]
        # "Less important" will be shortened before "Important"

Wide Character Support:
    All operations properly handle wide characters (CJK, emoji) which occupy
    2 terminal columns instead of 1. Wide characters are never split at boundaries.
    
    Example:
        segments = [AbbreviationSegment("Hello 世界 World")]
        draw_text_segments(renderer, 0, 0, segments, 10)
        # Properly accounts for wide characters taking 2 columns each
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Union, Optional
import unicodedata

# PuiKit text helpers for wide-character support. display_width is aliased to
# the historical name get_display_width to avoid churning every call site.
from puikit.text import display_width as get_display_width, truncate_to_width

# XeFM unified logging system
from xefm.log_manager import getLogger

# Initialize logger
logger = getLogger("TextLayout")


# ============================================================================
# Wide Character Support Utilities
# ============================================================================
# Note: We use PuiKit's truncate_to_width() directly with ellipsis="" for pure
# truncation. No wrapper needed - it handles the wide-character edge cases.


@dataclass
class TextSegment(ABC):
    """
    Abstract base class for text segments.
    
    A text segment represents a portion of text with configuration for how it
    should be shortened, rendered, and styled.
    
    Attributes:
        text: The text content of this segment (automatically normalized to NFC)
        priority: Shortening priority (higher values shortened first, default 0)
        min_length: Minimum characters to preserve when shortening (default 0)
        color_pair: Terminal color pair number, None uses default (default None)
        attributes: Terminal text attributes (bold, underline, etc.), None uses default (default None)
    
    Note:
        Text is automatically normalized to NFC form during initialization to ensure
        consistent character representation across platforms (especially macOS NFD filenames).
    """
    text: str
    priority: int = 0
    min_length: int = 0
    color_pair: Optional[int] = None
    attributes: Optional[int] = None
    
    def __post_init__(self):
        """
        Normalize text to NFC form after initialization.
        
        This ensures all text is in NFC (Canonical Composition) form, which:
        - Handles macOS NFD decomposed filenames correctly
        - Ensures consistent character representation
        - Allows all methods to assume text is already normalized
        
        Note: Subclasses should call super().__post_init__() if they override this.
        """
        # Normalize text to NFC form for consistent character representation
        # This is done once at initialization rather than repeatedly in methods
        object.__setattr__(self, 'text', unicodedata.normalize('NFC', self.text))
    
    @abstractmethod
    def shorten(self, target_width: int) -> str:
        """
        Shorten the text to fit within target_width columns.
        
        Each subclass implements its own shortening strategy.
        
        Args:
            target_width: Target display width in terminal columns
            
        Returns:
            Shortened text that fits within target_width
        """
        pass


@dataclass
class SpacerSegment:
    """
    A special segment that expands with whitespace when text doesn't need shortening.
    
    Spacers are collapsed to zero width when shortening is needed, and expanded
    to fill available space when the total text width is less than rendering width.
    
    Attributes:
        color_pair: Terminal color pair number, None uses default (default None)
        attributes: Terminal text attributes, None uses default (default None)
    """
    color_pair: Optional[int] = None
    attributes: Optional[int] = None
    
    def __post_init__(self):
        """Validate segment configuration after initialization."""
        # Validate color_pair if specified
        if self.color_pair is not None and (self.color_pair < 0 or self.color_pair > 255):
            logger.warning(
                f"Invalid color_pair {self.color_pair} in SpacerSegment "
                f"(must be 0-255), will use default color"
            )
            self.color_pair = None


@dataclass
class AbbreviationSegment(TextSegment):
    """
    A text segment that shortens by replacing removed content with an ellipsis.
    
    The ellipsis can be placed at the left, middle, or right of the text based
    on the abbrev_position setting.
    
    Attributes:
        abbrev_position: Where to place ellipsis ('left', 'middle', 'right', default 'right')
    """
    abbrev_position: str = 'right'
    
    def __post_init__(self):
        """Validate segment configuration after initialization."""
        # Call parent to normalize text
        super().__post_init__()
        
        # Validate abbrev_position
        if self.abbrev_position not in ('left', 'middle', 'right'):
            logger.warning(
                f"Invalid abbrev_position '{self.abbrev_position}' in AbbreviationSegment, "
                f"falling back to 'right'. Valid values: 'left', 'middle', 'right'"
            )
            self.abbrev_position = 'right'
        
        # Validate priority (should be non-negative)
        if self.priority < 0:
            logger.warning(f"Negative priority {self.priority} in AbbreviationSegment, treating as 0")
            self.priority = 0
        
        # Validate min_length (should be non-negative)
        if self.min_length < 0:
            logger.warning(f"Negative min_length {self.min_length} in AbbreviationSegment, treating as 0")
            self.min_length = 0
        
        # Validate color_pair if specified
        if self.color_pair is not None and (self.color_pair < 0 or self.color_pair > 255):
            logger.warning(
                f"Invalid color_pair {self.color_pair} in AbbreviationSegment "
                f"(must be 0-255), will use default color"
            )
            self.color_pair = None
    
    def shorten(self, target_width: int) -> str:
        """
        Shorten text by replacing removed content with an ellipsis.
        
        Args:
            target_width: Target display width in terminal columns
            
        Returns:
            Shortened text with ellipsis at the specified position
            
        Note:
            TTK's get_display_width() and truncate_to_width() already normalize
            to NFC internally, so no explicit normalization is needed here.
        """
        try:
            current_width = get_display_width(self.text)
            
            # If already fits, return as-is (normalized by get_display_width)
            if current_width <= target_width:
                # Need to normalize since we're returning early
                return self.text
            
            # Handle edge cases
            if target_width == 0:
                return ""
            
            ellipsis = "…"
            ellipsis_width = get_display_width(ellipsis)
            
            if target_width == 1:
                # Only room for ellipsis or single character
                if ellipsis_width <= 1:
                    return ellipsis
                normalized_text = self.text
                return normalized_text[0] if len(normalized_text) > 0 else ""
            
            # If text is shorter than ellipsis, just truncate
            if target_width < ellipsis_width:
                return truncate_to_width(self.text, target_width, ellipsis="")
            
            # Validate abbrev_position (should have been validated in __post_init__, but double-check)
            position = self.abbrev_position
            if position not in ('left', 'middle', 'right'):
                logger.warning(f"Invalid abbrev_position '{position}', falling back to 'right'")
                position = 'right'
            
            # Calculate available width for actual text (minus ellipsis)
            available_width = target_width - ellipsis_width
            
            # Normalize text once for use in truncation operations
            normalized_text = self.text
            
            if position == 'right':
                # Keep left portion, ellipsis at end
                left_part = truncate_to_width(normalized_text, available_width, ellipsis="")
                return left_part + ellipsis
            
            elif position == 'left':
                # Keep right portion, ellipsis at start
                # We need to find where to start from the right
                right_part = self._truncate_from_right(normalized_text, available_width)
                return ellipsis + right_part
            
            else:  # middle
                # Split available width between left and right
                left_width = available_width // 2
                right_width = available_width - left_width
                
                left_part = truncate_to_width(normalized_text, left_width, ellipsis="")
                right_part = self._truncate_from_right(normalized_text, right_width)
                return left_part + ellipsis + right_part
                
        except Exception as e:
            logger.error(f"AbbreviationSegment.shorten failed for text '{self.text}': {e}")
            # Fall back to simple truncation
            try:
                return truncate_to_width(self.text, target_width, ellipsis="")
            except Exception as e2:
                logger.error(f"Fallback truncation also failed: {e2}")
                # Last resort: return original text or empty string
                return self.text if target_width > 0 else ""
    
    def _truncate_from_right(self, text: str, target_width: int) -> str:
        """
        Truncate text from the right side to fit target_width.
        
        This is used for left and middle abbreviation positions where we need
        to preserve the right portion of the text.
        
        Args:
            text: Text to truncate
            target_width: Target display width
            
        Returns:
            Right portion of text that fits within target_width
        """
        try:
            if target_width <= 0:
                return ""
            
            # Start from the end and work backwards
            result = ""
            current_width = 0
            
            for char in reversed(text):
                char_width = get_display_width(char)
                if current_width + char_width > target_width:
                    break
                result = char + result
                current_width += char_width
            
            return result
            
        except Exception as e:
            logger.error(f"_truncate_from_right failed: {e}")
            # Fall back to simple character-based truncation from right
            if target_width <= 0:
                return ""
            return text[-target_width:] if len(text) >= target_width else text


@dataclass
class FilepathSegment(TextSegment):
    """
    A text segment that shortens filesystem paths by removing directory levels.
    
    When shortening is needed, entire directory components are removed (replaced
    with ellipsis) before the filename is abbreviated. This preserves the filename
    as much as possible.
    
    Attributes:
        abbrev_position: Where to place ellipsis when abbreviating filename ('left', 'middle', 'right', default 'right')
    """
    abbrev_position: str = 'right'
    
    def __post_init__(self):
        """Validate segment configuration after initialization."""
        # Call parent to normalize text
        super().__post_init__()
        
        # Validate abbrev_position
        if self.abbrev_position not in ('left', 'middle', 'right'):
            logger.warning(
                f"Invalid abbrev_position '{self.abbrev_position}' in FilepathSegment, "
                f"falling back to 'right'. Valid values: 'left', 'middle', 'right'"
            )
            self.abbrev_position = 'right'
        
        # Validate priority (should be non-negative)
        if self.priority < 0:
            logger.warning(f"Negative priority {self.priority} in FilepathSegment, treating as 0")
            self.priority = 0
        
        # Validate min_length (should be non-negative)
        if self.min_length < 0:
            logger.warning(f"Negative min_length {self.min_length} in FilepathSegment, treating as 0")
            self.min_length = 0
        
        # Validate color_pair if specified
        if self.color_pair is not None and (self.color_pair < 0 or self.color_pair > 255):
            logger.warning(
                f"Invalid color_pair {self.color_pair} in FilepathSegment "
                f"(must be 0-255), will use default color"
            )
            self.color_pair = None
            self.color_pair = None
    
    def shorten(self, target_width: int) -> str:
        """
        Shorten filesystem path by removing directory levels.
        
        Strategy:
        1. Parse path into directory components and filename
        2. Remove directory levels from left to right, replacing with ellipsis
        3. If still too long, abbreviate the filename itself
        
        Args:
            target_width: Target display width in terminal columns
            
        Returns:
            Shortened path with directory levels removed as needed
        """
        try:
            # Use helper function for normalization
            normalized_text = self.text
            current_width = get_display_width(normalized_text)
            
            # If already fits, return as-is
            if current_width <= target_width:
                return normalized_text
            
            # Handle edge cases
            if target_width == 0:
                return ""
            
            ellipsis = "…"
            ellipsis_width = get_display_width(ellipsis)
            
            # Detect path separator (handle both Unix and Windows paths)
            separator = '/'
            if '\\' in normalized_text and '/' not in normalized_text:
                separator = '\\'
            elif '\\' in normalized_text and '/' in normalized_text:
                # Mixed separators, prefer forward slash
                separator = '/'
            
            # Split path into components
            components = normalized_text.split(separator)
            
            # Handle edge case: single component (no directories)
            if len(components) <= 1:
                # Just abbreviate the filename
                return self._abbreviate_filename(normalized_text, target_width)
            
            # Separate directories from filename
            filename = components[-1]
            directories = components[:-1]
            
            # Strategy: Keep directories from both ends, remove from middle
            # This matches the legacy FilepathStrategy behavior
            num_dirs = len(directories)
            
            # First try: keep all directories (no ellipsis)
            if num_dirs > 0:
                test_path = separator.join(directories) + separator + filename
                path_width = get_display_width(test_path)
                if path_width <= target_width:
                    return test_path
            
            # Try removing directories from the center outward, one at a time
            # Generate removal order: center first, then alternate RIGHT-LEFT to maintain balance
            # Rule: left_count <= right_count (where right includes filename)
            # 
            # Strategy: Remove center first, then alternate RIGHT-LEFT-RIGHT-LEFT
            # This maintains balance because filename is always on the right side
            
            center = num_dirs // 2
            
            # Build removal order: center, then alternate RIGHT-LEFT
            removal_order = [center]
            
            # After removing center, alternate starting with RIGHT (to balance filename)
            left = center - 1
            right = center + 1
            
            while left >= 0 or right < num_dirs:
                # Add right first (to balance filename on right)
                if right < num_dirs:
                    removal_order.append(right)
                    right += 1
                # Then add left
                if left >= 0:
                    removal_order.append(left)
                    left -= 1
            
            # Try removing directories in the calculated order
            removed_set = set()
            for remove_idx in removal_order:
                removed_set.add(remove_idx)
                
                # Build path with remaining directories
                kept_dirs = [directories[i] for i in range(num_dirs) if i not in removed_set]
                
                if kept_dirs:
                    path_parts = kept_dirs + [filename]
                    # Insert ellipsis where directories were removed
                    # Find the first gap in kept indices
                    kept_indices = [i for i in range(num_dirs) if i not in removed_set]
                    if kept_indices:
                        # Check if there's a gap (removed directories anywhere)
                        has_gap = False
                        for i in range(len(kept_indices) - 1):
                            if kept_indices[i+1] - kept_indices[i] > 1:
                                has_gap = True
                                break
                        
                        # Check for gap at beginning or end
                        has_gap_at_start = kept_indices[0] > 0
                        has_gap_at_end = kept_indices[-1] < num_dirs - 1
                        
                        if has_gap or has_gap_at_start or has_gap_at_end:
                            # There's a gap, need ellipsis
                            # Split kept directories at the gap
                            start_dirs = []
                            end_dirs = []
                            gap_found = False
                            
                            for i in range(len(kept_indices)):
                                if not gap_found:
                                    if i < len(kept_indices) - 1 and kept_indices[i+1] - kept_indices[i] > 1:
                                        start_dirs = [directories[idx] for idx in kept_indices[:i+1]]
                                        end_dirs = [directories[idx] for idx in kept_indices[i+1:]]
                                        gap_found = True
                            
                            if not gap_found and has_gap_at_start:
                                # Gap at the beginning
                                end_dirs = kept_dirs
                                start_dirs = []
                            elif not gap_found and has_gap_at_end:
                                # Gap at the end only
                                start_dirs = kept_dirs
                                end_dirs = []
                            
                            if start_dirs or end_dirs:
                                path_parts = start_dirs + [ellipsis] + end_dirs + [filename]
                            else:
                                path_parts = [ellipsis] + [filename]
                        else:
                            # No gap, all kept directories are contiguous
                            path_parts = kept_dirs + [filename]
                    else:
                        path_parts = [ellipsis, filename]
                else:
                    path_parts = [ellipsis, filename]
                
                test_path = separator.join(path_parts)
                path_width = get_display_width(test_path)
                if path_width <= target_width:
                    return test_path
            
            # All directories removed, just ellipsis + separator + filename
            abbreviated_path = ellipsis + separator + filename
            path_width = get_display_width(abbreviated_path)
            
            if path_width <= target_width:
                return abbreviated_path
            
            # Still too long, need to abbreviate the filename itself
            # Calculate space available for filename
            prefix = ellipsis + separator
            prefix_width = get_display_width(prefix)
            
            if prefix_width >= target_width:
                # Not even room for prefix, just abbreviate filename alone
                return self._abbreviate_filename(filename, target_width)
            
            filename_width = target_width - prefix_width
            abbreviated_filename = self._abbreviate_filename(filename, filename_width)
            
            return prefix + abbreviated_filename
            
        except Exception as e:
            logger.error(f"FilepathSegment.shorten failed for path '{self.text}': {e}")
            # Fall back to simple truncation
            try:
                normalized_text = self.text
                return truncate_to_width(normalized_text, target_width, ellipsis="")
            except Exception as e2:
                logger.error(f"Fallback truncation also failed: {e2}")
                # Last resort: return original text or empty string
                return self.text if target_width > 0 else ""
    
    def _abbreviate_filename(self, filename: str, target_width: int) -> str:
        """
        Abbreviate a filename using the specified abbreviation position.
        
        Args:
            filename: Filename to abbreviate
            target_width: Target display width
            
        Returns:
            Abbreviated filename
        """
        try:
            current_width = get_display_width(filename)
            
            if current_width <= target_width:
                return filename
            
            if target_width == 0:
                return ""
            
            ellipsis = "…"
            ellipsis_width = get_display_width(ellipsis)
            
            if target_width < ellipsis_width:
                return truncate_to_width(filename, target_width, ellipsis="")
            
            # Validate abbrev_position (should have been validated in __post_init__, but double-check)
            position = self.abbrev_position
            if position not in ('left', 'middle', 'right'):
                logger.warning(f"Invalid abbrev_position '{position}', falling back to 'right'")
                position = 'right'
            
            available_width = target_width - ellipsis_width
            
            if position == 'right':
                left_part = truncate_to_width(filename, available_width, ellipsis="")
                return left_part + ellipsis
            
            elif position == 'left':
                right_part = self._truncate_from_right(filename, available_width)
                return ellipsis + right_part
            
            else:  # middle
                left_width = available_width // 2
                right_width = available_width - left_width
                
                left_part = truncate_to_width(filename, left_width, ellipsis="")
                right_part = self._truncate_from_right(filename, right_width)
                return left_part + ellipsis + right_part
                
        except Exception as e:
            logger.error(f"_abbreviate_filename failed for '{filename}': {e}")
            # Fall back to simple truncation
            try:
                return truncate_to_width(filename, target_width, ellipsis="")
            except Exception as e2:
                logger.error(f"Fallback truncation also failed: {e2}")
                return filename if target_width > 0 else ""
    
    def _truncate_from_right(self, text: str, target_width: int) -> str:
        """
        Truncate text from the right side to fit target_width.
        
        Args:
            text: Text to truncate
            target_width: Target display width
            
        Returns:
            Right portion of text that fits within target_width
        """
        try:
            if target_width <= 0:
                return ""
            
            result = ""
            current_width = 0
            
            for char in reversed(text):
                char_width = get_display_width(char)
                if current_width + char_width > target_width:
                    break
                result = char + result
                current_width += char_width
            
            return result
            
        except Exception as e:
            logger.error(f"_truncate_from_right failed: {e}")
            # Fall back to simple character-based truncation from right
            if target_width <= 0:
                return ""
            return text[-target_width:] if len(text) >= target_width else text


@dataclass
class AllOrNothingSegment(TextSegment):
    """
    A text segment that is either kept in full or removed entirely.
    
    This segment type never partially shortens. If the full text doesn't fit
    within the target width, it returns an empty string.
    """
    
    def __post_init__(self):
        """Validate segment configuration after initialization."""
        # Call parent to normalize text
        super().__post_init__()
        
        # Validate priority (should be non-negative)
        if self.priority < 0:
            logger.warning(f"Negative priority {self.priority} in AllOrNothingSegment, treating as 0")
            self.priority = 0
        
        # Validate min_length (should be non-negative)
        if self.min_length < 0:
            logger.warning(f"Negative min_length {self.min_length} in AllOrNothingSegment, treating as 0")
            self.min_length = 0
        
        # Validate color_pair if specified
        if self.color_pair is not None and (self.color_pair < 0 or self.color_pair > 255):
            logger.warning(
                f"Invalid color_pair {self.color_pair} in AllOrNothingSegment "
                f"(must be 0-255), will use default color"
            )
            self.color_pair = None
    
    def shorten(self, target_width: int) -> str:
        """
        Return full text if it fits, otherwise return empty string.
        
        Args:
            target_width: Target display width in terminal columns
            
        Returns:
            Full text if it fits, empty string otherwise
        """
        try:
            # Use helper function for normalization
            normalized_text = self.text
            current_width = get_display_width(normalized_text)
            
            # All or nothing: either keep full text or remove entirely
            if current_width <= target_width:
                return normalized_text
            else:
                return ""
                
        except Exception as e:
            logger.error(f"AllOrNothingSegment.shorten failed for text '{self.text}': {e}")
            # In case of error, return empty string (safer than returning potentially malformed text)
            return ""


@dataclass
class AsIsSegment(TextSegment):
    """
    A text segment that never shortens regardless of width constraints.
    
    This segment type always returns its original text, even if it exceeds
    the target width. Use this for text that must never be modified.
    """
    
    def __post_init__(self):
        """Validate segment configuration after initialization."""
        # Call parent to normalize text
        super().__post_init__()
        
        # Validate priority (should be non-negative)
        if self.priority < 0:
            logger.warning(f"Negative priority {self.priority} in AsIsSegment, treating as 0")
            self.priority = 0
        
        # Validate min_length (should be non-negative)
        if self.min_length < 0:
            logger.warning(f"Negative min_length {self.min_length} in AsIsSegment, treating as 0")
            self.min_length = 0
        
        # Validate color_pair if specified
        if self.color_pair is not None and (self.color_pair < 0 or self.color_pair > 255):
            logger.warning(
                f"Invalid color_pair {self.color_pair} in AsIsSegment "
                f"(must be 0-255), will use default color"
            )
            self.color_pair = None
    
    def shorten(self, target_width: int) -> str:
        """
        Always return the original text unchanged.
        
        Args:
            target_width: Target display width (ignored)
            
        Returns:
            Original text unchanged
        """
        try:
            # Use helper function for normalization
            normalized_text = self.text
            
            # Always return original text, never shorten
            return normalized_text
            
        except Exception as e:
            logger.error(f"AsIsSegment.shorten failed for text '{self.text}': {e}")
            # Return original text even if normalization failed
            return self.text


# ============================================================================
# Layout Calculation Engine
# ============================================================================

@dataclass
class LayoutState:
    """
    Internal state during layout calculation.
    
    This dataclass tracks the state of all segments during the layout calculation
    process, including their current widths, original widths, and which segments
    are spacers.
    
    Attributes:
        segments: List of text and spacer segments to layout
        current_widths: Current display width of each segment (modified during layout)
        original_widths: Original display width of each segment (0 for spacers)
        total_width: Current total width of all segments combined
        target_width: Target rendering width in terminal columns
        spacer_indices: Indices of spacer segments in the segments list
    """
    segments: List[Union[TextSegment, SpacerSegment]]
    current_widths: List[int]
    original_widths: List[int]
    total_width: int
    target_width: int
    spacer_indices: List[int]


def collapse_spacers(state: LayoutState) -> None:
    """
    Collapse all spacer segments to zero width.
    
    This function is called when shortening is needed. Before shortening any
    text segments, all spacers are collapsed to zero width to maximize available
    space for text content.
    
    Args:
        state: Layout state to modify (modified in-place)
        
    Side Effects:
        - Sets current_widths to 0 for all spacer indices
        - Updates total_width to reflect collapsed spacers
        
    Example:
        >>> state = LayoutState(...)
        >>> state.spacer_indices = [1, 3]
        >>> state.current_widths = [10, 5, 10, 3]
        >>> collapse_spacers(state)
        >>> state.current_widths
        [10, 0, 10, 0]
    """
    if not state.spacer_indices:
        return
    
    logger.debug(f"Collapsing {len(state.spacer_indices)} spacer(s) to zero width")
    
    # Set all spacer widths to zero
    for idx in state.spacer_indices:
        if state.current_widths[idx] > 0:
            state.total_width -= state.current_widths[idx]
            state.current_widths[idx] = 0
    
    logger.debug(f"Total width after spacer collapse: {state.total_width}")


def shorten_segments_by_priority(state: LayoutState, shortened_texts: List[str]) -> None:
    """
    Shorten text segments by priority until target width is met.
    
    This function implements the core shortening algorithm:
    1. Sort segments by priority (descending - higher values first)
    2. For each priority level, shorten all segments at that level
    3. Respect minimum length constraints
    4. Stop when target width is met or no more shortening possible
    
    Args:
        state: Layout state containing segments and width information
        shortened_texts: List to store shortened text for each segment (modified in-place)
        
    Side Effects:
        - Updates state.current_widths with new widths after shortening
        - Updates state.total_width to reflect shortened segments
        - Populates shortened_texts with shortened text for each segment
        
    Example:
        >>> state = LayoutState(...)
        >>> shortened_texts = [""] * len(state.segments)
        >>> shorten_segments_by_priority(state, shortened_texts)
        >>> # state.current_widths and shortened_texts are now updated
    """
    # Build list of (index, segment, priority) for text segments only (not spacers)
    text_segments = []
    for idx, segment in enumerate(state.segments):
        if isinstance(segment, TextSegment):
            text_segments.append((idx, segment, segment.priority))
    
    if not text_segments:
        logger.debug("No text segments to shorten")
        return
    
    # Sort by priority (descending), then by original order for equal priorities
    text_segments.sort(key=lambda x: (-x[2], x[0]))
    
    logger.debug(f"Shortening order by priority: {[(idx, pri) for idx, _, pri in text_segments]}")
    
    # Group segments by priority level
    priority_groups = []
    current_priority = None
    current_group = []
    
    for idx, segment, priority in text_segments:
        if priority != current_priority:
            if current_group:
                priority_groups.append((current_priority, current_group))
            current_priority = priority
            current_group = [(idx, segment)]
        else:
            current_group.append((idx, segment))
    
    if current_group:
        priority_groups.append((current_priority, current_group))
    
    # Process each priority level
    for priority, group in priority_groups:
        logger.debug(f"Processing priority level {priority} with {len(group)} segment(s)")
        
        # Check if we've already met the target
        if state.total_width <= state.target_width:
            logger.debug("Target width met, stopping shortening")
            break
        
        # Calculate how much we need to reduce
        excess_width = state.total_width - state.target_width
        
        # Try to shorten each segment in this priority group
        for idx, segment in group:
            if state.total_width <= state.target_width:
                break
            
            current_width = state.current_widths[idx]
            
            # Calculate target width for this segment
            # We want to reduce by a fair share, but respect minimum length
            min_length = max(0, segment.min_length)
            
            # Calculate minimum width based on min_length
            # For now, we'll use character count as approximation
            # (actual width may vary with wide characters)
            min_width = min_length
            
            # Don't shorten below minimum width
            if current_width <= min_width:
                logger.debug(f"Segment {idx} already at minimum width {min_width}, skipping")
                continue
            
            # Calculate how much we can reduce this segment
            max_reduction = current_width - min_width
            
            # Try to reduce by the excess, but not more than max_reduction
            target_reduction = min(excess_width, max_reduction)
            new_width = current_width - target_reduction
            
            # Shorten the segment
            try:
                shortened_text = segment.shorten(new_width)
                actual_width = get_display_width(shortened_text)
            except Exception as e:
                logger.error(f"Segment {idx} shorten() failed: {e}, using original text")
                # Use original text if shortening fails (already normalized in __post_init__)
                shortened_text = segment.text
                actual_width = get_display_width(shortened_text)
            
            # Update state
            width_reduction = current_width - actual_width
            state.current_widths[idx] = actual_width
            state.total_width -= width_reduction
            shortened_texts[idx] = shortened_text
            
            logger.debug(f"Shortened segment {idx} from {current_width} to {actual_width} columns")
            
            # Update excess for next segment
            excess_width = state.total_width - state.target_width
    
    logger.debug(f"Final total width after shortening: {state.total_width}")


def restore_segments_by_priority(state: LayoutState, shortened_texts: List[str]) -> None:
    """
    Restore text segments by priority when extra space is available.
    
    After shortening, if there's extra space available (total_width < target_width),
    this function attempts to restore segments to their original width in reverse
    priority order (lower priority values first).
    
    Args:
        state: Layout state containing segments and width information
        shortened_texts: List of shortened text for each segment (modified in-place)
        
    Side Effects:
        - Updates state.current_widths with restored widths
        - Updates state.total_width to reflect restored segments
        - Updates shortened_texts with restored text for segments
        
    Example:
        >>> state = LayoutState(...)
        >>> shortened_texts = ["short", "text"]
        >>> restore_segments_by_priority(state, shortened_texts)
        >>> # Segments may be restored to original width if space available
    """
    # Check if we have extra space
    if state.total_width >= state.target_width:
        logger.debug("No extra space available for restoration")
        return
    
    available_space = state.target_width - state.total_width
    logger.debug(f"Attempting restoration with {available_space} columns available")
    
    # Build list of (index, segment, priority) for text segments that were shortened
    text_segments = []
    for idx, segment in enumerate(state.segments):
        if isinstance(segment, TextSegment):
            # Only consider segments that were shortened
            if state.current_widths[idx] < state.original_widths[idx]:
                text_segments.append((idx, segment, segment.priority))
    
    if not text_segments:
        logger.debug("No shortened segments to restore")
        return
    
    # Sort by priority (ascending - lower values first), then by original order
    text_segments.sort(key=lambda x: (x[2], x[0]))
    
    logger.debug(f"Restoration order by priority: {[(idx, pri) for idx, _, pri in text_segments]}")
    
    # Try to restore each segment
    for idx, segment, priority in text_segments:
        if available_space <= 0:
            logger.debug("No more space available for restoration")
            break
        
        current_width = state.current_widths[idx]
        original_width = state.original_widths[idx]
        
        # Calculate how much we can restore
        max_restoration = original_width - current_width
        actual_restoration = min(available_space, max_restoration)
        
        if actual_restoration <= 0:
            continue
        
        # Try to restore to current_width + actual_restoration
        target_width = current_width + actual_restoration
        
        # Get the original text (not shortened, already normalized in __post_init__)
        original_text = segment.text
        
        # If we can restore to full width, use original text
        if target_width >= original_width:
            restored_text = original_text
            actual_width = original_width
        else:
            # Partially restore by shortening to the new target width
            try:
                restored_text = segment.shorten(target_width)
                actual_width = get_display_width(restored_text)
            except Exception as e:
                logger.error(f"Segment {idx} shorten() failed during restoration: {e}, using original text")
                # Use original text if shortening fails
                restored_text = original_text
                actual_width = original_width
        
        # Update state
        width_increase = actual_width - current_width
        state.current_widths[idx] = actual_width
        state.total_width += width_increase
        shortened_texts[idx] = restored_text
        available_space -= width_increase
        
        logger.debug(f"Restored segment {idx} from {current_width} to {actual_width} columns")
    
    logger.debug(f"Final total width after restoration: {state.total_width}")


def expand_spacers(state: LayoutState, shortened_texts: List[str]) -> None:
    """
    Expand spacer segments to fill available space.
    
    When the total width is less than the rendering width and spacers exist,
    this function distributes the extra space equally among all spacers.
    
    Args:
        state: Layout state containing segments and width information
        shortened_texts: List of text for each segment (modified in-place for spacers)
        
    Side Effects:
        - Updates state.current_widths for spacer segments
        - Updates state.total_width to reflect expanded spacers
        - Updates shortened_texts with whitespace for spacer segments
        
    Example:
        >>> state = LayoutState(...)
        >>> state.spacer_indices = [1, 3]
        >>> state.total_width = 70
        >>> state.target_width = 80
        >>> expand_spacers(state, shortened_texts)
        >>> # Spacers expanded to fill 10 columns (5 each)
    """
    # Check if we have spacers and extra space
    if not state.spacer_indices:
        logger.debug("No spacers to expand")
        return
    
    if state.total_width >= state.target_width:
        logger.debug("No extra space available for spacer expansion")
        return
    
    extra_space = state.target_width - state.total_width
    num_spacers = len(state.spacer_indices)
    
    logger.debug(f"Expanding {num_spacers} spacer(s) to fill {extra_space} columns")
    
    # Calculate base space per spacer and remainder
    base_space = extra_space // num_spacers
    remainder = extra_space % num_spacers
    
    # Distribute space among spacers
    # First 'remainder' spacers get base_space + 1
    # Remaining spacers get base_space
    for i, idx in enumerate(state.spacer_indices):
        if i < remainder:
            spacer_width = base_space + 1
        else:
            spacer_width = base_space
        
        # Update state
        state.current_widths[idx] = spacer_width
        state.total_width += spacer_width
        
        # Create whitespace string for this spacer
        shortened_texts[idx] = " " * spacer_width
        
        logger.debug(f"Expanded spacer {idx} to {spacer_width} columns")
    
    logger.debug(f"Final total width after spacer expansion: {state.total_width}")


# ============================================================================
# Rendering Logic
# ============================================================================

@dataclass
class RenderContext:
    """
    Context for rendering segments to the screen.
    
    This dataclass tracks the state during the rendering phase, including
    the renderer instance, current drawing position, and default styling.
    
    Attributes:
        renderer: TTK renderer instance for drawing text
        row: Row position for rendering (0-based)
        current_col: Current column position (updated as segments are rendered)
        default_color: Default color pair for segments without color
        default_attributes: Default attributes for segments without attributes
    """
    renderer: any  # TTK Renderer type
    row: int
    current_col: int
    default_color: int
    default_attributes: int


def render_segments(
    context: RenderContext,
    segments: List[Union[TextSegment, SpacerSegment]],
    shortened_texts: List[str],
    widths: List[int]
) -> None:
    """
    Render all segments to the screen with their calculated widths.
    
    This function iterates through all segments and renders each one at the
    appropriate position with the correct color and attributes. It handles
    both text segments and spacer segments (which render as whitespace).
    
    Args:
        context: Rendering context with renderer and position information
        segments: List of text and spacer segments to render
        shortened_texts: List of shortened/final text for each segment
        widths: List of display widths for each segment
        
    Side Effects:
        - Calls renderer.draw_text() for each segment
        - Updates context.current_col as segments are rendered
        
    Example:
        >>> context = RenderContext(renderer, row=0, current_col=0, ...)
        >>> render_segments(context, segments, shortened_texts, widths)
        >>> # All segments rendered at row 0, starting from column 0
    """
    logger.debug(f"Rendering {len(segments)} segment(s) at row {context.row}, starting col {context.current_col}")
    
    for idx, segment in enumerate(segments):
        text = shortened_texts[idx]
        width = widths[idx]
        
        # Skip empty segments
        if not text or width == 0:
            logger.debug(f"Skipping empty segment {idx}")
            continue
        
        # Determine color pair to use
        if isinstance(segment, SpacerSegment):
            color_pair = segment.color_pair if segment.color_pair is not None else context.default_color
        else:
            color_pair = segment.color_pair if segment.color_pair is not None else context.default_color
        
        # Determine attributes to use
        if isinstance(segment, SpacerSegment):
            attributes = segment.attributes if segment.attributes is not None else context.default_attributes
        else:
            attributes = segment.attributes if segment.attributes is not None else context.default_attributes
        
        # Validate color pair
        if color_pair < 0 or color_pair > 255:
            logger.warning(f"Invalid color_pair {color_pair} for segment {idx}, using default")
            color_pair = context.default_color
        
        logger.debug(f"Rendering segment {idx}: '{text}' at col {context.current_col} with color {color_pair}, attrs {attributes}")
        
        try:
            # Render the segment
            context.renderer.draw_text(
                context.row,
                context.current_col,
                text,
                color_pair,
                attributes
            )
            
            # Update current column position
            context.current_col += width
            
        except Exception as e:
            logger.error(f"Failed to render segment {idx} at row {context.row}, col {context.current_col}: {e}")
            # Continue with next segment even if this one failed
            context.current_col += width
    
    logger.debug(f"Rendering complete, final column: {context.current_col}")


# ============================================================================
# Main API Function
# ============================================================================

def draw_text_segments(
    renderer,
    row: int,
    col: int,
    segments: List[Union[TextSegment, SpacerSegment]],
    rendering_width: int,
    default_color: int = 0,
    default_attributes: int = 0
) -> None:
    """
    Calculate layout, shorten segments, and render text to screen.
    
    This is the primary entry point for the text layout system. It performs
    the complete layout and rendering pipeline:
    
    1. Validates input parameters
    2. Creates initial layout state from segments
    3. Collapses spacers if shortening is needed
    4. Shortens segments by priority until target width is met
    5. Restores segments if extra space is available
    6. Expands spacers to fill remaining space
    7. Renders each segment with its color and attributes
    
    The function handles all errors gracefully with logging and will not crash
    even if individual segments fail to render.
    
    Args:
        renderer: TTK renderer instance (must have draw_text method)
        row: Row position for rendering (0-based)
        col: Starting column position (0-based)
        segments: List of text/spacer segments to layout and render
        rendering_width: Target width in terminal columns
        default_color: Default color pair for segments without color (default 0)
        default_attributes: Default attributes for segments without attributes (default 0)
        
    Raises:
        ValueError: If renderer is None or segments list is None
        
    Example:
        >>> from xefm.text_layout import draw_text_segments, AbbreviationSegment, SpacerSegment
        >>> 
        >>> segments = [
        ...     AbbreviationSegment("Long filename.txt", priority=1, min_length=10),
        ...     SpacerSegment(),
        ...     AbbreviationSegment("Status", priority=0, min_length=3)
        ... ]
        >>> 
        >>> draw_text_segments(renderer, row=0, col=0, segments=segments,
        ...                    rendering_width=80, default_color=1)
        
    Notes:
        - Segments with higher priority values are shortened first
        - Spacers are collapsed before any text shortening occurs
        - Spacers expand to fill available space when text doesn't need shortening
        - Wide characters (CJK, emoji) are properly handled and never split
        - Each segment can have its own color and attributes
        - Minimum length constraints are respected during shortening
    """
    # ========================================================================
    # Input Validation
    # ========================================================================
    
    # Validate renderer
    if renderer is None:
        logger.error("draw_text_segments called with None renderer")
        raise ValueError("renderer cannot be None")
    
    # Validate segments
    if segments is None:
        logger.error("draw_text_segments called with None segments")
        raise ValueError("segments cannot be None")
    
    # Handle empty segments list
    if not segments:
        logger.debug("draw_text_segments called with empty segments list, nothing to render")
        return
    
    # Validate rendering_width
    if rendering_width < 0:
        logger.warning(f"Negative rendering_width {rendering_width}, treating as 0")
        rendering_width = 0
    
    if rendering_width == 0:
        logger.debug("rendering_width is 0, nothing to render")
        return
    
    # Validate row and col
    if row < 0:
        logger.warning(f"Negative row {row}, clipping to 0")
        row = 0
    
    if col < 0:
        logger.warning(f"Negative col {col}, clipping to 0")
        col = 0
    
    # ========================================================================
    # Create Initial Layout State
    # ========================================================================
    
    try:
        # Calculate initial widths for all segments
        current_widths = []
        original_widths = []
        spacer_indices = []
        
        for idx, segment in enumerate(segments):
            if isinstance(segment, SpacerSegment):
                # Spacers start with zero width
                current_widths.append(0)
                original_widths.append(0)
                spacer_indices.append(idx)
            elif isinstance(segment, TextSegment):
                # Text segments start with their full width
                try:
                    width = get_display_width(segment.text)
                except Exception as e:
                    logger.error(f"get_display_width failed for segment {idx}: {e}")
                    width = len(segment.text)  # Fall back to character count
                current_widths.append(width)
                original_widths.append(width)
            else:
                logger.error(f"Unknown segment type at index {idx}: {type(segment)}")
                # Treat as zero-width segment
                current_widths.append(0)
                original_widths.append(0)
        
        # Calculate total width
        total_width = sum(current_widths)
        
        # Create layout state
        state = LayoutState(
            segments=segments,
            current_widths=current_widths,
            original_widths=original_widths,
            total_width=total_width,
            target_width=rendering_width,
            spacer_indices=spacer_indices
        )
        
        logger.debug(f"Initial layout state: total_width={total_width}, target_width={rendering_width}, spacers={len(spacer_indices)}")
        
    except Exception as e:
        logger.error(f"Failed to create initial layout state: {e}")
        # Cannot proceed without valid state
        return
    
    # ========================================================================
    # Execute Layout Calculation
    # ========================================================================
    
    # Initialize shortened_texts with original text for all segments
    shortened_texts = []
    for idx, segment in enumerate(segments):
        if isinstance(segment, SpacerSegment):
            shortened_texts.append("")  # Spacers start empty
        elif isinstance(segment, TextSegment):
            shortened_texts.append(segment.text)  # Already normalized in __post_init__
        else:
            shortened_texts.append("")
    
    try:
        # Phase 1: Collapse spacers if shortening is needed
        if state.total_width > state.target_width:
            logger.debug("Total width exceeds target, collapsing spacers")
            collapse_spacers(state)
        
        # Phase 2: Shorten segments by priority if still over target
        if state.total_width > state.target_width:
            logger.debug("Total width still exceeds target after spacer collapse, shortening segments")
            shorten_segments_by_priority(state, shortened_texts)
        
        # Phase 3: Restore segments if extra space is available
        if state.total_width < state.target_width:
            logger.debug("Extra space available, attempting to restore segments")
            restore_segments_by_priority(state, shortened_texts)
        
        # Phase 4: Expand spacers to fill remaining space
        if state.total_width < state.target_width and state.spacer_indices:
            logger.debug("Extra space available with spacers, expanding spacers")
            expand_spacers(state, shortened_texts)
        
    except Exception as e:
        logger.error(f"Layout calculation failed: {e}")
        # Try to render with whatever state we have
        logger.warning("Attempting to render with partial layout state")
    
    # ========================================================================
    # Execute Rendering
    # ========================================================================
    
    try:
        # Create rendering context
        context = RenderContext(
            renderer=renderer,
            row=row,
            current_col=col,
            default_color=default_color,
            default_attributes=default_attributes
        )
        
        # Render all segments
        render_segments(context, segments, shortened_texts, state.current_widths)
        
    except Exception as e:
        logger.error(f"Rendering failed: {e}")
        # Rendering failure is logged but doesn't raise exception
        # This allows the application to continue even if rendering fails
