from __future__ import annotations

from asynkit import await_sync, sync_drive_async


@sync_drive_async
def blocking_read(value: int) -> str:
    return f"payload:{value}"


async def fetch(value: int) -> str:
    return await blocking_read(value)


def accepts_sync_drive_async() -> None:
    result: str = await_sync(fetch(3))
    _ = result
