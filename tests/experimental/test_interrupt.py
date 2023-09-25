import asyncio

import pytest

from asynkit.experimental import (
    create_pytask,
    task_interrupt,
    task_throw,
    task_timeout,
)
from asynkit.loop.default import PyTask
from asynkit.scheduling import task_is_blocked, task_is_runnable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestThrow:
    """Test the task_throw() experimental function."""

    @pytest.mark.parametrize("immediate", [True, False])
    async def test_event(self, immediate):
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

        task = create_pytask(task())
        await w.wait()
        assert self.state == "waiting"
        task_throw(task, ZeroDivisionError(), immediate=immediate)
        assert task_is_runnable(task)
        self.state = "interrupting"
        await task
        assert self.state == "interrupted"
        assert task.done()

    @pytest.mark.parametrize("immediate", [True, False])
    async def test_execution_order(self, immediate):
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
            if immediate:
                assert self.state == "interrupting"
            else:
                # other task ran first
                assert self.state == "task2"
            self.state = "interrupted"

        task = create_pytask(task())
        await w.wait()
        assert self.state == "waiting"

        async def task2():
            if immediate:
                # interrupted task ran first
                assert self.state == "interrupted"
            else:
                assert self.state == "interrupting"
            self.state = "task2"

        task2 = asyncio.create_task(task2())
        task_throw(task, ZeroDivisionError(), immediate=immediate)
        assert task_is_runnable(task)
        self.state = "interrupting"
        await task
        if immediate:
            assert self.state == "task2"  # interrupted task ran first
        else:
            assert self.state == "interrupted"
        assert task.done()

    async def test_ctask(self):
        if PyTask is asyncio.Task:
            pytest.skip("no CTask")

        async def task():
            pass

        t = asyncio.create_task(task())
        with pytest.raises(TypeError) as err:
            task_throw(t, ZeroDivisionError())
        assert err.match("python task")


class TestInterrupt:
    @pytest.mark.parametrize("interrupt", [True, False])
    async def test_event(self, interrupt):
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

        task = create_pytask(task())
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

    async def test_sleep(self):
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

        task = create_pytask(task())
        await w.wait()
        assert state == "waiting"
        state = "interrupting"
        await task_interrupt(task, ZeroDivisionError())
        assert state == "interrupted"
        # wait a bit too, to see if the sleep has an side effects
        await asyncio.sleep(0.02)
        await task

    @pytest.mark.parametrize("interrupt", [True, False])
    async def test_execution_order(self, interrupt):
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

        task = create_pytask(task())
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

    async def test_runnable(self):
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

        task = create_pytask(task())
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

    async def test_interrupt_await_task(self):
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
        task2 = create_pytask(task2(task1))
        await w.wait()
        assert task_is_blocked(task2)
        await task_interrupt(task2, ZeroDivisionError())
        assert task2.done()
        assert task_is_blocked(task1)
        task1.cancel()

    async def test_self(self):
        """Test that we cannot interrupt self."""

        async def task():
            with pytest.raises(RuntimeError) as err:
                await task_interrupt(asyncio.current_task(), ZeroDivisionError())
            assert err.match("cannot interrupt self")

        task = create_pytask(task())
        await task

    async def test_done(self):
        """Test that we cannot interrupt a task which is done."""

        async def task():
            pass

        task = create_pytask(task())
        await asyncio.sleep(0)
        assert task.done()
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt task which is done")

    async def test_new(self):
        """Teest that we can interrupt a task which hasn't started yet."""

        async def task():
            pass

        task = create_pytask(task())
        assert not task.done()
        await task_interrupt(task, ZeroDivisionError())
        with pytest.raises(ZeroDivisionError):
            await task

    async def test_queue(self):
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

        t = create_pytask(task())
        await w.wait()
        assert task_is_blocked(t)
        q.put_nowait(1)
        assert task_is_runnable(t)
        # task has been awoken, we interrupt it.
        await task_interrupt(t, ZeroDivisionError())
        # after handling the interrupt, the task tries again
        assert await t == 1

    async def test_cancelled_task(self):
        """Test that we cannot interrupt a task which has been cancelled."""
        e = asyncio.Event()

        async def task():
            await e.wait()

        task = create_pytask(task())
        await asyncio.sleep(0)
        assert task_is_blocked(task)
        task.cancel()
        assert task_is_runnable(task)
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt a cancelled task")
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_cancelled_runnable(self):
        """Test that we cannot interrupt a task which was cancelled
        while in a runnable state after sleep(0), i.e. it paused not
        due to waiting on a real future
        """

        async def task():
            # this just places it in the ready queue again
            await asyncio.sleep(0)

        task = create_pytask(task())
        await asyncio.sleep(0)
        assert task_is_runnable(task)
        task.cancel()
        assert task_is_runnable(task)
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(task, ZeroDivisionError())
        assert err.match("cannot interrupt a cancelled task")
        with pytest.raises(asyncio.CancelledError):
            await task


class TestTimeout:
    async def test_sleep(self):
        async def task():
            with pytest.raises(asyncio.TimeoutError):
                async with task_timeout(0.05):
                    await asyncio.sleep(0.1)

        task = create_pytask(task())
        await task

    async def test_await_task(self):
        async def task1():
            await asyncio.sleep(0.1)
            return "ok"

        async def task2():
            t = asyncio.create_task(task1())
            with pytest.raises(asyncio.TimeoutError):
                async with task_timeout(0.05):
                    await t
            assert task_is_blocked(t)
            assert await t == "ok"

        task = create_pytask(task2())
        await task

    async def test_nested(self):
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

        task = create_pytask(outer())
        await task

    async def test_ctask(self):
        if PyTask is asyncio.Task:
            pytest.skip("no CTask")

        with pytest.raises(TypeError) as err:
            async with task_timeout(0.1):
                await asyncio.sleep(0.2)
        assert err.match("python task")
