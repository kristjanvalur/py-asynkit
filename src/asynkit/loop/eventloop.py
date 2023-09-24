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
    Optional,
    Set,
    TypeVar,
)

from ..tools import deque_pop
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

    def get_task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        """
        Default implementation to extract the runnable Task object
        from its scheduled __step() callback.  Returns None if the
        Handle does not represent a runnable Task. Can be subclassed
        for other non-default Task implementations.
        """
        return default.get_task_from_handle_impl(handle)

    def ready_len(self) -> int:
        """Get the length of the runnable queue"""
        return len(self.get_ready_queue())

    def ready_rotate(self, n: int) -> None:
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called next.

        A negative value will rotate the queue to the left, placing the next
        entry at the end. A Positive values will move callbacks from the end
        to the front, making them next in line.
        """
        self.get_ready_queue().rotate(n)

    def ready_pop(self, pos: int = -1) -> Handle:
        """Pop an element off the ready list at the given position."""
        return deque_pop(self.get_ready_queue(), pos)

    def ready_insert(self, pos: int, element: Handle) -> None:
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        self.get_ready_queue().insert(pos, element)

    def ready_append(self, element: Handle) -> None:
        """Append a previously popped `element` to the end of the queue."""
        self.get_ready_queue().append(element)

    def call_insert(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None
    ) -> Handle:
        """Arrange for a callback to be inserted at `position` in the queue to be
        called later.
        """
        return default.call_insert_impl(
            self, position, callback, *args, context=context
        )

    def ready_index(self, task: TaskAny) -> int:
        """
        Look for a runnable task in the ready queue. Return its index if found
        or raise a ValueError
        """
        return default.ready_index_impl(self._ready, task)

    def ready_remove(self, task: TaskAny) -> Optional[Handle]:
        """Find a Task in the ready queue.  Remove and return its handle
        if present or return None.
        """
        idx = default.ready_find_impl(self._ready, task)
        if idx >= 0:
            return deque_pop(self._ready, idx)
        return None

    def ready_tasks(self) -> Set[TaskAny]:
        """
        Return a set of all all runnable tasks in the ready queue.
        """
        return default.ready_tasks_impl(self._ready)


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
