from asyncio import AbstractEventLoop, Future, Handle, Task
from typing import TYPE_CHECKING, Any, Deque

if TYPE_CHECKING:
    TaskAny = Task[Any]
    FutureAny = Future[Any]
else:
    TaskAny = Task
    FutureAny = Future

LoopType = AbstractEventLoop
QueueType = Deque[Handle]
