import asyncio
import async_df

async def dummy_request(result="dummy_request", log=[], delay=0.01):
    log.append(result)
    await asyncio.sleep(delay)
    log.append(result)
    return result


async def test_normal_simple():
    log = []
    future = dummy_request(log=log)
    log.append(1)
    await future
    assert log == [1, "dummy_request", "dummy_request"]