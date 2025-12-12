"""
Comprehensive context tests for eager task factory implementations.

Tests context isolation, inheritance, and proper behavior across
Python and C extension implementations.
"""

import asyncio
import contextvars

import pytest

import asynkit
import asynkit.coroutine


class TestEagerTaskFactoryContext:
    """Test context behavior in eager task factory."""

    pytestmark = pytest.mark.anyio

    @pytest.fixture
    def anyio_backend(self):
        """Use asyncio backend for these tests."""
        return "asyncio"

    @pytest.fixture(autouse=True)
    def setup_context_var(self):
        """Set up a context variable for testing."""
        self.test_var = contextvars.ContextVar("test_var", default="unset")
        self.data_var = contextvars.ContextVar("data_var", default=[])

    @pytest.fixture
    def implementations(self):
        """Provide both Python and C implementations for testing."""
        implementations = [("Python", asynkit.coroutine._PyCoroStart)]

        # Add C implementation if available
        if (
            hasattr(asynkit.coroutine, "_CCoroStart")
            and asynkit.coroutine._CCoroStart is not None
        ):
            implementations.append(("C Extension", asynkit.coroutine._CCoroStart))

        return implementations

    async def test_context_isolation_in_blocking_task(self, implementations):
        """
        Test that a blocking task maintains its context before and after sleep,
        and that the creator's context is not polluted.
        """
        for impl_name, impl_class in implementations:
            print(f"\n=== Testing {impl_name} Implementation ===")

            # Temporarily use this implementation
            original = asynkit.coroutine.CoroStart
            asynkit.coroutine.CoroStart = impl_class

            try:
                await self._test_context_isolation_blocking(impl_name)
            finally:
                asynkit.coroutine.CoroStart = original

    async def _test_context_isolation_blocking(self, impl_name: str):
        """Helper method for testing context isolation with blocking tasks."""

        # Set initial context in creator
        self.test_var.set("creator_value")
        creator_data = []
        self.data_var.set(creator_data)

        # Track what the task sees
        task_observations = []

        async def blocking_task():
            nonlocal task_observations

            # Record initial context
            initial_value = self.test_var.get()
            initial_data = self.data_var.get()
            task_observations.append(("initial", initial_value, id(initial_data)))

            # Modify context in task
            self.test_var.set("task_modified")
            task_data = initial_data.copy()
            task_data.append("task_data")
            self.data_var.set(task_data)

            # Record before sleep
            before_sleep = self.test_var.get()
            before_data = self.data_var.get()
            task_observations.append(("before_sleep", before_sleep, id(before_data)))

            # Block/yield
            await asyncio.sleep(0)

            # Record after sleep
            after_sleep = self.test_var.get()
            after_data = self.data_var.get()
            task_observations.append(("after_sleep", after_sleep, id(after_data)))

            # Final modification
            self.test_var.set("task_final")
            after_data.append("final_data")

            final_value = self.test_var.get()
            final_data = self.data_var.get()
            task_observations.append(("final", final_value, id(final_data)))

            return "task_completed"

        # Set up eager factory
        factory = asynkit.create_eager_task_factory(asyncio.Task)
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create and await task
            task = asyncio.create_task(blocking_task())
            result = await task

            # Verify task completed
            assert result == "task_completed"

            # Check creator's context wasn't polluted
            creator_final = self.test_var.get()
            creator_final_data = self.data_var.get()

            print(f"Creator context after task: {creator_final}")
            print(f"Creator data after task: {creator_final_data}")

            assert creator_final == "creator_value", (
                f"{impl_name}: Creator context was polluted. "
                f"Expected 'creator_value', got '{creator_final}'"
            )
            assert creator_final_data is creator_data, (
                f"{impl_name}: Creator data reference changed"
            )
            assert creator_final_data == [], (
                f"{impl_name}: Creator data was modified: {creator_final_data}"
            )

            # Verify task observations
            assert len(task_observations) == 4, (
                f"Expected 4 observations, got {len(task_observations)}"
            )

            # Task should have inherited creator's context initially
            initial_label, initial_value, initial_data_id = task_observations[0]
            assert initial_label == "initial"
            assert initial_value == "creator_value", (
                f"{impl_name}: Task didn't inherit creator context. "
                f"Expected 'creator_value', got '{initial_value}'"
            )

            # Task modifications should persist through sleep
            before_label, before_value, before_data_id = task_observations[1]
            after_label, after_value, after_data_id = task_observations[2]
            final_label, final_value, final_data_id = task_observations[3]

            assert before_value == "task_modified", (
                f"{impl_name}: Task context not modified before sleep"
            )
            assert after_value == "task_modified", (
                f"{impl_name}: Task context lost after sleep"
            )
            assert final_value == "task_final", (
                f"{impl_name}: Final task context incorrect"
            )

            # Data should be consistent throughout task execution
            assert before_data_id == after_data_id == final_data_id, (
                f"{impl_name}: Task data reference changed during execution"
            )

            print(f"{impl_name}: Context isolation test PASSED")

        finally:
            loop.set_task_factory(old_factory)

    async def test_context_inheritance_with_provided_context(self, implementations):
        """
        Test that when creator provides a specific context,
        the task runs in that context and modifications are visible.
        """
        for impl_name, impl_class in implementations:
            print(f"\n=== Testing {impl_name} Implementation with Provided Context ===")

            # Temporarily use this implementation
            original = asynkit.coroutine.CoroStart
            asynkit.coroutine.CoroStart = impl_class

            try:
                await self._test_provided_context(impl_name)
            finally:
                asynkit.coroutine.CoroStart = original

    async def _test_provided_context(self, impl_name: str):
        """Helper method for testing provided context behavior."""

        # Set up creator context
        self.test_var.set("creator_context")

        # Create a custom context
        custom_ctx = contextvars.copy_context()
        custom_ctx.run(self.test_var.set, "custom_context")
        custom_data = []
        custom_ctx.run(self.data_var.set, custom_data)

        # Verify custom context setup
        assert custom_ctx.run(self.test_var.get) == "custom_context"

        task_observations = []

        async def context_aware_task():
            nonlocal task_observations

            # Record what context we see
            value = self.test_var.get()
            data = self.data_var.get()
            task_observations.append(("initial", value, id(data)))

            # Modify the context
            self.test_var.set("modified_in_task")
            data.append("task_modification")

            # Sleep and check persistence
            await asyncio.sleep(0)

            after_value = self.test_var.get()
            after_data = self.data_var.get()
            task_observations.append(("after_sleep", after_value, id(after_data)))

            return "custom_context_task"

        # Set up eager factory
        factory = asynkit.create_eager_task_factory(asyncio.Task)
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Create task with custom context (if supported)
            try:
                task = asyncio.create_task(context_aware_task(), context=custom_ctx)
                context_param_supported = True
            except TypeError:
                # Fallback for Python < 3.11
                context_param_supported = False
                task = asyncio.create_task(context_aware_task())

            result = await task
            assert result == "custom_context_task"

            if context_param_supported:
                # Verify task saw the custom context
                assert len(task_observations) == 2

                initial_label, initial_value, initial_data_id = task_observations[0]
                after_label, after_value, after_data_id = task_observations[1]

                assert initial_value == "custom_context", (
                    f"{impl_name}: Task didn't use provided context. "
                    f"Expected 'custom_context', got '{initial_value}'"
                )

                assert after_value == "modified_in_task", (
                    f"{impl_name}: Context modification not preserved"
                )

                # Check that modifications are visible in the custom context
                final_custom_value = custom_ctx.run(self.test_var.get)
                final_custom_data = custom_ctx.run(self.data_var.get)

                assert final_custom_value == "modified_in_task", (
                    f"{impl_name}: Custom context not modified by task"
                )
                assert "task_modification" in final_custom_data, (
                    f"{impl_name}: Custom context data not modified"
                )

                # Verify creator context is unchanged
                creator_value = self.test_var.get()
                assert creator_value == "creator_context", (
                    f"{impl_name}: Creator context was affected"
                )

                print(f"{impl_name}: Provided context test PASSED")
            else:
                print(f"{impl_name}: Context parameter not supported (Python < 3.11)")

        finally:
            loop.set_task_factory(old_factory)

    async def test_context_debugging(self, implementations):
        """Debug test to understand context behavior differences."""
        for impl_name, impl_class in implementations:
            print(f"\n=== Debug Context Behavior: {impl_name} ===")

            # Temporarily use this implementation
            original = asynkit.coroutine.CoroStart
            asynkit.coroutine.CoroStart = impl_class

            try:
                await self._debug_context_behavior(impl_name)
            finally:
                asynkit.coroutine.CoroStart = original

    async def _debug_context_behavior(self, impl_name: str):
        """Debug helper to trace context usage."""

        self.test_var.set("debug_creator")

        async def debug_task():
            value = self.test_var.get()
            print(f"  {impl_name}: Task sees context value: {value}")

            await asyncio.sleep(0)

            after_value = self.test_var.get()
            print(f"  {impl_name}: After sleep context value: {after_value}")

            return "debug_complete"

        # Set up eager factory
        factory = asynkit.create_eager_task_factory(asyncio.Task)
        loop = asyncio.get_running_loop()
        old_factory = loop.get_task_factory()
        loop.set_task_factory(factory)

        try:
            # Test both with and without explicit context
            print(f"  {impl_name}: Testing without explicit context")
            task1 = asyncio.create_task(debug_task())
            await task1

            try:
                print(f"  {impl_name}: Testing with explicit context")
                custom_ctx = contextvars.copy_context()
                custom_ctx.run(self.test_var.set, "debug_custom")
                task2 = asyncio.create_task(debug_task(), context=custom_ctx)
                await task2
            except TypeError:
                print(f"  {impl_name}: Context parameter not supported")

        finally:
            loop.set_task_factory(old_factory)
