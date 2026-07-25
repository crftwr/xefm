"""
Test progress manager throttling functionality

Run with: python -m pytest test/test_progress_throttling.py -v
"""

import time

from xefm.progress_manager import ProgressManager, OperationType


def test_progress_throttling():
    """Test that progress callbacks are throttled appropriately"""
    print("Testing progress throttling...")
    
    callback_count = 0
    callback_times = []
    
    def test_callback(progress_data):
        nonlocal callback_count
        if progress_data is not None:
            callback_count += 1
            callback_times.append(time.time())
    
    progress_manager = ProgressManager()
    
    # Start operation
    progress_manager.start_operation(
        OperationType.DELETE,
        100,
        "",
        test_callback
    )
    
    start_time = time.time()
    
    # Rapidly update progress (simulating fast file operations)
    for i in range(1, 101):
        progress_manager.update_progress(f"file_{i}.txt", i)
        # Small delay to simulate file operation time
        time.sleep(0.001)  # 1ms per file
    
    progress_manager.finish_operation()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"Total operation time: {total_time:.3f} seconds")
    print(f"Total progress updates: 100")
    print(f"Actual callbacks called: {callback_count}")
    print(f"Throttling ratio: {callback_count}/100 = {callback_count/100:.2f}")
    
    # Verify throttling is working
    assert callback_count < 100, f"Expected fewer than 100 callbacks due to throttling, got {callback_count}"
    assert callback_count >= 2, f"Expected at least 2 callbacks (first and last), got {callback_count}"
    
    # Check timing between callbacks (allowing for some variance due to execution time)
    if len(callback_times) > 1:
        intervals = [callback_times[i+1] - callback_times[i] for i in range(len(callback_times)-1)]
        min_interval = min(intervals)
        avg_interval = sum(intervals) / len(intervals)
        print(f"Minimum interval between callbacks: {min_interval*1000:.1f}ms")
        print(f"Average interval between callbacks: {avg_interval*1000:.1f}ms")
        
        # The average interval should be reasonable (we're doing 100 updates in ~125ms)
        # With throttling, we should get fewer callbacks spread over time
        expected_avg_interval = total_time / max(1, callback_count - 1)
        print(f"Expected average interval: {expected_avg_interval*1000:.1f}ms")
        
        # Just verify that throttling is working (fewer callbacks than updates)
        assert callback_count < 50, f"Too many callbacks: {callback_count} (throttling not effective)"
    
    print("✅ Progress throttling test passed!")


def test_throttling_with_final_update():
    """Test that final update is always called regardless of throttling"""
    print("\nTesting final update behavior...")
    
    callback_count = 0
    final_update_called = False
    
    def test_callback(progress_data):
        nonlocal callback_count, final_update_called
        if progress_data is not None:
            callback_count += 1
            if progress_data['processed_items'] == progress_data['total_items']:
                final_update_called = True
    
    progress_manager = ProgressManager()
    
    # Start operation with small number of items
    progress_manager.start_operation(
        OperationType.COPY,
        5,
        "",
        test_callback
    )
    
    # Rapidly update progress
    for i in range(1, 6):
        progress_manager.update_progress(f"file_{i}.txt", i)
        time.sleep(0.001)  # Very fast updates
    
    progress_manager.finish_operation()
    
    print(f"Callbacks called: {callback_count}")
    print(f"Final update called: {final_update_called}")
    
    # The final update (100% complete) should always be called
    assert final_update_called, "Final update (100% complete) should always be called"
    
    print("✅ Final update test passed!")


def test_no_throttling_for_slow_operations():
    """Test that throttling doesn't interfere with slow operations"""
    print("\nTesting slow operations (no throttling needed)...")
    
    callback_count = 0
    
    def test_callback(progress_data):
        nonlocal callback_count
        if progress_data is not None:
            callback_count += 1
    
    progress_manager = ProgressManager()
    
    # Start operation
    progress_manager.start_operation(
        OperationType.MOVE,
        5,
        "",
        test_callback
    )
    
    # Slow updates (longer than throttle time)
    for i in range(1, 6):
        progress_manager.update_progress(f"file_{i}.txt", i)
        time.sleep(0.06)  # 60ms - longer than throttle time
    
    progress_manager.finish_operation()
    
    print(f"Callbacks called: {callback_count}")
    
    # All updates should be called since they're slow enough (plus initial callback)
    assert callback_count == 6, f"Expected 6 callbacks for slow operations (1 initial + 5 updates), got {callback_count}"
    
    print("✅ Slow operations test passed!")
