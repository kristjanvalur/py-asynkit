import asyncio

import pytest

import asynkit

DefaultLoop = asynkit.DefaultSchedulingEventLoop
SelectorLoop = asynkit.SchedulingSelectorEventLoop
ProactorLoop = getattr(asynkit, "SchedulingProactorEventLoop", None)


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


# fixture for pytest-asyncio plugin
@pytest.fixture
def event_loop(request):
    loop = scheduling_loop_type(request)()
    try:
        yield loop
    finally:
        loop.close()
