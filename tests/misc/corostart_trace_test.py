#!/usr/bin/env python3
"""
Simple trace test for C extension CoroStart behavior in eager task factory.

This test runs just one task with a few sleep operations to trace
exactly what methods are called in the C extension.
"""

import asyncio

import asynkit
import asynkit.coroutine


async def simple_trace_coro():
    """Simple coroutine that does a few sleeps for tracing."""
    print("  [TRACE] Coroutine starting")

    for i in range(3):
        print(f"  [TRACE] About to sleep #{i + 1}")
        await asyncio.sleep(0)
        print(f"  [TRACE] Woke up from sleep #{i + 1}")

    print("  [TRACE] Coroutine finishing")
    return "completed"


async def test_with_c_extension():
    """Test eager task factory with C extension enabled."""
    print("\n=== Testing with C Extension ===")

    # Ensure we're using C extension
    original = asynkit.coroutine.CoroStart
    asynkit.coroutine.CoroStart = asynkit.coroutine._CCoroStart

    try:
        # Set up eager task factory
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(asynkit.eager_task_factory)

        try:
            print("[TRACE] Creating task with eager_task_factory")
            task = asyncio.create_task(simple_trace_coro())

            print("[TRACE] Awaiting task")
            result = await task

            print(f"[TRACE] Task completed with result: {result}")

        finally:
            loop.set_task_factory(old_factory)

    finally:
        asynkit.coroutine.CoroStart = original


async def test_with_python_implementation():
    """Test eager task factory with Python implementation."""
    print("\n=== Testing with Python Implementation ===")

    # Force Python implementation
    original = asynkit.coroutine.CoroStart
    asynkit.coroutine.CoroStart = asynkit.coroutine._PyCoroStart

    try:
        # Set up eager task factory
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(asynkit.eager_task_factory)

        try:
            print("[TRACE] Creating task with eager_task_factory")
            task = asyncio.create_task(simple_trace_coro())

            print("[TRACE] Awaiting task")
            result = await task

            print(f"[TRACE] Task completed with result: {result}")

        finally:
            loop.set_task_factory(old_factory)

    finally:
        asynkit.coroutine.CoroStart = original


async def main():
    """Run both tests for comparison."""
    print("CoroStart C Extension Execution Trace Test")
    print("=" * 50)

    # Test with C extension (should have debug logging)
    await test_with_c_extension()

    # Test with Python implementation (for comparison)
    await test_with_python_implementation()

    print("\n[TRACE] All tests completed")


if __name__ == "__main__":
    asyncio.run(main())
