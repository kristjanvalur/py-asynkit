import asyncio
from unittest.mock import Mock

import pytest

from asynkit.experimental.priority import PriorityLock, PriorityTask

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_priority_lock():
    """
    Test that a priority lock correctly assumes the priority of the waiting tasks
    """

    lock = PriorityLock()

    async def do_something():
        await lock.acquire()
        await asyncio.sleep(0.1)
        lock.release()

    async with lock:
        assert lock.effective_priority() is None

        task1 = asyncio.Task(do_something())
        await asyncio.sleep(0)
        assert lock.effective_priority() == 0

        task2 = PriorityTask(do_something())
        task2.priority_value = -1
        await asyncio.sleep(0)
        assert lock.effective_priority() == -1

        task3 = PriorityTask(do_something())
        task3.priority_value = -2
        await asyncio.sleep(0)
        assert lock.effective_priority() == -2

        task4 = PriorityTask(do_something())
        task4.priority_value = 2
        await asyncio.sleep(0)
        assert lock.effective_priority() == -2

    await asyncio.gather(task1, task2, task3, task4)
    assert lock.effective_priority() is None


async def test_priority_inheritance():
    """
    Test that a priority task correctly inherits the priority of a held
    lock.
    """

    lock = PriorityLock()

    async def do_something():
        await lock.acquire()
        await asyncio.sleep(0.1)
        lock.release()

    async def taskfunc():
        task = asyncio.current_task()
        assert task.effective_priority() == 1

        async with lock:
            assert lock.effective_priority() is None

            task1 = asyncio.Task(do_something())
            await asyncio.sleep(0)
            assert lock.effective_priority() == 0
            assert task.effective_priority() == 0

            task2 = PriorityTask(do_something())
            task2.priority_value = -1
            await asyncio.sleep(0)
            assert lock.effective_priority() == -1
            assert task.effective_priority() == -1

            task3 = PriorityTask(do_something())
            task3.priority_value = -2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2
            assert task.effective_priority() == -2

            task4 = PriorityTask(do_something())
            task4.priority_value = 2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2
            assert task.effective_priority() == -2

        await asyncio.gather(task1, task2, task3, task4)
        assert lock.effective_priority() is None
        assert task.effective_priority() == 1

    task = PriorityTask(taskfunc(), priority=1)
    await task


async def test_priority_reschedule():
    """
    Test that a holding task gets a reschedule call when a possibly
    higher priority task starts waiting
    """

    lock = PriorityLock()

    async def do_something():
        await lock.acquire()
        await asyncio.sleep(0.1)
        lock.release()

    async def taskfunc():
        task = asyncio.current_task()
        assert task.get_effective_priority() == 1

        async with lock:
            assert lock.effective_priority() is None

            with Mock.object(task, "reschedule") as mock:
                mock.return_value = True
                asyncio.Task(do_something())
                await asyncio.sleep(0)  # we remain runnable
                assert lock.effective_priority() == 0
                assert task.get_effective_priority() == 0

                assert mock.called
