import asyncio
import pytest
import asynkit
from asynkit.experimental import *


async def test_callback():
    async def func(arg):
        await await_with_signals(asyncio.sleep(0.1))
        return arg

    mytask = TaskEx(func("ok"))
    await asyncio.sleep(0)

    val = ""

    def cb(a, b):
        nonlocal val
        val = f"I am cb {a} and {b}"

    r = mytask.execute_callback(cb, "foo", "bar")
    assert val == "I am cb foo and bar"

    assert await (mytask) == "ok"


@pytest.mark.parametrize("delay", [0, 0.1])
async def test_callback_sleep(delay):
    async def func(arg):
        await sleep_ex(delay)
        return arg

    mytask = TaskEx(func("ok"))
    await asyncio.sleep(0)

    val = ""

    def cb(a, b):
        nonlocal val
        val = f"I am cb {a} and {b}"

    r = mytask.execute_callback(cb, "foo", "bar")
    assert val == "I am cb foo and bar"

    assert await (mytask) == "ok"


async def test_callback_nohandler():
    async def func(arg):
        await asyncio.sleep(0.1)
        # await tasksignalhandler(asyncio.sleep(0.1))
        return arg

    mytask = TaskEx(func("ok"))
    await asyncio.sleep(0)

    val = ""

    def cb(a, b):
        nonlocal val
        val = f"I am cb {a} and {b}"

    with pytest.raises(ValueError):
        r = mytask.execute_callback(cb, "foo", "bar")
        assert val == "I am cb foo and bar"

    with pytest.raises(TaskCallbackSignal):
        assert await (mytask) == "ok"


async def test_stack():
    async def func(arg):
        await await_with_signals(asyncio.sleep(0.1))
        return arg

    async def func2(arg):
        return await func(arg)

    async def func3(arg):
        return await func2(arg)

    mytask = TaskEx(func3("ok"))
    await asyncio.sleep(0)

    # s = mytask.print_stack()
    stack = mytask.get_stack()
    assert "code func3" in str(stack[0])
    assert "code func" in str(stack[-1])
    assert await mytask == "ok"


async def test_coro_stack():
    async def a():
        return await b()

    async def b():
        return await asyncio.sleep(0)

    coro = a()
    task = asyncio.create_task(coro)

    await asyncio.sleep(0)
    stack = list(coro_walk_stack(coro))
    # print(stack)
    assert len(stack) >= 2


async def test_coro_stack_eager():
    async def a():
        # see that we pass through our "manual await" code.
        return await asynkit.coro_await(b())

    async def b():
        return await asyncio.sleep(0)

    coro = a()
    task = asyncio.create_task(coro)

    await asyncio.sleep(0)
    stack = list(coro_walk_stack(coro))
    print(stack)
    assert len(stack) >= 2


@pytest.mark.xfail(
    reason="cannot inspect async_generator_asend object for the inner async_generator"
)
async def test_coro_stack_generator():
    async def a():
        # see tht we can pass into an async generator
        async for _ in b():
            pass

    async def b():
        await asyncio.sleep(0)
        yield 1

    coro = a()
    task = asyncio.create_task(coro)

    await asyncio.sleep(0)
    stack = list(coro_walk_stack(coro))
    assert len(stack) >= 2
