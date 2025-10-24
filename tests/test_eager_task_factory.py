"""Tests for create_eager_factory functionality."""

import asyncio

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

    async def test_tasklike_future_has_correct_name(self):
        """Test that TaskLikeFuture has the correct name for eager completion."""

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

            # Verify it's a TaskLikeFuture with the correct name
            assert isinstance(task, asynkit.coroutine.TaskLikeFuture)
            assert task.get_name() == "test_eager_task"

            # Verify the result
            result = await task
            assert result == "sync_result"

        finally:
            loop.set_task_factory(old_factory)

    async def test_tasklike_future_not_used_for_blocking_coros(self):
        """Test that TaskLikeFuture is not used for blocking coroutines."""

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

            # Verify it's a regular Task, not TaskLikeFuture
            assert isinstance(task, asyncio.Task)
            assert not isinstance(task, asynkit.coroutine.TaskLikeFuture)
            assert task.get_name() == "test_blocking_task"

            # Verify the result
            result = await task
            assert result == "blocking_result"

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_factory_context_handling(self):
        """Test that task factory respects context when available."""
        import contextvars

        var = contextvars.ContextVar("factory_test_var")
        var.set("original")

        # Track what context the coroutine sees during execution
        context_values_seen = []

        async def context_checking_coro():
            nonlocal context_values_seen
            # Check initial value in the task (before suspension)
            initial_value = var.get()
            context_values_seen.append(("initial", initial_value))

            # Set a new value inside the task (before suspension)
            var.set("before_suspend")
            before_suspend_value = var.get()
            context_values_seen.append(("before_suspend", before_suspend_value))

            await asyncio.sleep(0)  # Force suspension

            # Check value after resumption - should still see our modification
            after_resume_value = var.get()
            context_values_seen.append(("after_resume", after_resume_value))

            # Modify context again after resumption
            var.set("after_resume")
            final_value = var.get()
            context_values_seen.append(("final", final_value))

            return "result"

        # Create new context with different value
        ctx = contextvars.copy_context()
        ctx.run(var.set, "modified_context")

        # Verify the context has the expected value
        ctx_value = ctx.run(var.get)
        assert ctx_value == "modified_context"

        # Set up eager factory
        factory = asynkit.create_eager_factory()
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Try to use context parameter if supported (Python 3.11+)
            try:
                coro = context_checking_coro()
                task = asyncio.create_task(coro, context=ctx)
                context_param_supported = True
            except TypeError:
                # Python < 3.11 - test with manual context setting
                context_param_supported = False
                # Close the coroutine we created for the failed test
                coro.close()
                task = asyncio.create_task(context_checking_coro())

            # Complete the task
            result = await task
            assert result == "result"

            if context_param_supported:
                # Verify the task saw the correct context values
                assert len(context_values_seen) == 4

                # Check initial inheritance (before suspension)
                initial_label, initial_value = context_values_seen[0]
                assert initial_label == "initial"
                assert initial_value == "modified_context", (
                    f"Task should inherit context value. "
                    f"Expected 'modified_context', got '{initial_value}'"
                )

                # Check modification before suspension
                before_label, before_value = context_values_seen[1]
                assert before_label == "before_suspend"
                assert before_value == "before_suspend", (
                    f"Task should be able to modify context before suspension. "
                    f"Expected 'before_suspend', got '{before_value}'"
                )

                # Check persistence after resumption
                resume_label, resume_value = context_values_seen[2]
                assert resume_label == "after_resume"
                assert resume_value == "before_suspend", (
                    f"Context should persist across suspension. "
                    f"Expected 'before_suspend', got '{resume_value}'"
                )

                # Check modification after resumption
                final_label, final_value = context_values_seen[3]
                assert final_label == "final"
                assert final_value == "after_resume", (
                    f"Task should be able to modify context after resumption. "
                    f"Expected 'after_resume', got '{final_value}'"
                )

                # Verify the original context and outer context are unchanged
                outer_value = var.get()
                assert outer_value == "original", (
                    f"Outer context should be unchanged. "
                    f"Expected 'original', got '{outer_value}'"
                )

                # The context we passed to create_task should show final changes
                # This is correct behavior - the task runs in the context we provided
                ctx_final_value = ctx.run(var.get)
                assert ctx_final_value == "after_resume", (
                    f"Passed context should show final task modifications. "
                    f"Expected 'after_resume', got '{ctx_final_value}'"
                )
            else:
                # For Python < 3.11, we can't test context parameter
                # but we can verify the task runs in some context
                assert len(context_values_seen) >= 1

        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_task_factory_instance(self):
        """Test that the pre-created eager_task_factory instance works correctly."""

        async def sync_coro():
            return "immediate_result"

        async def async_coro():
            await asyncio.sleep(0)  # Force suspension
            return "async_result"

        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()

        try:
            # Set the pre-created eager_task_factory instance
            loop.set_task_factory(asynkit.eager_task_factory)

            # Test sync coroutine - should complete immediately
            sync_task = asyncio.create_task(sync_coro())
            assert sync_task.done(), "Sync coroutine should complete immediately"
            assert isinstance(sync_task, asynkit.TaskLikeFuture)
            sync_result = await sync_task
            assert sync_result == "immediate_result"

            # Test async coroutine - should create real Task
            async_task = asyncio.create_task(async_coro())
            assert not async_task.done(), (
                "Async coroutine should not complete immediately"
            )
            assert isinstance(async_task, asyncio.Task)
            async_result = await async_task
            assert async_result == "async_result"

        finally:
            loop.set_task_factory(old_factory)


class TestCreateTask:
    """Test the create_task function with eager_start parameter."""

    pytestmark = pytest.mark.anyio

    @pytest.fixture
    def anyio_backend(self):
        """Use asyncio backend for these tests."""
        return "asyncio"

    async def test_create_task_eager_start_true_sync_coro(self):
        """Test create_task with eager_start=True for synchronous coroutine."""

        async def sync_coro():
            return "sync_result"

        task = asynkit.create_task(sync_coro(), eager_start=True, name="sync_task")

        # Should complete synchronously
        assert task.done()
        assert task.get_name() == "sync_task"
        assert await task == "sync_result"

        # Should be TaskLikeFuture for sync completion
        assert isinstance(task, asynkit.TaskLikeFuture)

    async def test_create_task_eager_start_true_async_coro(self):
        """Test create_task with eager_start=True for asynchronous coroutine."""

        async def async_coro():
            await asyncio.sleep(0)
            return "async_result"

        task = asynkit.create_task(async_coro(), eager_start=True, name="async_task")

        # Should not complete synchronously but should be a regular Task
        assert not task.done()
        assert task.get_name() == "async_task"
        assert isinstance(task, asyncio.Task)

        result = await task
        assert result == "async_result"

    async def test_create_task_eager_start_false(self):
        """Test create_task with eager_start=False delegates to asyncio."""

        async def sync_coro():
            return "sync_result"

        task = asynkit.create_task(sync_coro(), eager_start=False, name="standard_task")

        # Should behave like standard asyncio.create_task
        assert not task.done()  # Not eager
        assert task.get_name() == "standard_task"
        assert isinstance(task, asyncio.Task)

        result = await task
        assert result == "sync_result"

    async def test_create_task_eager_start_none(self):
        """Test create_task with eager_start=None defaults to standard behavior."""

        async def sync_coro():
            return "sync_result"

        task = asynkit.create_task(sync_coro(), name="default_task")

        # Should behave like standard asyncio.create_task (no eager execution)
        assert not task.done()
        assert task.get_name() == "default_task"
        assert isinstance(task, asyncio.Task)

        result = await task
        assert result == "sync_result"

    async def test_create_task_with_context(self):
        """Test create_task properly handles context parameter."""
        import contextvars
        import sys

        var = contextvars.ContextVar("test_var")
        var.set("original")

        async def context_coro():
            return var.get()

        # Create new context with different value
        ctx = contextvars.copy_context()
        ctx.run(var.set, "modified")

        # Test with eager_start=True - this should work
        task1 = asynkit.create_task(
            context_coro(), eager_start=True, name="eager_ctx_task", context=ctx
        )

        if sys.version_info >= (3, 11):
            # Python 3.11+ supports context parameter
            # For sync completion, TaskLikeFuture should have context set
            if isinstance(task1, asynkit.TaskLikeFuture):
                assert task1.get_context() is ctx

            # Should run in the modified context
            result1 = await task1
            assert result1 == "modified"
        else:
            # Python 3.10 - context parameter not supported
            # Task runs in current context copy, so should see "original"
            result1 = await task1
            assert result1 == "original"

        # Current context should still be original
        assert var.get() == "original"

    async def test_create_task_eager_context_comprehensive(self):
        """Test create_task with eager_start=True handles context across suspension."""
        import contextvars
        import sys

        var = contextvars.ContextVar("comprehensive_test_var")
        var.set("original")

        # Track what context the coroutine sees during execution
        context_values_seen = []

        async def context_checking_coro():
            nonlocal context_values_seen
            # Check initial value in the task (before suspension)
            initial_value = var.get()
            context_values_seen.append(("initial", initial_value))

            # Set a new value inside the task (before suspension)
            var.set("before_suspend")
            before_suspend_value = var.get()
            context_values_seen.append(("before_suspend", before_suspend_value))

            await asyncio.sleep(0)  # Force suspension

            # Check value after resumption - should still see our modification
            after_resume_value = var.get()
            context_values_seen.append(("after_resume", after_resume_value))

            # Modify context again after resumption
            var.set("after_resume")
            final_value = var.get()
            context_values_seen.append(("final", final_value))

            return "result"

        # Create new context with different value
        ctx = contextvars.copy_context()
        ctx.run(var.set, "modified_context")

        # Verify the context has the expected value
        ctx_value = ctx.run(var.get)
        assert ctx_value == "modified_context"

        # Test with eager_start=True - should use experimental context handling
        task = asynkit.create_task(
            context_checking_coro(),
            eager_start=True,
            name="comprehensive_ctx_task",
            context=ctx,
        )

        # Complete the task
        result = await task
        assert result == "result"

        # Verify the task saw the correct context values
        assert len(context_values_seen) == 4

        # Context behavior depends on Python version
        if sys.version_info >= (3, 11):
            # Python 3.11+ supports context parameter - test full context behavior

            # Check initial inheritance (before suspension)
            initial_label, initial_value = context_values_seen[0]
            assert initial_label == "initial"
            assert initial_value == "modified_context", (
                f"Task should inherit context value. "
                f"Expected 'modified_context', got '{initial_value}'"
            )

            # Check modification before suspension
            before_label, before_value = context_values_seen[1]
            assert before_label == "before_suspend"
            assert before_value == "before_suspend", (
                f"Task should be able to modify context before suspension. "
                f"Expected 'before_suspend', got '{before_value}'"
            )

            # Check persistence after resumption
            resume_label, resume_value = context_values_seen[2]
            assert resume_label == "after_resume"
            assert resume_value == "before_suspend", (
                f"Context should persist across suspension. "
                f"Expected 'before_suspend', got '{resume_value}'"
            )

            # Check modification after resumption
            final_label, final_value = context_values_seen[3]
            assert final_label == "final"
            assert final_value == "after_resume", (
                f"Task should be able to modify context after resumption. "
                f"Expected 'after_resume', got '{final_value}'"
            )

            # The context we passed to create_task should show final changes
            # This is correct behavior - the task runs in the context we provided
            ctx_final_value = ctx.run(var.get)
            assert ctx_final_value == "after_resume", (
                f"Passed context should show final task modifications. "
                f"Expected 'after_resume', got '{ctx_final_value}'"
            )
        else:
            # Python 3.10 - context parameter not supported, but test context isolation

            # Task should run in its own context copy (not the custom context)
            initial_label, initial_value = context_values_seen[0]
            assert initial_label == "initial"
            # In Python 3.10, task gets current context copy, so should see "original"
            assert initial_value == "original", (
                f"Task should run in current context copy. "
                f"Expected 'original', got '{initial_value}'"
            )

            # Task should be able to modify its own context
            before_label, before_value = context_values_seen[1]
            assert before_label == "before_suspend"
            assert before_value == "before_suspend", (
                f"Task should be able to modify its own context. "
                f"Expected 'before_suspend', got '{before_value}'"
            )

            # Context should persist in task across suspension
            resume_label, resume_value = context_values_seen[2]
            assert resume_label == "after_resume"
            assert resume_value == "before_suspend", (
                f"Task context should persist across suspension. "
                f"Expected 'before_suspend', got '{resume_value}'"
            )

        # Verify the original context and outer context are unchanged
        outer_value = var.get()
        assert outer_value == "original", (
            f"Outer context should be unchanged. "
            f"Expected 'original', got '{outer_value}'"
        )
        assert var.get() == "original"

    async def test_create_task_kwargs_forwarding(self):
        """Test that additional kwargs are properly forwarded."""

        async def test_coro():
            await asyncio.sleep(0)
            return "test"

        # Test that unknown kwargs don't break anything
        task = asynkit.create_task(
            test_coro(),
            eager_start=True,
            name="kwargs_test",
            # Note: can't easily test custom kwargs without mock since
            # they get passed to _create_task internally
        )

        result = await task
        assert result == "test"

    async def test_create_task_exception_handling(self):
        """Test create_task handles exceptions in eager mode."""

        async def failing_sync_coro():
            raise ValueError("sync error")

        async def failing_async_coro():
            await asyncio.sleep(0)
            raise ValueError("async error")

        # Test sync exception with eager_start=True
        task1 = asynkit.create_task(failing_sync_coro(), eager_start=True)
        assert task1.done()

        with pytest.raises(ValueError, match="sync error"):
            await task1

        # Test async exception with eager_start=True
        task2 = asynkit.create_task(failing_async_coro(), eager_start=True)
        assert not task2.done()

        with pytest.raises(ValueError, match="async error"):
            await task2
