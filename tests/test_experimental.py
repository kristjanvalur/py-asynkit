import asyncio
import pytest
from asynkit.experimental import *


async def test_callback():
    async def func(arg):
        await signals(asyncio.sleep(0.1))
        return arg

    mytask = MyTask(func("ok"))
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

    mytask = MyTask(func("ok"))
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
        await signals(asyncio.sleep(0.1))
        return arg

    async def func2(arg):
        return await func(arg)

    async def func3(arg):
        return await func2(arg)

    mytask = MyTask(func3("ok"))
    await asyncio.sleep(0)

    # s = mytask.print_stack()
    stack = mytask.get_stack()
    assert "code func3" in str(stack[0])
    assert "code func" in str(stack[-1])
    assert await mytask == "ok"
