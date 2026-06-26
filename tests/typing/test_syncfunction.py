from __future__ import annotations

from asynkit import syncfunction


@syncfunction
async def sync_label(value: int, *, prefix: str = "item") -> str:
    return f"{prefix}:{value}"


async def async_count(value: str) -> int:
    return len(value)


sync_count = syncfunction(async_count)


def accepts_sync_functions() -> None:
    label: str = sync_label(3, prefix="id")
    count: int = sync_count("abc")

    _ = label
    _ = count
