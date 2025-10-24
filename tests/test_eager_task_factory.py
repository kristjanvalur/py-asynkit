"""Tests for create_eager_task_factory functionality."""

import asyncio
from unittest.mock import Mock

import pytest

import asynkit


class TestEagerTaskFactory:
    """Test the create_eager_task_factory function."""

    pytestmark = pytest.mark.anyio

    @pytest.fixture
    def anyio_backend(self):
        """Use asyncio backend for these tests."""
        return "asyncio"

    async def test_eager_task_factory_returns_future_when_sync(self):
        """Test that factory returns Future when coroutine completes synchronously."""

        async def sync_coro():
            return "completed_sync"

        # Create our eager task factory
        factory = asynkit.create_eager_task_factory()

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task - should return a Future, not a Task
            result = asyncio.create_task(sync_coro())

            # Check if it's completed immediately (Future behavior)
            assert result.done(), "Expected Future to be completed immediately"
            assert await result == "completed_sync"

            # This should be a Future, not a Task
            # Note: We can't easily distinguish Future from Task in isinstance checks
            # since Task inherits from Future, but we can check if it started eagerly

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_task_factory_returns_task_when_async(self):
        """Test that factory returns Task when coroutine blocks."""

        async def async_coro():
            await asyncio.sleep(0.01)  # Small delay to force async behavior
            return "completed_async"

        # Create our eager task factory
        factory = asynkit.create_eager_task_factory()

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task - should return a Task since it blocks
            result = asyncio.create_task(async_coro())

            # Should not be completed immediately (Task behavior)
            assert not result.done(), "Expected Task to not be completed immediately"

            # Should be a proper Task
            assert isinstance(result, asyncio.Task), "Expected result to be a Task"

            # Should complete when awaited
            assert await result == "completed_async"

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_task_factory_with_previous_factory(self):
        """Test that factory properly delegates to inner factory when coroutine
        blocks."""

        # Mock inner factory
        mock_task = Mock(spec=asyncio.Task)
        mock_task.done.return_value = False

        def mock_factory(loop, coro, **kwargs):
            # Return our mock task with special name
            mock_task.get_name = Mock(return_value="mock_task")
            return mock_task

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Create our eager task factory with the mock as inner factory
        factory = asynkit.create_eager_task_factory(mock_factory)

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task - should use our mock factory for the continuation
            result = asyncio.create_task(async_coro())

            # The result should be our mock task (since coroutine blocks)
            assert result is mock_task, "Expected result to be the mock task"

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_task_factory_with_no_previous_factory(self):
        """Test that factory creates Task directly when no inner factory exists."""

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Ensure no task factory is set initially
        loop = asyncio.get_running_loop()
        loop.set_task_factory(None)

        # Create our eager task factory (should get None as previous)
        factory = asynkit.create_eager_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task - should create asyncio.Task directly
            result = asyncio.create_task(async_coro())

            # Should be a proper Task
            assert isinstance(result, asyncio.Task), "Expected result to be a Task"
            assert not result.done(), "Expected Task to not be completed immediately"

            # Should complete normally
            assert await result == "completed"

        finally:
            loop.set_task_factory(None)

    async def test_eager_task_factory_preserves_kwargs(self):
        """Test that factory preserves kwargs like name when delegating."""

        # Mock factory that records what it receives
        received_kwargs = {}

        def recording_factory(loop, coro, **kwargs):
            received_kwargs.update(kwargs)
            return asyncio.Task(coro, loop=loop, **kwargs)

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Create our eager task factory with the recording factory
        factory = asynkit.create_eager_task_factory(recording_factory)

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task with a name
            result = asyncio.create_task(async_coro(), name="test_task")

            # Wait for completion to ensure our factory was called
            await result

            # Check that kwargs were preserved
            assert "name" in received_kwargs
            assert received_kwargs["name"] == "test_task"

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_task_factory_exception_handling(self):
        """Test that factory handles exceptions properly."""

        async def failing_coro():
            raise ValueError("test error")

        # Create our eager task factory
        factory = asynkit.create_eager_task_factory()

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task that will fail immediately
            result = asyncio.create_task(failing_coro())

            # Should be completed with exception
            assert result.done(), "Expected Future to be completed immediately"

            # Should raise the exception when awaited
            with pytest.raises(ValueError, match="test error"):
                await result

        finally:
            loop.set_task_factory(old_factory)

    async def test_loop_compatibility(self):
        """Test that the event loop doesn't break with mixed return types."""

        async def sync_coro():
            return "sync"

        async def async_coro():
            await asyncio.sleep(0.01)
            return "async"

        # Create our eager task factory
        factory = asynkit.create_eager_task_factory()

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create multiple tasks of different types
            sync_task = asyncio.create_task(sync_coro())
            async_task = asyncio.create_task(async_coro())

            # Both should work with asyncio.gather
            results = await asyncio.gather(sync_task, async_task)
            assert results == ["sync", "async"]

            # Both should work individually
            assert sync_task.done()
            assert await sync_task == "sync"
            assert await async_task == "async"

        finally:
            loop.set_task_factory(old_factory)
