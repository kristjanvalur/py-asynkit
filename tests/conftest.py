import asyncio

import pytest

import asynkit

DefaultLoop = asynkit.DefaultSchedulingEventLoop
SelectorLoop = asynkit.SchedulingSelectorEventLoop
ProactorLoop = getattr(asynkit, "SchedulingProactorEventLoop", None)

# Check if trio is available and compatible
try:
    import trio  # noqa: F401  # type: ignore[import-untyped]

    TRIO_AVAILABLE = True
except (ImportError, TypeError):
    # TypeError can occur on Python 3.13+ with old trio versions
    TRIO_AVAILABLE = False

# Skip trio tests only when trio is not available
# trio 0.31.0+ now supports Python 3.13+
SKIP_TRIO = not TRIO_AVAILABLE


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "trio: marks tests that require trio backend "
        "(automatically skipped when trio is unavailable or incompatible)",
    )


def pytest_collection_modifyitems(config, items):
    """Mark and skip trio tests when trio is not available or incompatible."""
    skip_trio = pytest.mark.skip(
        reason="trio not available or incompatible with this Python version"
    )
    for item in items:
        # Mark and potentially skip tests that use trio backend
        if "anyio_backend" in item.fixturenames:
            # Check if this test is parameterized with trio
            if hasattr(item, "callspec"):
                backend = item.callspec.params.get("anyio_backend")
                if backend == "trio" or (
                    isinstance(backend, tuple) and backend[0] == "trio"
                ):
                    item.add_marker(pytest.mark.trio)
                    if SKIP_TRIO:
                        item.add_marker(skip_trio)
        # Also mark if anyio_backend_name fixture indicates trio
        if "anyio_backend_name" in item.fixturenames:
            if hasattr(item, "callspec"):
                backend_name = item.callspec.params.get("anyio_backend_name")
                if backend_name == "trio":
                    item.add_marker(pytest.mark.trio)
                    if SKIP_TRIO:
                        item.add_marker(skip_trio)


def pytest_addoption(parser):
    parser.addoption("--proactor", action="store_true", default=False)
    parser.addoption("--selector", action="store_true", default=False)


def scheduling_loop_type(request):
    loop_type = DefaultLoop
    if ProactorLoop and request.config.getoption("proactor"):
        loop_type = ProactorLoop
    if request.config.getoption("selector"):
        loop_type = SelectorLoop
    return loop_type


# loop policy for pytest-anyio plugin
class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def __init__(self, request):
        super().__init__()
        self.request = request

    def new_event_loop(self):
        return scheduling_loop_type(self.request)()


def make_loop_factory(loop_policy):
    """
    Create a loop_factory callable from an event loop policy.
    anyio 4.x requires loop_factory instead of policy.
    """

    def loop_factory():
        return loop_policy.new_event_loop()

    return loop_factory
