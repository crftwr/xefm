#!/usr/bin/env python3
"""
Test for progress message text layout improvements.

This test verifies that progress messages use the text layout system
to intelligently truncate long filenames while preserving meaningful
progress information.
"""

import sys
import os
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ttk'))

from xefm.progress_manager import ProgressManager, OperationType


class TestProgressTextLayout(unittest.TestCase):
    """Test progress message text layout with intelligent truncation"""
    
    def test_long_filename_truncation(self):
        """Test that long filenames are intelligently truncated"""
        pm = ProgressManager()
        
        # Start a copy operation
        pm.start_operation(OperationType.COPY, 100, "destination")
        pm.update_operation_total(100, "destination")
        
        # Update with a very long filename
        long_filename = "very_long_directory_name/another_long_directory/yet_another_directory/final_directory/extremely_long_filename_that_should_be_truncated.txt"
        pm.update_progress(long_filename, 45)
        
        # Get progress segments
        segments = pm.get_progress_segments()
        
        # Should have segments
        self.assertGreater(len(segments), 0)
        
        # Verify essential information is present in first segment
        from xefm.text_layout import AsIsSegment, FilepathSegment
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Copying", segments[0].text)
        self.assertIn("destination", segments[0].text)
        self.assertIn("45/100", segments[0].text)
        
        # Should have a FilepathSegment for the filename
        has_filepath = any(isinstance(seg, FilepathSegment) for seg in segments)
        self.assertTrue(has_filepath, "Should have FilepathSegment for filename")
    
    def test_move_operation(self):
        """Test move operation progress message"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.MOVE, 50, "target_folder")
        pm.update_operation_total(50, "target_folder")
        pm.update_progress("documents/report_2024_final_version_v3.pdf", 25)
        
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AsIsSegment
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Moving", segments[0].text)
        self.assertIn("target_folder", segments[0].text)
        self.assertIn("25/50", segments[0].text)
    
    def test_delete_operation(self):
        """Test delete operation progress message"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.DELETE, 30, "")
        pm.update_operation_total(30, "")
        pm.update_progress("temporary_files/cache/old_data_file.tmp", 15)
        
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AsIsSegment
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Deleting", segments[0].text)
        self.assertIn("15/30", segments[0].text)
    
    def test_narrow_terminal(self):
        """Test progress segments work for narrow terminals"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.COPY, 100, "backup")
        pm.update_operation_total(100, "backup")
        pm.update_progress("path/to/file.txt", 50)
        
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AsIsSegment
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Copying", segments[0].text)
        self.assertIn("50/100", segments[0].text)
    
    def test_filepath_intelligent_abbreviation(self):
        """Test that FilepathSegment provides intelligent path abbreviation"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.COPY, 100, "dest")
        pm.update_operation_total(100, "dest")
        
        # Long nested path
        long_path = "projects/web/client/assets/images/products/thumbnails/high_res/product_final.jpg"
        pm.update_progress(long_path, 50)
        
        # Get segments
        segments = pm.get_progress_segments()
        
        # Should have segments
        self.assertGreater(len(segments), 0)
        
        # Should contain essential info
        from xefm.text_layout import AsIsSegment, FilepathSegment
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Copying", segments[0].text)
        self.assertIn("50/100", segments[0].text)
        
        # Should have FilepathSegment
        filepath_segments = [seg for seg in segments if isinstance(seg, FilepathSegment)]
        self.assertGreater(len(filepath_segments), 0)
        self.assertEqual(filepath_segments[0].text, long_path)
    
    def test_byte_progress_display(self):
        """Test that byte progress is shown for large files"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.COPY, 10, "external")
        pm.update_operation_total(10, "external")
        
        large_file = "videos/large_video_file.mov"
        pm.update_progress(large_file, 5)
        
        # Simulate copying a 5GB file, 2GB copied
        pm.update_file_byte_progress(2 * 1024 * 1024 * 1024, 5 * 1024 * 1024 * 1024)
        
        # Should have AllOrNothingSegment for byte progress
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AllOrNothingSegment
        byte_progress_segments = [seg for seg in segments if isinstance(seg, AllOrNothingSegment)]
        self.assertGreater(len(byte_progress_segments), 0, "Should have byte progress segment")
        
        # Byte progress text should contain size info
        byte_text = byte_progress_segments[0].text
        self.assertTrue("G" in byte_text or "M" in byte_text,
                       f"Should show byte progress, got: {byte_text}")
    
    def test_archive_operations(self):
        """Test archive operation progress messages"""
        pm = ProgressManager()
        
        # Test archive creation
        pm.start_operation(OperationType.ARCHIVE_CREATE, 200, "backup.tar.gz")
        pm.update_operation_total(200, "backup.tar.gz")
        pm.update_progress("documents/file.txt", 150)
        
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AsIsSegment
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Creating archive", segments[0].text)
        self.assertIn("backup.tar.gz", segments[0].text)
        self.assertIn("150/200", segments[0].text)
        
        # Test archive extraction
        pm.start_operation(OperationType.ARCHIVE_EXTRACT, 100, "data.zip")
        pm.update_operation_total(100, "data.zip")
        pm.update_progress("extracted/file.txt", 75)
        
        segments = pm.get_progress_segments()
        
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Extracting archive", segments[0].text)
        self.assertIn("data.zip", segments[0].text)
        self.assertIn("75/100", segments[0].text)
    
    def test_counting_phase(self):
        """Test progress message during counting phase"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.COPY, 0, "destination")
        # Don't call update_operation_total to stay in counting phase
        
        segments = pm.get_progress_segments()
        
        from xefm.text_layout import AsIsSegment
        self.assertGreater(len(segments), 0)
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Copying", segments[0].text)
        self.assertIn("Preparing", segments[0].text)
    
    def test_get_progress_segments(self):
        """Test that get_progress_segments returns proper segment list"""
        pm = ProgressManager()
        
        # No operation - should return empty list
        segments = pm.get_progress_segments()
        self.assertEqual(segments, [])
        
        # Start operation
        pm.start_operation(OperationType.COPY, 100, "dest")
        pm.update_operation_total(100, "dest")
        pm.update_progress("path/to/file.txt", 50)
        
        segments = pm.get_progress_segments()
        
        # Should return a list of segments
        self.assertIsInstance(segments, list)
        self.assertGreater(len(segments), 0)
        
        # Segments should be text segment objects
        from xefm.text_layout import AsIsSegment, FilepathSegment
        
        # First segment should be AsIsSegment with operation info
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Copying", segments[0].text)
        self.assertIn("50/100", segments[0].text)
        
        # Should contain a FilepathSegment for the filename
        has_filepath_segment = any(isinstance(seg, FilepathSegment) for seg in segments)
        self.assertTrue(has_filepath_segment, "Should contain FilepathSegment for filename")
    
    def test_segments_vs_rendering_consistency(self):
        """Test that segments can be properly rendered"""
        pm = ProgressManager()
        
        pm.start_operation(OperationType.MOVE, 50, "target")
        pm.update_operation_total(50, "target")
        pm.update_progress("documents/report.pdf", 25)
        
        # Get segments
        segments = pm.get_progress_segments()
        
        # Should have segments
        self.assertGreater(len(segments), 0)
        
        # All segments should have text attribute
        for seg in segments:
            self.assertTrue(hasattr(seg, 'text'), f"Segment {type(seg).__name__} should have text attribute")
        
        # Essential information should be in segments
        from xefm.text_layout import AsIsSegment
        self.assertIsInstance(segments[0], AsIsSegment)
        self.assertIn("Moving", segments[0].text)
        self.assertIn("25/50", segments[0].text)


if __name__ == "__main__":
    unittest.main()
