import asyncio
from asyncio import AbstractEventLoop, Handle, Task
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, Deque, Optional, Set

from ..tools import deque_pop
from .schedulingloop import ReadyQueueBase

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


def get_ready_queue(loop: Optional[LoopType] = None) -> QueueType:
    """
    Default implementation to get the Ready Queue of the loop.
    Subclassable by other implementations.
    """
    loop = loop or asyncio.get_running_loop()
    return loop._ready  # type: ignore


def get_task_from_handle(
    handle: Handle, loop: Optional[LoopType] = None
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


def ready_len(
    queue: Optional[QueueType] = None, loop: Optional[LoopType] = None
) -> int:
    """Get the length of the runnable queue"""
    queue = queue or get_ready_queue(loop)
    return len(queue)


def ready_rotate(
    n: int,
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """
    Rotate the ready queue.

    The leftmost part of the ready queue is the callback called next.

    A negative value will rotate the queue to the left, placing the next
    entry at the end. A Positive values will move callbacks from the end
    to the front, making them next in line.
    """
    queue = queue or get_ready_queue(loop)
    queue.rotate(n)


def ready_pop(
    pos: int = -1,
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    """Pop an element off the ready list at the given position."""
    queue = queue or get_ready_queue(loop)
    return deque_pop(queue, pos)


def ready_insert(
    pos: int,
    element: Handle,
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Insert a previously popped `element` back into the
    ready queue at `pos`"""
    queue = queue or get_ready_queue(loop)
    queue.insert(pos, element)


def ready_append(
    element: Handle,
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Append a previously popped `element` to the end of the queue."""
    queue = queue or get_ready_queue(loop)
    queue.append(element)


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
    loop = loop or asyncio.get_running_loop()
    queue = get_ready_queue(loop)
    handle = loop.call_soon(callback, *args, context=context)
    handle2 = ready_pop(-1, queue=queue)
    assert handle2 is handle
    ready_insert(position, handle, queue=queue)
    return handle


def ready_index(
    task: TaskAny,
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    """
    Look for a runnable task in the ready queue. Return its index if found
    or raise a ValueError
    """
    # we search in reverse, since the task is likely to have been
    # just appended to the queue
    ready = queue or get_ready_queue(loop)
    for i, handle in enumerate(reversed(ready)):
        found = get_task_from_handle(handle)
        if found is task:
            return len(ready) - i - 1
    raise ValueError("task not in ready queue")


def ready_tasks(
    *,
    queue: Optional[QueueType] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    """
    Return a set of all all runnable tasks in the ready queue.
    """
    result = set()
    queue = queue or get_ready_queue(loop)
    for handle in queue:
        task = get_task_from_handle(handle)
        if task:
            result.add(task)
    return result


class ReadyQueue(ReadyQueueBase):
    def __init__(self, loop: Optional[AbstractEventLoop] = None) -> None:
        self._queue = get_ready_queue(loop)

    def ready_index(self, task: TaskAny) -> int:
        return ready_index(task, queue=self._queue)

    def ready_pop(self, pos: int = -1) -> Handle:
        return deque_pop(self._queue, pos)

    def ready_insert(self, pos: int, element: Handle) -> None:
        self._queue.insert(pos, element)
