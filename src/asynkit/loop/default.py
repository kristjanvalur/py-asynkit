import asyncio
from asyncio import AbstractEventLoop, Handle, Task
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, Deque, Optional, Set

from ..tools import deque_pop
from .schedulingloop import AbstractSchedulingLoop

"""
Helper methods which work with the default event loop from
Python's asyncio module.
"""

if TYPE_CHECKING:

    TaskAny = Task[Any]
else:
    TaskAny = Task

LoopType = AbstractEventLoop
QueueType = Deque[Handle]


def _get_task_from_handle(
    handle: Handle,
) -> Optional[TaskAny]:
    """
    Extract the runnable Task object
    from its scheduled __step() callback.  Returns None if the
    Handle does not represent a runnable Task.
    """
    # It would be _great_ if a Handle object contained meta information,
    # like the Task it was created for. But it doesn't.
    try:
        task = handle._callback.__self__  # type: ignore
    except AttributeError:
        return None
    if isinstance(task, Task):
        return task
    return None


class SchedulingHelper(AbstractSchedulingLoop):
    def __init__(self, loop: Optional[AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._queue = loop._ready

    def get_ready_queue(self) -> QueueType:
        return self._queue

    def ready_append(self, element: Handle) -> None:
        self._queue.append(element)

    def ready_len(self) -> int:
        return len(self._queue)

    def ready_index(self, task: TaskAny) -> int:
        for i, handle in enumerate(reversed(self._queue)):
            found = _get_task_from_handle(handle)
            if found is task:
                return len(self._queue) - i - 1
        raise ValueError("task not in ready queue")

    def ready_insert(self, pos: int, element: Handle) -> None:
        self._queue.insert(pos, element)

    def ready_pop(self, pos: int = -1) -> Handle:
        return deque_pop(self._queue, pos)

    def ready_rotate(self, n: int) -> None:
        self._queue.rotate(n)

    def call_insert(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        """
        Arrange for a callback to be inserted at `position` in the queue to be
        called later.
        """
        handle = self._loop.call_soon(callback, *args, context=context)
        handle2 = self.ready_pop(-1)
        assert handle2 is handle
        self.ready_insert(position, handle)
        return handle

    def get_task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        return _get_task_from_handle(handle)

    def ready_tasks(self) -> Set[TaskAny]:
        result = set()
        for handle in self._queue:
            task = _get_task_from_handle(handle)
            if task:
                result.add(task)
        return result


def get_ready_queue(loop: Optional[LoopType] = None) -> QueueType:
    """
    Default implementation to get the Ready Queue of the loop.
    Subclassable by other implementations.
    """
    return SchedulingHelper(loop=loop).get_ready_queue()


def get_task_from_handle(
    handle: Handle,
) -> Optional[TaskAny]:
    """
    Extract the runnable Task object
    from its scheduled __step() callback.  Returns None if the
    Handle does not represent a runnable Task.
    """
    return _get_task_from_handle(handle)


def ready_len(loop: Optional[LoopType] = None) -> int:
    """Get the length of the runnable queue"""
    return SchedulingHelper(loop=loop).ready_len()


def ready_rotate(
    n: int,
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """
    Rotate the ready queue.

    The leftmost part of the ready queue is the callback called next.

    A negative value will rotate the queue to the left, placing the next
    entry at the end. A Positive values will move callbacks from the end
    to the front, making them next in line.
    """
    return SchedulingHelper(loop=loop).ready_rotate(n)


def ready_pop(
    pos: int = -1,
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    """Pop an element off the ready list at the given position."""
    return SchedulingHelper(loop=loop).ready_pop(pos)


def ready_insert(
    pos: int,
    element: Handle,
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Insert a previously popped `element` back into the
    ready queue at `pos`"""
    return SchedulingHelper(loop=loop).ready_insert(pos, element)


def ready_append(
    element: Handle,
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Append a previously popped `element` to the end of the queue."""
    return SchedulingHelper(loop=loop).ready_append(element)


def call_insert(
    position: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Optional[Context] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    """
    Arrange for a callback to be inserted at `position` in the queue to be
    called later.
    """
    return SchedulingHelper(loop=loop).call_insert(
        position, callback, *args, context=context
    )


def ready_index(
    task: TaskAny,
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    """
    Look for a runnable task in the ready queue. Return its index if found
    or raise a ValueError
    """
    return SchedulingHelper(loop=loop).ready_index(task)


def ready_tasks(
    *,
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    """
    Return a set of all all runnable tasks in the ready queue.
    """
    return SchedulingHelper(loop=loop).ready_tasks()
