import pytest
from asynkit import DefaultSchedulingEventLoop

@pytest.fixture
def event_loop():
    loop = DefaultSchedulingEventLoop()
    yield loop
    loop.close()