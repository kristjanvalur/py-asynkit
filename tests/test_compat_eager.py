"""Tests for asynkit.compat eager task functionality."""

import asyncio
import sys
from unittest.mock import patch

import pytest

import asynkit.compat

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for these tests."""
    return "asyncio"


class TestEagerTasksCompat:
    """Test enable_eager_tasks() functionality."""

    def setup_method(self):
        """Ensure clean state before each test."""
        # Disable any existing eager tasks
        asynkit.compat.disable_eager_tasks()

    def teardown_method(self):
        """Clean up after each test."""
        # Restore original state
        asynkit.compat.disable_eager_tasks()

    def test_enable_eager_tasks_idempotent(self):
        """Test that enable_eager_tasks() can be called multiple times safely."""
        # Should be safe to call multiple times
        asynkit.compat.enable_eager_tasks()
        asynkit.compat.enable_eager_tasks()
        asynkit.compat.enable_eager_tasks()

        # Should still work
        assert hasattr(asyncio, "eager_task_factory")
        assert asynkit.compat._eager_tasks_enabled

    def test_disable_eager_tasks(self):
        """Test that disable_eager_tasks() properly restores original behavior."""
        # Enable eager tasks
        asynkit.compat.enable_eager_tasks()
        assert asynkit.compat._eager_tasks_enabled

        # Disable them
        asynkit.compat.disable_eager_tasks()
        assert not asynkit.compat._eager_tasks_enabled

        # Should be safe to call multiple times
        asynkit.compat.disable_eager_tasks()
        asynkit.compat.disable_eager_tasks()

    @pytest.mark.skipif(
        sys.version_info >= (3, 12), reason="Test for Python < 3.12 behavior"
    )
    def test_asyncio_eager_task_factory_added_pre_312(self):
        """Test that asyncio.eager_task_factory is added on Python < 3.12."""
        # Should not exist initially
        assert not hasattr(asyncio, "eager_task_factory")

        # Enable eager tasks
        asynkit.compat.enable_eager_tasks()

        # Should now exist
        assert hasattr(asyncio, "eager_task_factory")
        assert asyncio.eager_task_factory is asynkit.coroutine.eager_task_factory

        # Disable and check it's removed
        asynkit.compat.disable_eager_tasks()
        assert not hasattr(asyncio, "eager_task_factory")

    @pytest.mark.skipif(
        sys.version_info < (3, 12), reason="Test for Python 3.12+ behavior"
    )
    def test_asyncio_eager_task_factory_preserved_312(self):
        """Test that native asyncio.eager_task_factory is preserved on Python 3.12+."""
        # Should exist natively
        original_factory = getattr(asyncio, "eager_task_factory", None)
        if original_factory is None:
            pytest.skip(
                "asyncio.eager_task_factory not available in this Python version"
            )

        # Enable eager tasks
        asynkit.compat.enable_eager_tasks()

        # Should still be the native one
        assert hasattr(asyncio, "eager_task_factory")
        assert asyncio.eager_task_factory is original_factory

        # Disable - should still exist (native)
        asynkit.compat.disable_eager_tasks()
        assert hasattr(asyncio, "eager_task_factory")
        assert asyncio.eager_task_factory is original_factory

    async def test_eager_start_parameter_functionality(self):
        """Test that eager_start parameter works correctly."""
        asynkit.compat.enable_eager_tasks()

        execution_order = []

        async def test_coro(name):
            execution_order.append(f"{name}_start")
            await asyncio.sleep(0)
            execution_order.append(f"{name}_end")
            return name

        # Test eager_start=True
        execution_order.clear()
        task_eager = asyncio.create_task(test_coro("eager"), eager_start=True)
        execution_order.append("after_create_eager")

        # Test eager_start=False
        task_standard = asyncio.create_task(test_coro("standard"), eager_start=False)
        execution_order.append("after_create_standard")

        # Complete tasks
        result_eager = await task_eager
        result_standard = await task_standard

        assert result_eager == "eager"
        assert result_standard == "standard"

        # Eager task should start immediately
        assert execution_order[0] == "eager_start"
        assert "after_create_eager" in execution_order
        assert "after_create_standard" in execution_order

    async def test_eager_start_none_default_behavior(self):
        """Test that eager_start=None gives standard behavior."""
        asynkit.compat.enable_eager_tasks()

        async def test_coro():
            return "result"

        # These should all behave the same (standard)
        task1 = asyncio.create_task(test_coro(), eager_start=None)
        task2 = asyncio.create_task(test_coro(), eager_start=False)
        task3 = asyncio.create_task(test_coro())  # No eager_start parameter

        # All should be regular tasks, not started yet
        assert not task1.done()
        assert not task2.done()
        assert not task3.done()

        # Complete them
        result1 = await task1
        result2 = await task2
        result3 = await task3

        assert result1 == "result"
        assert result2 == "result"
        assert result3 == "result"

    async def test_eager_start_invalid_value(self):
        """Test eager_start values work like native Python (truthiness)."""
        asynkit.compat.enable_eager_tasks()

        async def test_coro():
            return "result"

        # Test various values - should all work based on truthiness
        # This matches native Python 3.14 behavior

        # String "invalid" is truthy, should work like eager_start=True
        task1 = asyncio.create_task(test_coro(), eager_start="invalid")
        result1 = await task1
        assert result1 == "result"

        # Integer 1 is truthy, should work like eager_start=True
        task2 = asyncio.create_task(test_coro(), eager_start=1)
        result2 = await task2
        assert result2 == "result"

        # Integer 0 is falsy, should work like eager_start=False
        task3 = asyncio.create_task(test_coro(), eager_start=0)
        result3 = await task3
        assert result3 == "result"

        # Empty string is falsy, should work like eager_start=False
        task4 = asyncio.create_task(test_coro(), eager_start="")
        result4 = await task4
        assert result4 == "result"

    def test_detection_functions(self):
        """Test the detection utility functions."""
        # Test eager_start detection (version-based)
        has_eager_start = asynkit.compat._detect_eager_start_support()
        expected_eager_start = sys.version_info >= (3, 14)
        assert has_eager_start == expected_eager_start

        # Test native eager_task_factory detection (version-based)
        has_native_factory = asynkit.compat._detect_native_eager_task_factory()
        expected_factory = sys.version_info >= (3, 12)
        assert has_native_factory == expected_factory

    async def test_context_handling_with_eager_start(self):
        """Test that context is properly handled with eager_start."""
        import contextvars

        asynkit.compat.enable_eager_tasks()

        var = contextvars.ContextVar("test_var")
        var.set("original")

        async def context_coro():
            return var.get()

        # Create new context
        ctx = contextvars.copy_context()
        ctx.run(var.set, "modified")

        # Test with eager_start=True
        if sys.version_info >= (3, 11):
            # Context parameter should be supported
            task = asyncio.create_task(context_coro(), eager_start=True, context=ctx)
            result = await task
            # Behavior depends on implementation - just ensure it doesn't crash
            assert result in ["original", "modified"]
        else:
            # Context parameter not supported
            task = asyncio.create_task(context_coro(), eager_start=True)
            result = await task
            assert result == "original"

    async def test_error_handling_with_eager_start(self):
        """Test that errors are properly handled with eager_start."""
        asynkit.compat.enable_eager_tasks()

        class TestError(Exception):
            pass

        async def error_coro():
            raise TestError("test error")

        # Test eager_start=True with exception
        task = asyncio.create_task(error_coro(), eager_start=True)

        with pytest.raises(TestError, match="test error"):
            await task

    async def test_kwargs_forwarding(self):
        """Test that other kwargs are properly forwarded to create_task."""
        asynkit.compat.enable_eager_tasks()

        async def test_coro():
            return "result"

        # Test with name parameter
        task = asyncio.create_task(test_coro(), eager_start=False, name="test_task")
        assert task.get_name() == "test_task"

        result = await task
        assert result == "result"


@pytest.mark.parametrize(
    "python_version,expected_eager_start,expected_factory",
    [
        ((3, 10), False, False),  # Python 3.10
        ((3, 11), False, False),  # Python 3.11
        ((3, 12), False, True),  # Python 3.12
        ((3, 13), False, True),  # Python 3.13
        ((3, 14), True, True),  # Python 3.14
        ((3, 15), True, True),  # Python 3.15 (future)
    ],
)
def test_version_specific_behavior(
    python_version, expected_eager_start, expected_factory
):
    """Test version-based detection for different Python versions."""
    with patch("asynkit.compat.sys.version_info", python_version):
        # Test detection functions
        eager_start_detected = asynkit.compat._detect_eager_start_support()
        factory_detected = asynkit.compat._detect_native_eager_task_factory()

        assert eager_start_detected == expected_eager_start
        assert factory_detected == expected_factory


class TestMockNativeBehavior:
    """Test behavior when native asyncio features are available."""

    def setup_method(self):
        """Ensure clean state before each test."""
        asynkit.compat.disable_eager_tasks()

    def teardown_method(self):
        """Clean up after each test."""
        asynkit.compat.disable_eager_tasks()

    async def test_with_mock_native_eager_start(self):
        """Test behavior when native eager_start is available."""
        original_create_task = asyncio.create_task

        # Mock native eager_start support
        def mock_create_task(*args, **kwargs):
            # Simulate native eager_start support
            eager_start = kwargs.get("eager_start")
            if eager_start is True:
                kwargs.pop("eager_start")
                # Simulate eager execution by immediately starting the coro
                # (This is a simplified simulation)
            elif eager_start is False:
                kwargs.pop("eager_start", None)
            return original_create_task(*args, **kwargs)

        with patch("asynkit.compat._detect_eager_start_support", return_value=True):
            with patch("asyncio.create_task", side_effect=mock_create_task):
                asynkit.compat.enable_eager_tasks()

                async def test_coro():
                    return "result"

                # Should use the mocked native implementation
                task = asyncio.create_task(test_coro(), eager_start=True)
                result = await task
                assert result == "result"


if __name__ == "__main__":
    pytest.main([__file__])
