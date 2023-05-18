from asyncio import AbstractEventLoop, Handle, Task
from typing import TYPE_CHECKING, Any, Deque

if TYPE_CHECKING:

    TaskAny = Task[Any]
else:
    TaskAny = Task

LoopType = AbstractEventLoop
QueueType = Deque[Handle]
