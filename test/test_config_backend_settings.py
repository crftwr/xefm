"""
Test configuration system desktop (font) settings.

Tests:
1. Default desktop font settings
2. Desktop font validation
3. Configuration loading with desktop settings
4. Configuration reload / persistence

Run with: python -m pytest test/test_config_backend_settings.py -v
"""

from pathlib import Path
import tempfile
import shutil

from xefm.config import ConfigManager
from xefm._config import Config  # the default config template (was xefm.config.DefaultConfig)


def test_default_desktop_config():
    """Test that default configuration includes desktop font settings"""
    config = Config()

    # Check desktop mode settings exist
    assert hasattr(config, 'UI_FONT_NAME'), "DefaultConfig should have UI_FONT_NAME"
    assert hasattr(config, 'MONO_FONT_NAME'), "DefaultConfig should have MONO_FONT_NAME"
    assert hasattr(config, 'FONT_SIZE'), "DefaultConfig should have FONT_SIZE"

    # Check default values
    assert config.UI_FONT_NAME is None, "Default UI font should be None (system UI font)"
    assert config.MONO_FONT_NAME is None, "Default mono font should be None (system mono font)"
    assert config.FONT_SIZE == 12, "Default font size should be 12"

    print("✓ Default desktop configuration test passed")


def test_desktop_settings_validation():
    """Test desktop mode settings validation"""
    manager = ConfigManager()

    # Test valid desktop settings: a mono family + UI font as None (system UI)
    class ValidDesktopConfig:
        UI_FONT_NAME = None
        MONO_FONT_NAME = 'Monaco'
        FONT_SIZE = 14

    errors = manager.validate_config(ValidDesktopConfig())
    assert len(errors) == 0, f"Valid desktop settings should have no errors, got: {errors}"

    # Test valid: a named proportional UI font
    class ValidUiFontNamed:
        UI_FONT_NAME = 'Helvetica Neue'
        MONO_FONT_NAME = 'Menlo'

    errors = manager.validate_config(ValidUiFontNamed())
    assert len(errors) == 0, f"A named UI font should be valid, got: {errors}"

    # Test invalid mono font name (empty string)
    class InvalidMonoFontEmpty:
        MONO_FONT_NAME = ''

    errors = manager.validate_config(InvalidMonoFontEmpty())
    assert len(errors) > 0, "Empty mono font name should produce validation error"
    assert any('MONO_FONT_NAME' in err for err in errors), "Error should mention MONO_FONT_NAME"

    # Test invalid UI font name (empty string — use None for the system font)
    class InvalidUiFontEmpty:
        UI_FONT_NAME = ''

    errors = manager.validate_config(InvalidUiFontEmpty())
    assert len(errors) > 0, "Empty UI font name should produce validation error"
    assert any('UI_FONT_NAME' in err for err in errors), "Error should mention UI_FONT_NAME"

    # Test invalid font name (a list is not accepted — one family only)
    class InvalidFontNameList:
        MONO_FONT_NAME = ['Monaco', 'Menlo', 'Courier']

    errors = manager.validate_config(InvalidFontNameList())
    assert len(errors) > 0, "A font list should produce a validation error"
    assert any('MONO_FONT_NAME' in err for err in errors), "Error should mention MONO_FONT_NAME"

    # Test invalid font name (wrong type)
    class InvalidFontNameType:
        MONO_FONT_NAME = 123

    errors = manager.validate_config(InvalidFontNameType())
    assert len(errors) > 0, "Invalid font name type should produce validation error"
    assert any('MONO_FONT_NAME' in err for err in errors), "Error should mention MONO_FONT_NAME"

    # Test invalid font size (too small)
    class InvalidFontSizeSmall:
        FONT_SIZE = 5

    errors = manager.validate_config(InvalidFontSizeSmall())
    assert len(errors) > 0, "Font size < 8 should produce validation error"
    assert any('FONT_SIZE' in err for err in errors), "Error should mention FONT_SIZE"

    # Test invalid font size (too large)
    class InvalidFontSizeLarge:
        FONT_SIZE = 100

    errors = manager.validate_config(InvalidFontSizeLarge())
    assert len(errors) > 0, "Font size > 72 should produce validation error"

    print("✓ Desktop settings validation test passed")


def test_config_loading_with_desktop_settings():
    """Test that configuration loading works with desktop settings"""
    # Create a temporary config directory
    temp_dir = tempfile.mkdtemp()
    config_dir = Path(temp_dir) / '.xefm'
    config_file = config_dir / 'config.py'

    try:
        # Create config directory
        config_dir.mkdir(parents=True, exist_ok=True)

        # Write a test config file with desktop settings
        config_content = '''
class Config:
    """Test configuration"""

    # Desktop settings
    UI_FONT_NAME = 'Helvetica Neue'
    MONO_FONT_NAME = 'Monaco'
    FONT_SIZE = 16

    # Other settings
    SHOW_HIDDEN_FILES = True
'''

        with open(config_file, 'w') as f:
            f.write(config_content)

        # Create a ConfigManager with custom config directory
        manager = ConfigManager()
        original_config_dir = manager.config_dir
        original_config_file = manager.config_file

        try:
            # Override config paths for testing
            manager.config_dir = config_dir
            manager.config_file = config_file

            # Load the config
            config = manager.load_config()

            # Verify desktop settings were loaded
            assert hasattr(config, 'UI_FONT_NAME'), "Config should have UI_FONT_NAME"
            assert config.UI_FONT_NAME == 'Helvetica Neue', "UI font should be 'Helvetica Neue'"

            assert hasattr(config, 'MONO_FONT_NAME'), "Config should have MONO_FONT_NAME"
            assert config.MONO_FONT_NAME == 'Monaco', "Mono font should be 'Monaco'"

            assert hasattr(config, 'FONT_SIZE'), "Config should have FONT_SIZE"
            assert config.FONT_SIZE == 16, "Font size should be 16"

            print("✓ Configuration loading with desktop settings test passed")

        finally:
            # Restore original paths
            manager.config_dir = original_config_dir
            manager.config_file = original_config_file

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_config_reload_persistence():
    """Test that configuration changes can be saved and reloaded"""
    # Create a temporary config directory
    temp_dir = tempfile.mkdtemp()
    config_dir = Path(temp_dir) / '.xefm'
    config_file = config_dir / 'config.py'

    try:
        # Create config directory
        config_dir.mkdir(parents=True, exist_ok=True)

        # Write initial config with font size 14
        config_content_initial = '''
class Config:
    FONT_SIZE = 14
'''

        with open(config_file, 'w') as f:
            f.write(config_content_initial)

        # Load and verify initial font size
        manager = ConfigManager()
        manager.config_dir = config_dir
        manager.config_file = config_file

        config = manager.load_config()
        assert config.FONT_SIZE == 14, "Initial font size should be 14"

        # Update config to font size 16. The trailing comment makes this file a
        # different byte length than the initial one: importlib keys its bytecode
        # cache on source mtime (seconds resolution) + size, and both writes land
        # in the same second, so a same-size rewrite would be served stale.
        config_content_updated = '''
class Config:
    FONT_SIZE = 16  # reloaded value
'''

        with open(config_file, 'w') as f:
            f.write(config_content_updated)

        # Reload and verify updated font size
        config = manager.reload_config()
        assert config.FONT_SIZE == 16, "Updated font size should be 16"

        print("✓ Configuration reload persistence test passed")

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_all_tests():
    """Run all configuration desktop-settings tests"""
    print("\n=== Testing Configuration Desktop Settings ===\n")

    test_default_desktop_config()
    test_desktop_settings_validation()
    test_config_loading_with_desktop_settings()
    test_config_reload_persistence()

    print("\n=== All Configuration Desktop Tests Passed ===\n")
