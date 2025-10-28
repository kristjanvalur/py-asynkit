#!/usr/bin/env python3
"""
Test that C extension matches Python CoroStart lifecycle behavior
"""
import asyncio
import sys
sys.path.insert(0, '/mnt/e/git/py-asynkit/src')

import asynkit.coroutine as coroutine_mod
PyCoroStart = coroutine_mod.PyCoroStart  # Pure Python version
from asynkit._cext import CoroStart as CCoroStart  # Direct C version

async def sync_coro():
    return 42

async def async_coro():
    await asyncio.sleep(0.001)
    return "async result"

def test_lifecycle(CoroStartClass, name):
    """Test the complete lifecycle behavior"""
    print(f"\n=== {name} Lifecycle ===")
    
    # Sync coroutine lifecycle
    print("\n1. Sync coroutine:")
    cs_sync = CoroStartClass(sync_coro())
    print(f"  After creation - done(): {cs_sync.done()}")
    if cs_sync.done():
        print(f"  result(): {cs_sync.result()}")
    
    return cs_sync

async def test_await_lifecycle(cs_sync, name):
    """Test await behavior and state changes"""
    print(f"\n2. {name} - Awaiting sync coroutine:")
    result = await cs_sync
    print(f"  Await result: {result}")
    print(f"  After await - done(): {cs_sync.done()}")
    
    # Try result() after await
    try:
        result2 = cs_sync.result()
        print(f"  result() after await: {result2}")
    except Exception as e:
        print(f"  result() after await failed: {type(e).__name__}: {e}")
    
    # Try second await
    print(f"\n3. {name} - Second await attempt:")
    try:
        result3 = await cs_sync
        print(f"  Second await result: {result3}")
    except Exception as e:
        print(f"  Second await failed: {type(e).__name__}: {e}")

async def main():
    """Compare Python and C lifecycle behavior"""
    print("Testing CoroStart lifecycle behavior - Python vs C")
    print("=" * 60)
    
    # Create both instances
    py_cs = test_lifecycle(PyCoroStart, "Python CoroStart")
    c_cs = test_lifecycle(CCoroStart, "C CoroStart")
    
    # Test await behavior
    await test_await_lifecycle(py_cs, "Python")
    await test_await_lifecycle(c_cs, "C Extension")
    
    print("\n" + "=" * 60)
    print("Summary: Both implementations should behave identically!")

if __name__ == "__main__":
    asyncio.run(main())