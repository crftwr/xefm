#!/usr/bin/env python3
"""
TUI File Manager - Progress Animator Component
Provides animated progress indicators for various operations
"""

import time


class ProgressAnimator:
    """Handles animated progress indicators for any operation"""
    
    def __init__(self, config, pattern_override=None, speed_override=None):
        """Initialize progress animator
        
        Args:
            config: Configuration object
            pattern_override: Override the configured pattern for this instance
            speed_override: Override the configured speed for this instance
        """
        self.config = config
        
        # Use overrides if provided, otherwise fall back to config
        self.animation_pattern = pattern_override or config.PROGRESS_ANIMATION_PATTERN
        self.animation_speed = speed_override or config.PROGRESS_ANIMATION_SPEED
        
        # Animation patterns
        self.patterns = {
            'spinner': ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
            'dots': ['⠁', '⠂', '⠄', '⡀', '⢀', '⠠', '⠐', '⠈'],
            'progress': ['▏', '▎', '▍', '▌', '▋', '▊', '▉', '█'],
            'bounce': ['⠁', '⠂', '⠄', '⠂'],
            'pulse': ['●', '◐', '◑', '◒', '◓', '◔', '◕', '○'],
            'wave': ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█', '▇', '▆', '▅', '▄', '▃', '▂'],
            'clock': ['🕐', '🕑', '🕒', '🕓', '🕔', '🕕', '🕖', '🕗', '🕘', '🕙', '🕚', '🕛'],
            'arrow': ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙']
        }
        
        # Animation state
        self.frame_index = 0
        self.last_update_time = 0
        
    def get_current_frame(self):
        """Get the current animation frame"""
        current_time = time.time()
        
        # Update frame if enough time has passed
        if current_time - self.last_update_time >= self.animation_speed:
            pattern = self.patterns.get(self.animation_pattern, self.patterns['spinner'])
            self.frame_index = (self.frame_index + 1) % len(pattern)
            self.last_update_time = current_time
        
        pattern = self.patterns.get(self.animation_pattern, self.patterns['spinner'])
        return pattern[self.frame_index]
    
    def reset(self):
        """Reset animation to first frame"""
        self.frame_index = 0
        self.last_update_time = 0
    
    def set_pattern(self, pattern):
        """Change animation pattern dynamically
        
        Args:
            pattern: New pattern name
        """
        if pattern in self.patterns:
            self.animation_pattern = pattern
            self.reset()  # Reset to avoid index out of bounds
    
    def set_speed(self, speed):
        """Change animation speed dynamically
        
        Args:
            speed: New speed in seconds per frame
        """
        self.animation_speed = speed
    
    def get_available_patterns(self):
        """Get list of available animation patterns"""
        return list(self.patterns.keys())
    
    def get_pattern_preview(self, pattern=None):
        """Get a preview of pattern frames
        
        Args:
            pattern: Pattern to preview (default: current pattern)
            
        Returns:
            List of frames for the pattern
        """
        pattern_name = pattern or self.animation_pattern
        return self.patterns.get(pattern_name, self.patterns['spinner'])
    
    def get_progress_indicator(self, context_info=None, is_active=True, style='default'):
        """Get formatted progress indicator text
        
        Args:
            context_info: Optional context information (e.g., count, percentage)
            is_active: Whether the operation is currently active
            style: Formatting style ('default', 'brackets', 'minimal')
            
        Returns:
            Formatted progress indicator string
        """
        if not is_active:
            return ""
        
        frame = self.get_current_frame()
        
        if self.animation_pattern == 'progress':
            # For progress pattern, show a progress bar effect
            progress_length = 8
            filled = (self.frame_index * progress_length) // len(self.patterns['progress'])
            bar = '█' * filled + '░' * (progress_length - filled)
            
            if style == 'brackets':
                return f" [{bar}] "
            elif style == 'minimal':
                return bar
            else:
                return f" [{bar}] "
        else:
            # For other patterns, show the frame
            if style == 'brackets':
                return f" [{frame}] "
            elif style == 'minimal':
                return frame
            else:
                return f" {frame} "
    
    def get_status_text(self, operation_name, context_info=None, is_active=True):
        """Get complete status text with animation
        
        Args:
            operation_name: Name of the operation (e.g., "Searching", "Loading")
            context_info: Additional context (e.g., "42 found", "50%")
            is_active: Whether the operation is active
            
        Returns:
            Complete status text with animation
        """
        if not is_active:
            if context_info:
                return f"{operation_name} complete: {context_info}"
            else:
                return f"{operation_name} complete"
        
        progress_indicator = self.get_progress_indicator(context_info, is_active)
        
        if context_info:
            return f"{operation_name}{progress_indicator}({context_info})"
        else:
            return f"{operation_name}{progress_indicator}"


class ProgressAnimatorFactory:
    """Factory for creating progress animators with common configurations"""
    
    @staticmethod
    def create_search_animator(config):
        """Create animator optimized for search operations"""
        return ProgressAnimator(config)
    
    @staticmethod
    def create_loading_animator(config):
        """Create animator optimized for loading operations"""
        return ProgressAnimator(
            config,
            pattern_override='spinner',
            speed_override=0.15
        )
    
    @staticmethod
    def create_processing_animator(config):
        """Create animator optimized for processing operations"""
        return ProgressAnimator(
            config,
            pattern_override='progress',
            speed_override=0.25
        )
    
    @staticmethod
    def create_custom_animator(config, pattern='spinner', speed=0.2):
        """Create animator with custom settings"""
        return ProgressAnimator(
            config,
            pattern_override=pattern,
            speed_override=speed
        )