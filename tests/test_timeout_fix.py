"""Test that the timeout fix works correctly."""

import asyncio
import sys

# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

import asynkit


async def operation_with_timeout(name: str, delay: float) -> str:
    """An operation that uses timeout(0) to check if data is ready."""
    print(f"{name}: Starting operation")
    
    # Simulate checking if data is ready with timeout(0)
    try:
        async with asyncio.timeout(0):
            print(f"{name}: Inside timeout context")
            # This would normally check something non-blocking
            await asyncio.sleep(0)  # This will cause timeout
    except TimeoutError:
        print(f"{name}: Timeout fired (expected)")
    
    # Now do the actual work
    print(f"{name}: Doing actual work")
    await asyncio.sleep(delay)
    print(f"{name}: Work completed")
    return f"Result from {name}"


async def test_concurrent_timeouts():
    """Test concurrent operations with timeout(0), similar to Redis pattern."""
    print("\n=== Test 1: Concurrent operations with timeout(0) ===")
    
    # Create multiple concurrent operations
    coros = [
        operation_with_timeout(f"Op{i}", 0.01)
        for i in range(3)
    ]
    
    try:
        results = await asyncio.gather(*coros)
        print(f"✓ Success! Results: {results}")
        return True
    except Exception as e:
        print(f"✗ Failed with {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def timeout_during_eager():
    """Test timeout that fires during eager execution."""
    print("\n=== Test 2: Timeout during eager execution ===")
    
    async def fast_op(name: str) -> str:
        """Operation that completes before suspending."""
        print(f"{name}: Running eagerly")
        async with asyncio.timeout(0.1):
            # This runs eagerly (doesn't suspend)
            result = f"Result from {name}"
            print(f"{name}: Completed eagerly")
            return result
    
    try:
        results = await asyncio.gather(
            fast_op("A"),
            fast_op("B"),
            fast_op("C")
        )
        print(f"✓ Success! Results: {results}")
        return True
    except Exception as e:
        print(f"✗ Failed with {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def nested_eager_timeout():
    """Test nested eager execution with timeouts."""
    print("\n=== Test 3: Nested eager execution with timeouts ===")
    
    async def inner_op(name: str) -> str:
        """Inner operation with timeout."""
        async with asyncio.timeout(0.05):
            print(f"  {name}: Inner timeout entered")
            return f"Inner {name}"
    
    async def outer_op(name: str) -> str:
        """Outer operation that calls inner operations."""
        print(f"{name}: Starting")
        async with asyncio.timeout(0.1):
            print(f"{name}: Outer timeout entered")
            # Call inner operations
            result = await inner_op(f"{name}.inner")
            print(f"{name}: Completed")
            return f"Outer {result}"
    
    try:
        results = await asyncio.gather(
            outer_op("A"),
            outer_op("B")
        )
        print(f"✓ Success! Results: {results}")
        return True
    except Exception as e:
        print(f"✗ Failed with {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("Testing asyncio.timeout() fix for eager execution\n")
    print(f"Python version: {sys.version}")
    print(f"Asyncio policy: {asyncio.get_event_loop_policy()}")
    
    # Install eager task factory
    print("\nInstalling eager task factory...")
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asynkit.eager_task_factory)
    
    results = []
    results.append(await test_concurrent_timeouts())
    results.append(await timeout_during_eager())
    results.append(await nested_eager_timeout())
    
    print("\n" + "=" * 60)
    if all(results):
        print("✓ ALL TESTS PASSED")
        return 0
    else:
        print(f"✗ {sum(not r for r in results)} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
