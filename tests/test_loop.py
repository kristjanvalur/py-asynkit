import asyncio
import sys
from asyncio import DefaultEventLoopPolicy
from unittest.mock import patch

import pytest

import asynkit
from asynkit.loop.extensions import (
    call_pos,
    get_ready_queue,
    ready_find,
    ready_insert,
    ready_len,
    ready_remove,
    ready_tasks,
    task_from_handle,
)
from asynkit.scheduling import task_is_runnable

from .conftest import SchedulingEventLoopPolicy, make_loop_factory
from .experimental.test_priority import PriorityEventLoopPolicy

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["regular", "custom", "priority"])
def anyio_backend(request):
    if request.param == "custom":
        policy = SchedulingEventLoopPolicy(request)
        return ("asyncio", {"loop_factory": make_loop_factory(policy)})
    elif request.param == "priority":
        policy = PriorityEventLoopPolicy(request)
        return ("asyncio", {"loop_factory": make_loop_factory(policy)})
    else:
        policy = DefaultEventLoopPolicy()
        return ("asyncio", {"loop_factory": make_loop_factory(policy)})


class TestCallInsertReady:
    """
    Test that we can insert callbacks at given places in the runnable
    queue. Compare the order of execution with a list that has been
    similarly inserted into via list.insert()
    """

    def add_insert(self, pos, label):
        def callback():
            self.log.append(label)

        call_pos(pos, callback)

    def prepare(self, n=3):
        self.log = []
        self.tasks = [asyncio.create_task(self.simple(k)) for k in range(n)]
        return list(range(n))

    @pytest.mark.parametrize("count", [1, 2, 6])
    async def test_normal(self, count):
        self.log = []
        expect = []
        perm = list(range(count))
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect

    @pytest.mark.parametrize("count", [2, 6])
    async def test_reverse(self, count):
        await asyncio.sleep(0)
        assert ready_len() == 0

        self.log = []
        expect = []
        perm = list(range(count))
        perm.reverse()
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect

    @pytest.mark.parametrize("count", [2, 6])
    async def test_cut(self, count):
        await asyncio.sleep(0)
        assert ready_len() == 0
        self.log = []
        expect = []
        perm = list(range(count))
        perm = perm[len(perm) // 2 :] + perm[: len(perm) // 2]
        perm.reverse()
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect


@pytest.mark.parametrize("count", [2, 6])
async def test_ready_len(count):
    # proactor loop may start out with a proactor task in place.
    # flush it.
    await asyncio.sleep(0)
    assert ready_len() == 0

    for i in range(count):

        async def foo():
            pass

        asyncio.create_task(foo())

    assert ready_len() == count
    await asyncio.sleep(0)
    # add a non-runnable callback to ready loop
    asyncio.get_running_loop().call_soon(lambda: None)
    assert ready_len() == 1
    assert len(asynkit.runnable_tasks()) == 0

    # and add a proper method callback
    class Foo:
        def cb(self):
            pass

    asyncio.get_running_loop().call_soon(Foo().cb)
    assert len(asynkit.runnable_tasks()) == 0


@pytest.mark.parametrize("pos", [0, 1, 3])
async def test_sleep_insert(pos):
    await asyncio.sleep(0)
    assert ready_len() == 0
    log = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        asyncio.create_task(foo(i))

    assert ready_len() == 6
    await asynkit.sleep_insert(pos)
    assert ready_len() == 6 - pos
    log.append("me")
    await asyncio.sleep(0)

    expect = list(range(6))
    expect.insert(pos, "me")
    assert log == expect


@pytest.mark.parametrize("pos", [0, 1, 6])
async def test_task_reinsert(pos):
    await asyncio.sleep(0)
    assert ready_len() == 0
    log = []
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    asynkit.task_reinsert(tasks[-1], pos)
    await asyncio.sleep(0)

    expect = list(range(6))
    p = expect.pop(-1)
    expect.insert(pos, p)
    assert log == expect


async def test_task_reinsert_blocked():
    async def foo():
        await asyncio.sleep(0.1)

    task = asyncio.create_task(foo())
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        asynkit.task_reinsert(task, 0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("pos", [0, 1, 3, 5])
async def test_task_switch(pos):
    await asyncio.sleep(0)
    assert ready_len() == 0
    log = []
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    assert len(log) == 0
    await asynkit.task_switch(tasks[pos])
    log.append("me")
    await asyncio.sleep(0)
    assert len(log) == 7

    expect = list(range(6))
    expect.pop(pos)
    expect.insert(0, pos)
    expect.append("me")
    assert log == expect


@pytest.mark.parametrize("pos", [0, 1, 3, 5])
async def test_task_switch_insert(pos):
    await asyncio.sleep(0)
    assert ready_len() == 0
    log = []
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    assert len(log) == 0
    await asynkit.task_switch(tasks[pos], insert_pos=1)
    log.append("me")
    await asyncio.sleep(0)
    assert len(log) == 7

    expect = list(range(6))
    expect.pop(pos)
    expect.insert(0, pos)
    expect.insert(1, "me")
    assert log == expect


async def test_task_switch_notfound():
    async def foo():
        pass

    task = asyncio.create_task(foo())
    item = ready_find(task, remove=True)
    with pytest.raises(ValueError):
        await asynkit.task_switch(task)
    ready_insert(item)


async def test_task_switch_blocked():
    async def foo():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(foo())
    # make it settle on its sleep
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        await asynkit.task_switch(task)
    await task


class TestTasks:
    async def foo(self, sleeptime):
        await asyncio.sleep(sleeptime)

    def tasks(self, sleeptime=0):
        return [asyncio.create_task(self.foo(sleeptime)) for _ in range(4)]

    def identity(self, loop=None):
        all = asyncio.all_tasks(loop)
        all2 = (
            asynkit.runnable_tasks(loop)
            | asynkit.blocked_tasks(loop)
            | {asyncio.current_task(loop)}
        )
        assert all == all2

    async def test_find_task(self):
        await asyncio.sleep(0)
        tasks = self.tasks()
        t2 = list(ready_tasks())
        assert tasks == t2[-len(tasks) :]

        async def foo():
            pass

        task = asyncio.create_task(foo())
        item = ready_find(task, remove=True)
        assert ready_find(task) is None
        ready_insert(item)

    async def test_remove_task(self):
        await asyncio.sleep(0)
        tasks = self.tasks()
        t2 = list(ready_tasks())
        assert tasks == t2[-len(tasks) :]

        async def foo():
            pass

        task = asyncio.create_task(foo())
        item = ready_find(task, remove=True)
        assert item is not None
        item2 = ready_find(task, remove=True)
        assert item2 is None
        ready_insert(item)

    async def test_get_task(self):
        tasks = self.tasks()
        asyncio.get_running_loop()
        tasks2 = ready_tasks()
        assert set(tasks2) == set(tasks)

    async def test_get_task_extra(self):
        loop = asyncio.get_running_loop()
        await asyncio.sleep(0)  # flush ready queue
        initial = ready_len()
        tasks = self.tasks()
        assert ready_len() == len(tasks) + initial
        loop.call_soon(lambda: None)
        assert ready_len() > len(tasks) + initial
        tasks2 = ready_tasks()
        assert set(tasks2) == set(tasks)

    async def test_runnable_tasks(self):
        tasks = self.tasks()
        tasks2 = asynkit.runnable_tasks()
        assert set(tasks) == tasks2
        self.identity()

        # get them settled on their sleep
        await asyncio.sleep(0)
        assert set(tasks) == asynkit.runnable_tasks()
        self.identity()

        # make them return from sleep
        await asyncio.sleep(0)
        assert asynkit.runnable_tasks() == set()

    async def test_blocked_tasks(self):
        loop = asyncio.get_running_loop()
        self.identity(loop)  # test both with None and provided loop
        tasks = self.tasks(0.1)
        self.identity()
        await asyncio.sleep(0)  # make our tasks blocked on the sleep
        tasks2 = asynkit.blocked_tasks()
        # With anyio 4.x, the test runner task is also blocked
        # Filter to only tasks we created
        assert set(tasks) <= tasks2, "Created tasks should be in blocked tasks"
        our_tasks = {t for t in tasks2 if t in tasks}
        assert set(tasks) == our_tasks, "Only our tasks should match"
        self.identity()
        assert asynkit.runnable_tasks() == set()
        self.identity()
        for task in tasks:
            task.cancel()
        self.identity()

    async def test_blocked_tasks_current(self):
        """Test that if current_task() is None, it is not removed from
        the list of blocked tasks.
        This test is added for complete coverage testing.
        """
        with patch("asyncio.current_task", lambda: None):
            with patch("asynkit.scheduling.task_is_blocked", lambda t: True):
                blocked = asynkit.blocked_tasks()
        assert asyncio.current_task() in blocked

    async def test_task_from_handle(self):
        async def foo():
            pass

        task = asyncio.create_task(foo())
        queue = get_ready_queue()
        for handle in queue:
            if task_from_handle(handle) == task:
                break
        else:
            assert False, "task not found in ready queue"
        await task

    @pytest.mark.parametrize("count", [1, 2, 6])
    async def test_handle_remove(self, count):
        async def foo():
            pass

        tasks = [asyncio.create_task(foo()) for _ in range(count)]
        task = tasks[0]
        handle = ready_find(task, remove=False)
        assert handle is not None
        assert task_is_runnable(task)
        ready_remove(handle)
        with pytest.raises(ValueError):
            ready_remove(handle)
        assert ready_find(task, remove=False) is None
        ready_insert(handle)


class TestTaskIsBlocked:
    async def test_blocked_sleep(self):
        async def foo():
            await asyncio.sleep(0.1)

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        assert asynkit.task_is_runnable(task)

        # settle on the sleep
        await asyncio.sleep(0)
        assert asynkit.task_is_blocked(task)
        assert not asynkit.task_is_runnable(task)
        task.cancel()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()
        assert not asynkit.task_is_blocked(task)
        assert not asynkit.task_is_runnable(task)

    async def test_blocked_future(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert ready_find(task) is None
        assert asynkit.task_is_blocked(task)

        task.cancel()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_blocked_future_result(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert ready_find(task) is None
        assert asynkit.task_is_blocked(task)

        fut.set_result(None)
        assert ready_find(task) is not None
        assert not asynkit.task_is_blocked(task)
        await task

    async def test_blocked_future_exception(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert ready_find(task) is None
        assert asynkit.task_is_blocked(task)

        fut.set_exception(ZeroDivisionError())
        assert ready_find(task) is not None
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(ZeroDivisionError):
            await task

    async def test_blocked_future_cancel(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert ready_find(task) is None
        assert asynkit.task_is_blocked(task)

        fut.cancel()
        assert ready_find(task) is not None
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_blocked_await(self):
        # Test a task, blocked waiting for another blocked task
        async def foo():
            await asyncio.sleep(0.1)

        async def bar(task):
            await task

        task2 = asyncio.create_task(foo())
        task = asyncio.create_task(bar(task2))
        assert not asynkit.task_is_blocked(task)

        # settle on the sleep
        await asyncio.sleep(0)
        assert asynkit.task_is_blocked(task)
        assert asynkit.task_is_blocked(task2)
        # cancel the second task. But the awaiting task doesn't become unblocked
        # before the second task has had a chance to finish, by being run for a bit.
        task2.cancel()
        assert not asynkit.task_is_blocked(task2)
        assert not task2.done()
        # task is still blocked
        assert asynkit.task_is_blocked(task)
        assert ready_find(task) is None

        # give task2 a chance to finish, unblocking task
        await asyncio.sleep(0)
        assert task2.done()
        assert not task.done()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()
        assert not asynkit.task_is_blocked(task)


def test_event_loop_policy_context():
    with asynkit.event_loop_policy() as a:
        assert isinstance(a, asynkit.SchedulingEventLoopPolicy)

        async def foo():
            assert isinstance(asyncio.get_running_loop(), asynkit.SchedulingMixin)

        asyncio.run(foo())


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="loop_factory parameter added in Python 3.12",
)
def test_scheduling_loop_factory():
    """Test that scheduling_loop_factory works with asyncio.run() in Python 3.12+"""

    async def main():
        loop = asyncio.get_running_loop()
        # Verify we got a scheduling loop
        assert isinstance(loop, asynkit.SchedulingMixin)
        assert hasattr(loop, "queue_len")
        assert hasattr(loop, "queue_insert_pos")
        # Test that scheduling features work
        assert loop.queue_len() >= 0
        return "success"

    # Test with asyncio.run and loop_factory
    result = asyncio.run(main(), loop_factory=asynkit.scheduling_loop_factory)
    assert result == "success"
