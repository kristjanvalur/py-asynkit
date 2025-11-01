"""
Test utilities for parametrizing Python vs C implementations.
"""

import pytest

import asynkit.coroutine as coroutine_module


def get_corostart_implementations():
    """
    Get available CoroStart implementations for parametrization.

    Returns list of (name, implementation_class) tuples.
    """
    implementations = [
        ("python", coroutine_module.PyCoroStart),
    ]

    # Add C implementation if available
    if hasattr(coroutine_module, "_CCoroStart") and coroutine_module._CCoroStart:
        implementations.append(("c", coroutine_module._CCoroStart))

    return implementations


def corostart_implementations():
    """Pytest parametrize decorator for CoroStart implementations."""
    return pytest.mark.parametrize(
        "implementation_name,corostart_class",
        get_corostart_implementations(),
        ids=lambda x: x[0] if isinstance(x, tuple) else str(x),
    )


def c_implementation_available():
    """Check if C implementation is available."""
    return (
        hasattr(coroutine_module, "_CCoroStart")
        and coroutine_module._CCoroStart is not None
        and coroutine_module._CCoroStart is not coroutine_module.PyCoroStart
    )


def require_c_implementation():
    """Pytest skip decorator for tests that require C implementation."""
    return pytest.mark.skipif(
        not c_implementation_available(), reason="C extension not available"
    )


class CoroStartMonkeypatch:
    """
    Context manager for temporarily monkeypatching CoroStart implementations.

    Usage:
        with CoroStartMonkeypatch("python"):
            # All asynkit.CoroStart calls will use Python implementation
            cs = asynkit.CoroStart(coro)
    """

    def __init__(self, implementation_name):
        self.implementation_name = implementation_name
        self.original_corostart = None
        self.original_pycorostart = None

        if implementation_name == "python":
            self.target_class = coroutine_module.PyCoroStart
        elif implementation_name == "c":
            if not c_implementation_available():
                raise pytest.skip("C implementation not available")
            self.target_class = coroutine_module._CCoroStart
        else:
            raise ValueError(f"Unknown implementation: {implementation_name}")

    def __enter__(self):
        # Save original implementations
        self.original_corostart = coroutine_module.CoroStart

        # Monkey patch to force specific implementation
        coroutine_module.CoroStart = self.target_class

        # Also patch the asynkit module if it imports from coroutine
        import asynkit

        if hasattr(asynkit, "CoroStart"):
            asynkit.CoroStart = self.target_class

        return self.target_class

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original implementations
        if self.original_corostart is not None:
            coroutine_module.CoroStart = self.original_corostart

            # Restore in asynkit module too
            import asynkit

            if hasattr(asynkit, "CoroStart"):
                asynkit.CoroStart = self.original_corostart


def parametrize_corostart_implementations(test_func):
    """
    Decorator to parametrize a test function over available CoroStart implementations.

    The test function will receive an additional 'corostart_impl' parameter that
    can be used to monkeypatch the implementation.

    Usage:
        @parametrize_corostart_implementations
        async def test_something(corostart_impl):
            with corostart_impl:
                cs = asynkit.CoroStart(my_coro())
                # Test specific implementation
    """
    implementations = [
        pytest.param(CoroStartMonkeypatch("python"), id="python"),
    ]

    if c_implementation_available():
        implementations.append(pytest.param(CoroStartMonkeypatch("c"), id="c"))

    return pytest.mark.parametrize("corostart_impl", implementations)(test_func)


def parametrize_corostart_class():
    """
    Class decorator to parametrize an entire test class over CoroStart implementations.

    This adds a 'corostart_impl' fixture to every test method in the class.

    Usage:
        @parametrize_corostart_class()
        class TestSomething:
            def test_method(self, corostart_impl):
                with corostart_impl:
                    # Test code here
    """
    implementations = [
        pytest.param(CoroStartMonkeypatch("python"), id="python"),
    ]

    if c_implementation_available():
        implementations.append(pytest.param(CoroStartMonkeypatch("c"), id="c"))

    return pytest.mark.parametrize("corostart_impl", implementations, scope="class")
