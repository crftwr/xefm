# Automatic File List Reloading

## Overview

XeFM automatically detects and displays changes made to files by external applications. When another program creates, deletes, modifies, or renames files in the directory you're viewing, XeFM updates the file list automatically—no manual refresh needed.

This feature keeps your view synchronized with the actual filesystem state, preventing confusion and potential errors from working with outdated information.

## How It Works

XeFM monitors both the left and right pane directories simultaneously. When an external application makes changes:

- **New files appear automatically** when created by other programs
- **Deleted files disappear** from the list immediately
- **Modified files** show updated sizes and timestamps
- **Renamed files** reflect their new names

Your cursor position and selection are preserved during automatic updates, so your workflow isn't interrupted.

## Configuration

### Enabling or Disabling Monitoring

Automatic file monitoring is enabled by default. To change this setting, edit your XeFM configuration file (`~/.xefm/config.py`) and set the constant on the `Config` class:

```python
FILE_MONITORING_ENABLED = True
```

Set `FILE_MONITORING_ENABLED` to `False` to disable automatic monitoring. When disabled, XeFM only updates the file list after you perform actions like navigating directories or manually refreshing.

### Advanced Configuration Options

Most users won't need to adjust these settings, but they're available in `~/.xefm/config.py` for fine-tuning:

```python
FILE_MONITORING_ENABLED = True                # Enable/disable automatic reloading
FILE_MONITORING_COALESCE_DELAY_MS = 200       # Event coalescing window (milliseconds)
FILE_MONITORING_MAX_RELOADS_PER_SECOND = 5    # Maximum reloads per second (rate limiting)
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5  # Polling interval for fallback mode (seconds)
```

**Configuration Options:**

- `FILE_MONITORING_ENABLED` (default: `True`) - Enable or disable automatic monitoring
- `FILE_MONITORING_COALESCE_DELAY_MS` (default: `200`) - Time window in milliseconds to batch multiple changes into a single update
- `FILE_MONITORING_MAX_RELOADS_PER_SECOND` (default: `5`) - Maximum number of automatic updates per second to prevent UI thrashing
- `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S` (default: `5`) - Polling interval in seconds when native monitoring is unavailable

## Runtime Toggle

You can enable or disable monitoring while XeFM is running without restarting the application. Use the monitoring toggle command (check your key bindings) to switch monitoring on or off instantly.

When you disable monitoring at runtime:
- Automatic updates stop immediately
- File lists only update after your actions
- Monitoring can be re-enabled at any time

## Monitoring Modes

XeFM uses different monitoring strategies depending on your storage type:

### Native Mode (Preferred)

For local filesystems, XeFM uses efficient operating system APIs:
- **Linux**: inotify
- **macOS**: FSEvents  
- **Windows**: ReadDirectoryChangesW

Native mode provides instant change detection with minimal resource usage (typically less than 5MB memory and 1% CPU per watched directory).

### Fallback Mode (Polling)

When native monitoring isn't available on a **local** path, XeFM automatically switches to polling mode. This happens with:
- **Network mounts** without change notification support
- **Local filesystems** whose native change-notification API is unavailable

In fallback mode, XeFM checks for changes every 5 seconds (configurable). While less responsive than native mode, it ensures monitoring works everywhere on local storage.

### Remote and Cloud Backends (Monitoring Disabled)

Automatic monitoring only works on paths that live in the local filesystem. For remote or virtual backends it is **disabled** — not even polling can watch them, because there is no local path to scan. This applies to:
- **S3 buckets** and cloud storage
- **Remote filesystems** over SSH/SFTP
- **Archives** browsed in place

For these locations the file list does not refresh automatically; refresh manually (re-enter the directory) to see changes. XeFM skips monitoring for them silently instead of reporting errors.

### Fallback Mode Indicator

When XeFM operates in fallback mode due to storage limitations or errors, a status indicator appears in the interface. This lets you know that:
- Monitoring is active but using polling instead of native APIs
- Updates may take a few seconds to appear
- The feature is working correctly for your storage type

## What Gets Monitored

XeFM monitors **only the immediate files and directories** in the current view. Changes in subdirectories don't trigger updates to the parent directory list—you'll see those changes when you navigate into the subdirectory.

Both panes are monitored independently:
- Changes in the left pane only update the left pane
- Changes in the right pane only update the right pane
- Each pane maintains its own cursor position and selection

## Cursor and Selection Behavior

During automatic updates, XeFM preserves your context:

**If the selected file still exists:**
- Your cursor stays on the same file
- Your scroll position is maintained
- Your workflow continues uninterrupted

**If the selected file was deleted:**
- The cursor moves to the nearest remaining file alphabetically
- If the deleted file was "document.txt", the cursor moves to the next file alphabetically (e.g., "image.png")
- The scroll position adjusts to keep the cursor visible

## Troubleshooting

### File List Not Updating Automatically

**Check if monitoring is enabled:**
1. Verify `FILE_MONITORING_ENABLED` is `True` in your configuration
2. Try toggling monitoring off and on at runtime
3. Restart XeFM to reload configuration

**Check for fallback mode indicator:**
- If you see the fallback mode indicator, monitoring is working but using polling
- Changes may take up to 5 seconds to appear (or your configured polling interval)
- This is normal for network mounts and local filesystems without native change notifications

**Browsing S3, SSH, or an archive?**
- Automatic monitoring is disabled for remote and virtual backends — there is no local path to watch
- The file list won't refresh on its own; re-enter the directory to pick up changes

**Check the log file:**
- XeFM logs monitoring activity with the "FileMonitor" component name
- Look for initialization messages indicating monitoring mode
- Check for error messages that might explain issues

### Monitoring Not Working on Network Drives

Network drives and remote filesystems often don't support native change notifications. XeFM automatically detects this and switches to fallback polling mode. You should see the fallback mode indicator, and changes will appear within a few seconds.

If monitoring doesn't work at all on a network drive:
1. Check that you have read permissions for the directory
2. Verify the network connection is stable
3. Check XeFM logs for error messages
4. Consider increasing `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S` if the network is slow

### Too Many Updates / UI Feels Sluggish

If you're working in a directory with very frequent changes (e.g., a build output directory), you might experience:
- Rapid file list updates
- Cursor jumping
- Sluggish interface

**Solutions:**
1. Reduce `FILE_MONITORING_MAX_RELOADS_PER_SECOND` to limit update frequency
2. Increase `FILE_MONITORING_COALESCE_DELAY_MS` to batch more changes together
3. Temporarily disable monitoring in high-activity directories
4. Navigate to a parent directory where changes are less frequent

### Monitoring Stops Working After Errors

XeFM includes automatic error recovery:
- If monitoring fails, XeFM attempts to reinitialize (up to 3 times)
- If reinitialization fails, XeFM switches to fallback polling mode
- If polling also fails, monitoring is disabled for that directory

Check the log file for error messages. Common issues:
- **Permission denied**: You don't have read access to the directory
- **Too many open files**: System limit on file watches exceeded (Linux)
- **Network timeout**: Remote filesystem connection lost

To recover:
1. Navigate to a different directory and back
2. Toggle monitoring off and on
3. Restart XeFM
4. Check system limits (Linux: `cat /proc/sys/fs/inotify/max_user_watches`)

### Increasing Watch Limits (Linux)

Linux systems limit the number of directories that can be monitored simultaneously. If you see "too many open files" errors:

```bash
# Check current limit
cat /proc/sys/fs/inotify/max_user_watches

# Temporarily increase limit (until reboot)
sudo sysctl fs.inotify.max_user_watches=524288

# Permanently increase limit
echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Performance Considerations

Automatic file monitoring is designed to be lightweight:
- **Memory**: Less than 5MB per watched directory in native mode
- **CPU**: Less than 1% during idle periods
- **Network**: No network traffic for local filesystems

For remote filesystems in fallback mode:
- Polling generates periodic network requests
- Adjust `FILE_MONITORING_FALLBACK_POLL_INTERVAL_S` to balance responsiveness vs. network usage
- Consider disabling monitoring for very slow or metered connections

## When to Disable Monitoring

You might want to disable automatic monitoring if:
- You're working with very large directories (thousands of files)
- You're on a slow or metered network connection
- You're experiencing performance issues
- You prefer manual control over when the file list updates
- You're working in a directory with constant high-frequency changes

Disabling monitoring doesn't affect XeFM's core functionality—file lists still update after your actions like navigating, copying, or deleting files.

## Related Features

- **Manual Refresh**: You can always manually refresh the file list regardless of monitoring settings
- **Directory Navigation**: Monitoring automatically follows you as you navigate directories
- **Dual-Pane Operation**: Both panes are monitored independently

## Technical Details

For developers and advanced users interested in implementation details, see:
- `doc/dev/FILE_MONITORING_IMPLEMENTATION.md` - Architecture and implementation
- `xefm/file_monitor_manager.py` - Main monitoring coordinator
- `xefm/file_monitor_observer.py` - Per-directory monitoring

## Feedback and Issues

If you encounter issues with automatic file monitoring:
1. Check the troubleshooting section above
2. Review XeFM logs for error messages
3. Try disabling and re-enabling monitoring
4. Report persistent issues with log excerpts and reproduction steps
