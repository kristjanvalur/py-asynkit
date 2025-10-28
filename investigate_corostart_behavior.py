#!/usr/bin/env python3
"""
Investigate CoroStart behavior with done coroutines and multiple awaits
"""
import asyncio
import sys
sys.path.insert(0, '/mnt/e/git/py-asynkit/src')

# Get both versions
import asynkit.coroutine as coroutine_mod
PyCoroStart = coroutine_mod.PyCoroStart  # Pure Python version
CCoroStart = coroutine_mod.CoroStart     # Wrapped version (uses C if available)

async def sync_coro():
    """Coroutine that completes immediately (synchronously)"""
    return 42

async def async_coro():
    """Coroutine that suspends then completes"""
    await asyncio.sleep(0.001)
    return "async result"

async def failing_coro():
    """Coroutine that raises an exception"""
    await asyncio.sleep(0.001)
    raise ValueError("test error")

def test_done_behavior(CoroStartClass, name):
    """Test done() and result() behavior for different coroutine types"""
    print(f"\n=== Testing {name} ===")
    
    # Test 1: Synchronous coroutine (completes immediately)
    print("\n1. Synchronous coroutine:")
    cs_sync = CoroStartClass(sync_coro())
    print(f"  After creation - done(): {cs_sync.done()}")
    if cs_sync.done():
        try:
            result = cs_sync.result()
            print(f"  result(): {result}")
        except Exception as e:
            print(f"  result() raised: {type(e).__name__}: {e}")
    
    # Test 2: Asynchronous coroutine (initially not done)
    print("\n2. Asynchronous coroutine (before await):")
    cs_async = CoroStartClass(async_coro())
    print(f"  After creation - done(): {cs_async.done()}")
    if not cs_async.done():
        try:
            result = cs_async.result()
            print(f"  result(): {result}")
        except Exception as e:
            print(f"  result() raised: {type(e).__name__}: {e}")
    
    return cs_sync, cs_async

async def test_await_behavior(CoroStartClass, name):
    """Test await behavior with done and not-done coroutines"""
    print(f"\n=== Testing await behavior for {name} ===")
    
    # Test 3: Await a done (sync) coroutine
    print("\n3. Awaiting already-done (sync) coroutine:")
    cs_sync = CoroStartClass(sync_coro())
    print(f"  Before await - done(): {cs_sync.done()}")
    try:
        result = await cs_sync
        print(f"  Await result: {result}")
        print(f"  After await - done(): {cs_sync.done()}")
    except Exception as e:
        print(f"  Await raised: {type(e).__name__}: {e}")
    
    # Test 4: Await the same done coroutine again
    print("\n4. Awaiting the SAME done coroutine again:")
    try:
        result2 = await cs_sync
        print(f"  Second await result: {result2}")
        print(f"  After second await - done(): {cs_sync.done()}")
    except Exception as e:
        print(f"  Second await raised: {type(e).__name__}: {e}")
    
    # Test 5: Await an async coroutine (not initially done)
    print("\n5. Awaiting async coroutine:")
    cs_async = CoroStartClass(async_coro())
    print(f"  Before await - done(): {cs_async.done()}")
    try:
        result = await cs_async
        print(f"  Await result: {result}")
        print(f"  After await - done(): {cs_async.done()}")
    except Exception as e:
        print(f"  Await raised: {type(e).__name__}: {e}")
    
    # Test 6: Await the same async coroutine again (now done)
    print("\n6. Awaiting the SAME async coroutine again:")
    try:
        result2 = await cs_async
        print(f"  Second await result: {result2}")
        print(f"  After second await - done(): {cs_async.done()}")
    except Exception as e:
        print(f"  Second await raised: {type(e).__name__}: {e}")
    
    # Test 7: Exception handling
    print("\n7. Exception in coroutine:")
    cs_fail = CoroStartClass(failing_coro())
    print(f"  Before await - done(): {cs_fail.done()}")
    try:
        result = await cs_fail
        print(f"  Await result: {result}")
    except Exception as e:
        print(f"  Await raised: {type(e).__name__}: {e}")
        print(f"  After exception - done(): {cs_fail.done()}")
        try:
            result = cs_fail.result()
            print(f"  result(): {result}")
        except Exception as e2:
            print(f"  result() raised: {type(e2).__name__}: {e2}")
    
    # Test 8: Await the failed coroutine again
    print("\n8. Awaiting the SAME failed coroutine again:")
    try:
        result2 = await cs_fail
        print(f"  Second await result: {result2}")
    except Exception as e:
        print(f"  Second await raised: {type(e).__name__}: {e}")

async def main():
    """Run all tests"""
    print("Investigating CoroStart behavior with done coroutines and multiple awaits")
    print("=" * 80)
    
    # Test synchronous behavior (done/result without await)
    py_sync, py_async = test_done_behavior(PyCoroStart, "Pure Python CoroStart")
    c_sync, c_async = test_done_behavior(CCoroStart, "C/Wrapped CoroStart")
    
    # Test await behavior
    await test_await_behavior(PyCoroStart, "Pure Python CoroStart")
    await test_await_behavior(CCoroStart, "C/Wrapped CoroStart")

if __name__ == "__main__":
    asyncio.run(main())