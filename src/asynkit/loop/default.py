import asyncio
from asyncio import AbstractEventLoop, Handle, Task
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, Deque, Optional, Set

from ..tools import deque_pop

"""
Helper methods which work with the default event loop from
Python's asyncio module.
"""

if TYPE_CHECKING:

    TaskAny = Task[Any]
else:
    TaskAny = Task


def get_loop_ready_queue(loop: Optional[AbstractEventLoop] = None) -> Deque[Handle]:
    """
    Default implementation to get the Ready Queue of the loop.
    Subclassable by other implementations.
    """
    loop = loop or asyncio.get_running_loop()
    return loop._ready  # type: ignore


def get_task_from_handle(handle: Handle) -> Optional[TaskAny]:
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


def ready_len(loop: Optional[AbstractEventLoop] = None) -> int:
    """Get the length of the runnable queue"""
    return len(get_loop_ready_queue(loop))


def ready_rotate(
    n: int,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """
    Rotate the ready queue.

    The leftmost part of the ready queue is the callback called next.

    A negative value will rotate the queue to the left, placing the next
    entry at the end. A Positive values will move callbacks from the end
    to the front, making them next in line.
    """
    get_loop_ready_queue(loop).rotate(n)


def ready_pop(pos: int = -1, loop: Optional[AbstractEventLoop] = None) -> Handle:
    """Pop an element off the ready list at the given position."""
    return deque_pop(get_loop_ready_queue(loop), pos)


def ready_insert(
    pos: int,
    element: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Insert a previously popped `element` back into the
    ready queue at `pos`"""
    get_loop_ready_queue(loop).insert(pos, element)


def ready_append(
    element: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Append a previously popped `element` to the end of the queue."""
    get_loop_ready_queue(loop).append(element)


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
    handle = loop.call_soon(callback, *args, context=context)
    handle2 = ready_pop(-1, loop)
    assert handle2 is handle
    ready_insert(position, handle, loop)
    return handle


def ready_index(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    """
    Look for a runnable task in the ready queue. Return its index if found
    or raise a ValueError
    """
    # we search in reverse, since the task is likely to have been
    # just appended to the queue
    ready = get_loop_ready_queue(loop)
    for i, handle in enumerate(reversed(ready)):
        found = get_task_from_handle(handle)
        if found is task:
            return len(ready) - i - 1
    raise ValueError("task not in ready queue")


def ready_tasks(
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    """
    Return a set of all all runnable tasks in the ready queue.
    """
    result = set()
    for handle in get_loop_ready_queue(loop):
        task = get_task_from_handle(handle)
        if task:
            result.add(task)
    return result
