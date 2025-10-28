#!/usr/bin/env python3
"""
Test keyword argument support for context parameter
"""

import asyncio
import contextvars
import asynkit

# Context variable for testing
test_var = contextvars.ContextVar('test_var')


async def context_test_coro():
    """Simple coroutine to test context"""
    value = test_var.get('default_value')
    await asyncio.sleep(0)
    return f"saw: {value}"


def test_keyword_argument_support():
    """Test different ways to pass context argument"""
    print("=== Testing Keyword Argument Support ===")
    
    # Set up context
    ctx = contextvars.copy_context()
    ctx.run(test_var.set, 'keyword_test_value')
    
    async def run_test():
        # Test 1: Positional argument (should still work)
        print("Test 1: Positional argument")
        try:
            cs1 = asynkit._cext.CoroStart(context_test_coro(), ctx)
            print(f"  Positional context: Created successfully, done={cs1.done()}")
            if cs1.done():
                result = cs1.result()
            else:
                result = await cs1
            print(f"  Result: {result}")
        except Exception as e:
            print(f"  Positional context failed: {e}")
        
        # Test 2: Keyword argument  
        print("\nTest 2: Keyword argument")
        try:
            cs2 = asynkit._cext.CoroStart(context_test_coro(), context=ctx)
            print(f"  Keyword context: Created successfully, done={cs2.done()}")
            if cs2.done():
                result = cs2.result()
            else:
                result = await cs2
            print(f"  Result: {result}")
        except Exception as e:
            print(f"  Keyword context failed: {e}")
        
        # Test 3: No context (should use None)
        print("\nTest 3: No context")
        try:
            cs3 = asynkit._cext.CoroStart(context_test_coro())
            print(f"  No context: Created successfully, done={cs3.done()}")
            if cs3.done():
                result = cs3.result()
            else:
                result = await cs3
            print(f"  Result: {result}")
        except Exception as e:
            print(f"  No context failed: {e}")
        
        # Test 4: Mixed with Python implementation
        print("\nTest 4: Compare with Python implementation")
        try:
            cs_py = asynkit.CoroStart(context_test_coro(), context=ctx)
            print(f"  Python keyword context: Created successfully, done={cs_py.done()}")
            if cs_py.done():
                result = cs_py.result()
            else:
                result = await cs_py
            print(f"  Python result: {result}")
        except Exception as e:
            print(f"  Python keyword context failed: {e}")
    
    asyncio.run(run_test())


async def test_keyword_async():
    """Test keyword arguments in async context"""
    print("\n=== Testing in Async Context ===")
    
    ctx = contextvars.copy_context()
    ctx.run(test_var.set, 'async_keyword_test')
    
    # Test with keyword argument in async function
    cs = asynkit._cext.CoroStart(context_test_coro(), context=ctx)
    
    if not cs.done():
        result = await cs
    else:
        result = cs.result()
        
    print(f"Async keyword test result: {result}")


if __name__ == "__main__":
    test_keyword_argument_support()
    asyncio.run(test_keyword_async())