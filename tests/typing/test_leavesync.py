from __future__ import annotations

from asynkit import await_sync, leavesync


@leavesync
def blocking_read(value: int) -> str:
    return f"payload:{value}"


async def fetch(value: int) -> str:
    return await blocking_read(value)


def accepts_leavesync() -> None:
    result: str = await_sync(fetch(3))
    _ = result
