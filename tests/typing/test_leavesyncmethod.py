from __future__ import annotations

from asynkit import await_sync, leavesyncmethod


class Base:
    def blocking_read(self, value: int) -> str:
        return f"payload:{value}"

    ablocking_read = leavesyncmethod(blocking_read)


class Derived(Base):
    async def ablocking_read(self, value: int) -> str:
        raise NotImplementedError


def accepts_bound(client: Base) -> None:
    async def fetch() -> str:
        return await client.ablocking_read(3)

    result: str = await_sync(fetch())
    _ = result


async def accepts_unbound(client: Base) -> None:
    result: str = await Base.ablocking_read(client, 3)
    _ = result
