import asyncio

import asynkit


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

    middleware = AsyncMiddleWare(data_getter=asynkit.ensure_corofunc(data_getter))
    assert asynkit.coro_sync(middleware.get_processed_data()) == "hellohello"


if __name__ == "__main__":
    sync_client()
    asyncio.run(async_client())
