import asyncio
from inspect import isawaitable


class HybridMiddleWare:
    """Hybrid middleware, assuming optionally async callables
    and returning optionally awaitable results
    """

    def __init__(self, data_getter):
        self.data_getter = data_getter

    def get_processed_data(self):
        raw_data = self.data_getter()
        if isawaitable(raw_data):

            # Create async helper method to be returned
            async def async_helper():
                raw_data2 = await raw_data
                return self.process_data(raw_data2)  # duplicate code

            return async_helper()
        return self.process_data(raw_data)  # duplicate code

    def process_data(self, raw_data):
        return raw_data + raw_data


async def async_client():
    async def data_getter():
        return "hello"

    data = HybridMiddleWare(data_getter=data_getter).get_processed_data()
    data = await data if isawaitable(data) else data
    assert data == "hellohello"


def sync_client():
    def data_getter():
        return "hello"

    data = HybridMiddleWare(data_getter=data_getter).get_processed_data()
    if isawaitable(data):
        raise RuntimeError("could not complete synchronously")
    assert data == "hellohello"


if __name__ == "__main__":
    sync_client()
    asyncio.run(async_client())
