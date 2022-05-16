import pytest
import asynkit

SelectorLoop = asynkit.SchedulingSelectorEventLoop
SchedulingLoop = getattr(asynkit, "SchedulingProactorEventLoop")


def pytest_addoption(parser):
    parser.addoption("--proactor", action="store_true", default=False)


@pytest.fixture
def event_loop(request):
    loop_type = SelectorLoop
    if SchedulingLoop and request.config.getoption("proactor"):
        loop_type = SchedulingLoop
    loop = loop_type()
    try:
        yield loop
    finally:
        loop.close()