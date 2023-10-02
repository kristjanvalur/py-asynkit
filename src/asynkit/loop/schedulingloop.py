from abc import ABC, abstractmethod
from asyncio import Handle
from contextvars import Context
from typing import Any, Callable, Iterable, Optional, Set

from .types import QueueType, TaskAny

"""
Here we define a certain base class for event loops which
implement extended scheduling primitives.
"""


class AbstractSimpleSchedulingLoop(ABC):
    """
    This class represents the operations needed for a simple loop
    with scheduled callbacks, to provide simple rescheduing features
    without assuming too much about the implementation.  The implementation
    might, for example, have priority scheduling.
    The loop is not assumed to have a fixed order of excecution but it
    must support scheduling _at_ a specific low position, 0 or 1, whereby
    it recognises the _next_ callback, and the second callback, and so on,
    and respects that if asked.
    """

    @abstractmethod
    def queue_len(self) -> int:
        """Get the length of the queue"""
        ...

    @abstractmethod
    def queue_items(self) -> Iterable[Handle]:
        """Return the scheduled callbacks in the loop.
        The elements are returned in the order they will be called."""
        ...

    @abstractmethod
    def queue_find(
        self, key: Callable[[Handle], bool], remove: bool = False
    ) -> Optional[Handle]:
        """Find a callback in the queue and return its handle.
        Returns None if not found.  if `remove` is true, it is also
        removed from the queue."""
        ...

    @abstractmethod
    def queue_remove(self, handle: Handle) -> None:
        """Remove a callback from the queue, identified by its handle.
        raises ValueError if not found."""
        ...

    @abstractmethod
    def queue_insert(self, handle: Handle) -> None:
        """Insert a callback into the queue at the default position"""
        ...

    @abstractmethod
    def queue_insert_at(self, handle: Handle, pos: int) -> None:
        """Insert a callback into the queue at position 'pos'.
        'pos' is typically a low number, 0 or 1."""
        ...

    @abstractmethod
    def call_at(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None
    ) -> Handle:
        """Arrange for a callback to be inserted at position 'pos' near the the head of
        the queue to be called soon.  'pos' is typically a low number, 0 or 1.
        """
        ...

    # helpers to find tasks from handles and to find certain handles
    # in the queue
    @abstractmethod
    def task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        """
        Extract the runnable Task object
        from its scheduled __step() callback.  Returns None if the
        Handle does not represent a runnable Task.
        """
        ...

    @abstractmethod
    def task_key(self, task: TaskAny) -> Callable[[Handle], bool]:
        """
        Return a key function which can be used to find a task in the queue.
        """
        ...



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

    # deprecated, we don't want to work with indices
    @abstractmethod
    def ready_index(self, task: TaskAny) -> int:
        """
        Look for a runnable task in the ready queue. Return its index if found
        or raise a ValueError
        """
        ...

    # deprecated, we don't want to work with indices
    @abstractmethod
    def ready_pop(self, pos: int = -1) -> Handle:
        """Pop an element off the ready list at the given position."""
        ...

    @abstractmethod
    def ready_len(self) -> int:
        """Get the length of the runnable queue"""
        ...

    @abstractmethod
    def ready_remove(self, task: TaskAny) -> Optional[Handle]:
        """Find a Task in the ready queue.  Remove and return its handle
        if present or return None.
        """
        ...

    # deprecated, frivolous
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
    def task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
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
