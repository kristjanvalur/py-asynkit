#!/usr/bin/env python3
"""
Comprehensive test for context isolation and modification
"""

import asyncio
import contextvars
import asynkit

# Create context variables for testing
test_var = contextvars.ContextVar('test_var')
counter_var = contextvars.ContextVar('counter_var', default=0)


async def context_modifying_coro():
    """Coroutine that modifies context variables"""
    initial = test_var.get('not_set')
    count = counter_var.get()
    
    print(f"  Coro sees: test_var={initial}, counter={count}")
    
    # Modify context variables
    test_var.set(f'modified_from_{initial}')
    counter_var.set(count + 1)
    
    await asyncio.sleep(0)  # Force suspension
    
    # Check values after suspension
    final_test = test_var.get('not_set')
    final_count = counter_var.get()
    
    print(f"  Coro after sleep: test_var={final_test}, counter={final_count}")
    return f"final: {final_test}, count: {final_count}"


async def test_context_isolation():
    """Test that contexts are properly isolated"""
    print("=== Testing Context Isolation ===")
    
    # Set main context values
    test_var.set('main_value')
    counter_var.set(100)
    
    print(f"Main context: test_var={test_var.get()}, counter={counter_var.get()}")
    
    # Create separate context
    ctx1 = contextvars.copy_context()
    ctx1.run(test_var.set, 'ctx1_value')
    ctx1.run(counter_var.set, 10)
    
    ctx2 = contextvars.copy_context()
    ctx2.run(test_var.set, 'ctx2_value')
    ctx2.run(counter_var.set, 20)
    
    print(f"Context 1: test_var={ctx1.get(test_var)}, counter={ctx1.get(counter_var)}")
    print(f"Context 2: test_var={ctx2.get(test_var)}, counter={ctx2.get(counter_var)}")
    
    # Test C extension with different contexts
    print("\n--- Testing C extension context isolation ---")
    
    print("Testing with context 1:")
    cs1 = asynkit._cext.CoroStart(context_modifying_coro(), ctx1)
    if not cs1.done():
        result1 = await cs1
    else:
        result1 = cs1.result()
    print(f"  Result: {result1}")
    
    print("Testing with context 2:")
    cs2 = asynkit._cext.CoroStart(context_modifying_coro(), ctx2)
    if not cs2.done():
        result2 = await cs2
    else:
        result2 = cs2.result()
    print(f"  Result: {result2}")
    
    # Check that main context is unchanged
    print(f"\nMain context after tests: test_var={test_var.get()}, counter={counter_var.get()}")
    
    # Check that contexts were modified
    print(f"Context 1 after: test_var={ctx1.get(test_var)}, counter={ctx1.get(counter_var)}")
    print(f"Context 2 after: test_var={ctx2.get(test_var)}, counter={ctx2.get(counter_var)}")
    
    # Test Python implementation for comparison
    print("\n--- Testing Python implementation for comparison ---")
    
    ctx3 = contextvars.copy_context()
    ctx3.run(test_var.set, 'ctx3_value')
    ctx3.run(counter_var.set, 30)
    
    print("Testing Python CoroStart with context 3:")
    cs3 = asynkit.CoroStart(context_modifying_coro(), context=ctx3)
    if not cs3.done():
        result3 = await cs3
    else:
        result3 = cs3.result()
    print(f"  Python result: {result3}")
    
    print(f"Context 3 after Python test: test_var={ctx3.get(test_var)}, counter={ctx3.get(counter_var)}")


if __name__ == "__main__":
    asyncio.run(test_context_isolation())