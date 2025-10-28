#!/usr/bin/env python3

import asyncio
import asynkit
from contextvars import ContextVar, copy_context

# Test context variable
test_var = ContextVar("test_var", default="default")


async def test_context_support():
    """Test that context is properly supported in the C extension"""

    async def context_sensitive_coro():
        # Get the context variable value
        value = test_var.get()
        await asyncio.sleep(0)  # Force suspension
        return f"context_value: {value}"

    # Test 1: No context (should use default)
    print("=== Test 1: No context ===")
    cs_c_no_ctx = asynkit._cext.CoroStart(context_sensitive_coro())
    print(f"C extension (no context) done: {cs_c_no_ctx.done()}")
    if cs_c_no_ctx.done():
        result = cs_c_no_ctx.result()
        print(f"C extension (no context): {result}")
    else:
        result = await cs_c_no_ctx
        print(f"C extension (no context): {result}")

    cs_py_no_ctx = asynkit.coroutine.PyCoroStart(context_sensitive_coro())
    print(f"Python version (no context) done: {cs_py_no_ctx.done()}")
    if cs_py_no_ctx.done():
        result = cs_py_no_ctx.result()
        print(f"Python version (no context): {result}")
    else:
        result = await cs_py_no_ctx
        print(f"Python version (no context): {result}")

    print()

    # Test 2: With context
    print("=== Test 2: With context ===")
    ctx = copy_context()
    ctx.run(test_var.set, "custom_value")

    try:
        cs_c_ctx = asynkit._cext.CoroStart(context_sensitive_coro(), ctx)
        print(f"C extension (with context) done: {cs_c_ctx.done()}")
        if cs_c_ctx.done():
            result = cs_c_ctx.result()
            print(f"C extension (with context): {result}")
        else:
            result = await cs_c_ctx
            print(f"C extension (with context): {result}")
    except Exception as e:
        print(f"C extension context test failed: {e}")

    cs_py_ctx = asynkit.CoroStart(context_sensitive_coro(), context=ctx)
    print(f"Python version (with context) done: {cs_py_ctx.done()}")
    if cs_py_ctx.done():
        result = cs_py_ctx.result()
        print(f"Python version (with context): {result}")
    else:
        result = await cs_py_ctx
        print(f"Python version (with context): {result}")


if __name__ == "__main__":
    asyncio.run(test_context_support())
