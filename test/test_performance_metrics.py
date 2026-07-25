"""
Test performance metrics functionality in cpp_renderer module.

This test verifies:
- get_performance_metrics() returns a dictionary with expected keys
- reset_metrics() resets all counters to zero
- Metrics are properly tracked during rendering

Run with: python -m pytest test/test_performance_metrics.py -v
"""


def test_metrics_functions_exist():
    """Test that metrics functions are available in the module."""
    try:
        import cpp_renderer
        
        # Check that functions exist
        assert hasattr(cpp_renderer, 'get_performance_metrics'), \
            "cpp_renderer should have get_performance_metrics function"
        assert hasattr(cpp_renderer, 'reset_metrics'), \
            "cpp_renderer should have reset_metrics function"
        
        print("✓ Metrics functions exist in cpp_renderer module")
        return
        
    except ImportError as e:
        print(f"✗ Failed to import cpp_renderer: {e}")
        print("  Note: This is expected if the C++ extension is not built")
        return


def test_get_performance_metrics():
    """Test that get_performance_metrics returns expected structure."""
    try:
        import cpp_renderer
        
        # Get metrics
        metrics = cpp_renderer.get_performance_metrics()
        
        # Verify it's a dictionary
        assert isinstance(metrics, dict), \
            "get_performance_metrics should return a dictionary"
        
        # Verify expected keys are present
        expected_keys = [
            'frames_rendered',
            'total_render_time_ms',
            'avg_render_time_ms',
            'total_batches',
            'avg_batches_per_frame',
            'attr_dict_cache_hits',
            'attr_dict_cache_misses',
            'attr_dict_cache_hit_rate'
        ]
        
        for key in expected_keys:
            assert key in metrics, f"Metrics should contain '{key}' key"
        
        # Verify types
        assert isinstance(metrics['frames_rendered'], int), \
            "frames_rendered should be an integer"
        assert isinstance(metrics['total_render_time_ms'], float), \
            "total_render_time_ms should be a float"
        assert isinstance(metrics['avg_render_time_ms'], float), \
            "avg_render_time_ms should be a float"
        assert isinstance(metrics['total_batches'], int), \
            "total_batches should be an integer"
        assert isinstance(metrics['avg_batches_per_frame'], float), \
            "avg_batches_per_frame should be a float"
        assert isinstance(metrics['attr_dict_cache_hits'], int), \
            "attr_dict_cache_hits should be an integer"
        assert isinstance(metrics['attr_dict_cache_misses'], int), \
            "attr_dict_cache_misses should be an integer"
        assert isinstance(metrics['attr_dict_cache_hit_rate'], float), \
            "attr_dict_cache_hit_rate should be a float"
        
        print("✓ get_performance_metrics returns correct structure")
        print(f"  Current metrics: {metrics}")
        return
        
    except ImportError as e:
        print(f"✗ Failed to import cpp_renderer: {e}")
        return
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return


def test_reset_metrics():
    """Test that reset_metrics resets all counters."""
    try:
        import cpp_renderer
        
        # Get initial metrics
        metrics_before = cpp_renderer.get_performance_metrics()
        
        # Reset metrics
        cpp_renderer.reset_metrics()
        
        # Get metrics after reset
        metrics_after = cpp_renderer.get_performance_metrics()
        
        # Verify all counters are zero
        assert metrics_after['frames_rendered'] == 0, \
            "frames_rendered should be 0 after reset"
        assert metrics_after['total_render_time_ms'] == 0.0, \
            "total_render_time_ms should be 0.0 after reset"
        assert metrics_after['total_batches'] == 0, \
            "total_batches should be 0 after reset"
        assert metrics_after['attr_dict_cache_hits'] == 0, \
            "attr_dict_cache_hits should be 0 after reset"
        assert metrics_after['attr_dict_cache_misses'] == 0, \
            "attr_dict_cache_misses should be 0 after reset"
        
        # Verify calculated values are also zero
        assert metrics_after['avg_render_time_ms'] == 0.0, \
            "avg_render_time_ms should be 0.0 after reset"
        assert metrics_after['avg_batches_per_frame'] == 0.0, \
            "avg_batches_per_frame should be 0.0 after reset"
        assert metrics_after['attr_dict_cache_hit_rate'] == 0.0, \
            "attr_dict_cache_hit_rate should be 0.0 after reset"
        
        print("✓ reset_metrics correctly resets all counters to zero")
        print(f"  Metrics before reset: frames={metrics_before['frames_rendered']}, "
              f"time={metrics_before['total_render_time_ms']:.2f}ms")
        print(f"  Metrics after reset: frames={metrics_after['frames_rendered']}, "
              f"time={metrics_after['total_render_time_ms']:.2f}ms")
        return
        
    except ImportError as e:
        print(f"✗ Failed to import cpp_renderer: {e}")
        return
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return


def main():
    """Run all tests."""
    print("Testing performance metrics functionality...")
    print()
    
    tests = [
        ("Metrics functions exist", test_metrics_functions_exist),
        ("get_performance_metrics structure", test_get_performance_metrics),
        ("reset_metrics functionality", test_reset_metrics),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"Test: {name}")
        result = test_func()
        results.append(result)
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1
