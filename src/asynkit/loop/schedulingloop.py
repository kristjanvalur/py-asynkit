from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Set
from asyncio import Handle
from contextvars import Context

from .types import TaskAny, QueueType

"""
Here we define a certain base class for event loops which
implement extended scheduling primitives.
"""


class SchedulingLoopBase(ABC):
    @abstractmethod
    def get_loop_ready_queue(self) -> QueueType:
        """
        Default implementation to get the Ready Queue of the loop.
        Subclassable by other implementations.
        """
        ...

    @abstractmethod
    def get_task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        """
        Default implementation to extract the runnable Task object
        from its scheduled __step() callback.  Returns None if the
        Handle does not represent a runnable Task. Can be subclassed
        for other non-default Task implementations.
        """
        ...

    @abstractmethod
    def ready_len(self) -> int:
        """Get the length of the runnable queue"""
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
    def ready_pop(self, pos: int = -1) -> Handle:
        """Pop an element off the ready list at the given position."""
        ...

    @abstractmethod
    def ready_insert(self, pos: int, element: Handle) -> None:
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        ...

    @abstractmethod
    def ready_append(self, element: Handle) -> None:
        """Append a previously popped `element` to the end of the queue."""
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
    def ready_index(self, task: TaskAny) -> int:
        """
        Look for a runnable task in the ready queue. Return its index if found
        or raise a ValueError
        """
        ...

    @abstractmethod
    def ready_tasks(self) -> Set[TaskAny]:
        """
        Return a set of all all runnable tasks in the ready queue.
        """
        ...
