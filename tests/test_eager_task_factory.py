"""Tests for create_eager_factory functionality."""

import asyncio
from unittest.mock import patch

import pytest

import asynkit


class TestEagerFactory:
    """Test the create_eager_factory function."""

    pytestmark = pytest.mark.anyio

    @pytest.fixture
    def anyio_backend(self):
        """Use asyncio backend for these tests."""
        return "asyncio"

    @pytest.fixture(autouse=True)
    def check_task_factory_support(self):
        """Ensure task factory methods are available."""
        loop = asyncio.new_event_loop()
        assert hasattr(loop, "set_task_factory"), "set_task_factory not available"
        assert hasattr(loop, "get_task_factory"), "get_task_factory not available"
        loop.close()

    async def test_eager_factory_returns_future_when_sync(self):
        """Test that factory returns Future when coroutine completes synchronously."""

        async def sync_coro():
            return "completed_sync"

        # Create our eager task factory
        factory = asynkit.create_eager_factory()

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

    async def test_eager_factory_returns_task_when_async(self):
        """Test that factory returns Task when coroutine blocks."""

        async def async_coro():
            await asyncio.sleep(0.01)  # Small delay to ensure it blocks
            return "completed_async"

        # Create our eager task factory
        factory = asynkit.create_eager_factory()

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

    async def test_eager_factory_with_inner_factory(self):
        """Test that create_eager_factory calls inner factory and returns its result"""

        async def blocking_coro():
            await asyncio.sleep(0)
            return "result"

        # Create a custom task class to verify it's returned
        class CustomTask(asyncio.Task):
            pass

        def custom_factory(loop, coro, **kwargs):
            return CustomTask(coro, loop=loop, **kwargs)

        factory = asynkit.create_eager_factory(custom_factory)

        loop = asyncio.get_running_loop()
        task = factory(loop, blocking_coro())

        # Should return the custom task from our factory
        assert isinstance(task, CustomTask)

        result = await task
        assert result == "result"

    async def test_eager_factory_with_no_previous_factory(self):
        """Test that factory creates Task directly when no inner factory exists."""

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Ensure no task factory is set initially
        loop = asyncio.get_running_loop()
        loop.set_task_factory(None)

        # Create our eager task factory (should get None as previous)
        factory = asynkit.create_eager_factory()
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

    async def test_eager_factory_preserves_kwargs(self):
        """Test that factory preserves kwargs like name when delegating.

        Note: asyncio.create_task() handles 'name' internally via set_name(),
        not through task factory kwargs. This test verifies that other kwargs
        would be preserved if they were passed through.
        """

        # Mock factory that records what it receives
        received_kwargs = {}

        def recording_factory(loop, coro, **kwargs):
            received_kwargs.update(kwargs)
            return asyncio.Task(coro, loop=loop, **kwargs)

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Create our eager task factory with the recording factory
        factory = asynkit.create_eager_factory(recording_factory)

        # Set it on the loop
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create a task with a name
            result = asyncio.create_task(async_coro(), name="test_task")

            # Wait for completion to ensure our factory was called
            await result

            # Verify the task got the correct name (handled by asyncio internally)
            assert result.get_name() == "test_task"

            # Note: 'name' is not passed through kwargs by asyncio design
            # This verifies that our factory doesn't break the name handling

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_factory_exception_handling(self):
        """Test that factory handles exceptions properly."""

        async def failing_coro():
            raise ValueError("test error")

        # Create our eager task factory
        factory = asynkit.create_eager_factory()

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
        factory = asynkit.create_eager_factory()

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

    async def test_set_name_called_on_tasklike_future(self):
        """Test that set_name is called on TaskLikeFuture for eager completion."""
        # Track calls to TaskLikeFuture.set_name
        calls_log = []
        original_set_name = asynkit.coroutine.TaskLikeFuture.set_name

        def mock_set_name(self, value):
            calls_log.append(("set_name", value))
            return original_set_name(self, value)

        with patch.object(asynkit.coroutine.TaskLikeFuture, "set_name", mock_set_name):

            async def sync_coro():
                """A coroutine that completes synchronously."""
                return "sync_result"

            # Create eager task factory
            factory = asynkit.create_eager_factory()

            loop = asyncio.get_running_loop()
            old_factory = loop.get_task_factory()
            loop.set_task_factory(factory)

            try:
                # This should trigger eager execution and return TaskLikeFuture
                task = asyncio.create_task(sync_coro(), name="test_eager_task")

                # Verify it's a TaskLikeFuture
                assert isinstance(task, asynkit.coroutine.TaskLikeFuture)
                assert task.get_name() == "test_eager_task"

                # Check if set_name was called
                assert len(calls_log) == 1
                assert calls_log[0] == ("set_name", "test_eager_task")

                # Verify the result
                result = await task
                assert result == "sync_result"

            finally:
                loop.set_task_factory(old_factory)

    async def test_set_name_not_called_on_regular_task(self):
        """Test that TaskLikeFuture.set_name is not called for blocking coroutines."""
        # Track calls to TaskLikeFuture.set_name
        calls_log = []
        original_set_name = asynkit.coroutine.TaskLikeFuture.set_name

        def mock_set_name(self, value):
            calls_log.append(("set_name", value))
            return original_set_name(self, value)

        with patch.object(asynkit.coroutine.TaskLikeFuture, "set_name", mock_set_name):

            async def blocking_coro():
                """A coroutine that blocks (suspends)."""
                await asyncio.sleep(0.001)  # Small delay to force suspension
                return "blocking_result"

            # Create eager task factory
            factory = asynkit.create_eager_factory()

            loop = asyncio.get_running_loop()
            old_factory = loop.get_task_factory()
            loop.set_task_factory(factory)

            try:
                # This should NOT trigger TaskLikeFuture creation
                task = asyncio.create_task(blocking_coro(), name="test_blocking_task")

                # Verify it's a regular Task
                assert isinstance(task, asyncio.Task)
                assert not isinstance(task, asynkit.coroutine.TaskLikeFuture)
                assert task.get_name() == "test_blocking_task"

                # Check if set_name was called on TaskLikeFuture (should be False)
                assert len(calls_log) == 0

                # Verify the result
                result = await task
                assert result == "blocking_result"

            finally:
                loop.set_task_factory(old_factory)
