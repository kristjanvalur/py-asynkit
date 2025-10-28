#!/usr/bin/env python3
"""
Test context support with throw and close methods
"""

import asyncio
import contextvars
import asynkit

# Context variable for testing
test_var = contextvars.ContextVar("test_var")


async def exception_handling_coro():
    """Coroutine that handles exceptions in context"""
    ctx_value = test_var.get("not_set")
    print(f"  Exception handler sees: test_var={ctx_value}")

    try:
        await asyncio.sleep(0)  # Force suspension
        return f"normal completion with {ctx_value}"
    except ValueError as e:
        # Modify context when handling exception
        test_var.set(f"handled_{ctx_value}")
        final_value = test_var.get()
        print(f"  Exception handler modified to: {final_value}")
        return f"exception handled: {e}, context: {final_value}"


async def test_context_with_throw():
    """Test context support with throw method"""
    print("=== Testing Context with Throw Method ===")

    # Set up context
    ctx = contextvars.copy_context()
    ctx.run(test_var.set, "throw_test_value")

    print(f"Context has: {ctx.get(test_var)}")

    # Test C extension with throw
    print("\n--- Testing C extension throw with context ---")
    cs = asynkit._cext.CoroStart(exception_handling_coro(), ctx)

    if not cs.done():
        wrapper = cs.__await__()
        try:
            result = wrapper.throw(ValueError("test exception"))
            print(f"Throw returned: {result}")
        except StopIteration as e:
            print(f"Coroutine completed with: {e.value}")
        except Exception as e:
            print(f"Unexpected exception: {e}")

    print(f"Context after throw: {ctx.get(test_var)}")

    # Test Python implementation for comparison
    print("\n--- Testing Python implementation throw with context ---")
    ctx2 = contextvars.copy_context()
    ctx2.run(test_var.set, "python_throw_test")

    cs_py = asynkit.CoroStart(exception_handling_coro(), context=ctx2)

    if not cs_py.done():
        try:
            result = await cs_py.athrow(ValueError("python test exception"))
            print(f"Python athrow result: {result}")
        except Exception as e:
            print(f"Python athrow failed: {e}")

    print(f"Python context after athrow: {ctx2.get(test_var)}")


async def cleanup_coro():
    """Coroutine that performs cleanup in context"""
    ctx_value = test_var.get("not_set")
    print(f"  Cleanup coro sees: test_var={ctx_value}")

    try:
        await asyncio.sleep(0)
        return f"normal completion with {ctx_value}"
    except GeneratorExit:
        # Perform cleanup and modify context
        test_var.set(f"cleaned_{ctx_value}")
        print(f"  Cleanup performed, context set to: {test_var.get()}")
        raise


async def test_context_with_close():
    """Test context support with close method"""
    print("\n=== Testing Context with Close Method ===")

    # Set up context
    ctx = contextvars.copy_context()
    ctx.run(test_var.set, "close_test_value")

    print(f"Context has: {ctx.get(test_var)}")

    # Test C extension with close
    print("\n--- Testing C extension close with context ---")
    cs = asynkit._cext.CoroStart(cleanup_coro(), ctx)

    if not cs.done():
        wrapper = cs.__await__()
        try:
            result = wrapper.close()
            print(f"Close returned: {result}")
        except Exception as e:
            print(f"Close exception: {e}")

    print(f"Context after close: {ctx.get(test_var)}")


if __name__ == "__main__":
    asyncio.run(test_context_with_throw())
    asyncio.run(test_context_with_close())
