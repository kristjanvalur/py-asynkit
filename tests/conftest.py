import asyncio
import sys

import pytest

import asynkit
import asynkit.coroutine as coroutine_module

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
    config.addinivalue_line(
        "markers",
        "eager_tasks: marks tests running with Python 3.12+ eager_task_factory",
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
    parser.addoption(
        "--no-py",
        action="store_true",
        default=False,
        help="Skip Python implementation tests",
    )
    parser.addoption(
        "--no-c",
        action="store_true",
        default=False,
        help="Skip C extension implementation tests",
    )


def scheduling_loop_type(request):
    loop_type = DefaultLoop
    if ProactorLoop and request.config.getoption("proactor"):
        loop_type = ProactorLoop
    if request.config.getoption("selector"):
        loop_type = SelectorLoop
    return loop_type


# loop policy for pytest-anyio plugin
class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def __init__(self, request, eager_tasks=False):
        super().__init__()
        self.request = request
        self.eager_tasks = eager_tasks

    def new_event_loop(self):
        loop = scheduling_loop_type(self.request)()
        # Set eager task factory if Python 3.12+ and requested
        if self.eager_tasks and sys.version_info >= (3, 12):
            loop.set_task_factory(asyncio.eager_task_factory)
        return loop


def make_loop_factory(loop_policy):
    """
    Create a loop_factory callable from an event loop policy.
    anyio 4.x requires loop_factory instead of policy.
    """

    def loop_factory():
        return loop_policy.new_event_loop()

    return loop_factory


def make_anyio_backend(request, eager_tasks=False):
    """Create an anyio backend configuration with optional eager task factory.

    Args:
        request: pytest request object
        eager_tasks: if True and Python 3.12+, use eager_task_factory

    Returns:
        tuple: (backend_name, backend_options) for anyio
    """
    policy = SchedulingEventLoopPolicy(request, eager_tasks=eager_tasks)
    return ("asyncio", {"loop_factory": make_loop_factory(policy)})


def c_implementation_available():
    """Check if C implementation is available."""
    return (
        hasattr(coroutine_module, "_CCoroStart")
        and coroutine_module._CCoroStart is not None
        and coroutine_module._CCoroStart is not coroutine_module.PyCoroStart
    )


@pytest.fixture(
    params=[
        pytest.param("python", id="py"),
        pytest.param("c", id="c"),
    ],
    scope="function",
)
def corostart_type(request):
    """
    Parametrized fixture that returns the appropriate CoroStart class.

    This fixture provides the actual class (not a context manager) so tests can
    directly instantiate CoroStart with: cs = corostart_type(coro)
    """
    implementation_name = request.param

    # Check if C implementation should be skipped
    if implementation_name == "c" and not c_implementation_available():
        pytest.skip("C implementation not available")

    # Check command line skip options
    if implementation_name == "python" and request.config.getoption("--no-py"):
        pytest.skip("Python implementation tests skipped")
    if implementation_name == "c" and request.config.getoption("--no-c"):
        pytest.skip("C implementation tests skipped")

    # Return the appropriate class
    if implementation_name == "python":
        return coroutine_module.PyCoroStart
    elif implementation_name == "c":
        return coroutine_module._CCoroStart
    else:
        raise ValueError(f"Unknown implementation: {implementation_name}")
