"""
Test file for generalized ProgressAnimator functionality
Tests the new generalized animation system for various use cases

Run with: python -m pytest test/test_progress_animator_generalized.py -v
"""

import time

from xefm.progress_animator import ProgressAnimator, ProgressAnimatorFactory
from xefm._config import Config


class GeneralizedTestConfig(Config):
    """Test configuration for generalized animation testing"""
    PROGRESS_ANIMATION_PATTERN = 'pulse'
    PROGRESS_ANIMATION_SPEED = 0.1


def test_all_animation_patterns():
    """Test all available animation patterns"""
    print("Testing all animation patterns...")
    
    config = GeneralizedTestConfig()
    animator = ProgressAnimator(config)
    
    patterns = animator.get_available_patterns()
    expected_patterns = ['spinner', 'dots', 'progress', 'bounce', 'pulse', 'wave', 'clock', 'arrow']
    
    for pattern in expected_patterns:
        assert pattern in patterns, f"Pattern {pattern} should be available"
        
        # Test switching to each pattern
        animator.set_pattern(pattern)
        assert animator.animation_pattern == pattern
        
        # Test getting frames
        frame = animator.get_current_frame()
        assert frame in animator.patterns[pattern]
        
        # Test pattern preview
        preview = animator.get_pattern_preview(pattern)
        assert len(preview) > 0
        assert all(f in animator.patterns[pattern] for f in preview)
        
        print(f"  ✓ {pattern} pattern: {' '.join(preview[:5])}...")
    
    print("✓ All animation patterns test passed")


def test_dynamic_configuration():
    """Test dynamic pattern and speed changes"""
    print("Testing dynamic configuration changes...")
    
    config = GeneralizedTestConfig()
    animator = ProgressAnimator(config)
    
    # Test initial state
    assert animator.animation_pattern == 'pulse'
    assert animator.animation_speed == 0.1
    
    # Test pattern changes
    animator.set_pattern('wave')
    assert animator.animation_pattern == 'wave'
    assert animator.frame_index == 0  # Should reset on pattern change
    
    # Test speed changes
    animator.set_speed(0.05)
    assert animator.animation_speed == 0.05
    
    # Test invalid pattern (should not change)
    original_pattern = animator.animation_pattern
    animator.set_pattern('invalid_pattern')
    assert animator.animation_pattern == original_pattern
    
    print("✓ Dynamic configuration test passed")


def test_status_text_generation():
    """Test status text generation for different scenarios"""
    print("Testing status text generation...")
    
    config = GeneralizedTestConfig()
    animator = ProgressAnimator(config)
    
    # Test basic status text
    status = animator.get_status_text("Loading")
    assert "Loading" in status
    
    # Test with context info
    status_with_context = animator.get_status_text("Processing", "50 files", True)
    assert "Processing" in status_with_context
    assert "50 files" in status_with_context
    
    # Test inactive status
    inactive_status = animator.get_status_text("Processing", "100 files", False)
    assert "complete" in inactive_status
    assert "100 files" in inactive_status
    
    # Test without context when inactive
    simple_inactive = animator.get_status_text("Loading", None, False)
    assert "Loading complete" == simple_inactive
    
    print("✓ Status text generation test passed")


def test_progress_indicator_styles():
    """Test different progress indicator styles"""
    print("Testing progress indicator styles...")
    
    config = GeneralizedTestConfig()
    
    # Test with different patterns
    patterns_to_test = ['spinner', 'progress', 'dots']
    
    for pattern in patterns_to_test:
        animator = ProgressAnimator(config, pattern_override=pattern)
        
        # Test different styles
        default_style = animator.get_progress_indicator("test", True, 'default')
        brackets_style = animator.get_progress_indicator("test", True, 'brackets')
        minimal_style = animator.get_progress_indicator("test", True, 'minimal')
        
        assert len(default_style) > 0
        assert len(brackets_style) > 0
        assert len(minimal_style) > 0
        
        # Brackets style should contain brackets for progress pattern
        if pattern == 'progress':
            assert '[' in brackets_style and ']' in brackets_style
        
        # Minimal style should be shortest
        assert len(minimal_style) <= len(default_style)
        assert len(minimal_style) <= len(brackets_style)
        
        print(f"  ✓ {pattern}: default='{default_style.strip()}', brackets='{brackets_style.strip()}', minimal='{minimal_style.strip()}'")
    
    print("✓ Progress indicator styles test passed")


def test_factory_methods():
    """Test all factory methods"""
    print("Testing factory methods...")
    
    config = GeneralizedTestConfig()
    
    # Test search animator
    search_animator = ProgressAnimatorFactory.create_search_animator(config)
    assert isinstance(search_animator, ProgressAnimator)
    
    # Test loading animator
    loading_animator = ProgressAnimatorFactory.create_loading_animator(config)
    assert loading_animator.animation_pattern == 'spinner'
    assert loading_animator.animation_speed == 0.15
    
    # Test processing animator
    processing_animator = ProgressAnimatorFactory.create_processing_animator(config)
    assert processing_animator.animation_pattern == 'progress'
    assert processing_animator.animation_speed == 0.25
    
    # Test custom animator
    custom_animator = ProgressAnimatorFactory.create_custom_animator(config, 'clock', 0.3)
    assert custom_animator.animation_pattern == 'clock'
    assert custom_animator.animation_speed == 0.3
    
    # Test that they all work independently
    for animator in [search_animator, loading_animator, processing_animator, custom_animator]:
        frame = animator.get_current_frame()
        assert frame is not None
        assert len(frame) > 0
    
    print("✓ Factory methods test passed")


def test_configuration_fallbacks():
    """Config values are read from the config, and constructor args override them.

    The animator no longer synthesizes defaults for a config that is missing the
    attributes — the real ``_config.Config`` always provides
    ``PROGRESS_ANIMATION_PATTERN`` / ``PROGRESS_ANIMATION_SPEED`` — so we supply
    configs that carry them, as production always does."""
    print("Testing configuration reading + overrides...")

    class DefaultsConfig:
        PROGRESS_ANIMATION_PATTERN = 'spinner'
        PROGRESS_ANIMATION_SPEED = 0.2

    animator = ProgressAnimator(DefaultsConfig())
    assert animator.animation_pattern == 'spinner'
    assert animator.animation_speed == 0.2

    # Config values are honored.
    class DotsConfig:
        PROGRESS_ANIMATION_PATTERN = 'dots'
        PROGRESS_ANIMATION_SPEED = 0.2

    animator2 = ProgressAnimator(DotsConfig())
    assert animator2.animation_pattern == 'dots'
    assert animator2.animation_speed == 0.2

    # Constructor overrides win over config.
    animator3 = ProgressAnimator(DefaultsConfig(), 'wave', 0.05)
    assert animator3.animation_pattern == 'wave'
    assert animator3.animation_speed == 0.05

    print("✓ Configuration reading + overrides test passed")


def test_real_world_usage_scenarios():
    """Test real-world usage scenarios"""
    print("Testing real-world usage scenarios...")
    
    config = GeneralizedTestConfig()
    
    # Scenario 1: File copying operation
    copy_animator = ProgressAnimatorFactory.create_custom_animator(config, 'progress', 0.2)
    copy_status = copy_animator.get_status_text("Copying", "5/10 files", True)
    assert "Copying" in copy_status and "5/10 files" in copy_status
    
    # Scenario 2: Network loading
    network_animator = ProgressAnimatorFactory.create_loading_animator(config)
    network_status = network_animator.get_status_text("Downloading", "2.5 MB", True)
    assert "Downloading" in network_status and "2.5 MB" in network_status
    
    # Scenario 3: Background processing
    bg_animator = ProgressAnimatorFactory.create_processing_animator(config)
    bg_status = bg_animator.get_status_text("Indexing", "1000 items", True)
    assert "Indexing" in bg_status and "1000 items" in bg_status
    
    # Scenario 4: Quick status indicator
    quick_animator = ProgressAnimatorFactory.create_custom_animator(config, 'dots', 0.1)
    quick_indicator = quick_animator.get_progress_indicator(None, True, 'minimal')
    assert len(quick_indicator) > 0
    
    print("✓ Real-world usage scenarios test passed")


def test_animation_timing():
    """Test animation timing behavior"""
    print("Testing animation timing behavior...")
    
    config = GeneralizedTestConfig()
    fast_animator = ProgressAnimator(config, speed_override=0.05)
    slow_animator = ProgressAnimator(config, speed_override=0.3)
    
    # Get initial frames
    fast_frame1 = fast_animator.get_current_frame()
    slow_frame1 = slow_animator.get_current_frame()
    
    # Wait a short time
    time.sleep(0.1)
    
    # Get frames after delay
    fast_frame2 = fast_animator.get_current_frame()
    slow_frame2 = slow_animator.get_current_frame()
    
    # Fast animator should have advanced
    assert fast_animator.frame_index > 0
    
    # Slow animator might not have advanced yet
    # (depends on exact timing, but that's okay)
    
    # Test that both produce valid frames
    assert fast_frame1 in fast_animator.patterns[fast_animator.animation_pattern]
    assert fast_frame2 in fast_animator.patterns[fast_animator.animation_pattern]
    assert slow_frame1 in slow_animator.patterns[slow_animator.animation_pattern]
    assert slow_frame2 in slow_animator.patterns[slow_animator.animation_pattern]
    
    print("✓ Animation timing test passed")


def main():
    """Run all generalized animation tests"""
    print("Running generalized ProgressAnimator tests...")
    print("=" * 60)
    
    try:
        test_all_animation_patterns()
        test_dynamic_configuration()
        test_status_text_generation()
        test_progress_indicator_styles()
        test_factory_methods()
        test_configuration_fallbacks()
        test_real_world_usage_scenarios()
        test_animation_timing()
        
        print("=" * 60)
        print("✓ All generalized animation tests passed!")
        
    except Exception as e:
        print(f"✗ Generalized animation test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
