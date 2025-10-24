import asyncio
import sys

import pytest

from asynkit.experimental import (
    InterruptCondition,
    InterruptException,
    create_pytask,
    task_interrupt,
    task_throw,
    task_timeout,
)
from asynkit.experimental.priority import PriorityCondition, PriorityLock
from asynkit.loop.default import PyTask
from asynkit.scheduling import task_is_blocked, task_is_runnable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=[asyncio.Lock, PriorityLock])
def locktype(request):
    """A fixture returning a lock class"""
    return request.param


@pytest.fixture(params=[InterruptCondition, PriorityCondition])
def icondtype(request):
    """A fixture returning a an interruptable class"""
    return request.param


def create_task(ctask, coro, name=None):
    if ctask:
        return asyncio.create_task(coro)
    else:
        return create_pytask(coro)


@pytest.mark.parametrize("ctask", [True, False], ids=["ctask", "pytask"])
class TestThrow:
    """Test the task_throw() experimental function."""

    async def test_event(self, ctask):
        """Test that we can throw an exception into a task."""
        # create a task, have it wait on event
        e = asyncio.Event()
        w = asyncio.Event()
        self.state = "starting"

        async def task():
            assert self.state == "starting"
            self.state = "waiting"
            w.set()
            with pytest.raises(ZeroDivisionError):
                await e.wait()
            assert self.state == "interrupting"
            self.state = "interrupted"

        task = create_task(ctask, task())
        await w.wait()
        assert self.state == "waiting"
        task_throw(task, ZeroDivisionError())
        if not ctask:
            # NOTE Test is unreliable for ctasks until they have been run
            # since the task._fut_waiter cannot be cleared for them.
            assert task_is_runnable(task)
        self.state = "interrupting"
        await task
        assert self.state == "interrupted"
        assert task.done()

    async def test_execution_order(self, ctask):
        """Test that we can throw an exception into a task."""
        # create a task, have it wait on event
        e = asyncio.Event()
        w = asyncio.Event()
        self.state = "starting"

        async def task():
            assert self.state == "starting"
            self.state = "waiting"
            w.set()
            with pytest.raises(ZeroDivisionError):
                await e.wait()
            # other task ran first
            assert self.state == "task2"
            self.state = "interrupted"

        task = create_task(ctask, task())
        await w.wait()
        assert self.state == "waiting"

        async def task2():
            assert self.state == "interrupting"
            self.state = "task2"

        task2 = asyncio.create_task(task2())
        task_throw(task, ZeroDivisionError())
        if not ctask:
            # NOTE Test is unreliable for ctasks until they have been run
            # since the task._fut_waiter cannot be cleared for them.
            assert task_is_runnable(task)
        self.state = "interrupting"
        await task
        assert self.state == "interrupted"
        assert task.done()

    async def _test_ctask(self, ctask):
        if PyTask is asyncio.Task:
            pytest.skip("no CTask")

        async def task():
            pass

        t = asyncio.create_task(task())
        with pytest.raises(TypeError) as err:
            task_throw(t, ZeroDivisionError())
        assert err.match("python task")

    async def test_non_exception(self, ctask):
        """Test throwing a non-exception."""

        async def task():
            pass

        task = create_task(ctask, task())
        with pytest.raises(TypeError) as err:
            task_throw(task, 1)
        assert err.match("deriving from BaseException")


@pytest.mark.parametrize("ctask", [True, False], ids=["ctask", "pytask"])
class TestInterrupt:
    @pytest.mark.parametrize("interrupt", [True, False])
    async def test_event(self, ctask, interrupt):
        """Test that we can interrupt a task which is waiting on event."""
        # create a task, have it wait on event
        e = asyncio.Event()
        w = asyncio.Event()
        state = "starting"

        async def task():
            nonlocal state
            assert state == "starting"
            state = "waiting"
            w.set()
            if interrupt:
                with pytest.raises(ZeroDivisionError):
                    await e.wait()
                assert state == "interrupting"
                state = "interrupted"
            else:
                await e.wait()
                assert state == "waking"
                state = "waited"

        task = create_task(ctask, task())
        await w.wait()
        assert state == "waiting"
        assert not task_is_runnable(task)
        if interrupt:
            state = "interrupting"
            await task_interrupt(task, ZeroDivisionError())
            assert state == "interrupted"
            e.set()
        else:
            state = "waking"
            e.set()
            assert task_is_runnable(task)
            await task
            assert state == "waited"
        assert task.done()
        await task

    async def test_sleep(self, ctask):
        """Test that we can interrupt a task which is sleeping."""
        # create a task, have it wait on sleep
        w = asyncio.Event()
        state = "starting"

        async def task():
            nonlocal state
            assert state == "starting"
            state = "waiting"
            w.set()
            with pytest.raises(ZeroDivisionError):
                await asyncio.sleep(0.01)
            assert state == "interrupting"
            state = "interrupted"

        task = create_task(ctask, task())
        await w.wait()
        assert state == "waiting"
        state = "interrupting"
        await task_interrupt(task, ZeroDivisionError())
        assert state == "interrupted"
        # wait a bit too, to see if the sleep has an side effects
        await asyncio.sleep(0.02)
        await task

    async def test_sleep0(self, ctask):
        """Test that we can interrupt a task which is sleeping 0 seconds"""
        # create a task, have it run one step
        state = "starting"

        if ctask:
            pytest.xfail("CTask plain __step is not interruptable")

        async def task():
            nonlocal state
            assert state == "starting"
            state = "waiting"
            with pytest.raises(ZeroDivisionError):
                await asyncio.sleep(0)
            assert state == "interrupting"
            state = "interrupted"

        task = create_task(ctask, task())
        await asyncio.sleep(0)
        assert state == "waiting"
        state = "interrupting"
        await task_interrupt(task, ZeroDivisionError())
        assert state == "interrupted"
        # wait a bit too, to see if the sleep has an side effects
        await asyncio.sleep(0.02)
        await task

    @pytest.mark.parametrize("interrupt", [True, False])
    async def test_execution_order(self, ctask, interrupt):
        """Test that the interrupted task is run before any other task."""
        # create a task, have it wait on event
        e = asyncio.Event()
        w = asyncio.Event()
        state = "starting"

        async def task():
            nonlocal state
            assert state == "starting"
            state = "waiting"
            w.set()
            if interrupt:
                with pytest.raises(ZeroDivisionError):
                    await e.wait()
                assert state == "interrupting"
                state = "interrupted"
            else:
                await e.wait()
                assert state == "task2"
                state = "waited"

        task = create_task(ctask, task())
        await w.wait()

        # create another task, make it runnable.
        assert state == "waiting"

        async def task2():
            nonlocal state
            if interrupt:
                assert state == "interrupted"
            else:
                assert state == "waking"
            state = "task2"

        task2 = asyncio.create_task(task2())

        # Now task2 is runnable in the queue.  When we intterupt task, it should
        # be run before task2.  Then task 2 runs, and finally we get control
        assert not task_is_runnable(task)
        assert task_is_runnable(task2)
        if interrupt:
            state = "interrupting"
            await task_interrupt(task, ZeroDivisionError())
            assert state == "task2"
            e.set()
        else:
            state = "waking"
            e.set()
            assert task_is_runnable(task)
            await asyncio.sleep(0)
            assert state == "waited"
        assert task.done()
        assert task2.done()
        await task
        await task2

    async def test_runnable(self, ctask):
        """Test that we can interrupt a task which is already runnable."""
        # create a task, have it wait on event
        e = asyncio.Event()
        w = asyncio.Event()
        state = "starting"

        async def task():
            nonlocal state
            assert state == "starting"
            state = "waiting"
            w.set()
            with pytest.raises(ZeroDivisionError):
                await e.wait()
            assert state == "interrupting"
            state = "interrupted"

        task = create_task(ctask, task())
        await w.wait()
        assert state == "waiting"

        # create another task, make it runnable
        async def task2():
            nonlocal state
            assert state == "interrupted"
            state = "done"

        task2 = asyncio.create_task(task2())

        # now wake up the task. It should be at the end of the runnable queue
        e.set()
        assert task_is_runnable(task)
        assert task_is_runnable(task2)
        state = "interrupting"
        await task_interrupt(task, ZeroDivisionError())
        assert state == "done"
        assert task.done()
        assert task2.done()
        await task
        await task2

    async def test_interrupt_await_task(self, ctask):
        """Test that we can interrupt a task which is waiting on another task."""
        w = asyncio.Event()

        async def task1():
            await asyncio.sleep(0.1)
            return "ok"

        async def task2(wait_for):
            w.set()
            with pytest.raises(ZeroDivisionError):
                await wait_for

        task1 = asyncio.create_task(task1())
        task2 = create_task(ctask, task2(task1))
        await w.wait()
        assert task_is_blocked(task2)
        await task_interrupt(task2, ZeroDivisionError())
        assert task2.done()
        assert task_is_blocked(task1)
        task1.cancel()

    async def test_self(self, ctask):
        """Test that we cannot interrupt self."""

        async def task():
            with pytest.raises(RuntimeError) as err:
                await task_interrupt(asyncio.current_task(), ZeroDivisionError())
            assert err.match("cannot interrupt self")

        task = create_task(ctask, task())
        await task

    async def test_done(self, ctask):
        """Test that we cannot interrupt a task which is done."""

        async def task():
            pass

        task = create_task(ctask, task())
        await asyncio.sleep(0)
        assert task.done()
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt task which is done")

    async def test_new(self, ctask):
        """Test that we can interrupt a task which hasn't started yet."""

        if ctask:
            pytest.xfail("CTask plain __step is not interruptable")

        async def task():
            pass

        task = create_task(ctask, task())
        assert not task.done()
        await task_interrupt(task, ZeroDivisionError())
        with pytest.raises(ZeroDivisionError):
            await task

    async def test_queue(self, ctask):
        """Test that a value can be retrieved of a queue
        even when interrupted after becoming runnable
        """
        w = asyncio.Event()
        q = asyncio.Queue()

        async def task():
            w.set()
            with pytest.raises(ZeroDivisionError):
                await q.get()
            # retry
            return await q.get()

        t = create_task(ctask, task())
        await w.wait()
        assert task_is_blocked(t)
        q.put_nowait(1)
        assert task_is_runnable(t)
        # task has been awoken, we interrupt it.
        await task_interrupt(t, ZeroDivisionError())
        # after handling the interrupt, the task tries again
        assert await t == 1

    async def test_cancelled_task(self, ctask):
        """Test that we cannot interrupt a task which has been cancelled."""
        e = asyncio.Event()

        async def task():
            await e.wait()

        task = create_task(ctask, task())
        await asyncio.sleep(0)
        assert task_is_blocked(task)
        task.cancel()
        assert task_is_runnable(task)
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt a cancelled task")
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_cancelled_runnable(self, ctask):
        """Test that we cannot interrupt a task which was cancelled
        while in a runnable state after sleep(0), i.e. it paused not
        due to waiting on a real future
        """

        async def task():
            # this just places it in the ready queue again
            await asyncio.sleep(0)

        task = create_task(ctask, task())
        await asyncio.sleep(0)
        assert task_is_runnable(task)
        task.cancel()
        assert task_is_runnable(task)
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt a cancelled task")
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_cancelled_lock_acquire(self, ctask, locktype):
        """
        Test that we can interrupt a lock acquire at a critical phase
        where the lock has been freed.
        """

        lock = locktype()

        async def func():
            try:
                await lock.acquire()
            except InterruptException:
                return 0
            lock.release()
            return 1

        await lock.acquire()
        task1 = create_task(ctask, func())
        task2 = create_task(ctask, func())
        await asyncio.sleep(0)
        # both tasks are waiting on the lock, task1 is first in the queue
        lock.release()
        # task1 is now runnable, task2 is still waiting
        assert task_is_runnable(task1)
        assert task_is_blocked(task2)
        await task_interrupt(task1, InterruptException())
        assert await task1 == 0
        # task2 is now runnable, it should have got the lock instead of 1 which
        # was interrupted
        if not task_is_runnable(task2):
            task2.cancel()
            assert False, "task2 should be runnable"
        assert task_is_runnable(task2)
        assert await task2 == 1

    @pytest.mark.parametrize("base", [asyncio.Semaphore, asyncio.BoundedSemaphore])
    async def test_cancelled_semaphore_acquire(self, ctask, base):
        """
        Test that a Task can be interrupted when acquiring a mutex,
        even in the critical phase while runnable after being awoken,
        leaving the mutex in a consistent state.
        """
        sem = base()

        async def func():
            try:
                await sem.acquire()
            except InterruptException:
                return 0
            sem.release()
            return 1

        await sem.acquire()
        task1 = create_task(ctask, func())
        task2 = create_task(ctask, func())
        await asyncio.sleep(0)
        # both tasks are waiting on the lock, task1 is first in the queue
        sem.release()
        # task1 is now runnable, task2 is still waiting
        assert task_is_runnable(task1)
        assert task_is_blocked(task2)
        await task_interrupt(task1, InterruptException())
        assert await task1 == 0
        # task2 is now runnable, it should have got the lock instead of 1 which
        # was interrupted
        if not task_is_runnable(task2):
            task2.cancel()
            assert False, "task2 should be runnable"
        assert task_is_runnable(task2)
        assert await task2 == 1

    @pytest.mark.xfail(
        sys.version_info < (3, 13),
        reason="regular condition can only deal with 'CancelledError' on Python < 3.13",
    )
    async def test_cancelled_condition_wait_acquire_regular(self, ctask):
        await self._cancelled_condition_wait_acquire(ctask, asyncio.Condition())

    async def test_cancelled_condition_wait_acquire_interrupt(self, ctask, icondtype):
        await self._cancelled_condition_wait_acquire(ctask, icondtype())

    async def _cancelled_condition_wait_acquire(self, ctask, cond):
        """
        Test that interrupting task doing a wait() on a condition,
        after it has been awoken and waiting to re-aquire the lock,
        successfully acquires the lock, while raising the exception
        """

        wake = False

        async def func():
            async with cond:
                with pytest.raises(InterruptException):
                    await cond.wait_for(lambda: wake)
                print("task woke up")
            # leaving the context manager releases the lock, and if it is not already
            # held, we will get an error
            print("task re-acquireding lock")

        task1 = create_task(ctask, func())
        await asyncio.sleep(0)
        # Task is waiting on the condition
        await cond.acquire()
        wake = True
        cond.notify()
        await asyncio.sleep(0)
        # task is now trying to re-acquire the lock
        cond.release()
        # send it an interrupt while on the runnable queue to return from lock.acquire()
        await task_interrupt(task1, InterruptException())
        # task should finish
        assert await task1 is None


@pytest.mark.parametrize("ctask", [True, False], ids=["ctask", "pytask"])
class TestTimeout:
    @pytest.mark.parametrize("timeout", [0.0, 0.05, -1])
    async def test_sleep(self, ctask, timeout):
        async def task():
            with pytest.raises(asyncio.TimeoutError):
                async with task_timeout(timeout):
                    await asyncio.sleep(0.1)

        task = create_task(ctask, task())
        await task

    async def test_nosleep(self, ctask):
        async def task():
            async with task_timeout(0.0):
                pass

        task = create_task(ctask, task())
        await task

    async def test_await_task(self, ctask):
        async def task1():
            await asyncio.sleep(0.1)
            return "ok"

        async def task2():
            t = asyncio.create_task(task1(), name="task1")
            with pytest.raises(asyncio.TimeoutError):
                async with task_timeout(0.05):
                    await t
            assert task_is_blocked(t)
            assert await t == "ok"

        task = create_task(ctask, task2(), name="task2")
        await task

    async def test_nested(self, ctask):
        """Test that nested timeouts work as expected."""

        async def inner():
            # The inner timout should not trigger, as the
            # outer timeout should trigger first.
            try:
                async with task_timeout(0.1):
                    await asyncio.sleep(0.2)
            except BaseException as err:
                assert not isinstance(err, asyncio.TimeoutError)
                raise
            assert False, "should not get here"

        async def outer():
            # The outer timeout should trigger first

            with pytest.raises(asyncio.TimeoutError):
                async with task_timeout(0.01):
                    await inner()

        task = create_task(ctask, outer())
        await task

    async def test_sleep_none(self, ctask):
        async def task():
            async with task_timeout(None):
                await asyncio.sleep(0.01)

        task = create_task(ctask, task())
        await task
