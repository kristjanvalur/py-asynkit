from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Handle
from collections.abc import Callable, Iterable
from contextvars import Context
from typing import Any

from .types import TaskAny

"""
Here we define a certain base class for event loops which
implement extended scheduling primitives.
"""


class AbstractSchedulingLoop(ABC):
    """
    This class represents the operations needed for an eventloop
    with scheduled callbacks, to provide simple rescheduling features
    without assuming too much about the implementation.  The implementation
    might, for example, have priority scheduling.
    The loop is not assumed to have a fixed order of execution but it
    must support scheduling at a specific low _position_, 0 or 1, whereby
    it recognizes the _next_ callback, and the second callback, and so on,
    and respects that if asked.
    """

    @abstractmethod
    def queue_len(self) -> int:
        """Get the length of the queue"""
        ...

    @abstractmethod
    def queue_items(self) -> Iterable[Handle]:
        """Return the scheduled callbacks in the loop.
        The elements are returned in the current order in which
        they will be called."""
        ...

    @abstractmethod
    def queue_find(
        self, key: Callable[[Handle], bool], remove: bool = False
    ) -> Handle | None:
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
    def queue_insert_pos(self, handle: Handle, position: int) -> None:
        """Insert a callback into the queue at position 'position'.
        'position' is typically a low number, 0 or 1.  If it is 0, it will
        be the next callback to be called.  If it is 1, it will be the second
        to be called, after the current next callback, and so on."""
        ...

    @abstractmethod
    def call_pos(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> Handle:
        """Arrange for a callback to be inserted at position 'pos' near the head of
        the queue to be called soon.  'position' is typically a low number, 0 or 1.
        This is effectively the same as calling
        `call_soon()`, `queue_remove()` and `queue_insert_pos()` in turn.
        """
        ...

    # helper to find tasks from handles and to find certain handles
    # in the queue
    @abstractmethod
    def task_from_handle(self, handle: Handle) -> TaskAny | None:
        """
        Extract the runnable Task object
        from its scheduled callback.  Returns None if the
        Handle does not represent a callback for a Task.
        """
        ...

    # convenience functions, providing helpful default definitions

    def task_key(self, task: TaskAny) -> Callable[[Handle], bool]:
        """
        Return a key function which can be used to find a task in the queue.
        """
        tk = self.task_from_handle
        return lambda handle: tk(handle) is task

    def queue_tasks(self) -> Iterable[TaskAny]:
        """
        Return the tasks in the queue.
        """
        for handle in self.queue_items():
            task = self.task_from_handle(handle)
            if task is not None:
                yield task
