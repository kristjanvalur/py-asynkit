import asyncio

import asynkit

"""
Fully asynchronous middleware, assuming async callables
and returning async results.
When used in synchronous environment, the entire middleware
is invoked using asynkit.await_sync.
"""


class AsyncMiddleWare:
    """Fully asynchronous middleware, assuming async callables"""

    def __init__(self, data_getter):
        self.data_getter = data_getter

    async def get_processed_data(self):
        raw_data = await self.data_getter()
        return self.process_data(raw_data)

    def process_data(self, raw_data):
        return raw_data + raw_data


async def async_client():
    async def data_getter():
        return "hello"

    middleware = AsyncMiddleWare(data_getter=data_getter)
    assert await middleware.get_processed_data() == "hellohello"


def sync_client():
    def data_getter():
        return "hello"

    middleware = AsyncMiddleWare(data_getter=asynkit.asyncfunction(data_getter))
    assert asynkit.await_sync(middleware.get_processed_data()) == "hellohello"


def test_sync():
    sync_client()


def test_async():
    asyncio.run(async_client())


if __name__ == "__main__":
    test_sync()
    test_async()
