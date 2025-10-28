#!/usr/bin/env python3

import asyncio
import asynkit

async def test_exception_method():
    """Test that the exception() method works correctly in both C and Python implementations"""
    
    # Test 1: Normal completion (should return None)
    async def sync_coro():
        return 42
    
    # Test C extension
    cs_c = asynkit._cext.CoroStart(sync_coro())
    print(f"C extension - done(): {cs_c.done()}")
    print(f"C extension - exception(): {cs_c.exception()}")
    
    # Test Python version  
    cs_py = asynkit.coroutine.PyCoroStart(sync_coro())
    print(f"Python version - done(): {cs_py.done()}")
    print(f"Python version - exception(): {cs_py.exception()}")
    
    print()
    
    # Test 2: Exception completion (should return the exception)
    async def error_coro():
        raise ValueError("test error")
    
    # Test C extension
    cs_c_err = asynkit._cext.CoroStart(error_coro())
    print(f"C extension error - done(): {cs_c_err.done()}")
    exc_c = cs_c_err.exception()
    print(f"C extension error - exception(): {type(exc_c).__name__}: {exc_c}")
    
    # Test Python version
    cs_py_err = asynkit.coroutine.PyCoroStart(error_coro())
    print(f"Python version error - done(): {cs_py_err.done()}")
    exc_py = cs_py_err.exception()
    print(f"Python version error - exception(): {type(exc_py).__name__}: {exc_py}")
    
    print()
    
    # Test 3: Not done (should raise InvalidStateError)
    async def async_coro():
        await asyncio.sleep(0)
        return "never reached"
    
    # Test C extension
    cs_c_async = asynkit._cext.CoroStart(async_coro())
    print(f"C extension async - done(): {cs_c_async.done()}")
    try:
        cs_c_async.exception()
        print("C extension async - ERROR: exception() should have raised!")
    except Exception as e:
        print(f"C extension async - exception() raised: {type(e).__name__}: {e}")
    
    # Test Python version
    cs_py_async = asynkit.coroutine.PyCoroStart(async_coro())
    print(f"Python version async - done(): {cs_py_async.done()}")
    try:
        cs_py_async.exception()
        print("Python version async - ERROR: exception() should have raised!")
    except Exception as e:
        print(f"Python version async - exception() raised: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_exception_method())