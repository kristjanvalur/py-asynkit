import asyncio
import async_df


async def request(result="request", log=[], delay=0.01):
    log.append(result)
    await asyncio.sleep(delay)
    log.append(result)
    return result


async def two_requests(result="two_request", log=[], delay=0.01):
    log.append(result)
    r1 = request(result="r1", log=log)
    r2 = request(result="r2", log=log, delay=0.02)


async def test_nostart():
    future = await async_df.nostart(request())
    r = await(future)
    assert r == "request"


async def test_normal_simple():
    log = []
    future = request(log=log)
    log.append(1)
    await future
    assert log == [1, "request", "request"]


async def test_start_simple():
    log = []
    future = request(log=log)
    future = await async_df.start(future)
    log.append(1)
    await future
    assert log == ["request", 1, "request"]
