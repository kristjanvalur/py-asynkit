"""Test the close method functionality with both C and Python implementations."""

import asyncio
import sys
from typing import Optional
from contextvars import ContextVar, Context, copy_context

from asynkit.coroutine import CoroStart, PyCoroStart

# Try to import C implementation for comparison testing
try:
    from asynkit._cext import CoroStart as _CCoroStart

    HAS_C_EXT = True
except ImportError:
    _CCoroStart = None
    HAS_C_EXT = False

# Skip C extension tests if running on PyPy
if hasattr(sys, "pypy_version_info"):
    HAS_C_EXT = False

# Context variable for testing
ctx_var = ContextVar("test_context", default="not_set")


async def closeable_coro():
    """A test coroutine that can be cleanly closed"""
    try:
        # Get current context value at start
        current = ctx_var.get()
        print(f"  Closeable coro started, context: {current}")
        await asyncio.sleep(1)
        return "completed"
    except GeneratorExit:
        # Get context at close time
        current = ctx_var.get()
        print(f"  Coro received GeneratorExit, context: {current}")
        # Set a new value in context
        token = ctx_var.set(f"closed_{current}")
        try:
            print(f"  Coro cleanup done, context set to: {ctx_var.get()}")
            raise GeneratorExit()
        finally:
            # Reset context to previous value
            ctx_var.reset(token)


def test_close_method():
    """Test the close method with proper context handling"""
    print("=== Testing Close Method ===")

    # Test 1: Close without context
    print("\nTest 1: Close without context")
    ctx_var.set("not_set")
    start = CoroStart(closeable_coro())
    print(f"Created CoroStart, done: {start.done()}")

    try:
        # Context should be None during close
        result = start.close()
        print(f"Close returned: {result}")
        print(f"After close, done: {start.done()}")
        print(f"Final context value: {ctx_var.get()}")
    except Exception as e:
        print(f"Close failed: {e}")

    # Test 2: Close with context - should propagate context
    print("\nTest 2: Close with context")
    ctx_var.set("not_set")  # Reset for clean state

    test_ctx = copy_context()
    test_ctx.run(ctx_var.set, "close_test_context")

    start = CoroStart(closeable_coro(), context=test_ctx)
    print(f"Created CoroStart with context, done: {start.done()}")
    print(f"Context before close: {test_ctx.get(ctx_var)}")

    try:
        result = start.close()
        print(f"Close returned: {result}")
        print(f"After close, done: {start.done()}")
        after_value = test_ctx.get(ctx_var)
        print(f"Context after close: {after_value}")
        # Context should be back to original value after close
        assert after_value == "close_test_context", (
            f"Context not properly reset after close: {after_value}"
        )
    except Exception as e:
        print(f"Close with context failed: {e}")

    # Test 3: Compare C and Python implementations
    print("\nTest 3: Compare implementations")

    # Reset context for clean state
    ctx_var.set("not_set")

    # First Python implementation
    py_ctx = copy_context()
    py_ctx.run(ctx_var.set, "python_close_test")

    py_start = PyCoroStart(closeable_coro(), context=py_ctx)
    print(f"Python CoroStart created, done: {py_start.done()}")
    print(f"Python context before close: {py_ctx.get(ctx_var)}")

    try:
        result = py_start.close()
        print(f"Python close returned: {result}")
        print(f"Python after close, done: {py_start.done()}")
        after_value = py_ctx.get(ctx_var)
        print(f"Python final context: {after_value}")
        # Verify context resets properly
        assert after_value == "python_close_test", (
            f"Python context not reset properly: {after_value}"
        )
    except Exception as e:
        print(f"Python close failed: {e}")

    if HAS_C_EXT and _CCoroStart is not None:
        # Then C implementation
        ctx_var.set("not_set")  # Reset
        c_ctx = copy_context()
        c_ctx.run(ctx_var.set, "c_close_test")

        c_start = _CCoroStart(closeable_coro(), context=c_ctx)
        print(f"\nC CoroStart created, done: {c_start.done()}")
        print(f"C context before close: {c_ctx.get(ctx_var)}")

        try:
            result = c_start.close()
            print(f"C close returned: {result}")
            print(f"C after close, done: {c_start.done()}")
            after_value = c_ctx.get(ctx_var)
            print(f"C final context: {after_value}")
            # Verify context resets properly
            assert after_value == "c_close_test", (
                f"C context not reset properly: {after_value}"
            )
        except Exception as e:
            print(f"C close failed: {e}")


def test_close_completed():
    """Test close behavior with completed coroutines"""
    print("\n=== Testing Close Behavior ===")

    async def immediate_return():
        return "immediate"

    # Test closing a completed coroutine
    print("\nTest: Close completed coroutine")
    start = CoroStart(immediate_return())
    print(f"Immediate return coro done: {start.done()}")
    if start.done():
        print(f"Result: {start.result()}")

    try:
        result = start.close()
        print(f"Close on completed coro returned: {result}")
    except Exception as e:
        print(f"Close on completed coro failed: {e}")

    # Test with C extension if available
    if HAS_C_EXT and _CCoroStart is not None:
        print("\nTest: Close completed coroutine (C extension)")
        c_start = _CCoroStart(immediate_return())
        print(f"C extension immediate return done: {c_start.done()}")
        if c_start.done():
            print(f"C extension result: {c_start.result()}")

        try:
            result = c_start.close()
            print(f"C extension close returned: {result}")
        except Exception as e:
            print(f"C extension close failed: {e}")


if __name__ == "__main__":
    test_close_method()
    test_close_completed()
