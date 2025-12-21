"""
Test for async generator shutdown with eager task factory.

Regression test for issue where asyncio.run() cleanup would crash when
eager task factory is enabled and async generators need cleanup.

The issue: When asyncio.run() exits, it calls shutdown_asyncgens() to clean up
any unclosed async generators. This creates tasks via the task factory. With the
eager task factory enabled, this would fail because the event loop context was
being torn down and get_running_loop() would fail.
"""

import asyncio

import pytest

import asynkit

pytestmark = pytest.mark.anyio


async def simple_async_generator():
    """A simple async generator for testing."""
    yield 1
    yield 2
    yield 3


class TestAsyncGenShutdown:
    """Test async generator cleanup with eager task factory."""

    def test_shutdown_with_non_exhausted_generator(self):
        """Test that non-exhausted generators are cleaned up properly."""

        async def test_func():
            # Enable eager task factory
            loop = asyncio.get_running_loop()
            factory = asynkit.create_eager_task_factory(asyncio.Task)
            loop.set_task_factory(factory)

            # Create generator but don't exhaust it
            gen = simple_async_generator()
            value = await gen.__anext__()
            assert value == 1
            # Intentionally leave generator open
            # This will trigger shutdown_asyncgens() cleanup

        # This should not raise RuntimeError about no running event loop
        asyncio.run(test_func())

    def test_shutdown_with_exhausted_generator(self):
        """Test that exhausted generators are cleaned up properly."""

        async def test_func():
            # Enable eager task factory
            loop = asyncio.get_running_loop()
            factory = asynkit.create_eager_task_factory(asyncio.Task)
            loop.set_task_factory(factory)

            # Create and exhaust generator
            gen = simple_async_generator()
            values = []
            async for value in gen:
                values.append(value)
            assert values == [1, 2, 3]

        # This should not raise RuntimeError about no running event loop
        asyncio.run(test_func())

    def test_shutdown_with_multiple_generators(self):
        """Test cleanup with multiple async generators."""

        async def test_func():
            # Enable eager task factory
            loop = asyncio.get_running_loop()
            factory = asynkit.create_eager_task_factory(asyncio.Task)
            loop.set_task_factory(factory)

            # Create multiple generators, some exhausted, some not
            gen1 = simple_async_generator()
            gen2 = simple_async_generator()
            gen3 = simple_async_generator()

            # Exhaust gen1
            async for _ in gen1:
                pass

            # Partially consume gen2
            await gen2.__anext__()

            # Don't touch gen3 at all

            # All should be cleaned up without error

        # This should not raise RuntimeError about no running event loop
        asyncio.run(test_func())

    async def test_shutdown_with_anyio_backend(self):
        """Test that shutdown works with anyio backend as well."""
        # Enable eager task factory
        loop = asyncio.get_running_loop()
        factory = asynkit.create_eager_task_factory(asyncio.Task)
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create generator but don't exhaust it
            gen = simple_async_generator()
            value = await gen.__anext__()
            assert value == 1
            # Leave generator open - anyio cleanup should handle it
        finally:
            loop.set_task_factory(old_factory)
