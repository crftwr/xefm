#!/usr/bin/env python3
"""Tests for format_size utility function."""

import pytest
from xefm.str_format import format_size


class TestFormatSize:
    """Test format_size utility function."""
    
    def test_zero_bytes(self):
        """Test formatting zero bytes."""
        assert format_size(0) == "0 B"
        assert format_size(0, compact=True) == "0B"
    
    def test_negative_bytes(self):
        """Test formatting negative bytes (should be treated as zero)."""
        assert format_size(-100) == "0 B"
        assert format_size(-100, compact=True) == "0B"
    
    def test_bytes_standard(self):
        """Test formatting bytes in standard format."""
        assert format_size(1) == "1 B"
        assert format_size(512) == "512 B"
        assert format_size(1023) == "1023 B"
    
    def test_bytes_compact(self):
        """Test formatting bytes in compact format."""
        assert format_size(1, compact=True) == "1B"
        assert format_size(512, compact=True) == "512B"
        assert format_size(1023, compact=True) == "1023B"
    
    def test_kilobytes_standard(self):
        """Test formatting kilobytes in standard format."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(10240) == "10.0 KB"
        assert format_size(1048575) == "1024.0 KB"
    
    def test_kilobytes_compact(self):
        """Test formatting kilobytes in compact format."""
        assert format_size(1024, compact=True) == "1.0K"
        assert format_size(1536, compact=True) == "1.5K"
        assert format_size(10240, compact=True) == "10.0K"
    
    def test_megabytes_standard(self):
        """Test formatting megabytes in standard format."""
        assert format_size(1048576) == "1.0 MB"
        assert format_size(1572864) == "1.5 MB"
        assert format_size(10485760) == "10.0 MB"
    
    def test_megabytes_compact(self):
        """Test formatting megabytes in compact format."""
        assert format_size(1048576, compact=True) == "1.0M"
        assert format_size(1572864, compact=True) == "1.5M"
        assert format_size(10485760, compact=True) == "10.0M"
    
    def test_gigabytes_standard(self):
        """Test formatting gigabytes in standard format."""
        assert format_size(1073741824) == "1.0 GB"
        assert format_size(1610612736) == "1.5 GB"
        assert format_size(10737418240) == "10.0 GB"
    
    def test_gigabytes_compact(self):
        """Test formatting gigabytes in compact format."""
        assert format_size(1073741824, compact=True) == "1.0G"
        assert format_size(1610612736, compact=True) == "1.5G"
    
    def test_terabytes_standard(self):
        """Test formatting terabytes in standard format."""
        assert format_size(1099511627776) == "1.0 TB"
        assert format_size(1649267441664) == "1.5 TB"
    
    def test_terabytes_compact(self):
        """Test formatting terabytes in compact format."""
        assert format_size(1099511627776, compact=True) == "1.0T"
        assert format_size(1649267441664, compact=True) == "1.5T"
    
    def test_petabytes_standard(self):
        """Test formatting petabytes in standard format."""
        assert format_size(1125899906842624) == "1.0 PB"
    
    def test_petabytes_compact(self):
        """Test formatting petabytes in compact format."""
        assert format_size(1125899906842624, compact=True) == "1.0P"
    
    def test_bytes_no_decimal(self):
        """Test that bytes are shown as integers without decimals."""
        # Standard format should show "345 B" not "345.0 B"
        assert format_size(345) == "345 B"
        assert ".0" not in format_size(999)
        assert format_size(999) == "999 B"
    
    def test_real_world_sizes(self):
        """Test with real-world file sizes."""
        # Small text file
        assert format_size(4096) == "4.0 KB"
        
        # Medium document
        assert format_size(524288) == "512.0 KB"
        
        # Large image
        assert format_size(5242880) == "5.0 MB"
        
        # Video file
        assert format_size(734003200) == "700.0 MB"
        
        # Large backup
        assert format_size(53687091200) == "50.0 GB"
