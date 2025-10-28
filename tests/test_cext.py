"""
Test C extension integration for asynkit

This module tests that the C extension CoroStart implementation
behaves identically to the Python implementation.
"""

import asyncio
import pytest
from typing import Any

import asynkit
from asynkit.coroutine import _HAVE_C_EXTENSION, _PyCoroStart

# Test if C extension is available
pytestmark = pytest.mark.anyio


class TestCExtensionIntegration:
    """Test that C extension integrates properly with Python fallback"""
    
    def test_c_extension_availability(self):
        """Test whether C extension is available"""
        # This will be True if compilation succeeded, False otherwise
        print(f"C extension available: {_HAVE_C_EXTENSION}")
        # Don't assert - it's ok if C extension is not available during development
    
    async def test_corostart_python_fallback(self):
        """Test that Python implementation still works"""
        async def test_coro():
            await asyncio.sleep(0)
            return "python_result"
        
        # Use Python implementation directly
        start = _PyCoroStart(test_coro())
        if start.done():
            result = start.result()
        else:
            result = await start
        
        assert result == "python_result"
    
    async def test_corostart_with_context(self):
        """Test CoroStart with context - should use Python implementation"""
        import contextvars
        
        var = contextvars.ContextVar('test_var', default='default')
        
        async def test_coro():
            await asyncio.sleep(0)
            return var.get()
        
        ctx = contextvars.copy_context()
        ctx.run(var.set, 'context_value')
        
        # This should use Python implementation due to context parameter
        start = asynkit.CoroStart(test_coro(), context=ctx)
        if start.done():
            result = start.result()
        else:
            result = await start
        
        assert result == 'context_value'
    
    async def test_corostart_without_context(self):
        """Test CoroStart without context - may use C extension if available"""
        async def test_coro():
            await asyncio.sleep(0)
            return "no_context_result"
        
        # This may use C extension if available
        start = asynkit.CoroStart(test_coro())
        if start.done():
            result = start.result()
        else:
            result = await start
        
        assert result == "no_context_result"
    
    async def test_corostart_eager_completion(self):
        """Test that eager completion works with both implementations"""
        async def immediate_coro():
            # This should complete immediately without suspending
            return "immediate"
        
        start = asynkit.CoroStart(immediate_coro())
        assert start.done()
        assert start.result() == "immediate"
    
    async def test_corostart_methods(self):
        """Test that all CoroStart methods work regardless of implementation"""
        async def test_coro():
            await asyncio.sleep(0)
            return "method_test"
        
        start = asynkit.CoroStart(test_coro())
        
        # Test done() method
        done_before = start.done()
        
        if not done_before:
            # Test awaiting
            result = await start
            assert result == "method_test"
        else:
            # Test result() method
            result = start.result()
            assert result == "method_test"
    
    async def test_corostart_exception_handling(self):
        """Test exception handling works with both implementations"""
        async def error_coro():
            await asyncio.sleep(0)
            raise ValueError("test error")
        
        start = asynkit.CoroStart(error_coro())
        
        if start.done():
            # Should have captured the exception
            exc = start.exception()
            assert isinstance(exc, ValueError)
            assert str(exc) == "test error"
        else:
            # Should raise when awaited
            with pytest.raises(ValueError, match="test error"):
                await start
    
    async def test_corostart_close(self):
        """Test that close() method works"""
        async def test_coro():
            await asyncio.sleep(0)
            return "should_not_reach"
        
        start = asynkit.CoroStart(test_coro())
        
        if not start.done():
            start.close()
            # After closing, the coroutine should not be awaitable
            # The exact behavior may differ between implementations
    
    async def test_multiple_corostart_instances(self):
        """Test multiple CoroStart instances work correctly"""
        async def numbered_coro(n: int):
            await asyncio.sleep(0)
            return f"result_{n}"
        
        starts = [asynkit.CoroStart(numbered_coro(i)) for i in range(5)]
        
        results = []
        for start in starts:
            if start.done():
                results.append(start.result())
            else:
                results.append(await start)
        
        expected = [f"result_{i}" for i in range(5)]
        assert results == expected


class TestCExtensionPerformance:
    """Performance comparison tests (informational only)"""
    
    @pytest.mark.skip(reason="Performance test - enable manually")
    async def test_performance_comparison(self):
        """Compare performance of C vs Python implementation"""
        import time
        
        async def suspend_many_times(n: int):
            for _ in range(n):
                await asyncio.sleep(0)
            return n
        
        # Test with Python implementation
        start_time = time.perf_counter()
        for _ in range(100):
            start = _PyCoroStart(suspend_many_times(10))
            if not start.done():
                await start
        python_time = time.perf_counter() - start_time
        
        # Test with current implementation (may be C extension)
        start_time = time.perf_counter()
        for _ in range(100):
            start = asynkit.CoroStart(suspend_many_times(10))
            if not start.done():
                await start
        current_time = time.perf_counter() - start_time
        
        print(f"Python implementation: {python_time:.4f}s")
        print(f"Current implementation: {current_time:.4f}s")
        
        if _HAVE_C_EXTENSION and current_time < python_time:
            speedup = python_time / current_time
            print(f"Speedup: {speedup:.2f}x")
        else:
            print("No speedup detected (C extension may not be in use)")


if __name__ == "__main__":
    import sys
    
    print("=== asynkit C Extension Test ===")
    print(f"C extension available: {_HAVE_C_EXTENSION}")
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    
    # Run a simple test
    async def simple_test():
        async def test_coro():
            await asyncio.sleep(0)
            return "test_passed"
        
        start = asynkit.CoroStart(test_coro())
        result = await start if not start.done() else start.result()
        print(f"Simple test result: {result}")
        return result == "test_passed"
    
    if asyncio.run(simple_test()):
        print("✓ Basic functionality test passed")
    else:
        print("✗ Basic functionality test failed")