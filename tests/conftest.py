import pytest
import asynkit

SelectorLoop = asynkit.SchedulingSelectorEventLoop
ProactorLoop = getattr(asynkit, "SchedulingProactorEventLoop", None)


def pytest_addoption(parser):
    parser.addoption("--proactor", action="store_true", default=False)


@pytest.fixture
def event_loop(request):
    loop_type = SelectorLoop
    if ProactorLoop and request.config.getoption("proactor"):
        loop_type = ProactorLoop
    loop = loop_type()
    try:
        yield loop
    finally:
        loop.close()