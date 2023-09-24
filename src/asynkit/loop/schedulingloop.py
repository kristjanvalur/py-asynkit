from abc import ABC, abstractmethod
from asyncio import Handle
from contextvars import Context
from typing import Any, Callable, Optional, Set

from .types import QueueType, TaskAny

"""
Here we define a certain base class for event loops which
implement extended scheduling primitives.
"""


class AbstractSchedulingLoop(ABC):
    """
    This class represents the low level scheduling operations possible for
    an event loop.
    It may be implemented as a mixin, or as a subclass of the default loop,
    or as a wrapper class which wraps the default loop.
    """

    @abstractmethod
    def get_ready_queue(self) -> QueueType:
        """
        Return the ready queue of the loop.
        Internal method, exposed for unittests.
        May return None if not supported
        """
        ...

    @abstractmethod
    def ready_append(self, element: Handle) -> None:
        """Append a previously popped `element` to the end of the queue."""
        ...

    @abstractmethod
    def ready_insert(self, pos: int, element: Handle) -> None:
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        ...

    @abstractmethod
    def ready_index(self, task: TaskAny) -> int:
        """
        Look for a runnable task in the ready queue. Return its index if found
        or raise a ValueError
        """
        ...

    @abstractmethod
    def ready_len(self) -> int:
        """Get the length of the runnable queue"""
        ...

    @abstractmethod
    def ready_pop(self, pos: int = -1) -> Handle:
        """Pop an element off the ready list at the given position."""
        ...

    @abstractmethod
    def ready_remove(self, task: TaskAny) -> Optional[Handle]:
        """Find a Task in the ready queue.  Remove and return its handle
        if present or return None.
        """
        ...

    @abstractmethod
    def ready_rotate(self, n: int) -> None:
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called next.

        A negative value will rotate the queue to the left, placing the next
        entry at the end. A Positive values will move callbacks from the end
        to the front, making them next in line.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        """
        Extract the runnable Task object
        from its scheduled __step() callback.  Returns None if the
        Handle does not represent a runnable Task.
        Internal method, exposed for unittests.
        May raise NotImplemented if not supported.
        """
        ...

    @abstractmethod
    def ready_tasks(self) -> Set[TaskAny]:
        """
        Return a set of all all runnable tasks in the ready queue.
        """
        ...
