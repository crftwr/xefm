# XeFM Drives Dialog System

## Overview

The Drives Dialog System is a unified interface for selecting and navigating to different storage locations in XeFM, including local filesystem directories and remote S3 buckets. This system enhances XeFM's navigation capabilities by offering quick access to commonly used storage locations through a clean, consistent interface.

## Features

### Storage Types Supported

#### Local Filesystem
- **Home directory** (🏠) - User's home directory
- **Root directory** (📁) - System root directory
- **Current working directory** (📁) - Directory where XeFM was launched
- **Common system directories**:
  - Documents, Downloads, Desktop
  - Applications directory (macOS)
  - System directories (/usr/local, /opt, /tmp)

#### AWS S3 Storage
- **All accessible S3 buckets** (☁️) - Automatic discovery using AWS credentials
- **Bucket metadata** - Creation dates and descriptions
- **Graceful credential handling** - Clear messaging when credentials unavailable
- **Error recovery** - Robust handling of network and permission issues

### User Interface

#### Dialog Layout
- **Clean, centered dialog** with consistent XeFM styling
- **Visual indicators** with clear icons for different storage types
- **Real-time filtering** - Type to filter drives by name, path, or description
- **Progress animation** - Animated loading indicator during S3 bucket scanning
- **Status information** - Shows count of local vs S3 drives

#### Navigation Controls

| Key | Action |
|-----|--------|
| `↑/↓` | Navigate up/down through drives |
| `Page Up/Down` | Navigate by pages |
| `Home/End` | Jump to first/last drive |
| `Type` | Filter drives by text |
| `Enter` | Select and navigate to drive |
| `ESC` | Cancel and close dialog |

## Technical Implementation

### Architecture

The Drives Dialog follows XeFM's modular dialog architecture with clean separation of concerns:

#### Core Components

##### DriveEntry Class
```python
class DriveEntry:
    def __init__(self, name: str, path: str, description: str = "", icon: str = "💾")
    
    @property
    def display_name(self) -> str
    
    @property
    def full_description(self) -> str
```

Represents individual storage locations with:
- **Name**: Display name for the drive
- **Path**: Full path or URI (e.g., `s3://bucket-name/`)
- **Description**: Additional information (creation date, type, etc.)
- **Icon**: Visual indicator (🏠, 📁, ☁️, 💾)

##### DrivesDialog Class
```python
class DrivesDialog(BaseListDialog):
    def __init__(self, config)
    def show(self)
    def exit(self)
    def handle_input(self, key)
    def draw(self, stdscr, safe_addstr_func)
    def get_selected_drive(self) -> Optional[DriveEntry]
```

Main dialog class extending `BaseListDialog` with:
- **Threading support** for background S3 scanning
- **Real-time filtering** with efficient search algorithms
- **Progress animation** during loading operations
- **Thread-safe access** to drive lists

##### DrivesDialogHelpers Class
```python
class DrivesDialogHelpers:
    @staticmethod
    def navigate_to_drive(file_manager, drive_entry: DriveEntry)
    
    @staticmethod
    def get_local_drives() -> List[DriveEntry]
    
    @staticmethod
    def get_s3_drives() -> List[DriveEntry]
```

Static helper methods for:
- **Navigation integration** with XeFM's pane system
- **Drive discovery** for local filesystem
- **S3 bucket enumeration** with error handling

### Threading Support

#### Background S3 Scanning
```python
def _scan_s3_buckets_thread(self):
    """Background thread for S3 bucket discovery"""
    try:
        # Discover S3 buckets using boto3
        s3_drives = DrivesDialogHelpers.get_s3_drives()
        
        # Thread-safe update of drive list
        with self._drives_lock:
            self.s3_drives = s3_drives
            self.drives_loaded = True
            self.content_changed = True
    except Exception as e:
        # Handle errors gracefully
        self._handle_s3_error(e)
```

Features:
- **Non-blocking operation** - UI remains responsive during S3 discovery
- **Thread-safe access** - Uses locks for safe data sharing
- **Cancellable operations** - Can be interrupted when dialog is closed
- **Error handling** - Graceful degradation on network/credential issues

#### Progress Animation
```python
def _get_loading_indicator(self) -> str:
    """Animated loading indicator for S3 scanning"""
    if not self.scanning_s3:
        return ""
    
    frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    frame_index = (time.time() * 4) % len(frames)
    return frames[int(frame_index)]
```

Provides smooth visual feedback during background operations.

### Error Handling

#### Local Filesystem Errors
- **Permission Denied**: Directories are skipped silently
- **Path Not Found**: Stale entries are filtered out
- **Access Errors**: Graceful fallback to available directories

#### S3 Errors
- **No Credentials**: Shows helpful placeholder with configuration instructions
- **Network Errors**: Shows error message with retry capability
- **Permission Errors**: Shows accessible buckets only
- **Service Errors**: Graceful degradation to local-only mode

#### Error Recovery Patterns
```python
def _handle_s3_error(self, error):
    """Handle S3 errors with appropriate user feedback"""
    if isinstance(error, NoCredentialsError):
        self._add_s3_placeholder("S3 (No Credentials)", 
                                "Configure AWS credentials to access S3 buckets")
    elif isinstance(error, ClientError):
        self._add_s3_placeholder("S3 (Access Error)", 
                                f"Error accessing S3: {error}")
    else:
        self._add_s3_placeholder("S3 (Error)", 
                                "Unable to load S3 buckets")
```

### Performance Optimization

#### Efficient Filtering
```python
def _filter_drives(self, filter_text: str) -> List[DriveEntry]:
    """Efficient case-insensitive filtering of drives"""
    if not filter_text:
        return self.all_drives
    
    filter_lower = filter_text.lower()
    return [drive for drive in self.all_drives 
            if filter_lower in drive.name.lower() 
            or filter_lower in drive.path.lower() 
            or filter_lower in drive.description.lower()]
```

#### Memory Management
- **Lazy loading** of S3 buckets
- **Minimal memory footprint** for drive entries
- **Efficient data structures** for filtering and navigation

#### Background Loading
- **Non-blocking S3 discovery** maintains UI responsiveness
- **Real-time updates** as buckets are discovered
- **Cancellation support** prevents resource leaks

## Integration with XeFM

### Main Application Integration

#### Initialization
```python
# In FileManager.__init__()
self.drives_dialog = DrivesDialog(self.config)
```

#### Input Handling
```python
# In FileManager.run() main loop
elif self.is_key_for_action(key, 'drives'):
    self.show_drives_dialog()

# Dialog input handling
if self.drives_dialog.mode:
    result = self.drives_dialog.handle_input(key)
    if result == 'select':
        selected_drive = self.drives_dialog.get_selected_drive()
        if selected_drive:
            DrivesDialogHelpers.navigate_to_drive(self, selected_drive)
        self.drives_dialog.exit()
    elif result == 'cancel':
        self.drives_dialog.exit()
```

#### Drawing Integration
```python
# In main draw loop
def _draw_dialogs_if_needed(self):
    if self.drives_dialog.mode:
        self.drives_dialog.draw(self.stdscr, self.safe_addstr)
```

### Pane Manager Integration

#### Navigation Implementation
```python
@staticmethod
def navigate_to_drive(file_manager, drive_entry: DriveEntry):
    """Navigate to selected drive in active pane"""
    try:
        # Update active pane path
        active_pane = file_manager.get_active_pane()
        active_pane['path'] = Path(drive_entry.path)
        active_pane['selected_files'] = set()
        active_pane['scroll_offset'] = 0
        
        # Refresh pane content
        file_manager.refresh_files()
        file_manager.needs_full_redraw = True
        
        # User feedback
        file_manager.show_status(f"Navigated to: {drive_entry.name}")
        
    except Exception as e:
        file_manager.show_error(f"Failed to navigate to {drive_entry.name}: {e}")
```

## Configuration

### Key Bindings

Default configuration in `xefm/_config.py`:

```python
KEY_BINDINGS = {
    # ... other bindings ...
    'drives': ['d', 'D'],  # Show drives/storage selection dialog
}
```

### Fixed locations (`DRIVE_LOCATIONS`)

The rows above the mounted volumes are configurable (issue #356); everything
below them — Windows drive letters, `/Volumes`, `/media`, `/mnt`, the hosts in
`~/.ssh/config`, S3 buckets — is always discovered, never configured.

```python
DRIVE_LOCATIONS = None   # built-in set (default)
DRIVE_LOCATIONS = []     # no fixed rows at all — only what is discovered
DRIVE_LOCATIONS = [{'name': 'Work', 'path': '~/work'}]
```

`config.get_drive_locations()` resolves it, and `XeFMApp._local_drives()` starts
from what it returns. The resolution is deliberately a *replacement*, not a
filter: a user who wants `Documents` gone says what they do want, rather than
naming what to subtract.

Three rules live in `get_drive_locations()`:

- `None` means the built-in set (`_default_drive_locations()`): Home, Root on
  POSIX only — on Windows the drive letters already cover it — and whichever of
  Documents / Downloads / Desktop exist.
- A local path is dropped unless it exists and is a directory. Missing *default*
  folders are silent (no Desktop is normal); a missing *configured* one warns,
  because a hand-written path that isn't there is a typo.
- A path opening with a remote scheme (`_REMOTE_SCHEMES`: `ssh://`, `s3://`, …)
  is passed through unprobed. `Path.exists()` on one would open a connection on
  the UI thread while the picker is being built — the picker's job is to *offer*
  a connection, not to make one.

### Customization Options

The drives dialog respects existing XeFM configuration:
- **Color scheme settings** - Uses XeFM's color configuration
- **Animation preferences** - Respects animation settings
- **Dialog sizing ratios** - Follows XeFM dialog conventions

## Usage Examples

### Basic Usage

1. **Open Dialog**: Press `d` or `D` to open the drives dialog
2. **Navigate**: Use arrow keys to navigate through available drives
3. **Filter**: Type to filter drives (e.g., type "s3" to show only S3 buckets)
4. **Select**: Press `Enter` to navigate to selected drive
5. **Cancel**: Press `ESC` to cancel and close dialog

### Filtering Examples

- **Type "home"** → Shows home directory and related paths
- **Type "s3"** → Shows only S3 buckets
- **Type "doc"** → Shows Documents directory and S3 buckets with "doc" in name
- **Type "tmp"** → Shows temporary directories

### S3 Integration Scenarios

#### With AWS Credentials Configured
- All accessible S3 buckets are automatically discovered
- Bucket creation dates are shown in descriptions
- Navigation to S3 buckets enables S3 file operations
- Background loading with progress animation

#### Without AWS Credentials
- Placeholder entry shows "S3 (No Credentials)"
- Instructions for configuring AWS credentials
- Local drives remain fully functional

## Testing

### Test Coverage

#### Unit Tests (`test/test_drives_dialog.py`)
- Drive entry creation and formatting
- Dialog state management
- Filtering functionality
- Error handling scenarios

#### Integration Tests (`test/test_drives_dialog_integration.py`)
- XeFM component integration
- Navigation helpers
- Pane manager integration
- Configuration system integration


### Test Scenarios

1. **Drive Discovery**
   - Local filesystem enumeration
   - S3 bucket discovery with valid credentials
   - Error handling with invalid/missing credentials

2. **User Interface**
   - Navigation controls (up/down, page up/down, home/end)
   - Real-time filtering
   - Progress animation during loading
   - Visual indicators and icons

3. **Integration**
   - Pane navigation after drive selection
   - State management and cleanup
   - Error handling and user feedback

4. **Threading**
   - Background S3 scanning
   - Thread safety and cancellation
   - Race condition prevention

### Test Results

All tests pass successfully:
- ✅ **Unit Tests**: Basic functionality verified
- ✅ **Integration Tests**: XeFM integration working correctly
- ✅ **Demo Script**: Interactive testing successful
- ✅ **Manual Testing**: Verified with real S3 buckets and local filesystem

## Dependencies

### Required Dependencies
- **Python 3.9+**: Core language support
- **curses**: Terminal UI library
- **threading**: Background S3 scanning
- **pathlib**: Path manipulation

### Optional Dependencies
- **boto3**: AWS S3 integration (graceful fallback if not available)
- **botocore**: AWS error handling

### Installation Notes

The drives dialog is automatically available when XeFM is installed. For S3 functionality:

```bash
# Install AWS SDK
pip install boto3

# Configure AWS credentials
aws configure
# or set environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-west-2
```

## Benefits

### User Experience Benefits
- **Unified Interface**: Single dialog for all storage types
- **Quick Access**: Faster navigation to frequently used locations
- **Visual Clarity**: Clear icons and descriptions for each drive
- **Responsive**: Real-time filtering and background loading
- **Intuitive**: Familiar navigation controls and keyboard shortcuts

### Developer Benefits
- **Extensible**: Easy to add new storage types
- **Maintainable**: Clean separation of concerns
- **Testable**: Comprehensive unit test coverage
- **Consistent**: Follows established XeFM patterns
- **Modular**: Reusable components for other dialogs

### Technical Benefits
- **Thread-safe**: Proper concurrency handling
- **Error-resilient**: Graceful error handling and recovery
- **Performance-optimized**: Background loading and efficient filtering
- **Memory-efficient**: Minimal resource usage
- **Scalable**: Handles large numbers of drives efficiently

## Troubleshooting

### Common Issues

#### S3 Buckets Not Showing
**Symptoms**: No S3 buckets appear in the drives dialog
**Solutions**:
- Check AWS credentials: `aws s3 ls`
- Verify network connectivity
- Check IAM permissions for ListBuckets action
- Review AWS region configuration

#### Slow Loading
**Symptoms**: Dialog takes long time to show S3 buckets
**Causes**: 
- Large number of S3 buckets may take time to load
- Network latency affects S3 discovery
- AWS API rate limiting
**Solutions**:
- Consider filtering to reduce visible items
- Check network connection quality
- Verify AWS service status

#### Permission Errors
**Symptoms**: Some drives show access errors
**Causes**:
- Some local directories may not be accessible
- S3 buckets may have restricted access
- Insufficient IAM permissions
**Solutions**:
- Check user permissions for local directories
- Review IAM policies for S3 access
- Verify bucket policies and ACLs

### Debug Information

Enable debug logging to troubleshoot issues:
- S3 operations are logged with error details
- Thread operations show timing information
- Navigation events are tracked
- Error conditions are logged with context

### Error Messages

Common error messages and their meanings:
- **"S3 (No Credentials)"**: AWS credentials not configured
- **"S3 (Access Error)"**: Network or permission issues
- **"S3 (Error)"**: General S3 service error
- **"Failed to navigate to [drive]"**: Navigation error with specific drive

## Future Enhancements

### Planned Features

#### Additional Storage Types
1. **SFTP/SSH Remote Directories**
   - SSH key authentication
   - Password authentication
   - Connection management

2. **FTP Servers**
   - FTP and FTPS support
   - Anonymous and authenticated access
   - Directory browsing

3. **Network Shares**
   - SMB/CIFS support
   - Windows network drives
   - Authentication handling

4. **Cloud Storage**
   - Google Drive integration
   - Dropbox support
   - OneDrive connectivity

#### Enhanced Features
1. **Favorite Drives Management**
   - User-defined favorite locations
   - Quick access shortcuts
   - Custom aliases and descriptions

2. **Recent Drives History**
   - Track recently accessed drives
   - Quick access to recent locations
   - Configurable history size

3. **Drive Usage Statistics**
   - Access frequency tracking
   - Usage patterns analysis
   - Smart recommendations

#### Advanced S3 Features
1. **Multi-region Support**
   - Cross-region bucket discovery
   - Region-specific filtering
   - Regional performance optimization

2. **Bucket Metadata Display**
   - Storage class information
   - Versioning status
   - Encryption settings
   - Cost estimation

3. **Access Policy Information**
   - Bucket policy summary
   - Permission analysis
   - Security recommendations

### Implementation Roadmap

#### Phase 1: Core Enhancements
- Favorite drives management
- Recent drives history
- Enhanced error reporting

#### Phase 2: Additional Storage Types
- SFTP/SSH support
- FTP server integration
- Network share support

#### Phase 3: Advanced Features
- Cloud storage integration
- Advanced S3 features
- Usage analytics and recommendations

## API Reference

### DriveEntry Class

```python
class DriveEntry:
    def __init__(self, name: str, path: str, description: str = "", icon: str = "💾")
    
    @property
    def display_name(self) -> str
        """Get formatted display name with icon"""
    
    @property
    def full_description(self) -> str
        """Get complete description including path"""
```

### DrivesDialog Class

```python
class DrivesDialog(BaseListDialog):
    def __init__(self, config)
        """Initialize drives dialog with configuration"""
    
    def show(self)
        """Show the drives dialog and start S3 scanning"""
    
    def exit(self)
        """Exit dialog and cleanup resources"""
    
    def handle_input(self, key) -> str
        """Handle keyboard input, returns 'select', 'cancel', or None"""
    
    def get_selected_drive(self) -> Optional[DriveEntry]
        """Get currently selected drive entry"""
```

### DrivesDialogHelpers Class

```python
class DrivesDialogHelpers:
    @staticmethod
    def navigate_to_drive(file_manager, drive_entry: DriveEntry)
        """Navigate XeFM to the specified drive"""
    
    @staticmethod
    def get_local_drives() -> List[DriveEntry]
        """Get list of local filesystem drives"""
    
    @staticmethod
    def get_s3_drives() -> List[DriveEntry]
        """Get list of accessible S3 buckets"""
```

## Conclusion

The XeFM Drives Dialog System successfully enhances XeFM's navigation capabilities by providing a unified, user-friendly interface for accessing both local and remote storage locations. The implementation follows XeFM's established patterns, includes comprehensive error handling, and provides a solid foundation for future enhancements.

### Key Achievements

- ✅ **Unified Storage Access**: Single interface for local and S3 storage
- ✅ **Thread-safe Background Operations**: Non-blocking S3 bucket discovery
- ✅ **Real-time Filtering**: Efficient search and navigation
- ✅ **Comprehensive Error Handling**: Graceful degradation and recovery
- ✅ **Full XeFM Integration**: Seamless integration with existing architecture
- ✅ **Complete Test Coverage**: Unit, integration, and demo testing
- ✅ **User-friendly Interface**: Clear visual indicators and intuitive controls

The system is production-ready and provides immediate value to XeFM users who work with both local files and cloud storage, while maintaining the performance and reliability standards expected from XeFM.

## Related Documentation

- [S3 Support System](S3_SUPPORT_SYSTEM.md) - S3 integration details
- [Dialog System](DIALOG_SYSTEM.md) - General dialog framework
- [XeFM Application Overview](XEFM_APPLICATION_OVERVIEW.md) - Overall application architecture