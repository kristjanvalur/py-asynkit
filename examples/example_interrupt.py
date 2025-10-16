import asyncio

import pytest

from asynkit.experimental import interrupt

"""
This example demonstrates how to use the interrupt feature of the
experimental package.
"""

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Interrupt(Exception):
    caller = None


async def test_stop_doing_that():
    """
    This example shows how we can use task_interrupt()
    to immediately send an exception to a task in a certain
    state, and know how it has got the interrupt delivered by
    the time we have awaited.
    """

    async def do_something():
        nonlocal state
        while True:
            state = "doing it"
            try:
                await asyncio.sleep(1)
            except Interrupt:
                break
        state = "not doing it"
        await asyncio.sleep(1)
        state = "finished"

    task = interrupt.create_pytask(do_something())
    state = "normal"
    while state != "doing it":
        await asyncio.sleep(0)
    await interrupt.task_interrupt(task, Interrupt())
    assert state == "not doing it"


async def test_task_kill():
    """This example shows how we can kill a task immediately."""

    async def do_something():
        while True:
            try:
                await asyncio.sleep(1)
            except Interrupt:
                break

    task1 = interrupt.create_pytask(do_something())
    task2 = interrupt.create_pytask(do_something())
    await asyncio.sleep(0)
    assert not task1.done()
    assert not task2.done()
    task1.cancel()
    assert not task1.done()
    await interrupt.task_interrupt(task2, asyncio.CancelledError())
    assert task2.done()
    # task1 is also probably done by now.
    assert task1.done()


async def test_interrupt_ack():
    """Show how an interrupted task can send an acknowledgement.
    by interrupting the interruptor.
    """

    async def send_ack():
        try:
            while True:
                await asyncio.sleep(1)
        except Interrupt as e:
            if e.caller is not None:
                print("sending ack")
                await interrupt.task_interrupt(e.caller, EOFError())

    async def nosend_ack():
        try:
            while True:
                await asyncio.sleep(1)
        except Interrupt:
            pass

    task1 = interrupt.create_pytask(send_ack())
    task2 = interrupt.create_pytask(nosend_ack())

    async def interruptor():
        my_interrupt = Interrupt()
        my_interrupt.caller = asyncio.current_task()
        r = []
        for t in [task1, task2]:
            print(t)
            assert not t.done()
            try:
                await interrupt.task_interrupt(t, my_interrupt)
            except EOFError:
                # the target interruped us back
                r.append("ack")
            else:
                r.append("noack")
        return r

    await asyncio.sleep(0)
    r = await interrupt.create_pytask(interruptor())
    assert r == ["ack", "noack"]


async def test_task_timeout():
    """show the interrupt.timeout contextmanager in action"""
    with pytest.raises(asyncio.TimeoutError):
        async with interrupt.task_timeout(0.1):
            try:
                await asyncio.sleep(1)
                assert False, "should not get here"
            except BaseException as e:
                # it interrupts us with a base exception
                assert isinstance(e, interrupt.TimeoutInterrupt)
                raise
