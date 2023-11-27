from __future__ import annotations

import asyncio
import asyncio.base_events
import contextlib
import sys
from asyncio import AbstractEventLoop, AbstractEventLoopPolicy, Future, Handle, Task
from contextvars import Context
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Deque,
    Generator,
    Iterable,
    Optional,
    Protocol,
    TypeVar,
    cast,
)

from . import default
from .schedulingloop import AbstractSchedulingLoop

"""This module contains a mixin to extend event loops
with scheduling features."""

__all__ = [
    "SchedulingMixin",
    "SchedulingSelectorEventLoop",
    "SchedulingEventLoopPolicy",
    "DefaultSchedulingEventLoop",
    "event_loop_policy",
]

if TYPE_CHECKING:
    TaskAny = Task[Any]
    FutureAny = Future[Any]

else:
    TaskAny = Task
    FutureAny = Future

T = TypeVar("T")


class HasReadyQueue(Protocol):
    @property
    def _ready(self) -> Deque[Handle]:
        ...  # pragma: no cover

    def get_ready_queue(self: HasReadyQueue) -> Deque[Handle]:
        ...  # pragma: no cover


class SchedulingMixin(AbstractSchedulingLoop):
    """
    A mixin class adding features to the base event loop.
    """

    def get_ready_queue(self: HasReadyQueue) -> Deque[Handle]:
        """
        Default implementation to get the Ready Queue of the loop.
        Subclassable by other implementations.
        """
        return self._ready

    # AbstractSchedulingLoop methods

    def queue_len(self: HasReadyQueue) -> int:
        """Get the length of the runnable queue"""
        return len(self.get_ready_queue())

    def queue_items(self: HasReadyQueue) -> Iterable[Handle]:
        return self.get_ready_queue()

    def queue_find(
        self: HasReadyQueue, key: Callable[[Handle], bool], remove: bool = False
    ) -> Optional[Handle]:
        return default.queue_find(self.get_ready_queue(), key, remove)

    def queue_insert(self: HasReadyQueue, handle: Handle) -> None:
        self.get_ready_queue().append(handle)

    def queue_insert_pos(self: HasReadyQueue, handle: Handle, position: int) -> None:
        self.get_ready_queue().insert(position, handle)

    def queue_remove(self: HasReadyQueue, in_handle: Handle) -> None:
        return default.queue_remove(self.get_ready_queue(), in_handle)

    def call_pos(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        loop = cast(AbstractEventLoop, self)
        return default.call_pos(loop, position, callback, *args, context=context)

    def task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        return default.task_from_handle(handle)


class SchedulingSelectorEventLoop(asyncio.SelectorEventLoop, SchedulingMixin):
    pass


DefaultSchedulingEventLoop = SchedulingSelectorEventLoop

# The following code needs coverage and typing exceptions
# to lint cleanly on linux where there is no ProactorEventLoop
if hasattr(asyncio, "ProactorEventLoop"):  # pragma: no coverage

    class SchedulingProactorEventLoop(
        asyncio.ProactorEventLoop, SchedulingMixin  # type: ignore
    ):
        pass

    __all__.append("SchedulingProactorEventLoop")

    if sys.platform == "win32":  # pragma: no coverage
        DefaultSchedulingEventLoop = SchedulingProactorEventLoop  # type: ignore


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> AbstractEventLoop:
        return DefaultSchedulingEventLoop()  # type: ignore


@contextlib.contextmanager
def event_loop_policy(
    policy: Optional[AbstractEventLoopPolicy] = None,
) -> Generator[AbstractEventLoopPolicy, Any, None]:
    policy = policy or SchedulingEventLoopPolicy()
    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(policy)
    try:
        yield policy
    finally:
        asyncio.set_event_loop_policy(previous)
