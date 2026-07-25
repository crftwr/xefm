# Path Polymorphism System

## Overview

The Path Polymorphism System is XeFM's core abstraction layer that enables storage-agnostic code throughout the application. By extending the `PathImpl` interface with strategic virtual methods, the system eliminates all storage-specific conditionals from UI and dialog code, making it trivial to add new storage types without modifying existing code.

## Architecture

### Component Hierarchy

```mermaid
flowchart TB
    subgraph UI["UI / Dialog Layer — storage-agnostic (zero if/elif on storage type)"]
        direction LR
        TV["TextViewer"]
        ID["InfoDialog"]
        SD["SearchDialog"]
        FO["FileOperationService"]
    end

    Path["Path — facade (xefm.path)<br/>delegates every call to self._impl"]
    Impl["PathImpl — abstract base (xefm.path)<br/>Display: get_display_prefix / get_display_title<br/>Content strategy: get_search_strategy · supports_streaming_read · requires_extraction_for_reading<br/>Capability: supports_write_operations · is_remote · supports_directory_rename<br/>Metadata: get_extended_metadata"]
    Local["LocalPathImpl<br/>xefm.path"]
    SSH["SSHPathImpl<br/>xefm.ssh"]
    S3["S3PathImpl<br/>xefm.s3"]
    Archive["ArchivePathImpl<br/>xefm.archive"]

    UI -->|polymorphic methods only| Path
    Path -->|delegates| Impl
    Impl --> Local & SSH & S3 & Archive

    classDef ui fill:#1e7e34,stroke:#7fd39b,color:#fff;
    classDef facade fill:#1a5490,stroke:#7fb3d5,color:#fff;
    classDef abc fill:#5e2d70,stroke:#b98fd0,color:#fff;
    classDef impl fill:#9a6308,stroke:#e0b45f,color:#fff;
    class TV,ID,SD,FO ui;
    class Path facade;
    class Impl abc;
    class Local,SSH,S3,Archive impl;
```

### Design Principles

1. **Open/Closed Principle**: Open for extension (new storage types), closed for modification (UI code)
2. **Dependency Inversion**: UI depends on abstractions (PathImpl), not concrete implementations
3. **Single Responsibility**: Each PathImpl subclass handles only its storage type
4. **Polymorphism Over Conditionals**: Behavior varies through method overriding, not if/else checks

## Path Facade and Migration History

### The Facade / Implementation Split

The polymorphism system is built on a three-layer split in `xefm/path.py`:

- **`PathImpl` (abstract base)** — defines the full `pathlib.Path`-compatible
  interface (`exists`, `is_dir`, `is_file`, `iterdir`, `stat`, …) plus the
  strategic virtual methods documented below. Instantiating it directly raises
  `TypeError`.
- **`LocalPathImpl` (concrete)** — implements `PathImpl` for the local filesystem
  by wrapping a `pathlib.Path`, so local operations have no overhead and behave
  identically to stock `pathlib`.
- **`Path` (facade)** — the public class every module imports. It holds a single
  `self._impl` and delegates every call to it. `Path.__init__` selects the
  implementation via **`Path._create_implementation(path_str)`**, which dispatches
  by URI scheme.

`_create_implementation` is the real entry point for backend selection (there is
no `Path()`): it returns an `ArchivePathImpl`, `S3PathImpl`, or
`SSHPathImpl` for the matching scheme, and falls back to `LocalPathImpl` for
ordinary paths. `Path.__init__` also keeps the raw URI intact (instead of running
it through `PathlibPath`) for any registered remote scheme.

### pathlib Compatibility

The facade preserves 100% compatibility with `pathlib.Path`:

- **Import swap only** — modules migrated from `from pathlib import Path` to
  `from xefm.path import Path`; call sites were left unchanged.
- **Same behavior and performance** — local paths delegate straight to `pathlib.Path`.
- **Zero breaking changes** — existing local-path code kept working through the migration.

### Migration History

XeFM originally used `pathlib.Path` directly throughout `src/`. To make room for
non-local storage without rewriting call sites, the codebase was migrated to the
`Path` facade above. All `src/` modules that touch paths were switched to
`from xefm.path import Path` — including `xefm/app.py`, `xefm/file_operations.py`,
`xefm/pane_manager.py`, `xefm/state_manager.py`, `xefm/config.py`,
`xefm/text_viewer.py`, and the various dialog modules.

What early design notes framed as "future remote storage" now **exists**: the
archive (`xefm.archive.ArchivePathImpl`), S3 (`xefm.s3.S3PathImpl`), and SSH/SFTP
(`xefm.ssh.SSHPathImpl`) backends are all implemented and selected automatically by
`_create_implementation`. Additional schemes (FTP, WebDAV, etc.) can be added the
same way — see "Adding New Storage Types" below.

## PathImpl Virtual Methods

The `PathImpl` abstract base class defines 7 strategic virtual methods that encapsulate all storage-specific behavior:

### Display Methods

#### `get_display_prefix() -> str`

Returns a prefix string for display purposes in viewers and dialogs.

**Purpose**: Allows each storage type to identify itself visually without UI code needing to check storage types.

**Return Values**:
- Local files: `""` (empty string)
- Archive files: `"ARCHIVE: "` (with trailing space)
- S3 objects: `"S3: "` (with trailing space)

**Usage Example**:
```python
# In text viewer
title = path.get_display_prefix() + path.get_display_title()
```

**Implementation Requirements**:
- Must return a string (never None)
- If non-empty, should include trailing space for formatting
- Should be short and recognizable

#### `get_display_title() -> str`

Returns a formatted title string appropriate for display.

**Purpose**: Provides storage-appropriate formatting for path display without UI code parsing URIs.

**Return Values**:
- Local files: Standard path string (e.g., `/home/user/file.txt`)
- Archive files: Full archive URI (e.g., `archive:///path/to/file.zip#internal/path.txt`)
- S3 objects: S3 URI (e.g., `s3://bucket/key`)

**Usage Example**:
```python
# In info dialog
dialog.add_line(f"Path: {path.get_display_title()}")
```

**Implementation Requirements**:
- Must return a string (never None)
- Should be human-readable
- Should uniquely identify the resource

### Content Reading Strategy Methods

#### `requires_extraction_for_reading() -> bool`

Indicates whether content must be extracted before reading.

**Purpose**: Informs code whether direct file access is possible or if extraction/download is needed.

**Return Values**:
- Local files: `False` (direct access via filesystem)
- Archive files: `True` (must extract from archive)
- S3 objects: `True` (must download from S3)

**Usage Example**:
```python
if path.requires_extraction_for_reading():
    content = path.read_text()  # Full extraction
else:
    with open(path) as f:  # Direct access
        content = f.read()
```

**Implementation Requirements**:
- Must return boolean
- Should reflect actual access requirements
- Affects memory usage and performance

#### `supports_streaming_read() -> bool`

Indicates whether file can be read line-by-line without full extraction.

**Purpose**: Enables memory-efficient operations like search for storage types that support streaming.

**Return Values**:
- Local files: `True` (can iterate line-by-line)
- Archive files: `False` (must read entire content)
- S3 objects: `False` (must download entire object)

**Usage Example**:
```python
if path.supports_streaming_read():
    with open(path) as f:
        for line in f:  # Memory-efficient
            process_line(line)
else:
    content = path.read_text()  # Must load all
    for line in content.splitlines():
        process_line(line)
```

**Implementation Requirements**:
- Must return boolean
- Should be consistent with `requires_extraction_for_reading()`
- Affects search performance and memory usage

#### `get_search_strategy() -> str`

Returns the recommended search strategy for this storage type.

**Purpose**: Allows each storage type to specify optimal search approach without search code containing storage-specific logic.

**Return Values**:
- Local files: `"streaming"` (line-by-line reading)
- Archive files: `"extracted"` (extract entire content)
- S3 objects: `"buffered"` (download to buffer)

**Usage Example**:
```python
strategy = path.get_search_strategy()
if strategy == 'streaming':
    search_streaming(path, pattern)
elif strategy == 'extracted':
    search_extracted(path, pattern)
elif strategy == 'buffered':
    search_buffered(path, pattern)
```

**Implementation Requirements**:
- Must return one of: `"streaming"`, `"extracted"`, `"buffered"`
- Should match the storage type's capabilities
- Should optimize for performance and memory

#### `should_cache_for_search() -> bool`

Indicates whether content should be cached during search operations.

**Purpose**: Allows storage types to specify caching behavior for performance optimization.

**Return Values**:
- Local files: `False` (direct access is efficient)
- Archive files: `True` (extraction is expensive)
- S3 objects: `True` (download is expensive)

**Usage Example**:
```python
if path.should_cache_for_search():
    if path not in cache:
        cache[path] = path.read_text()
    content = cache[path]
else:
    content = path.read_text()
```

**Implementation Requirements**:
- Must return boolean
- Should consider extraction/download cost
- Should balance memory vs. performance

### Metadata Method

#### `get_extended_metadata() -> Dict[str, any]`

Returns storage-specific metadata for display in info dialogs.

**Purpose**: Provides structured metadata appropriate for each storage type without info dialog containing storage-specific code.

**Return Structure**:
```python
{
    'type': str,              # Storage type: 'local', 'archive', 's3'
    'details': [              # List of (label, value) tuples
        (str, str),           # e.g., ('Size', '1.2 MB')
        (str, str),           # e.g., ('Modified', '2024-01-15 10:30:00')
        ...
    ],
    'format_hint': str        # Display format: 'standard', 'archive', 'remote'
}
```

**Storage-Specific Details**:

**Local Files**:
```python
{
    'type': 'local',
    'details': [
        ('Type', 'File' or 'Directory'),
        ('Size', '1.2 MB'),
        ('Permissions', 'rwxr-xr-x'),
        ('Modified', '2024-01-15 10:30:00')
    ],
    'format_hint': 'standard'
}
```

**Archive Files**:
```python
{
    'type': 'archive',
    'details': [
        ('Archive', 'data.zip'),
        ('Internal Path', 'folder/file.txt'),
        ('Type', 'File'),
        ('Compressed Size', '1.2 MB'),
        ('Uncompressed Size', '3.4 MB'),
        ('Compression', 'Deflated'),
        ('Modified', '2024-01-15 10:30:00')
    ],
    'format_hint': 'archive'
}
```

**S3 Objects**:
```python
{
    'type': 's3',
    'details': [
        ('Bucket', 'my-bucket'),
        ('Key', 'path/to/object'),
        ('Type', 'Object'),
        ('Size', '1.2 MB'),
        ('Storage Class', 'STANDARD'),
        ('Last Modified', '2024-01-15 10:30:00')
    ],
    'format_hint': 'remote'
}
```

**Usage Example**:
```python
metadata = path.get_extended_metadata()
for label, value in metadata['details']:
    dialog.add_line(f"{label}: {value}")
```

**Implementation Requirements**:
- Must return dict with required keys: `type`, `details`, `format_hint`
- `details` must be list of (str, str) tuples
- `type` must be one of: `'local'`, `'archive'`, `'s3'`, or custom type name
- `format_hint` should guide display formatting
- Values should be human-readable strings

## Adding New Storage Types

Adding a new storage type to XeFM requires zero changes to UI code. Follow these steps:

### Step 1: Create PathImpl Subclass

Create a new class that inherits from `PathImpl` and implements all abstract methods:

```python
from src.xefm.path import PathImpl
from typing import Dict, List, Tuple

class CustomPathImpl(PathImpl):
    """Implementation for custom storage type."""
    
    def __init__(self, uri: str):
        self._uri = uri
        # Initialize storage-specific state
    
    # Implement all abstract methods from PathImpl
    # (exists, is_dir, is_file, iterdir, stat, etc.)
    
    # Implement the 7 virtual methods
    
    def get_display_prefix(self) -> str:
        return "CUSTOM: "
    
    def get_display_title(self) -> str:
        return self._uri
    
    def requires_extraction_for_reading(self) -> bool:
        return True  # or False based on your storage
    
    def supports_streaming_read(self) -> bool:
        return False  # or True based on your storage
    
    def get_search_strategy(self) -> str:
        return 'buffered'  # or 'streaming' or 'extracted'
    
    def should_cache_for_search(self) -> bool:
        return True  # or False based on performance
    
    def get_extended_metadata(self) -> Dict[str, any]:
        return {
            'type': 'custom',
            'details': [
                ('Custom Field 1', 'value1'),
                ('Custom Field 2', 'value2'),
                # Add storage-specific fields
            ],
            'format_hint': 'remote'  # or 'standard' or 'archive'
        }
```

### Step 2: Register with the Path Factory

Add your scheme to the `Path._create_implementation()` method in `xefm/path.py`.
This instance method is called from `Path.__init__` and selects the implementation
by URI scheme:

```python
def _create_implementation(self, path_str: str) -> PathImpl:
    """Create the appropriate implementation based on the path string"""
    if path_str.startswith('custom://'):
        from xefm_custom import CustomPathImpl
        return CustomPathImpl(path_str)
    if path_str.startswith('archive://'):
        # ... existing archive handling
    if path_str.startswith('s3://'):
        # ... existing S3 handling
    if path_str.startswith('ssh://'):
        # ... existing SSH handling
    # Default to the local file system
    return LocalPathImpl(PathlibPath(path_str))
```

Also add the scheme to the prefix tuple in `Path.__init__`, so the raw URI is
passed through untouched instead of being normalized by `PathlibPath`:

```python
if len(args) == 1 and isinstance(args[0], str) and args[0].startswith(
        ('archive://', 's3://', 'ssh://', 'scp://', 'ftp://', 'custom://')):
    path_str = args[0]
```

### Step 3: Add Capability Methods (if needed)

If your storage type has specific capabilities, add methods to your PathImpl:

```python
class CustomPathImpl(PathImpl):
    # ... other methods ...
    
    def supports_file_editing(self) -> bool:
        return False  # Custom storage is read-only
    
    def supports_directory_rename(self) -> bool:
        return False  # Custom storage doesn't support rename
```

### Step 4: Test Your Implementation

Create unit tests for your new PathImpl:

```python
def test_custom_path_display():
    path = Path('custom://resource')
    assert path.get_display_prefix() == "CUSTOM: "
    assert path.get_display_title() == 'custom://resource'

def test_custom_path_metadata():
    path = Path('custom://resource')
    metadata = path.get_extended_metadata()
    assert metadata['type'] == 'custom'
    assert len(metadata['details']) > 0
```

### Step 5: Verify UI Integration

Run existing UI tests to verify your storage type works:

```bash
# Text viewer should work automatically
python -m pytest test/test_text_viewer_refactoring.py

# Info dialog should work automatically
python -m pytest test/test_info_dialog_refactoring.py

# Search dialog should work automatically
python -m pytest test/test_archive_search_integration.py
```

**That's it!** No UI code changes needed. The polymorphic architecture handles everything.

## Implementation Checklist

When implementing a new storage type:

- [ ] Create PathImpl subclass with all abstract methods
- [ ] Implement `get_display_prefix()` - return appropriate prefix
- [ ] Implement `get_display_title()` - return formatted title
- [ ] Implement `requires_extraction_for_reading()` - return True/False
- [ ] Implement `supports_streaming_read()` - return True/False
- [ ] Implement `get_search_strategy()` - return strategy string
- [ ] Implement `should_cache_for_search()` - return True/False
- [ ] Implement `get_extended_metadata()` - return metadata dict
- [ ] Add capability methods if needed (supports_file_editing, etc.)
- [ ] Register with Path factory
- [ ] Write unit tests for all methods
- [ ] Run integration tests to verify UI compatibility
- [ ] Test with real storage operations

## Common Patterns

### Read-Only Storage

For read-only storage types (archives, remote filesystems):

```python
def supports_file_editing(self) -> bool:
    return False

def supports_directory_rename(self) -> bool:
    return False
```

### Remote Storage

For remote storage types (S3, SFTP, WebDAV):

```python
def requires_extraction_for_reading(self) -> bool:
    return True  # Must download

def supports_streaming_read(self) -> bool:
    return False  # Must download entire file

def get_search_strategy(self) -> str:
    return 'buffered'  # Download to buffer

def should_cache_for_search(self) -> bool:
    return True  # Download is expensive
```

### Local-Like Storage

For storage types with direct filesystem access:

```python
def requires_extraction_for_reading(self) -> bool:
    return False  # Direct access

def supports_streaming_read(self) -> bool:
    return True  # Can iterate line-by-line

def get_search_strategy(self) -> str:
    return 'streaming'  # Memory-efficient

def should_cache_for_search(self) -> bool:
    return False  # Direct access is fast
```

## Migration Guide

### For Existing Code

If you have existing code that checks storage types, migrate it to use virtual methods:

#### Before (Storage-Specific Conditionals):
```python
# Bad - checks storage type
if path.scheme == 'archive':
    title = f"ARCHIVE: {path.uri}"
else:
    title = str(path)
```

#### After (Polymorphic):
```python
# Good - uses virtual methods
title = path.get_display_prefix() + path.get_display_title()
```

#### Before (String Parsing):
```python
# Bad - parses URI string
if path.uri.startswith('archive://'):
    metadata = get_archive_metadata(path)
else:
    metadata = get_local_metadata(path)
```

#### After (Polymorphic):
```python
# Good - uses virtual method
metadata = path.get_extended_metadata()
```

#### Before (isinstance Checks):
```python
# Bad - checks concrete type
from src.xefm.archive import ArchivePathImpl
if isinstance(path._impl, ArchivePathImpl):
    strategy = 'extracted'
else:
    strategy = 'streaming'
```

#### After (Polymorphic):
```python
# Good - uses virtual method
strategy = path.get_search_strategy()
```

### Migration Checklist

When refactoring existing code:

- [ ] Remove all `if scheme == 'archive'` checks
- [ ] Remove all `if scheme == 's3'` checks
- [ ] Remove all `uri.startswith('archive://')` checks
- [ ] Remove all `isinstance(path._impl, ArchivePathImpl)` checks
- [ ] Remove imports of concrete PathImpl classes from UI code
- [ ] Replace with virtual method calls
- [ ] Update error messages to be storage-agnostic
- [ ] Test with all storage types

## Performance Considerations

### Virtual Method Overhead

Virtual method calls in Python have negligible overhead:
- Method lookup is cached by Python's attribute resolution
- No measurable performance impact in practice
- Benefits of clean architecture far outweigh any theoretical cost

### Caching Strategies

Use `should_cache_for_search()` to implement smart caching:

```python
class SearchDialog:
    def __init__(self):
        self._content_cache = {}
    
    def search_file(self, path, pattern):
        if path.should_cache_for_search():
            if path not in self._content_cache:
                self._content_cache[path] = path.read_text()
            content = self._content_cache[path]
        else:
            content = path.read_text()
        
        return self._search_content(content, pattern)
```

### Memory Management

Use `supports_streaming_read()` for memory-efficient operations:

```python
def search_large_file(path, pattern):
    if path.supports_streaming_read():
        # Memory-efficient: process line by line
        with open(path) as f:
            for line_num, line in enumerate(f, 1):
                if pattern in line:
                    yield (line_num, line)
    else:
        # Must load entire file
        content = path.read_text()
        for line_num, line in enumerate(content.splitlines(), 1):
            if pattern in line:
                yield (line_num, line)
```

## Testing Guidelines

### Unit Tests

Test each virtual method independently:

```python
def test_display_prefix():
    """Test get_display_prefix() returns correct value."""
    path = create_test_path()
    prefix = path.get_display_prefix()
    assert isinstance(prefix, str)
    assert prefix == expected_prefix

def test_metadata_structure():
    """Test get_extended_metadata() returns valid structure."""
    path = create_test_path()
    metadata = path.get_extended_metadata()
    assert 'type' in metadata
    assert 'details' in metadata
    assert 'format_hint' in metadata
    assert isinstance(metadata['details'], list)
    for label, value in metadata['details']:
        assert isinstance(label, str)
        assert isinstance(value, str)
```

### Integration Tests

Test UI components work with your storage type:

```python
def test_text_viewer_with_custom_storage():
    """Test text viewer displays custom storage correctly."""
    path = Path('custom://resource')
    viewer = TextViewer(path)
    title = viewer.get_title()
    assert 'CUSTOM:' in title

def test_info_dialog_with_custom_storage():
    """Test info dialog shows custom metadata."""
    path = Path('custom://resource')
    dialog = InfoDialog(path)
    content = dialog.get_content()
    assert 'Custom Field 1' in content
```

### Property-Based Tests

Use Hypothesis to test properties across many inputs:

```python
from hypothesis import given, strategies as st

@given(st.text())
def test_display_methods_never_none(uri):
    """Test display methods never return None."""
    path = Path(f'custom://{uri}')
    assert path.get_display_prefix() is not None
    assert path.get_display_title() is not None

@given(st.text())
def test_metadata_structure_valid(uri):
    """Test metadata structure is always valid."""
    path = Path(f'custom://{uri}')
    metadata = path.get_extended_metadata()
    assert isinstance(metadata, dict)
    assert 'type' in metadata
    assert 'details' in metadata
```

## Troubleshooting

### Common Issues

**Issue**: UI code still has storage-specific conditionals
**Solution**: Search for `if scheme ==`, `if uri.startswith`, `isinstance(path._impl` and replace with virtual method calls

**Issue**: New storage type not recognized
**Solution**: Verify `Path._create_implementation()` includes your URI scheme

**Issue**: Metadata not displaying correctly
**Solution**: Verify `get_extended_metadata()` returns dict with required keys and proper structure

**Issue**: Search not working with new storage type
**Solution**: Verify `get_search_strategy()` returns valid strategy string and implement corresponding search logic

### Debugging Tips

Enable verbose logging to see virtual method calls:

```python
class Path:
    def get_display_prefix(self) -> str:
        result = self._impl.get_display_prefix()
        print(f"get_display_prefix() -> {result!r}")
        return result
```

Verify PathImpl implementation:

```python
from abc import ABC
import inspect

def verify_pathimpl(impl_class):
    """Verify PathImpl subclass implements all required methods."""
    abstract_methods = {
        name for name, method in inspect.getmembers(PathImpl)
        if getattr(method, '__isabstractmethod__', False)
    }
    
    implemented = set(dir(impl_class))
    missing = abstract_methods - implemented
    
    if missing:
        print(f"Missing methods: {missing}")
    else:
        print("All abstract methods implemented!")
```

## Best Practices

1. **Never check storage type in UI code** - Always use virtual methods
2. **Keep virtual methods simple** - They should return data, not perform complex operations
3. **Document return values** - Be explicit about what each method returns
4. **Test thoroughly** - Verify all virtual methods work correctly
5. **Follow naming conventions** - Use descriptive method names that indicate purpose
6. **Handle errors gracefully** - Return sensible defaults if operations fail
7. **Optimize for common case** - Make frequent operations efficient
8. **Cache expensive operations** - Use `should_cache_for_search()` appropriately
9. **Keep metadata human-readable** - Format values for display
10. **Maintain consistency** - Similar storage types should behave similarly

## References

- **Source Code**: `xefm/path.py` - PathImpl interface and Path facade
- **Implementations**: `xefm/path.py` (Local), `xefm/archive.py` (Archive), `xefm/s3.py` (S3), `xefm/ssh.py` (SSH/SFTP)
- **UI Integration**: `xefm/text_viewer.py`, `xefm/text_dialog.py`, `xefm/progressive_search_dialog.py`
- **Tests**: `test/test_virtual_methods_checkpoint.py`, `test/test_info_dialog_refactoring.py`
- **Design Document**: `.kiro/specs/path-polymorphism-refactoring/design.md`
- **Requirements**: `.kiro/specs/path-polymorphism-refactoring/requirements.md`
