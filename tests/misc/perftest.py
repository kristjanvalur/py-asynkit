import asyncio
from types import coroutine
import time

# compare speed of returning a Future and a coroutine to get a non-blocking value

future = None
exception = StopIteration(1)


def get_future():
    if exception is not None:
        future = asyncio.Future()
        if isinstance(exception, StopIteration):
            future.set_result(exception.value)
        return future


@coroutine
def get_coro():
    _, exc = future, exception
    # process any exception generated by the initial start
    if exc:
        if isinstance(exc, StopIteration):
            return exc.value
        raise exc
    yield 1


async def run1():
    f = get_future()
    return await f


async def run2():
    c = get_coro()
    return await c


async def main():
    n = 100000
    t0 = time.time()
    for i in range(n):
        await run1()
    t1 = time.time()

    for i in range(n):
        await run2()
    t2 = time.time()

    print(t1 - t0, t2 - t1)


asyncio.run(main())
