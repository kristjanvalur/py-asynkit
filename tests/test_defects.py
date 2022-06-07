import asyncio
import pytest
import types
import traceback


@types.coroutine
def myawait(coro):
    try:
        val = coro.send(None)
    except StopIteration as e:
        return e.value
    while True:
        try:
            val = yield val
        except BaseException as e:
            try:
                val = coro.throw(e)
            except StopIteration as e:
                return e.value
        else:
            try:
                val = coro.send(val)
            except StopIteration as e:
                return e.value

async def realawait(coro):
    return await coro

async def bas(result):
    return await bar(result)

async def foo1(result, n=2):
    if n:
        return await foo1(result, n-1)
    return await bas(result)

async def foo2(result, n=2):
    if n:
        return await foo2(result, n-1)
    return await realawait(bar(result))

async def foo3(result, n=2):
    if n:
        return await foo3(result, n-1)
    return await myawait(bar(result))

async def bar(result):
    try:
        await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        traceback.print_stack(limit=5)
        result.append(False)
        result.append(traceback.format_stack())
    else:
        traceback.print_stack(limit=5)
        result.append(True)
        result.append(traceback.format_stack())
   
@pytest.mark.parametrize("func", [foo1, foo2, foo3])
async def test_regular(func):
    result = []
    t = asyncio.Task(func(result))
    await asyncio.sleep(0)
    await t
    ok, stack = result
    assert ok
    assert len(stack) > 5

@pytest.mark.xfail()
@pytest.mark.parametrize("func", [foo1, foo2, foo3])
async def test_truncated(func):
    result = []
    t = asyncio.Task(func(result))
    await asyncio.sleep(0)
    t.cancel()
    await t
    ok, stack = result
    assert not ok
    assert len(stack) > 5
