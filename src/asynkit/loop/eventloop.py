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
    TypeVar,
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

    class _Base(asyncio.base_events.BaseEventLoop):
        _ready: Deque[Handle]

else:
    TaskAny = Task
    FutureAny = Future
    _Base = object

T = TypeVar("T")


class SchedulingMixin(AbstractSchedulingLoop, _Base):
    """
    A mixin class adding features to the base event loop.
    """

    def get_ready_queue(self) -> Deque[Handle]:
        """
        Default implementation to get the Ready Queue of the loop.
        Subclassable by other implementations.
        """
        return self._ready

    # AbstractSchedulingLoop methods

    def queue_len(self) -> int:
        """Get the length of the runnable queue"""
        return len(self.get_ready_queue())

    def queue_items(self) -> Iterable[Handle]:
        return self.get_ready_queue()

    def queue_find(
        self, key: Callable[[Handle], bool], remove: bool = False
    ) -> Optional[Handle]:
        return default.queue_find(self.get_ready_queue(), key, remove)

    def queue_insert(self, handle: Handle) -> None:
        self.get_ready_queue().append(handle)

    def queue_insert_pos(self, handle: Handle, position: int) -> None:
        self.get_ready_queue().insert(position, handle)

    def queue_remove(self, in_handle: Handle) -> None:
        return default.queue_remove(self.get_ready_queue(), in_handle)

    def call_pos(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None
    ) -> Handle:
        return default.call_pos(self, position, callback, *args, context=context)

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
