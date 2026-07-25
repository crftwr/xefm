# Subshell System Documentation

## Overview

The Subshell System allows users to temporarily suspend the XeFM interface and enter a shell environment with pre-configured environment variables that provide access to the current state of both file panes and selected files. The system includes intelligent remote directory fallback for seamless operation with both local and remote storage.

## Core Features

### ✅ **Shell Environment Access**
- **Temporary suspension** of XeFM interface for shell operations
- **Pre-configured environment variables** with current XeFM state
- **Automatic shell detection** using user's preferred shell
- **Working directory management** with remote fallback support

### ✅ **Environment Variables**
- **Directory variables** for both panes and current context
- **Selected files variables** with automatic shell quoting
- **Control variables** for shell prompt customization
- **Consistent behavior** across local and remote directories

### ✅ **Remote Directory Support**
- **Intelligent fallback** when browsing remote directories
- **Transparent operation** with S3, SCP, and other remote storage
- **User notification** when fallback occurs
- **Full functionality** maintained via environment variables

## Activation

- **Key binding**: `x` or `X`
- **Action**: Suspends XeFM curses interface and starts a new shell session
- **Visual indicator**: Shell prompt includes `[XeFM]` label for easy identification
- **Working directory**: Automatically set to appropriate directory (with remote fallback)

## Environment Variables

When entering subshell mode, the following environment variables are automatically set:

### Directory Variables
- `XEFM_LEFT_DIR`: Absolute path of the left file pane directory
- `XEFM_RIGHT_DIR`: Absolute path of the right file pane directory  
- `XEFM_THIS_DIR`: Absolute path of the currently focused pane directory
- `XEFM_OTHER_DIR`: Absolute path of the non-focused pane directory

### Selected Files Variables
- `XEFM_LEFT_SELECTED`: Space-separated list of shell-quoted file names in the left pane
- `XEFM_RIGHT_SELECTED`: Space-separated list of shell-quoted file names in the right pane
- `XEFM_THIS_SELECTED`: Space-separated list of shell-quoted file names in the focused pane
- `XEFM_OTHER_SELECTED`: Space-separated list of shell-quoted file names in the non-focused pane

### Control Variables
- `XEFM_ACTIVE`: Set to `"1"` when in XeFM sub-shell mode (used for shell prompt customization)

### Selection Behavior

The selected files variables (`XEFM_*_SELECTED`) follow this logic:

1. **If files are explicitly selected**: Contains the names of all selected files
2. **If no files are selected**: Contains the name of the file at the current cursor position
3. **If directory is empty**: Contains an empty string

**Example scenarios:**
- **Multiple files selected**: `XEFM_THIS_SELECTED="file1.txt file2.py 'file with spaces.md'"`
- **No selection, cursor on file**: `XEFM_THIS_SELECTED="'current file.txt'"`
- **Empty directory**: `XEFM_THIS_SELECTED=""`

## Remote Directory Fallback

### Problem Solved

When browsing remote directories (such as S3 buckets), traditional shell operations would fail because:
- Remote paths (e.g., `s3://bucket/folder/`) cannot be used as shell working directories
- `os.chdir()` would fail with remote paths
- This made subshell unusable when browsing remote storage

### Solution

The system implements intelligent working directory selection:

#### Local Directories
```bash
# Normal behavior - uses pane directory
XeFM Sub-shell Mode
==================================================
XEFM_THIS_DIR:      /home/user/documents
Working Directory: /home/user/documents
==================================================
```

#### Remote Directories
```bash
# Fallback behavior with user notification
XeFM Sub-shell Mode
==================================================
XEFM_THIS_DIR:      s3://my-bucket/folder/
Working Directory: /home/user/xefm
==================================================
Note: Current pane is browsing remote directory: s3://my-bucket/folder/
Subshell working directory set to XeFM's directory: /home/user/xefm
```

### Implementation Logic

```python
# Determine working directory for subshell
if current_pane['path'].is_remote():
    working_dir = os.getcwd()  # XeFM's working directory
    print(f"Note: Current pane is browsing remote directory: {current_pane['path']}")
    print(f"Working directory set to XeFM's directory: {working_dir}")
else:
    working_dir = str(current_pane['path'])  # Use pane directory normally

# Change to the selected working directory
os.chdir(working_dir)
```

## Shell Quoting and File Handling

### Automatic Shell Quoting

XeFM automatically quotes all filenames using shell-safe quoting (via Python's `shlex.quote()`):

- **Filenames with spaces** are quoted: `'My Document.txt'`
- **Filenames with special characters** are escaped: `'file$with&special.txt'`
- **Simple filenames** remain unquoted: `simple.txt`

### Direct Usage (Recommended)

```bash
# ✅ Works directly with any filenames, including spaces and special characters
cd "$XEFM_THIS_DIR"
ls -la $XEFM_THIS_SELECTED
cp $XEFM_THIS_SELECTED "$XEFM_OTHER_DIR/"
tar -czf backup.tar.gz $XEFM_THIS_SELECTED
```

### Examples of Automatic Quoting

```bash
# If you have files: "My Document.txt", "file with spaces.py", "normal.txt"
# XEFM_THIS_SELECTED becomes: 'My Document.txt' 'file with spaces.py' normal.txt

# This now works perfectly:
ls -la $XEFM_THIS_SELECTED
# Expands to: ls -la 'My Document.txt' 'file with spaces.py' normal.txt
```

## Usage Examples

### Basic Directory Operations

```bash
# List files in both panes
ls -la "$XEFM_LEFT_DIR" "$XEFM_RIGHT_DIR"

# Compare directory sizes
du -sh "$XEFM_LEFT_DIR" "$XEFM_RIGHT_DIR"

# Find files in both directories
find "$XEFM_LEFT_DIR" "$XEFM_RIGHT_DIR" -name "*.py"

# List selected files directly (works with spaces!)
ls -la $XEFM_THIS_SELECTED
```

### Working with Selected Files

```bash
# ✅ List selected files (works with spaces and special characters!)
cd "$XEFM_THIS_DIR"
ls -la $XEFM_THIS_SELECTED

# ✅ Copy selected files to other pane
cd "$XEFM_THIS_DIR"
cp $XEFM_THIS_SELECTED "$XEFM_OTHER_DIR/"

# ✅ Archive selected files
cd "$XEFM_THIS_DIR"
tar -czf selected_files.tar.gz $XEFM_THIS_SELECTED

# ✅ Show file information
cd "$XEFM_THIS_DIR"
file $XEFM_THIS_SELECTED

# ✅ Process files with any command
cd "$XEFM_THIS_DIR"
wc -l $XEFM_THIS_SELECTED  # Count lines in selected files
```

### Remote Directory Operations

#### S3 File Management
```bash
# While browsing s3://my-bucket/logs/ in XeFM
$ aws s3 ls $XEFM_THIS_DIR
$ aws s3 cp $XEFM_THIS_DIR/error.log .
$ aws s3 sync $XEFM_THIS_DIR ./backup/
```

#### Remote Development Workflow
```bash
# While browsing s3://code-bucket/projects/
$ git clone https://github.com/user/repo.git
$ aws s3 cp $XEFM_THIS_DIR/config.json ./repo/
$ cd repo && make build
```

#### Data Processing
```bash
# While browsing s3://data-bucket/datasets/
$ python analyze.py --input $XEFM_THIS_DIR
$ aws s3 cp results.csv $XEFM_THIS_DIR/processed/
```

### Advanced Operations

```bash
# Sync directories (copy newer files)
rsync -av "$XEFM_THIS_DIR/" "$XEFM_OTHER_DIR/"

# Compare selected files between panes
for file in $XEFM_THIS_SELECTED; do
    if [ -f "$XEFM_OTHER_DIR/$file" ]; then
        diff "$XEFM_THIS_DIR/$file" "$XEFM_OTHER_DIR/$file"
    fi
done

# Batch rename selected files
for file in $XEFM_THIS_SELECTED; do
    mv "$XEFM_THIS_DIR/$file" "$XEFM_THIS_DIR/backup_$file"
done
```

### Loop Usage (For Complex Operations)

```bash
# For more complex per-file operations, you can still use loops
for file in $XEFM_THIS_SELECTED; do
    echo "Processing: $file"  # $file is already properly quoted
    # Use the quoted filename directly
    cp "$XEFM_THIS_DIR"/$file "$XEFM_OTHER_DIR"/
done
```

## Shell Integration

### Shell Detection
- Uses the user's default shell (from `$SHELL` environment variable)
- Falls back to `/bin/bash` if `$SHELL` is not set
- Ensures compatibility with user's preferred shell configuration, aliases, and functions

### Working Directory Management
- **Local directories**: Working directory set to the currently focused pane's directory
- **Remote directories**: Working directory set to XeFM's working directory with user notification
- **Environment variables**: Always contain actual pane paths regardless of working directory

## Shell Prompt Customization

### Why Manual Configuration is Needed

Shell configuration files (like `.zshrc` and `.bashrc`) are loaded after XeFM sets environment variables, which overwrites any prompt modifications XeFM makes. The solution is to modify your shell configuration to check for the `XEFM_ACTIVE` environment variable.

### Zsh Configuration

Add this to your `~/.zshrc` file:

```bash
# XeFM sub-shell prompt modification
if [[ -n "$XEFM_ACTIVE" ]]; then
    PROMPT="[XeFM] $PROMPT"
fi
```

### Bash Configuration

Add this to your `~/.bashrc` file:

```bash
# XeFM sub-shell prompt modification
if [[ -n "$XEFM_ACTIVE" ]]; then
    PS1="[XeFM] $PS1"
fi
```

### Advanced Prompt Customization

#### Zsh Advanced Example
```bash
# Advanced XeFM prompt customization for zsh
if [[ -n "$XEFM_ACTIVE" ]]; then
    # Add colored [XeFM] label
    PROMPT="%F{yellow}[XeFM]%f $PROMPT"
    
    # Or modify the right prompt
    RPROMPT="$RPROMPT %F{red}(XeFM)%f"
fi
```

#### Bash Advanced Example
```bash
# Advanced XeFM prompt customization for bash
if [[ -n "$XEFM_ACTIVE" ]]; then
    # Add colored [XeFM] label
    PS1="\[\033[1;33m\][XeFM]\[\033[0m\] $PS1"
    
    # Or create a completely custom XeFM prompt
    PS1="\[\033[1;33m\][XeFM]\[\033[0m\] \[\033[1;32m\]\u@\h\[\033[0m\]:\[\033[1;34m\]\w\[\033[0m\]\$ "
fi
```

### Testing Your Configuration

1. **Add the configuration** to your shell config file (`.zshrc` or `.bashrc`)
2. **Reload your shell configuration**:
   ```bash
   # For zsh
   source ~/.zshrc
   
   # For bash  
   source ~/.bashrc
   ```
3. **Test with XeFM**:
   - Start XeFM and press `x` to enter sub-shell mode
   - Your prompt should now display the `[XeFM]` label
   - Type `exit` to return to XeFM

### Shell Compatibility

| Shell | Config File | Variable | Example |
|-------|-------------|----------|---------|
| zsh | `~/.zshrc` | `PROMPT` | `[XeFM] %n@%m:%~%# ` |
| bash | `~/.bashrc` | `PS1` | `[XeFM] \u@\h:\w\$ ` |
| fish | `~/.config/fish/config.fish` | Custom function | See fish documentation |

## Returning to XeFM

To return to XeFM from sub-shell mode:
- Type `exit` in the shell
- Press `Ctrl+D` (EOF) in the shell
- The XeFM interface will be restored automatically

## Configuration

The sub-shell feature can be customized through the key bindings configuration:

```python
KEY_BINDINGS = {
    'subshell': ['x', 'X'],  # Customize the key binding
    # ... other bindings
}
```

## Technical Implementation

### Curses Management
- The curses interface is properly suspended using `curses.endwin()`
- Terminal is restored to normal mode for shell interaction
- Curses is reinitialized when returning to XeFM

### Environment Preservation
- Original stdout/stderr are temporarily restored
- Log capture is suspended during shell session
- All XeFM state is preserved and restored
- Environment variables are properly passed using `subprocess.run()`

### Path Handling
- All paths are converted to absolute paths for reliability
- Path expansion and resolution is handled automatically
- Non-existent or inaccessible paths are handled gracefully
- Remote path detection using `is_remote()` method

### Remote Directory Detection

```python
# Examples of remote path detection
s3_path = Path('s3://my-bucket/folder/')
local_path = Path('/home/user/documents')

s3_path.is_remote()    # Returns True
local_path.is_remote() # Returns False
```

### Error Handling
- If the shell fails to start, an error message is displayed
- The curses interface is properly restored even if errors occur
- Log messages are captured when returning to XeFM
- Graceful handling of permission errors and inaccessible directories

## Benefits

### Functionality Benefits
- **Batch Operations**: Perform complex operations on selected files using shell tools
- **System Integration**: Use system commands with XeFM's file selection
- **Remote Storage Support**: Work with remote directories seamlessly
- **Scripting**: Write and execute scripts that operate on XeFM's current state

### User Experience Benefits
- **Reliability**: Subshell works consistently with both local and remote directories
- **Transparency**: Users are informed when remote fallback occurs
- **Flexibility**: Works with any remote storage type (S3, SCP, FTP, etc.)
- **Consistency**: Same behavior and environment variables regardless of storage type

### Technical Benefits
- **Advanced File Management**: Use specialized tools like `rsync`, `find`, `grep`, etc.
- **Development Workflow**: Integrate XeFM with development tools and build systems
- **No Loss of Functionality**: Remote directory access maintained via environment variables
- **Backward Compatibility**: Existing scripts continue to work normally

## Testing

### Comprehensive Test Coverage

#### Unit Tests
- `test/test_subshell.py` - Core subshell functionality
- `test/test_subshell_remote_fallback.py` - Remote directory fallback
- `test/test_subshell_remote_simple.py` - Core remote logic tests


### Test Commands
```bash
# Test environment variables
python3 test/test_subshell.py

# Test remote fallback
python3 test/test_subshell_remote_fallback.py
```

## Use Cases

### Local File Management
1. **Batch Operations**: Complex operations on selected files using shell tools
2. **System Integration**: Use system commands with XeFM's file selection
3. **Scripting**: Write and execute scripts that operate on XeFM's current state
4. **Advanced File Management**: Use specialized tools like `rsync`, `find`, `grep`
5. **Development Workflow**: Integrate XeFM with development tools and build systems

### Remote Storage Operations
1. **Cloud File Management**: Work with S3, Azure, GCP storage
2. **Data Processing**: Process remote datasets with local tools
3. **Backup and Sync**: Synchronize between local and remote storage
4. **Development Workflow**: Access remote code repositories and assets
5. **System Administration**: Manage remote server files and configurations

## Troubleshooting

### Common Issues

#### Prompt Configuration
**Prompt not showing [XeFM] label:**
1. Verify the configuration is added to the correct file
2. Make sure the syntax is correct for your shell
3. Test by manually setting `XEFM_ACTIVE=1` and starting a new shell
4. Check if other prompt modifications in your config are overriding the XeFM setting

#### Remote Directory Issues
**"Permission denied" errors**: Ensure XeFM has write access to its working directory
**Environment variables not set**: Verify external programs are launched through XeFM
**Remote paths not accessible**: Check cloud CLI configuration (AWS CLI, etc.)

#### File Handling
**Filenames with spaces**: XeFM automatically quotes all filenames - use `$XEFM_THIS_SELECTED` directly
**Configuration conflicts**: Place XeFM configuration after other prompt modifications in config file

### Debug Information

When remote fallback occurs, XeFM provides clear information:
- Current remote directory being browsed
- Fallback working directory being used
- Reason for the fallback

## Security Considerations

- Environment variables contain file paths and names from XeFM
- Selected file names are passed as space-separated strings with automatic quoting
- Users should be cautious with file names containing special characters
- Standard shell quoting and escaping practices apply
- Remote storage credentials should be properly configured and secured

## Future Enhancements

### Planned Improvements
1. **Configurable Fallback Directory**: Allow users to specify custom fallback directory
2. **Remote Working Directory Emulation**: Create temporary local mirror of remote directory
3. **Enhanced Notifications**: More detailed information about remote storage capabilities
4. **Integration with Cloud CLIs**: Automatic detection and setup of cloud CLI tools
5. **Custom Environment Variables**: User-defined variables for specific workflows

## Conclusion

The Subshell System provides a powerful bridge between XeFM's file management capabilities and the full power of the shell environment. With intelligent remote directory fallback, automatic file quoting, and comprehensive environment variable support, it enables seamless operation across local and remote storage systems while maintaining the flexibility and power that makes XeFM an effective file management tool.