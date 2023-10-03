import asyncio
from collections import deque

import pytest

import asynkit.tools
from asynkit.loop.extensions import get_scheduling_loop

from .conftest import SchedulingEventLoopPolicy

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend(request):
    return ("asyncio", {"policy": SchedulingEventLoopPolicy(request)})


def test_deque_pop():
    """
    Test that our pop for a deque has same semantics as that for a list
    """

    for i in range(-7, 7):
        ref = list(range(5))
        deq = deque(range(5))

        try:
            refpop = ref.pop(i)
            ok = True
        except IndexError:
            ok = False

        if ok:
            pop = asynkit.tools.deque_pop(deq, i)
            assert pop == refpop
            assert list(deq) == ref
        else:
            with pytest.raises(IndexError):
                asynkit.tools.deque_pop(deq, i)


async def test_get_wakeup():
    # create an event, then make a task which waits on it
    # then, get the wakeup callback from the task
    # and store it

    loop = get_scheduling_loop()
    event = asyncio.Event()

    # create a fresh task
    task = asyncio.create_task(event.wait())
    queue = loop.get_ready_queue()
    for h in queue:
        if loop.get_task_from_handle(h) is task:
            break
    else:
        assert False, "task not found in ready queue"

    # create a just awoken task
    task = asyncio.create_task(event.wait())
    await asyncio.sleep(0)
    event.set()

    queue = loop.get_ready_queue()
    for h in queue:
        if loop.get_task_from_handle(h) is task:
            break
    else:
        assert False, "task not found in ready queue"

    # now, we have the handle, we can get the wakeup callback

    event.set()
    await task
