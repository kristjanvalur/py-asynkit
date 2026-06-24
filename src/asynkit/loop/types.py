from __future__ import annotations

from asyncio import AbstractEventLoop, Future, Handle, Task
from collections import deque
from typing import TYPE_CHECKING, Any

__all__ = [
    "FutureAny",
    "LoopType",
    "QueueType",
    "TaskAny",
]

if TYPE_CHECKING:
    TaskAny = Task[Any]
    FutureAny = Future[Any]
else:
    TaskAny = Task
    FutureAny = Future

LoopType = AbstractEventLoop
QueueType = deque[Handle]
