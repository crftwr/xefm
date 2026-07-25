# XeFM AWS S3 Support Feature

## Overview

XeFM provides native AWS S3 integration, allowing you to browse, navigate, and manage files in S3 buckets directly from the terminal interface. S3 paths are treated like local directories, providing a seamless experience for working with cloud storage.

## Features

- **Browse S3 Buckets**: Navigate S3 buckets like local directories
- **List Objects**: View files and prefixes (virtual directories) in buckets
- **View File Details**: See file sizes, modification times, and metadata
- **Copy Files**: Copy files between S3 and local storage
- **Move Files**: Move files between S3 locations
- **Delete Files**: Remove files from S3 buckets
- **Caching**: Intelligent caching reduces API calls and improves performance
- **Virtual Directories**: Navigate S3 prefixes as if they were directories

## Prerequisites

### Required Dependencies

Install boto3 for AWS S3 support:

```bash
pip install boto3
```

### AWS Credentials

Configure AWS credentials using one of these methods:

#### Method 1: AWS CLI Configuration (Recommended)

```bash
aws configure
```

This creates `~/.aws/credentials` with your access keys.

#### Method 2: Environment Variables

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"
```

#### Method 3: IAM Role (EC2/ECS)

If running on AWS infrastructure, use IAM roles (no configuration needed).

### Verify Setup

Test your AWS credentials:

```bash
aws s3 ls
```

If this works, XeFM will be able to access S3.

## Quick Start

### Accessing S3 Buckets

Start XeFM and navigate to an S3 bucket:

```bash
xefm s3://my-bucket-name/
```

Or navigate to S3 from within XeFM:

1. Press the key for "Jump to Path" (default: `Shift-J`)
2. Enter: `s3://my-bucket-name/`
3. Press Enter

### S3 Path Format

S3 paths follow this format:

```
s3://bucket-name/prefix/path/to/file.txt
```

Examples:
- `s3://my-bucket/` - Root of bucket
- `s3://my-bucket/documents/` - Documents prefix
- `s3://my-bucket/photos/2024/` - Nested prefix
- `s3://my-bucket/file.txt` - Specific file

## Navigation

### Browsing Buckets

Navigate S3 buckets like local directories:

- **Enter**: Open prefix (virtual directory) or download file
- **Backspace**: Go up one level
- **Arrow Keys**: Navigate through files and prefixes
- **Home/End**: Jump to first/last item

### Virtual Directories

S3 uses prefixes to simulate directories:

```
s3://my-bucket/
  ├── documents/          (prefix, acts like directory)
  │   ├── report.pdf
  │   └── notes.txt
  ├── photos/             (prefix, acts like directory)
  │   └── vacation.jpg
  └── readme.txt          (object)
```

XeFM treats prefixes as directories, allowing natural navigation.

### Listing Buckets

To see all available buckets:

1. Navigate to `s3://` (root)
2. XeFM lists all buckets you have access to
3. Select a bucket to browse its contents

## File Operations

### Copying Files

XeFM copies the selected files from the active pane straight to the **other**
pane's current directory — there is no separate clipboard/paste step.

#### From S3 to Local

1. Open the S3 file's directory in one pane and the local destination in the other
2. Select the file(s) in the S3 pane with `Space`
3. Press `C` to copy them to the other (local) pane

#### From Local to S3

1. Open the local file's directory in one pane and the S3 destination (e.g. `s3://my-bucket/uploads/`) in the other
2. Select the file(s) with `Space`
3. Press `C` to copy them to the S3 pane

#### Between S3 Locations

Same as above with both panes on S3 paths: select in one pane, press `C` to copy to the other.

### Moving Files

Move works like copy — it sends the selection to the other pane's directory:

1. Open the destination in the other pane
2. Select the file(s) and press `M`
3. Confirm the move

**Note:** Moving between S3 and local storage performs copy + delete.

### Deleting Files

Delete S3 objects:

1. Navigate to (or select) the file
2. Press the delete key (`K` or `Delete`)
3. Confirm deletion

**Warning:** Deleted S3 objects cannot be recovered unless versioning is enabled on the bucket.

### Viewing Files

View S3 file contents:

1. Navigate to the file
2. Press the view key (`V`)
3. XeFM downloads the file to a temporary location and opens the viewer

**Note:** Large files may take time to download.

## Performance and Caching

### Intelligent Caching

XeFM caches S3 API responses to improve performance:

- **Directory Listings**: Cached for 60 seconds (default)
- **File Metadata**: Cached for 60 seconds (default)
- **Automatic Invalidation**: Cache cleared when operations modify S3

### Cache Configuration

Configure caching in `~/.xefm/config.py`:

```python
# S3 cache TTL in seconds (how long directory listings are cached)
S3_CACHE_TTL = 60
```

### Cache Behavior

- **First Access**: Fetches from S3 (may be slow)
- **Subsequent Access**: Uses cache (fast)
- **After Timeout**: Refreshes from S3
- **After Modifications**: Automatically invalidates affected cache entries

### Refresh Cache

Get fresh data:

1. Re-enter the directory (navigate away and back), or wait for `S3_CACHE_TTL` to expire
2. XeFM then fetches fresh data from S3

## Limitations and Considerations

### S3-Specific Limitations

1. **No True Directories**: S3 uses prefixes, not real directories
2. **No Rename**: S3 doesn't support rename (XeFM performs copy + delete)
3. **No Edit in Place**: Files must be downloaded, edited, and re-uploaded
4. **API Rate Limits**: AWS may throttle requests for high-volume operations
5. **Costs**: S3 operations incur AWS charges (requests and data transfer)

### Performance Considerations

1. **Latency**: Network latency affects responsiveness
2. **Large Files**: Downloading large files takes time
3. **Many Objects**: Buckets with thousands of objects may be slow to list
4. **Pagination**: Large listings are paginated (may require multiple requests)

### Permission Requirements

Required S3 permissions:
- `s3:ListBucket` - List bucket contents
- `s3:GetObject` - Download files
- `s3:PutObject` - Upload files
- `s3:DeleteObject` - Delete files
- `s3:GetObjectMetadata` - View file details

## Troubleshooting

### Cannot Access S3

**Problem:** XeFM shows error when accessing S3 paths.

**Solutions:**
1. Verify boto3 is installed: `pip list | grep boto3`
2. Check AWS credentials: `aws s3 ls`
3. Verify bucket name is correct
4. Check IAM permissions for bucket access

### Slow Performance

**Problem:** S3 operations are very slow.

**Solutions:**
1. Check network connection
2. Increase cache timeout in configuration
3. Use S3 in same region as your location
4. Consider using S3 Transfer Acceleration (AWS feature)

### Permission Denied

**Problem:** "Access Denied" errors when accessing buckets.

**Solutions:**
1. Verify IAM permissions for the bucket
2. Check bucket policy allows your AWS account
3. Verify credentials are correct: `aws sts get-caller-identity`
4. Check if bucket requires specific permissions

### Files Not Appearing

**Problem:** Files don't appear in bucket listing.

**Solutions:**
1. Re-enter the directory to re-list it (the cache also auto-invalidates after `S3_CACHE_TTL`)
2. Check if files exist: `aws s3 ls s3://bucket-name/`
3. Verify you have `s3:ListBucket` permission
4. Check if bucket has many objects (pagination may be slow)

### Download Failures

**Problem:** Cannot download files from S3.

**Solutions:**
1. Check network connection
2. Verify you have `s3:GetObject` permission
3. Check available disk space
4. Try smaller files first
5. Check AWS service status

## Advanced Features

### Cross-Region Operations

XeFM supports buckets in any AWS region:

```
s3://us-east-bucket/file.txt
s3://eu-west-bucket/file.txt
```

**Note:** Cross-region transfers may be slower and incur data transfer costs.

### Large File Handling

For large files:
- XeFM shows progress during downloads
- Uploads use multipart upload for files >5MB
- Consider using AWS CLI for very large files (>1GB)

### Bucket Policies

XeFM respects bucket policies:
- Public buckets: Accessible without credentials
- Private buckets: Require proper IAM permissions
- Encrypted buckets: Transparent encryption/decryption

### S3 Storage Classes

XeFM works with all S3 storage classes:
- Standard
- Intelligent-Tiering
- Glacier (requires restore before access)
- Deep Archive (requires restore before access)

**Note:** Glacier objects must be restored before they can be accessed.

## Best Practices

### Security

1. **Use IAM Roles**: Prefer IAM roles over access keys when possible
2. **Least Privilege**: Grant only necessary S3 permissions
3. **Rotate Credentials**: Regularly rotate AWS access keys
4. **Audit Access**: Review S3 access logs periodically

### Performance

1. **Use Caching**: Keep default cache settings for better performance
2. **Batch Operations**: Perform multiple operations in one session
3. **Same Region**: Use S3 buckets in your region when possible
4. **Avoid Large Listings**: Use prefixes to organize objects

### Cost Management

1. **Monitor Usage**: Track S3 API requests and data transfer
2. **Use Caching**: Reduces API calls and costs
3. **Lifecycle Policies**: Use S3 lifecycle policies for old data
4. **Storage Classes**: Use appropriate storage class for your data

### Organization

1. **Use Prefixes**: Organize objects with prefix structure
2. **Naming Conventions**: Use consistent naming for objects
3. **Metadata**: Add metadata to objects for better organization
4. **Tags**: Use S3 tags for categorization and cost allocation

## Configuration Reference

### Enable/Disable S3 Support

In `~/.xefm/config.py`:

```python
# Enable S3 support
S3_ENABLED = True
```

### Cache Settings

```python
# S3 cache TTL in seconds
S3_CACHE_TTL = 60
```

### Performance Tuning

```python
# Multipart upload threshold (bytes)
S3_MULTIPART_THRESHOLD = 5 * 1024 * 1024  # 5MB

# Multipart chunk size (bytes)
S3_MULTIPART_CHUNKSIZE = 5 * 1024 * 1024  # 5MB
```

## Examples

### Example 1: Backup Local Files to S3

```bash
# Start XeFM
xefm

# Open the local directory in one pane and s3://my-backup-bucket/ in the other
# Select files in the local pane, then press C to copy them to the S3 pane
```

### Example 2: Download S3 Files

```bash
# Start XeFM with S3 path
xefm s3://my-bucket/downloads/

# Open the S3 directory in one pane and the local destination in the other
# Select files, then press C to copy them to the local pane
```

### Example 3: Organize S3 Objects

```bash
# Navigate to s3://my-bucket/
# Select files to move
# Press move key
# Navigate to s3://my-bucket/organized/
# Confirm move
```

## Related Documentation

- [Configuration](CONFIGURATION_FEATURE.md) - S3 configuration options
- [File Operations](XEFM_USER_GUIDE.md) - General file operations
- [File Operations](FILE_OPERATIONS_FEATURE.md) - Copy/move progress tracking for S3 transfers
- [External Programs](EXTERNAL_PROGRAMS_FEATURE.md) - Using external tools with S3 files

## Conclusion

XeFM's S3 support provides seamless integration with AWS S3, allowing you to manage cloud storage directly from the terminal. With intelligent caching, virtual directory navigation, and full file operation support, XeFM makes working with S3 as natural as working with local files.

For optimal performance, ensure proper AWS credentials are configured, use caching effectively, and organize your S3 objects with a clear prefix structure.
