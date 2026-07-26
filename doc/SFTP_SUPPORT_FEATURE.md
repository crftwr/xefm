# SFTP Support Feature Guide

## Overview

XeFM provides seamless SFTP (SSH File Transfer Protocol) support, allowing you to browse, search, and manage files on remote servers as if they were local directories. SFTP integration uses SSH multiplexing for optimal performance and supports all standard file operations.

## Quick Start

### Prerequisites

1. **SSH access** to the remote server
2. **SSH config** (optional but recommended) in `~/.ssh/config`
3. **SSH keys** (optional) for passwordless authentication

### Basic Usage

Navigate to an SFTP location using the standard SSH URL format:

```
ssh://hostname/path/to/directory
ssh://user@hostname/path/to/directory
ssh://hostname:port/path/to/directory
```

**Examples:**
```
ssh://myserver/home/user/projects
ssh://admin@192.168.1.100/var/log
ssh://server.example.com:2222/opt/data
```

### Quick Access Methods

**Method 1: Jump to Path Dialog**
1. Press `Shift-J` (Jump to path)
2. Enter: `ssh://hostname/path`
3. Press Enter

**Method 2: Favorite Directories**
1. Add SFTP paths to favorites in config: `~/.xefm/config.py`
2. Press `J` to access favorites
3. Select your SFTP bookmark

**Method 3: Command Line**
```bash
python3 -m xefm --left ssh://server/path --right ~/local/path
```

## SSH Configuration

### Recommended Setup

Create or edit `~/.ssh/config` to simplify connections:

```ssh-config
Host myserver
    HostName server.example.com
    User myusername
    Port 22
    IdentityFile ~/.ssh/id_rsa
    
Host devbox
    HostName 192.168.1.100
    User developer
    Port 2222
    
Host prod-*
    User admin
    IdentityFile ~/.ssh/prod_key
    StrictHostKeyChecking yes
```

**Benefits:**
- Use short names: `ssh://myserver/path` instead of full details
- Centralized authentication configuration
- Connection multiplexing for better performance
- Consistent settings across all SSH tools

### SSH Key Authentication

**Generate SSH key** (if you don't have one):
```bash
ssh-gen -t rsa -b 4096 -C "your_email@example.com"
```

**Copy key to server:**
```bash
ssh-copy-id user@hostname
```

**Test connection:**
```bash
ssh user@hostname
```

Once SSH key authentication works, XeFM will use it automatically.

## Features

### File Operations

All standard file operations work on SFTP paths:

- **Copy** (`C`): Copy files/directories between local and remote
- **Move** (`M`): Move files/directories on remote server
- **Delete** (`K`): Delete remote files/directories
- **Rename** (`R`): Rename remote files/directories
- **Create Directory** (`M` when nothing is selected): Create directories on remote server
- **View Files** (`V`): View remote text files with syntax highlighting

### Cross-Storage Operations

XeFM seamlessly handles operations between different storage types:

**Local ↔ SFTP:**
```
Copy: ~/local/file → ssh://server/remote/path
Move: ssh://server/data → ~/backup/
```

**SFTP ↔ S3:**
```
Copy: ssh://server/logs → s3://bucket/archive/
Move: s3://bucket/data → ssh://server/processing/
```

**SFTP ↔ Archive:**
```
Copy: ssh://server/file.txt → local-archive.zip
Extract: ssh://server/archive.tar.gz → ~/extracted/
```

### Search Functionality

**Filename Search** (`Alt+F7` or `F`):
- Search for files by name pattern
- Supports wildcards: `*.py`, `test_*.txt`
- Real-time results as search progresses
- Works recursively through directories

**Content Search** (`G`):
- Search file contents using regex patterns
- Automatically detects text files
- Shows matching lines with context
- Efficient streaming for large files

**Example searches:**
```
*.log          # Find all log files
config.*       # Find config files with any extension
test_.*\.py    # Find Python test files
```

### Performance Optimizations

XeFM includes several optimizations for SFTP operations:

1. **SSH Control Master Multiplexing**
   - Reuses existing SSH connections
   - 99% reduction in connection overhead
   - Automatic connection health monitoring

2. **Bulk Stat Operations**
   - Fetches file metadata in batches
   - 99% reduction in network round trips
   - Dramatically faster directory listings

3. **Intelligent Caching**
   - Caches directory listings and file metadata
   - Configurable TTL (default: 30 seconds)
   - Automatic cache invalidation on modifications

4. **Optimized Search**
   - Streams file content for memory efficiency
   - Parallel processing where possible
   - Cancellable operations

### Text Viewer

View remote text files with full syntax highlighting:

1. Navigate to a text file on SFTP
2. Press `Enter` or `V` to open viewer
3. Use arrow keys to scroll
4. Press `/` to search within file
5. Press `q` to close viewer

**Supported formats:** Python, JavaScript, JSON, YAML, Markdown, Shell scripts, and 20+ more with `pygments` installed.

## Configuration

### SFTP-Specific Settings

Add to `~/.xefm/config.py`:

```python
# SFTP cache TTL for successful results (seconds)
SSH_CACHE_TTL = 30

# SFTP cache TTL for cached errors (seconds)
SSH_CACHE_ERROR_TTL = 300
```

### Favorite SFTP Directories

Add frequently-used SFTP paths to favorites:

```python
FAVORITE_DIRECTORIES = [
    ('Local Projects', '~/projects'),
    ('Dev Server', 'ssh://devbox/var/www'),
    ('Production Logs', 'ssh://prod-web1/var/log/nginx'),
    ('Backup Server', 'ssh://backup/mnt/backups'),
    ('S3 Bucket', 's3://my-bucket/data'),
]
```

Access with `j` key.

## Advanced Usage

### SSH Multiplexing

XeFM automatically uses SSH Control Master for connection multiplexing. To verify it's working:

```bash
# Check for control socket
ls -la ~/.ssh/
# Look for: controlmaster-*

# Monitor SSH connections
ssh -O check user@hostname
```

**Benefits:**
- Single SSH connection shared across operations
- Faster subsequent operations (no re-authentication)
- Reduced server load
- Better performance on high-latency connections

### Batch Operations

Select multiple files and perform batch operations:

1. Use `Space` to select files
2. Use `A` to select all files in directory
3. Press the operation key (`C` for copy, `K` for delete, etc.)
4. Confirm operation
5. Watch progress bar for completion

The progress bar fills as the bytes actually move, in both directions, so a slow
transfer over a high-latency link no longer looks stalled at 0%. Press **ESC**
to cancel: the transfer stops within about half a second rather than running to
completion in the background, and the partly-transferred file is removed.

**Example: Backup multiple directories**
```
1. Navigate to ssh://server/data
2. Select directories with Space
3. Press C (Copy)
4. Navigate to ~/backup
5. Press Enter to confirm
```

### Sub-shell with SFTP

Press `Shift-X` to enter sub-shell mode with SFTP environment variables:

```bash
# Environment variables available:
echo $XEFM_LEFT_DIR    # May be ssh://server/path
echo $XEFM_RIGHT_DIR   # May be local path
echo $XEFM_THIS_DIR    # Current pane (SFTP or local)

# Use with standard tools:
scp $XEFM_THIS_DIR/file.txt user@other:/path/
rsync -av $XEFM_THIS_DIR/ backup/
```

Type `exit` to return to XeFM.

## Troubleshooting

### Connection Issues

**Problem: "Connection refused" or "Connection timeout"**

Solutions:
1. Verify SSH access works: `ssh user@hostname`
2. Check firewall settings on server
3. Verify correct port (default: 22)
4. Check SSH service is running on server

**Problem: "Permission denied (publickey)"**

Solutions:
1. Verify SSH key is added: `ssh-add -l`
2. Copy key to server: `ssh-copy-id user@hostname`
3. Check SSH config has correct IdentityFile
4. Try password authentication first

**Problem: "Host key verification failed"**

Solutions:
1. Accept host key manually: `ssh user@hostname`
2. Or remove old key: `ssh-keygen -R hostname`
3. Update `~/.ssh/known_hosts`

### Performance Issues

**Problem: Slow directory listings**

Solutions:
1. Check network latency: `ping hostname`
2. Verify SSH multiplexing is active
3. Increase cache TTL in config
4. Use SSH compression: Add to `~/.ssh/config`:
   ```
   Compression yes
   CompressionLevel 6
   ```

**Problem: Search is slow**

Solutions:
1. Use filename search instead of content search when possible
2. Limit search scope to specific directories
3. Use more specific patterns to reduce results
4. Check network bandwidth

### Cache Issues

**Problem: Directory listing not updating**

Solutions:
1. Navigate out of and back into the directory to re-list it
2. Reduce SSH_CACHE_TTL in config
3. Restart XeFM to clear all caches

**Problem: Deleted files still showing**

Solution:
- Navigate out of and back into the directory to re-list it
- Cache will auto-invalidate after TTL expires

## Best Practices

### Security

1. **Use SSH keys** instead of passwords
2. **Restrict key permissions:** `chmod 600 ~/.ssh/id_rsa`
3. **Use different keys** for different servers
4. **Enable StrictHostKeyChecking** in SSH config
5. **Regularly rotate** SSH keys

### Performance

1. **Use SSH config** for connection settings
2. **Enable compression** for slow connections
3. **Keep cache TTL reasonable** (30-60 seconds)
4. **Use filename search** when content search isn't needed
5. **Batch operations** instead of individual file operations

### Workflow

1. **Add favorites** for frequently-accessed servers
2. **Use short hostnames** via SSH config
3. **Keep local and remote panes** for easy transfers
4. **Use search** to find files quickly
5. **Monitor progress** for large operations

## Limitations

### Current Limitations

1. **Read-only archives on SFTP:** Cannot modify files inside remote archives
2. **No symbolic link creation:** Can read symlinks but not create them
3. **No permission changes:** Cannot chmod files (use sub-shell mode)
4. **No ownership changes:** Cannot chown files (use sub-shell mode)

### Workarounds

**For permission changes:**
```bash
# Press X to enter sub-shell
chmod 755 $XEFM_THIS_DIR/script.sh
exit
```

**For advanced operations:**
```bash
# Use sub-shell with standard tools
rsync -av --progress $XEFM_THIS_DIR/ backup/
tar czf archive.tar.gz $XEFM_THIS_DIR/*
```

## Examples

### Example 1: Deploy Website

```
1. Left pane: ~/projects/website (local)
2. Right pane: ssh://webserver/var/www/html
3. Select updated files in left pane (Space)
4. Press F5 (Copy)
5. Confirm overwrite
6. Watch progress bar
```

### Example 2: Download Logs

```
1. Left pane: ssh://server/var/log
2. Right pane: ~/logs/backup
3. Search for logs: Alt+F7, pattern: *.log
4. Select all results: a
5. Press F5 (Copy)
6. Files copied to local backup
```

### Example 3: Clean Old Files

```
1. Navigate to: ssh://server/tmp
2. Search for old files: Alt+F7, pattern: *.tmp
3. Review results
4. Select files to delete: Space
5. Press F8 (Delete)
6. Confirm deletion
```

### Example 4: Compare Directories

```
1. Left pane: ~/local/config
2. Right pane: ssh://server/etc/app
3. Use external diff tool: x
4. Select "Beyond Compare" or "diff"
5. Review differences
```

## Related Documentation

- **[User Guide](XEFM_USER_GUIDE.md)** - Complete XeFM documentation
- **[Configuration](CONFIGURATION_FEATURE.md)** - Configuration options
- **[AWS S3 Support](S3_SUPPORT_FEATURE.md)** - Cloud storage integration
- **[Archive Browsing](ARCHIVE_FEATURE.md)** - Archive support

## Technical Details

For implementation details and architecture, see:
- **[SSH System](../doc/dev/SSH_SYSTEM.md)** - Connection, control-master sharing, bulk-stat caching, default-directory resolution
- **[Path Polymorphism System](../doc/dev/PATH_POLYMORPHISM_SYSTEM.md)**
