#!/usr/bin/env python3
"""
XeFM Progress Manager - Handles progress tracking for file operations
"""

import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
from xefm.progress_animator import ProgressAnimator
from xefm.str_format import format_size
from xefm.text_layout import (
    AsIsSegment,
    FilepathSegment,
    SpacerSegment,
    AllOrNothingSegment
)


class OperationType(Enum):
    """Types of operations that can show progress"""
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    ARCHIVE_CREATE = "archive_create"
    ARCHIVE_EXTRACT = "archive_extract"


#: A file's fixed per-item cost in the progress percentage, in byte-equivalents.
#: The primary bar advances on ``processed_bytes + _ITEM_WEIGHT * processed_items``
#: over the same expression for the totals, so one huge file no longer freezes a
#: bar that counts items, and thousands of tiny files no longer pin a bar that
#: counts bytes. Operations that report no byte totals (delete, archives) reduce
#: to the old pure item ratio.
_ITEM_WEIGHT = 8 * 1024


class ProgressManager:
    """Manages progress tracking for long-running file operations"""
    
    def __init__(self, config=None):
        self.current_operation: Optional[Dict[str, Any]] = None
        self.progress_callback: Optional[Callable] = None
        self.last_callback_time: float = 0
        self.callback_throttle_ms: float = 50  # Minimum 50ms between callbacks
        # A parallel copy has several worker threads reporting into one
        # operation dict; the read-modify-write updates below hold this lock so
        # a processed-items increment is never lost between threads.
        self._lock = threading.Lock()
        
        # Create animator with config or use minimal config
        if config:
            self.animator = ProgressAnimator(config, pattern_override='spinner', speed_override=0.08)
        else:
            # Create a minimal config object for standalone use
            class MinimalConfig:
                PROGRESS_ANIMATION_PATTERN = 'spinner'
                PROGRESS_ANIMATION_SPEED = 0.08
            self.animator = ProgressAnimator(MinimalConfig())
    

    
    def start_operation(self, operation_type: OperationType, total_items: int, 
                       description: str = "", progress_callback: Optional[Callable] = None):
        """Start tracking progress for an operation
        
        Args:
            operation_type: Type of operation being performed
            total_items: Total number of items to process
            description: Optional description of the operation
            progress_callback: Optional callback to call when progress updates
        """
        self.current_operation = {
            'type': operation_type,
            'total_items': total_items,
            'processed_items': 0,
            'current_item': '',
            'description': description,
            'errors': 0,
            'file_bytes_copied': 0,  # Bytes copied for current file
            'file_bytes_total': 0,   # Total bytes for current file
            'counting': True,        # Flag to indicate we're still counting files
            'total_bytes': 0,        # Bytes the whole operation will move (0 = unknown)
            'processed_bytes': 0,    # Bytes moved so far, across all workers
            'transfers': {}          # slot -> per-file transfer state (file_begin)
        }
        self.progress_callback = progress_callback
        self.animator.reset()
        
        # Call callback with initial state
        if self.progress_callback:
            self.progress_callback(self.current_operation)
    
    def update_operation_total(self, total_items: int, description: str = "",
                               total_bytes: int = 0):
        """Update the total item count for current operation

        This is useful when the total count isn't known at operation start
        (e.g., during file counting phase).

        Args:
            total_items: New total number of items
            description: Optional updated description
            total_bytes: Total bytes the operation will move, when the counting
                pass measured them; 0 leaves the bar weighted by items alone
        """
        if not self.current_operation:
            return

        self.current_operation['total_items'] = total_items
        if description:
            self.current_operation['description'] = description
        self.current_operation['total_bytes'] = max(0, int(total_bytes))

        # Mark counting as complete
        self.current_operation['counting'] = False

        # Trigger callback to update display
        self._trigger_callback_if_needed(force=True)
    
    def update_progress(self, current_item: str, processed_items: Optional[int] = None):
        """Update progress with current item being processed
        
        Args:
            current_item: Name of the current item being processed
            processed_items: Optional override for processed count (auto-increments if None)
        """
        with self._lock:
            op = self.current_operation
            if not op:
                return

            op['current_item'] = current_item
            op['file_bytes_copied'] = 0  # Reset byte progress for new file
            op['file_bytes_total'] = 0

            # Mark counting as complete when we start processing items
            op['counting'] = False

            if processed_items is not None:
                op['processed_items'] = processed_items
            else:
                op['processed_items'] += 1

        # Call callback with updated state (with throttling)
        self._trigger_callback_if_needed()
    
    def update_file_byte_progress(self, bytes_copied: int, bytes_total: int):
        """Update the byte-level progress for the current file being copied

        The single-current-item path (archives, and any operation that works one
        file at a time through :meth:`update_progress`). The copy engine's
        workers report through per-file slots instead — see :meth:`file_begin`.

        Args:
            bytes_copied: Number of bytes copied so far
            bytes_total: Total number of bytes in the file
        """
        with self._lock:
            op = self.current_operation
            if not op:
                return

            op['file_bytes_copied'] = bytes_copied
            op['file_bytes_total'] = bytes_total

        # Call callback with updated state (with throttling)
        self._trigger_callback_if_needed()

    # --- per-file transfer slots (the copy engine's path) --------------------
    #
    # A parallel copy has several files in flight at once; each takes a slot for
    # its lifetime. The slot keys a row in the progress dialog (lowest free slot
    # is reused, so rows stay put while workers cycle through files), its byte
    # updates accumulate into the operation-wide ``processed_bytes``, and the
    # item is counted when the file *finishes* — the item bar no longer jumps to
    # "4/5" the moment four workers have merely started.

    def file_begin(self, item: str, total_bytes: int = 0) -> int:
        """A file starts: claim a slot and name it. Returns the slot id for
        :meth:`file_bytes` / :meth:`file_end`. Does not advance the item count.

        Args:
            item: Name of the file
            total_bytes: The file's size when already known; usually left 0 and
                published by the first :meth:`file_bytes` call instead
        """
        with self._lock:
            op = self.current_operation
            if not op:
                return -1
            transfers = op['transfers']
            slot = 0
            while slot in transfers and not transfers[slot].get('done'):
                slot += 1
            transfers[slot] = {'item': item, 'copied': 0,
                               'total': max(0, int(total_bytes)), 'done': False}
            op['current_item'] = item
            op['file_bytes_copied'] = 0  # Reset byte progress for new file
            op['file_bytes_total'] = 0
            op['counting'] = False
        self._trigger_callback_if_needed()
        return slot

    def file_bytes(self, slot: int, copied: int, total: Optional[int] = None):
        """Cumulative bytes for the file in ``slot``; the growth since the last
        report is added to the operation's ``processed_bytes``.

        Args:
            slot: The id :meth:`file_begin` returned
            copied: Bytes of this file copied so far (cumulative, not a delta)
            total: The file's size, when the caller has it; None leaves the
                slot's stored total unchanged
        """
        with self._lock:
            op = self.current_operation
            if not op:
                return
            t = op['transfers'].get(slot)
            if t is None or t.get('done'):
                return
            if total is not None:
                t['total'] = max(0, int(total))
            copied = max(0, int(copied))
            if copied > t['copied']:
                op['processed_bytes'] += copied - t['copied']
            t['copied'] = copied
            # Mirror into the legacy per-file fields while this is the current
            # item, so the flat-text renderers keep showing the newest file's
            # bytes exactly as the sequential path always has.
            if t['item'] == op.get('current_item'):
                op['file_bytes_copied'] = t['copied']
                op['file_bytes_total'] = t['total']
        self._trigger_callback_if_needed()

    def file_end(self, slot: int):
        """The file in ``slot`` is done (copied, skipped, or failed): count the
        item, and credit any of its bytes that were never streamed — a small
        file copied in one shot, an instant clone, a skip — so the byte-weighted
        bar stays honest without every path having to report bytes itself."""
        with self._lock:
            op = self.current_operation
            if not op:
                return
            t = op['transfers'].get(slot)
            if t is not None and not t.get('done'):
                if t['total'] > t['copied']:
                    op['processed_bytes'] += t['total'] - t['copied']
                    t['copied'] = t['total']
                t['done'] = True
            op['processed_items'] += 1
        self._trigger_callback_if_needed()

    def get_transfers(self) -> list:
        """Snapshot of the per-slot transfer rows, ``(slot, state)`` sorted by
        slot, copied under the lock so the UI thread never iterates a dict the
        workers are mutating. Finished files stay in their slot (marked
        ``done``) until a new file reuses it, so dialog rows don't blink."""
        with self._lock:
            op = self.current_operation
            if not op:
                return []
            return [(slot, dict(t)) for slot, t in sorted(op['transfers'].items())]
    
    def _trigger_callback_if_needed(self, force: bool = False):
        """Trigger progress callback if enough time has passed or forced
        
        Args:
            force: If True, bypass throttling and always trigger callback
        """
        if not self.progress_callback:
            return
        
        current_time = time.time() * 1000  # Convert to milliseconds
        
        # Always call callback for the first update, if forced, or if enough time has passed
        if (force or 
            self.last_callback_time == 0 or 
            current_time - self.last_callback_time >= self.callback_throttle_ms or
            (self.current_operation and 
             self.current_operation['processed_items'] >= self.current_operation['total_items'])):
            
            self.progress_callback(self.current_operation)
            self.last_callback_time = current_time
    
    def refresh_animation(self):
        """Force a callback to refresh animation without changing progress data
        
        This should be called periodically to keep the animation smooth even when
        there are no progress updates (e.g., during large file copies).
        """
        if self.current_operation and self.progress_callback:
            # Force callback to update animation
            self._trigger_callback_if_needed(force=True)
    
    def increment_errors(self):
        """Increment the error count for the current operation"""
        with self._lock:
            if self.current_operation:
                self.current_operation['errors'] += 1
    
    def finish_operation(self):
        """Finish the current operation and clear progress state"""
        if self.progress_callback and self.current_operation:
            # Call callback one final time to clear progress display
            self.progress_callback(None)
        
        self.current_operation = None
        self.progress_callback = None
        self.last_callback_time = 0  # Reset throttling
        self.animator.reset()
    
    def is_operation_active(self) -> bool:
        """Check if an operation is currently being tracked"""
        return self.current_operation is not None
    
    def get_current_operation(self) -> Optional[Dict[str, Any]]:
        """Get the current operation state"""
        return self.current_operation
    
    def get_progress_percentage(self) -> int:
        """Get the current progress as a percentage (0-100)

        Weighted by bytes as well as items (see :data:`_ITEM_WEIGHT`): with no
        byte totals reported this is the plain item ratio, and with them a
        4 GiB file among a dozen small ones holds the bar back for the time it
        will actually take."""
        op = self.current_operation
        if not op or op['total_items'] == 0:
            return 0

        weight = op.get('total_bytes', 0) + _ITEM_WEIGHT * op['total_items']
        done = op.get('processed_bytes', 0) + _ITEM_WEIGHT * op['processed_items']
        return int(min(weight, done) / weight * 100)
    
    def get_progress_text(self, max_width: int = 80) -> str:
        """Render the current operation's progress as a single plain-text line no
        wider than ``max_width``.

        A flat-text companion to :meth:`get_progress_segments` (which returns
        rich segments for the animated renderer) — handy for logging and tests.
        Returns an empty string when no operation is active."""
        if not self.current_operation:
            return ""

        op = self.current_operation
        operation_verbs = {
            OperationType.COPY: "Copying",
            OperationType.MOVE: "Moving",
            OperationType.DELETE: "Deleting",
            OperationType.ARCHIVE_CREATE: "Creating archive",
            OperationType.ARCHIVE_EXTRACT: "Extracting archive",
        }
        verb = operation_verbs.get(op['type'], "Processing")
        frame = self.animator.get_current_frame()
        desc = f" ({op['description']})" if op.get('description') else ""

        if op.get('counting', False):
            text = f"{frame} {verb}{desc}... Preparing"
        else:
            text = f"{frame} {verb}{desc}... {op['processed_items']}/{op['total_items']}"

        if op.get('current_item'):
            text = f"{text} - {op['current_item']}"
            file_bytes_copied = op.get('file_bytes_copied', 0)
            file_bytes_total = op.get('file_bytes_total', 0)
            if file_bytes_total > 1024 * 1024 and file_bytes_copied > 0:
                copied = format_size(file_bytes_copied, compact=True)
                total = format_size(file_bytes_total, compact=True)
                text = f"{text} [{copied}/{total}]"

        return text[:max_width]

    def get_progress_segments(self):
        """Get progress segments for rendering with text layout system

        Returns:
            List of text segments, or empty list if no operation is active
        """
        if not self.current_operation:
            return []
        
        op = self.current_operation
        op_type = op['type']
        processed = op['processed_items']
        total = op['total_items']
        current_item = op['current_item']
        file_bytes_copied = op.get('file_bytes_copied', 0)
        file_bytes_total = op.get('file_bytes_total', 0)
        
        # Get operation verb
        operation_verbs = {
            OperationType.COPY: "Copying",
            OperationType.MOVE: "Moving", 
            OperationType.DELETE: "Deleting",
            OperationType.ARCHIVE_CREATE: "Creating archive",
            OperationType.ARCHIVE_EXTRACT: "Extracting archive"
        }
        
        verb = operation_verbs.get(op_type, "Processing")
        
        # Get animation frame using the existing animator
        animation_frame = self.animator.get_current_frame()
        
        # Build base progress text with animator (no percentage)
        # Hide count during counting phase
        is_counting = op.get('counting', False)
        
        # Build segments using text layout system
        segments = []
        
        # Animation frame and verb (always visible)
        if is_counting:
            # During counting, show "Preparing..." without count
            if op['description']:
                base_text = f"{animation_frame} {verb} ({op['description']})... Preparing"
            else:
                base_text = f"{animation_frame} {verb}... Preparing"
            segments.append(AsIsSegment(base_text))
        else:
            # After counting, show actual progress count
            if op['description']:
                base_text = f"{animation_frame} {verb} ({op['description']})... {processed}/{total}"
            else:
                base_text = f"{animation_frame} {verb}... {processed}/{total}"
            segments.append(AsIsSegment(base_text))
        
        # Add current item if present
        if current_item:
            # Add separator
            segments.append(AsIsSegment(" - "))
            
            # Add filename with intelligent truncation
            # Use FilepathSegment for paths, which intelligently abbreviates them
            segments.append(FilepathSegment(
                text=current_item,
                priority=2,  # Shortened before byte progress
                min_length=10,  # Keep at least 10 characters
                abbrev_position='middle'  # Abbreviate from the middle
            ))
            
            # Add byte progress if applicable (all-or-nothing)
            # Only show byte progress for large files (>1MB) that require multiple read/write operations
            if file_bytes_total > 1024 * 1024 and file_bytes_copied > 0:
                bytes_copied_str = format_size(file_bytes_copied, compact=True)
                bytes_total_str = format_size(file_bytes_total, compact=True)
                byte_progress_text = f" [{bytes_copied_str}/{bytes_total_str}]"
                
                # Use AllOrNothingSegment so byte progress is only shown if there's enough space
                # Higher priority (lower number) than filepath - keep byte progress, shorten path first
                segments.append(AllOrNothingSegment(
                    text=byte_progress_text,
                    priority=1  # Keep this before shortening filepath
                ))
        
        return segments