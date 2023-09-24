import asyncio
from decimal import DivisionByZero

import pytest

from asynkit.experimental.interrupt import create_pytask, task_interrupt, task_timeout
from asynkit.scheduling import task_is_blocked, task_is_runnable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("interrupt", [True, False])
async def test_interrupt(interrupt):
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
            with pytest.raises(DivisionByZero):
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
        await task_interrupt(task, DivisionByZero())
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


async def test_interrupt_sleep():
    """Test that we can interrupt a task which is sleeping."""
    # create a task, have it wait on sleep
    w = asyncio.Event()
    state = "starting"

    async def task():
        nonlocal state
        assert state == "starting"
        state = "waiting"
        w.set()
        with pytest.raises(DivisionByZero):
            await asyncio.sleep(0.01)
        assert state == "interrupting"
        state = "interrupted"

    task = create_pytask(task())
    await w.wait()
    assert state == "waiting"
    state = "interrupting"
    await task_interrupt(task, DivisionByZero())
    assert state == "interrupted"
    # wait a bit too, to see if the sleep has an side effects
    await asyncio.sleep(0.02)
    await task


@pytest.mark.parametrize("interrupt", [True, False])
async def test_interrupt_immediate(interrupt):
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
            with pytest.raises(DivisionByZero):
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
        await task_interrupt(task, DivisionByZero())
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


async def test_interrupt_runnable():
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
        with pytest.raises(DivisionByZero):
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
    await task_interrupt(task, DivisionByZero())
    assert state == "done"
    assert task.done()
    assert task2.done()
    await task
    await task2


async def test_interrupt_await_task():
    """Test that we can interrupt a task which is waiting on another task."""
    w = asyncio.Event()

    async def task1():
        await asyncio.sleep(0.1)
        return "ok"

    async def task2(wait_for):
        w.set()
        with pytest.raises(DivisionByZero):
            await wait_for

    task1 = asyncio.create_task(task1())
    task2 = create_pytask(task2(task1))
    await w.wait()
    assert task_is_blocked(task2)
    await task_interrupt(task2, DivisionByZero())
    assert task2.done()
    assert task_is_blocked(task1)
    task1.cancel()


async def test_interrupt_self():
    """Test that we cannot interrupt self."""

    async def task():
        with pytest.raises(RuntimeError) as err:
            await task_interrupt(asyncio.current_task(), DivisionByZero())
        assert err.match("cannot interrupt self")

    task = create_pytask(task())
    await task


async def test_interrupt_cancelled():
    """Test that we can interrupt a cancelled task
    which hasn't finished its cancellation."""
    e = asyncio.Event()

    async def task():
        await e.wait()

    task = create_pytask(task())
    await asyncio.sleep(0)
    assert task_is_blocked(task)
    task.cancel()
    assert task_is_runnable(task)
    await task_interrupt(task, DivisionByZero())
    with pytest.raises(DivisionByZero):
        await task


async def test_interrupt_done():
    """Test that we cannot interrupt a task which is done."""

    async def task():
        pass

    task = create_pytask(task())
    await asyncio.sleep(0)
    assert task.done()
    with pytest.raises(RuntimeError) as err:
        await task_interrupt(task, DivisionByZero())
    assert err.match("cannot interrupt task which is done")


async def test_interrupt_new():
    """Teest that we can interrupt a task which hasn't started yet."""

    async def task():
        pass

    task = create_pytask(task())
    assert not task.done()
    await task_interrupt(task, DivisionByZero())
    with pytest.raises(DivisionByZero):
        await task


async def test_timeout_sleep():
    async def task():
        with pytest.raises(asyncio.TimeoutError):
            async with task_timeout(0.05):
                await asyncio.sleep(0.1)

    task = create_pytask(task())
    await task


async def test_timeout_await_task():
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


async def test_nested_timeouts():
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
