from __future__ import annotations

import asyncio
import asyncio.base_events
import contextlib
import sys
from asyncio import AbstractEventLoop, AbstractEventLoopPolicy, Future, Handle, Task
from collections import deque
from collections.abc import Callable, Generator, Iterable
from contextvars import Context
from typing import (
    TYPE_CHECKING,
    Any,
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
    "scheduling_loop_factory",
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
    def _ready(self) -> deque[Handle]: ...  # pragma: no cover

    def get_ready_queue(self: HasReadyQueue) -> deque[Handle]: ...  # pragma: no cover


class SchedulingMixin(AbstractSchedulingLoop):
    """
    A mixin class adding features to the base event loop.
    """

    def get_ready_queue(self: HasReadyQueue) -> deque[Handle]:
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
    ) -> Handle | None:
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
        context: Context | None = None,
    ) -> Handle:
        loop = cast(AbstractEventLoop, self)
        return default.call_pos(loop, position, callback, *args, context=context)

    def task_from_handle(self, handle: Handle) -> TaskAny | None:
        return default.task_from_handle(handle)


class SchedulingSelectorEventLoop(asyncio.SelectorEventLoop, SchedulingMixin):
    pass


DefaultSchedulingEventLoop = SchedulingSelectorEventLoop

# The following code needs coverage and typing exceptions
# to lint cleanly on linux where there is no ProactorEventLoop
if hasattr(asyncio, "ProactorEventLoop"):  # pragma: no coverage

    class SchedulingProactorEventLoop(
        asyncio.ProactorEventLoop,  # type: ignore[name-defined,misc]
        SchedulingMixin,
    ):
        pass

    __all__.append("SchedulingProactorEventLoop")

    if sys.platform == "win32":  # pragma: no coverage
        DefaultSchedulingEventLoop = SchedulingProactorEventLoop  # type: ignore


def scheduling_loop_factory() -> AbstractEventLoop:
    """
    Create a new scheduling event loop.

    Returns an event loop with extended scheduling capabilities. On most
    platforms, this returns a SchedulingSelectorEventLoop. On Windows, it
    returns a SchedulingProactorEventLoop.

    This factory function is the recommended way to create scheduling event
    loops for use with asyncio.run() (Python 3.12+) or asyncio.Runner:

        asyncio.run(main(), loop_factory=asynkit.scheduling_loop_factory)

    For Python 3.10-3.11 compatibility, use the SchedulingEventLoopPolicy
    instead:

        asyncio.set_event_loop_policy(asynkit.SchedulingEventLoopPolicy())
        asyncio.run(main())
    """
    return DefaultSchedulingEventLoop()  # type: ignore


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """
    Event loop policy that creates scheduling event loops.

    Note: Event loop policies are deprecated as of Python 3.14 and will be
    removed in Python 3.16. For Python 3.12+, use scheduling_loop_factory
    with asyncio.run() or asyncio.Runner instead.

    This policy is provided for compatibility with Python 3.10-3.11 and for
    code that hasn't migrated away from the policy system.
    """

    def new_event_loop(self) -> AbstractEventLoop:
        return scheduling_loop_factory()


@contextlib.contextmanager
def event_loop_policy(
    policy: AbstractEventLoopPolicy | None = None,
) -> Generator[AbstractEventLoopPolicy, Any, None]:
    policy = policy or SchedulingEventLoopPolicy()
    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(policy)
    try:
        yield policy
    finally:
        asyncio.set_event_loop_policy(previous)
