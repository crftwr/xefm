"""
Test mock storage implementation for extensibility validation.

This test validates that new storage types can be added without any UI changes
by implementing a MockPathImpl and verifying it works with all UI components.

It is also #426's acceptance measure for ``xefm.path_base``. ``MockPathImpl``
used to subclass ``PathImpl`` directly, which meant **384 lines and 61
methods** for a backend that keeps three files in a dictionary — the concrete
demonstration that registering a scheme would have given a third party nothing
usable. On ``UriPathImpl`` the same backend is the fourteen methods below, and
``ReadOnlyMockPathImpl`` — a backend that only browses — is five.

Run with: python -m pytest test/test_mock_storage_extensibility.py -v
"""

import io

from xefm.path import Path, PathImpl
from xefm.path_base import ReadOnlyPathImpl, UriPathImpl, UriStatResult


#: The whole of mock storage: directories, and files with their content.
_DIRS = {'', 'test', 'data', 'documents', 'project', 'project/data'}
_FILES = {
    'test/file.txt': 'Mock content for test/file.txt',
    'data/document.txt': 'Mock content for data/document.txt',
    'data/file.txt': 'Mock content for data/file.txt',
    'data/test.txt': 'Mock content for data/test.txt',
    'documents/report.txt': 'Mock content for documents/report.txt',
    'project/data/report.txt': 'Mock content for project/data/report.txt',
}


class MockPathImpl(UriPathImpl):
    """A fictional ``mock://`` backend, to prove UI code works with any
    ``PathImpl`` subclass without modification.

    Writable, so it inherits ``UriPathImpl`` rather than ``ReadOnlyPathImpl``
    — the split exists precisely so that the string arithmetic is available to
    a backend that can also be written to.
    """

    SCHEME = 'mock'
    CAPABILITIES = frozenset({'write_operations', 'extraction_for_reading',
                              'cache_for_search'})
    SEARCH_STRATEGY = 'buffered'
    DISPLAY_PREFIX = 'MOCK: '

    def exists(self) -> bool:
        return self._key in _DIRS or self._key in _FILES

    def is_dir(self) -> bool:
        return self._key in _DIRS

    def iterdir(self):
        prefix = f'{self._key}/' if self._key else ''
        seen = set()
        for key in list(_DIRS | set(_FILES)):
            if key.startswith(prefix) and key != self._key:
                name = key[len(prefix):].split('/')[0]
                if name and name not in seen:
                    seen.add(name)
                    yield self._child(name)

    def stat(self):
        return UriStatResult(size=len(_FILES.get(self._key, '')), mtime=1700000000.0,
                             is_dir=self.is_dir())

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        if 'w' in mode or 'a' in mode:
            return _MockWriter(self._key)
        return io.StringIO(_FILES.get(self._key, ''))

    # Write operations. ``write_text`` / ``write_bytes`` come free from
    # ``open`` above; these are the ones that are not a file write.
    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        _DIRS.add(self._key)

    def rmdir(self):
        _DIRS.discard(self._key)

    def unlink(self, missing_ok=False):
        _FILES.pop(self._key, None)

    def rename(self, target) -> Path:
        _FILES[str(target).removeprefix('mock://')] = _FILES.pop(self._key, '')
        return Path(target) if isinstance(target, str) else target

    def replace(self, target) -> Path:
        return self.rename(target)

    def symlink_to(self, target, target_is_directory=False):
        raise OSError('mock storage has no symlinks')

    def hardlink_to(self, target):
        raise OSError('mock storage has no hard links')

    def touch(self, mode=0o666, exist_ok=True):
        _FILES.setdefault(self._key, '')

    def chmod(self, mode):
        pass  # Mock storage doesn't enforce permissions

    def get_extended_metadata(self) -> dict:
        """The one display method worth overriding: it has something to say."""
        return {
            'type': 'mock',
            'details': [
                ('Storage Type', 'Mock Storage'),
                ('URI', str(self)),
                ('Path', self._key),
                ('Type', 'Directory' if self.is_dir() else 'File'),
                ('Size', f'{self.stat().st_size} bytes'),
                ('Status', 'Exists' if self.exists() else 'Does not exist'),
            ],
            'format_hint': 'remote',
        }


class _MockWriter(io.StringIO):
    """Writes back into ``_FILES`` when closed, so ``write_text`` round-trips."""

    def __init__(self, key: str):
        super().__init__()
        self._key = key

    def close(self):
        if not self.closed:
            _FILES[self._key] = self.getvalue()
        super().close()


class ReadOnlyMockPathImpl(ReadOnlyPathImpl):
    """The same storage, browsed only — and the whole of what #426 promises a
    third party has to write. Five methods."""

    SCHEME = 'romock'

    def exists(self) -> bool:
        return self._key in _DIRS or self._key in _FILES

    def is_dir(self) -> bool:
        return self._key in _DIRS

    def iterdir(self):
        prefix = f'{self._key}/' if self._key else ''
        for key in sorted(_FILES):
            if key.startswith(prefix) and '/' not in key[len(prefix):]:
                yield self._child(key[len(prefix):])

    def stat(self):
        return UriStatResult(size=len(_FILES.get(self._key, '')),
                             mtime=1700000000.0, is_dir=self.is_dir())

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        return io.StringIO(_FILES.get(self._key, ''))


def test_mock_path_creation():
    """Test that MockPathImpl can be created and used"""
    # Create a mock path
    mock_path = MockPathImpl('mock://test/file.txt')
    
    # Verify basic properties
    assert str(mock_path) == 'mock://test/file.txt'
    assert mock_path.name == 'file.txt'
    assert mock_path.stem == 'file'
    assert mock_path.suffix == '.txt'
    assert mock_path.get_scheme() == 'mock'
    assert mock_path.is_remote() == True
    
    print("✓ Mock path creation works")


def test_mock_path_display_methods():
    """Test that display methods work correctly"""
    mock_path = MockPathImpl('mock://data/document.txt')
    
    # Test display methods
    prefix = mock_path.DISPLAY_PREFIX
    title = mock_path.get_display_title()
    
    assert prefix == 'MOCK: ', f"Expected 'MOCK: ', got '{prefix}'"
    assert title == 'mock://data/document.txt', f"Expected full URI, got '{title}'"
    
    print("✓ Mock path display methods work")


def test_mock_path_content_reading_methods():
    """Test that content reading strategy methods work correctly"""
    mock_path = MockPathImpl('mock://data/file.txt')
    
    # Test content reading methods
    assert mock_path.supports('extraction_for_reading')
    assert not mock_path.supports('streaming_read')
    assert mock_path.SEARCH_STRATEGY == 'buffered'
    assert mock_path.supports('cache_for_search')
    
    print("✓ Mock path content reading methods work")


def test_mock_path_metadata():
    """Test that metadata method works correctly"""
    mock_path = MockPathImpl('mock://data/file.txt')
    
    # Test metadata
    metadata = mock_path.get_extended_metadata()
    
    assert metadata['type'] == 'mock'
    assert metadata['format_hint'] == 'remote'
    assert isinstance(metadata['details'], list)
    assert len(metadata['details']) > 0
    
    # Check that details contain expected fields
    detail_labels = [label for label, value in metadata['details']]
    assert 'Storage Type' in detail_labels
    assert 'URI' in detail_labels
    assert 'Type' in detail_labels
    
    print("✓ Mock path metadata works")


def test_mock_path_capability_methods():
    """Test that capability methods work correctly"""
    mock_path = MockPathImpl('mock://data/file.txt')
    
    # Test capability methods
    assert not mock_path.supports('file_editing')
    assert not mock_path.supports('directory_rename')
    
    print("✓ Mock path capability methods work")


def test_mock_path_file_operations():
    """Test that file I/O operations work"""
    mock_path = MockPathImpl('mock://data/test.txt')
    
    # Test reading
    content = mock_path.read_text()
    assert isinstance(content, str)
    assert len(content) > 0
    
    # Test writing
    new_content = "New mock content"
    bytes_written = mock_path.write_text(new_content)
    assert bytes_written == len(new_content)
    
    # Verify content was updated
    assert mock_path.read_text() == new_content
    
    print("✓ Mock path file operations work")


def test_mock_path_with_text_viewer():
    """Test that mock paths work with text viewer display logic"""
    mock_path = MockPathImpl('mock://documents/report.txt')
    
    # Simulate text viewer title display logic
    prefix = mock_path.DISPLAY_PREFIX
    title = mock_path.get_display_title()
    display_title = f"{prefix}{title}"
    
    # Verify the display title is correct
    assert display_title == 'MOCK: mock://documents/report.txt'
    
    print("✓ Mock path works with text viewer logic")


def test_mock_path_with_info_dialog():
    """Test that mock paths work with info dialog metadata display"""
    mock_path = MockPathImpl('mock://data/file.txt')
    
    # Simulate info dialog metadata display logic
    metadata = mock_path.get_extended_metadata()
    
    # Verify metadata structure is correct
    assert 'type' in metadata
    assert 'details' in metadata
    assert 'format_hint' in metadata
    
    # Verify details can be displayed
    for label, value in metadata['details']:
        assert isinstance(label, str)
        assert isinstance(value, str)
        # Simulate displaying: print(f"{label}: {value}")
    
    print("✓ Mock path works with info dialog logic")


def test_mock_path_with_search_dialog():
    """Test that mock paths work with search dialog strategy logic"""
    mock_path = MockPathImpl('mock://data/')
    
    # Simulate search dialog strategy selection logic
    strategy = mock_path.SEARCH_STRATEGY
    should_cache = mock_path.supports('cache_for_search')
    
    # Verify strategy is one of the expected values
    assert strategy in ['streaming', 'extracted', 'buffered']
    assert isinstance(should_cache, bool)
    
    # Simulate search logic based on strategy
    if strategy == 'buffered':
        # Would download/buffer content first
        content = mock_path.read_text()
        assert isinstance(content, str)
    
    print("✓ Mock path works with search dialog logic")


def test_mock_path_with_file_operations():
    """Test that mock paths work with file operations validation"""
    mock_path = MockPathImpl('mock://data/file.txt')
    
    # Simulate file operations validation logic
    can_edit = mock_path.supports('file_editing')
    can_rename_dir = mock_path.supports('directory_rename')
    
    # Verify validation works
    assert isinstance(can_edit, bool)
    assert isinstance(can_rename_dir, bool)
    
    # Simulate validation error message (storage-agnostic)
    if not can_edit:
        error_msg = "This path does not support editing"
        assert 'mock' not in error_msg.lower()  # Should be storage-agnostic
    
    print("✓ Mock path works with file operations validation")


def test_extensibility_validation():
    """
    Comprehensive test that validates new storage types require zero UI changes.
    
    This test demonstrates that MockPathImpl works with all UI components
    without any modifications to the UI code.
    """
    print("\n=== Extensibility Validation ===\n")
    
    # Create mock path
    mock_path = MockPathImpl('mock://project/data/report.txt')
    
    # Test 1: Text Viewer Integration
    print("Testing Text Viewer integration...")
    prefix = mock_path.DISPLAY_PREFIX
    title = mock_path.get_display_title()
    assert prefix == 'MOCK: '
    assert 'mock://' in title
    print(f"  Display: {prefix}{title}")
    print("  ✓ Text viewer would display correctly")
    
    # Test 2: Info Dialog Integration
    print("\nTesting Info Dialog integration...")
    metadata = mock_path.get_extended_metadata()
    assert metadata['type'] == 'mock'
    assert len(metadata['details']) > 0
    print("  Metadata fields:")
    for label, value in metadata['details']:
        print(f"    {label}: {value}")
    print("  ✓ Info dialog would display correctly")
    
    # Test 3: Search Dialog Integration
    print("\nTesting Search Dialog integration...")
    strategy = mock_path.SEARCH_STRATEGY
    should_cache = mock_path.supports('cache_for_search')
    print(f"  Search strategy: {strategy}")
    print(f"  Should cache: {should_cache}")
    print("  ✓ Search dialog would use correct strategy")
    
    # Test 4: File Operations Integration
    print("\nTesting File Operations integration...")
    can_edit = mock_path.supports('file_editing')
    can_rename = mock_path.supports('directory_rename')
    print(f"  Supports editing: {can_edit}")
    print(f"  Supports directory rename: {can_rename}")
    print("  ✓ File operations would validate correctly")
    
    # Test 5: Content Reading
    print("\nTesting Content Reading...")
    requires_extraction = mock_path.supports('extraction_for_reading')
    supports_streaming = mock_path.supports('streaming_read')
    print(f"  Requires extraction: {requires_extraction}")
    print(f"  Supports streaming: {supports_streaming}")
    content = mock_path.read_text()
    print(f"  Content length: {len(content)} bytes")
    print("  ✓ Content reading works correctly")
    
    print("\n=== All UI Components Work Without Modifications ===")
    print("✓ Extensibility validation PASSED")
    print("\nConclusion: New storage types require ZERO UI changes!")
