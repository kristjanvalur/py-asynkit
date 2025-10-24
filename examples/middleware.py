"""
Middleware examples showing different approaches to handling sync/async callables.
These are simplified pseudocode examples for illustration purposes.
See example_middleware_hybrid.py and example_middleware_async.py for complete
working implementations.
"""

import asyncio
from inspect import isawaitable

import asynkit


def process_data(data):
    """Mock data processing function."""
    return f"processed: {data}"


# Hybrid middleware, multiple execution paths
def hybrid_middleware(callable_func):
    """Handle both sync and async callables dynamically."""
    result = callable_func()
    if isawaitable(result):

        async def helper():
            return process_data(await result)

        return helper()
    else:
        return process_data(result)


# Async middleware, assumes everything is async
async def async_middleware(async_callable):
    """Fully async middleware."""
    return process_data(await async_callable())


# Sync middleware, run async middleware in sync mode
def sync_middleware(sync_callable):
    """Convert sync callable to async and process."""

    async def wrapper():
        return process_data(sync_callable())

    return asynkit.await_sync(wrapper())


def test_hybrid_sync():
    """Test hybrid middleware with sync callable."""

    def sync_func():
        return "sync_data"

    result = hybrid_middleware(sync_func)
    expected = "processed: sync_data"
    assert result == expected, f"Expected '{expected}', got {result}"


def test_hybrid_async():
    """Test hybrid middleware with async callable."""

    async def async_func():
        return "async_data"

    async def test():
        result = await hybrid_middleware(async_func)
        expected = "processed: async_data"
        assert result == expected, f"Expected '{expected}', got {result}"

    asyncio.run(test())


def test_async_middleware():
    """Test async middleware."""

    async def async_func():
        return "async_data"

    async def test():
        result = await async_middleware(async_func)
        expected = "processed: async_data"
        assert result == expected, f"Expected '{expected}', got {result}"

    asyncio.run(test())


def test_sync_middleware():
    """Test sync middleware."""

    def sync_func():
        return "sync_data"

    result = sync_middleware(sync_func)
    expected = "processed: sync_data"
    assert result == expected, f"Expected '{expected}', got {result}"


if __name__ == "__main__":
    test_hybrid_sync()
    test_hybrid_async()
    test_async_middleware()
    test_sync_middleware()
    print("All middleware tests passed!")
