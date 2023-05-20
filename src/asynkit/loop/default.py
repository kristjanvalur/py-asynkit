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
        return ready_index_impl(self._queue, task)

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
        return call_insert_impl(self._loop, position, callback, *args, context=context)

    def get_task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        return get_task_from_handle_impl(handle)

    def ready_tasks(self) -> Set[TaskAny]:
        return ready_tasks_impl(self._queue)


def ready_index_impl(
    queue: Deque[Handle],
    task: TaskAny,
) -> int:
    for i, handle in enumerate(reversed(queue)):
        found = get_task_from_handle_impl(handle)
        if found is task:
            return len(queue) - i - 1
    raise ValueError("task not in ready queue")


def ready_tasks_impl(queue: QueueType) -> Set[TaskAny]:
    result = set()
    for handle in queue:
        task = get_task_from_handle_impl(handle)
        if task:
            result.add(task)
    return result


def call_insert_impl(
    loop: AbstractEventLoop,
    position: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Optional[Context] = None,
) -> Handle:
    """
    Arrange for a callback to be inserted at `position` in the queue to be
    called later.
    """
    handle = loop.call_soon(callback, *args, context=context)
    queue = loop._ready
    handle2 = deque_pop(queue, -1)
    assert handle2 is handle
    queue.insert(position, handle)
    return handle


def get_task_from_handle_impl(
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
