"""Tests for eager_task_factory functionality."""

import asyncio

import pytest

import asynkit


@pytest.fixture
def eager_loop():
    """Fixture providing an event loop with eager task factory.

    Note: We still need manual loop management here (not asyncio.run()) because
    these tests specifically use loop.run_until_complete() to test the initial
    task behavior - the very thing we're regression testing.
    """
    loop = asyncio.new_event_loop()
    loop.set_task_factory(asynkit.eager_task_factory)
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        asyncio.set_event_loop(None)
        loop.close()


@pytest.fixture
def asyncio_run_eager():
    """Fixture that provides asyncio.run with eager task factory.

    Yields asyncio.run with a custom event loop policy that installs
    eager task factory on new loops. This tests the modern asyncio.run()
    pattern with eager execution.
    """
    original_policy = asyncio.get_event_loop_policy()

    # Create a custom policy that installs eager task factory
    class EagerPolicy(type(original_policy)):
        def new_event_loop(self):
            loop = super().new_event_loop()
            loop.set_task_factory(asynkit.eager_task_factory)
            return loop

    policy = EagerPolicy()
    asyncio.set_event_loop_policy(policy)
    try:
        yield asyncio.run
    finally:
        asyncio.set_event_loop_policy(original_policy)


class TestEagerFactory:
    """Test the create_eager_task_factory function."""

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

    @pytest.fixture
    async def eager_factory(self):
        """fixture setting up eager task factory"""
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(asynkit.eager_task_factory)
        try:
            yield asynkit.eager_task_factory
        finally:
            loop.set_task_factory(old_factory)

    async def test_eager_factory_returns_future_when_sync(self, eager_factory):
        """Test that factory returns Future when coroutine completes synchronously."""

        async def sync_coro():
            return "completed_sync"

        # Create a task - should return a Future, not a Task
        result = asyncio.create_task(sync_coro())

        # Check if it's completed immediately (Future behavior)
        assert result.done(), "Expected Future to be completed immediately"
        assert await result == "completed_sync"

        # This should be a Future, not a Task
        # Note: We can't easily distinguish Future from Task in isinstance checks
        # since Task inherits from Future, but we can check if it started eagerly

    async def test_eager_factory_returns_task_when_async(self, eager_factory):
        """Test that factory returns Task when coroutine blocks."""

        async def async_coro():
            await asyncio.sleep(0.01)  # Small delay to ensure it blocks
            return "completed_async"

        # Create a task - should return a Task since it blocks
        result = asyncio.create_task(async_coro())

        # Should not be completed immediately (Task behavior)
        assert not result.done(), "Expected Task to not be completed immediately"

        # Should be a proper Task
        assert isinstance(result, asyncio.Task), "Expected result to be a Task"

        # Should complete when awaited
        assert await result == "completed_async"

    async def test_eager_task_factory_with_custom_task(self):
        """Test that create_eager_task_factory uses custom task constructor"""

        async def blocking_coro():
            await asyncio.sleep(0)
            return "result"

        # Create a custom task class to verify it's returned
        class CustomTask(asyncio.Task):
            pass

        def custom_task_constructor(coro, loop=None, **kwargs):
            return CustomTask(coro, loop=loop, **kwargs)

        factory = asynkit.create_eager_task_factory(custom_task_constructor)

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
        factory = asynkit.eager_task_factory
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

        def recording_task_constructor(coro, loop=None, **kwargs):
            received_kwargs.update(kwargs)
            return asyncio.Task(coro, loop=loop, **kwargs)

        async def async_coro():
            await asyncio.sleep(0.01)
            return "completed"

        # Create our eager task factory with the recording constructor
        factory = asynkit.create_eager_task_factory(recording_task_constructor)

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

    async def test_eager_factory_exception_handling(self, eager_factory):
        """Test that factory handles exceptions properly."""

        async def failing_coro():
            raise ValueError("test error")

        # Create a task that will fail immediately
        result = asyncio.create_task(failing_coro())

        # Should be completed with exception
        assert result.done(), "Expected Future to be completed immediately"

        # Should raise the exception when awaited
        with pytest.raises(ValueError, match="test error"):
            await result

    async def test_loop_compatibility(self, eager_factory):
        """Test that the event loop doesn't break with mixed return types."""

        async def sync_coro():
            return "sync"

        async def async_coro():
            await asyncio.sleep(0.01)
            return "async"

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

    async def test_tasklike_future_has_correct_name(self, eager_factory):
        """Test that TaskLikeFuture has the correct name for eager completion."""

        async def sync_coro():
            """A coroutine that completes synchronously."""
            return "sync_result"

        # This should trigger eager execution and return TaskLikeFuture
        task = asyncio.create_task(sync_coro(), name="test_eager_task")

        # Verify it's a TaskLikeFuture with the correct name
        assert isinstance(task, asynkit.coroutine.TaskLikeFuture)
        assert task.get_name() == "test_eager_task"

        # Verify the result
        result = await task
        assert result == "sync_result"

    async def test_tasklike_future_not_used_for_blocking_coros(self, eager_factory):
        """Test that TaskLikeFuture is not used for blocking coroutines."""

        async def blocking_coro():
            """A coroutine that blocks (suspends)."""
            await asyncio.sleep(0.001)  # Small delay to force suspension
            return "blocking_result"

        # This should NOT trigger TaskLikeFuture creation
        task = asyncio.create_task(blocking_coro(), name="test_blocking_task")

        # Verify it's a regular Task, not TaskLikeFuture
        assert isinstance(task, asyncio.Task)
        assert not isinstance(task, asynkit.coroutine.TaskLikeFuture)
        assert task.get_name() == "test_blocking_task"

        # Verify the result
        result = await task
        assert result == "blocking_result"

    async def test_eager_factory_context_handling(self, eager_factory):
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

    async def test_eager_task_factory_instance(self, eager_factory):
        """Test that the pre-created eager_task_factory instance works correctly."""

        async def sync_coro():
            return "immediate_result"

        async def async_coro():
            await asyncio.sleep(0)  # Force suspension
            return "async_result"

        # Test sync coroutine - should complete immediately
        sync_task = asyncio.create_task(sync_coro())
        assert sync_task.done(), "Sync coroutine should complete immediately"
        assert isinstance(sync_task, asynkit.TaskLikeFuture)
        sync_result = await sync_task
        assert sync_result == "immediate_result"

        # Test async coroutine - should create real Task
        async_task = asyncio.create_task(async_coro())
        assert not async_task.done(), "Async coroutine should not complete immediately"
        assert isinstance(async_task, asyncio.Task)
        async_result = await async_task
        assert async_result == "async_result"

    async def test_wait_for(self, eager_factory):
        """Test that eager task factory works with asyncio.wait_for().

        Unlike asyncio.timeout(), wait_for() does not schedule a cancel() for a task
        but scheduls a cancel for a future.
        """
        eager = 0

        async def operation_timeout():
            """Operation that times out."""
            nonlocal eager
            eager = 1
            await asyncio.sleep(0.1)  # Should cause timeout
            return "completed"

        async def operation_fast():
            """Operation that completes before timeout."""
            nonlocal eager
            eager = 2
            return "fast_result"

        # Test operation that times out
        task = asyncio.create_task(operation_timeout())
        assert eager == 1, "Eager task factory did not run eagerly"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0)

        # Test operation that completes synchronously
        task = asyncio.create_task(operation_fast())
        assert eager == 2, "Eager task factory did not run eagerly"
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result == "fast_result"

    async def test_wait_for_zero_timeout(self, eager_factory):
        """Test wait_for with zero timeout on eager tasks."""
        eager_ran = False

        async def immediate_operation():
            """Operation that completes synchronously."""
            nonlocal eager_ran
            eager_ran = True
            return "immediate"

        async def blocking_operation():
            """Operation that blocks."""
            nonlocal eager_ran
            eager_ran = True
            await asyncio.sleep(0.1)
            return "blocked"

        # Test immediate completion with zero timeout
        task = asyncio.create_task(immediate_operation())
        assert eager_ran, "Eager execution should have run"
        # Should complete before timeout fires
        result = await asyncio.wait_for(task, timeout=0)
        assert result == "immediate"

        # Test blocking operation with zero timeout
        eager_ran = False
        task = asyncio.create_task(blocking_operation())
        assert eager_ran, "Eager execution should have run"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0)


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

    async def test_ghost_task_context_when_no_current_task(self):
        """Test that ghost task provides context when creating eager task without current task."""
        from asynkit.compat import swap_current_task

        # Track the current_task context during different phases
        context_states = []

        async def context_checking_coro():
            """Coroutine that records current_task at different execution points."""
            # Record initial current_task (should be ghost task during eager execution)
            initial_task = asyncio.current_task()
            context_states.append(("initial", initial_task))

            # Suspend to force creation of real task
            await asyncio.sleep(0)

            # Record current_task after suspension (should be real task)
            resumed_task = asyncio.current_task()
            context_states.append(("resumed", resumed_task))

            return "completed"

        # Get current context - should have a running task
        loop = asyncio.get_running_loop()
        original_task = asyncio.current_task()
        assert original_task is not None, "Test should run within a task context"

        # Set up eager task factory
        factory = asynkit.eager_task_factory
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Clear current task context using swap_current_task to simulate no-task context
            old_current_task = swap_current_task(loop, None)

            try:
                # Verify we have no current task
                no_task = asyncio.current_task()
                assert no_task is None, "Should have no current task after swap"

                # Create eager task in no-task context - should use ghost task
                task = asyncio.create_task(context_checking_coro())

                # Restore original task context
                swap_current_task(loop, old_current_task)

                # Wait for task completion
                result = await task
                assert result == "completed"

                # Verify we recorded the expected context states
                assert len(context_states) == 2, (
                    f"Expected 2 context states, got {len(context_states)}"
                )

                initial_label, initial_task = context_states[0]
                resumed_label, resumed_task = context_states[1]

                assert initial_label == "initial"
                assert resumed_label == "resumed"

                # Initial execution should have had a ghost task (not None)
                assert initial_task is not None, (
                    "Initial execution should have ghost task context"
                )

                # Resumed execution should have the real task
                assert resumed_task is not None, (
                    "Resumed execution should have real task context"
                )
                assert resumed_task is task, (
                    "Resumed context should be the actual task we created"
                )

                # Ghost task should be different from the real task
                assert initial_task is not resumed_task, (
                    "Ghost task should be different from real task. "
                    f"Ghost: {initial_task}, Real: {resumed_task}"
                )

                # Ghost task should be different from original task
                assert initial_task is not original_task, (
                    "Ghost task should be different from original task. "
                    f"Ghost: {initial_task}, Original: {original_task}"
                )

            finally:
                # Ensure we restore task context even if test fails
                swap_current_task(loop, old_current_task)

        finally:
            loop.set_task_factory(old_factory)


class TestEagerFactoryShutdown:
    """Test eager task factory behavior during event loop shutdown.

    These tests verify that the eager task factory correctly handles async generator
    cleanup during event loop shutdown. This is a regression test for an issue where
    shutdown_asyncgens() would crash when calling get_running_loop() from the task
    factory while the loop was shutting down.
    """

    def test_shutdown_with_non_exhausted_async_generator(self, eager_loop):
        """Test that eager task factory handles shutdown with non-exhausted async generators.

        This is a regression test for an issue where asyncio.run() shutdown would crash
        when using eager task factory. During shutdown, asyncio calls shutdown_asyncgens()
        which creates tasks via the task factory, but get_running_loop() fails because
        the loop is shutting down.
        """

        async def simple_async_generator():
            yield 1
            yield 2
            yield 3

        async def test_without_exhausting():
            # Create and use async generator without exhausting it
            gen = simple_async_generator()
            first_value = await gen.__anext__()
            assert first_value == 1
            # Don't exhaust the generator - leave it open
            # This will trigger asyncio shutdown_asyncgens() during asyncio.run() cleanup

        # This should not raise RuntimeError about no running event loop
        eager_loop.run_until_complete(test_without_exhausting())
        # Cleanup - this is where shutdown_asyncgens() is called
        eager_loop.run_until_complete(eager_loop.shutdown_asyncgens())

    def test_shutdown_with_exhausted_async_generator(self, eager_loop):
        """Test that eager task factory handles shutdown with exhausted async generators."""

        async def simple_async_generator():
            yield 1
            yield 2

        async def test_with_exhausting():
            # Create and fully exhaust async generator
            gen = simple_async_generator()
            values = []
            async for value in gen:
                values.append(value)
            assert values == [1, 2]

        # This should also not raise during shutdown
        eager_loop.run_until_complete(test_with_exhausting())
        eager_loop.run_until_complete(eager_loop.shutdown_asyncgens())

    def test_shutdown_with_multiple_async_generators(self, eager_loop):
        """Test shutdown with multiple non-exhausted async generators."""

        async def generator_a():
            yield "a1"
            yield "a2"

        async def generator_b():
            yield "b1"
            yield "b2"

        async def test_multiple():
            gen_a = generator_a()
            gen_b = generator_b()

            # Use both generators without exhausting them
            val_a = await gen_a.__anext__()
            val_b = await gen_b.__anext__()

            assert val_a == "a1"
            assert val_b == "b1"
            # Leave both generators open

        eager_loop.run_until_complete(test_multiple())
        eager_loop.run_until_complete(eager_loop.shutdown_asyncgens())


class TestEagerFactoryInitialTaskRegression:
    """Regression tests for eager task factory behavior with initial tasks.

    These tests verify that code requiring a running event loop (like
    asyncio.current_task() or get_running_loop()) works correctly even
    during eager execution of the initial task passed to run_until_complete()
    or asyncio.run().
    """

    @pytest.mark.parametrize("runner_fixture", ["eager_loop", "asyncio_run_eager"])
    def test_get_running_loop_in_initial_task(self, runner_fixture, request):
        """Test that get_running_loop() works in eagerly executed initial task.

        Regression test: When run_until_complete() or asyncio.run() creates
        the initial task, if eager execution starts the coroutine during task
        factory time, get_running_loop() may fail because the loop hasn't set
        itself as running in TLS yet.
        """

        async def coro_needing_loop():
            loop = asyncio.get_running_loop()
            assert loop is not None
            return "completed"

        runner = request.getfixturevalue(runner_fixture)
        if runner_fixture == "eager_loop":
            result = runner.run_until_complete(coro_needing_loop())
        else:  # asyncio_run_eager
            result = runner(coro_needing_loop())
        assert result == "completed"

    @pytest.mark.parametrize("runner_fixture", ["eager_loop", "asyncio_run_eager"])
    def test_current_task_in_initial_task(self, runner_fixture, request):
        """Test that asyncio.current_task() works in eagerly executed initial task.

        Regression test: asyncio.current_task() should return a valid task
        even during eager execution of the initial task.
        """

        async def coro_needing_current_task():
            task = asyncio.current_task()
            assert task is not None
            return "completed"

        runner = request.getfixturevalue(runner_fixture)
        if runner_fixture == "eager_loop":
            result = runner.run_until_complete(coro_needing_current_task())
        else:  # asyncio_run_eager
            result = runner(coro_needing_current_task())
        assert result == "completed"

    def test_different_loop(self):
        """Test that eager task factory does not run eagerly for different loop."""
        outer_loop = None
        inner_loop = None
        inner_task = None
        inner_runs = 0

        inner_loop = asyncio.new_event_loop()
        inner_loop.set_task_factory(asynkit.eager_task_factory)

        async def inner():
            nonlocal inner_runs
            inner_runs += 1

        async def main():
            nonlocal outer_loop, inner_task
            outer_loop = asyncio.get_running_loop()

            coro = inner()
            n = inner_runs
            inner_task = inner_loop.create_task(
                coro
            )  # does not run yet (different loop)
            assert inner_runs == n  # did not run eagerly

        asyncio.run(main())

        # clean up the inner loop
        async def cleanup():
            await inner_task

        inner_loop.run_until_complete(cleanup())
        inner_loop.close()
