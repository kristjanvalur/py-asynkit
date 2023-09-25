import asyncio
import asyncio.tasks
from asyncio import AbstractEventLoop, Handle, Task
from contextvars import Context
from typing import Any, Callable, Deque, Optional, Set, Tuple, cast

from ..compat import call_soon
from ..tools import deque_pop
from .schedulingloop import AbstractSchedulingLoop
from .types import QueueType, TaskAny

# asyncio by default uses a C implemented task from _asyncio module
TaskTypes: Tuple[Any, ...]
if hasattr(asyncio.tasks, "_PyTask"):
    PyTask = asyncio.tasks._PyTask
    TaskTypes = (Task, PyTask)
else:  # pragma: no cover
    PyTask = asyncio.tasks.Task
    TaskTypes = (Task,)

"""
Helper methods which work with the default event loop from
Python's asyncio module.
"""


class SchedulingHelper(AbstractSchedulingLoop):
    """
    Helper class providing scheduling methods for the default
    event loop.
    """

    def __init__(self, loop: Optional[AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._queue: QueueType = loop._ready  # type: ignore

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

    def ready_remove(self, task: TaskAny) -> Optional[Handle]:
        idx = ready_find_impl(self._queue, task)
        if idx >= 0:
            return deque_pop(self._queue, idx)
        return None

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


# Asyncio does not directly have the concept of "runnable"
# or "blocked" Tasks.  The EventLoop only holds a weak dictionary
# of all its Task objects but otherwise does not track them.
# A Task, which is not currently running, exists either as
# * `done()` callback on a Future, (we consider it blocked)
# * a `Task.__step()` callback in the Loop's "ready" queue (runnable)
# It is the Task.__step() method which handles running a Task until a
# coroutine blocks, which it does by yielding a Future.
#
# To discover runnable Tasks, we must iterate over the ready queue and
# then discover the Task objects from the scheduled __step() callbacks.
# This is doable via some hacky introspection.  It would be nicer if the
# EventLoop considered Tasks separately from scheduled callbacks though.


def ready_index_impl(
    queue: Deque[Handle],
    task: TaskAny,
) -> int:
    idx = ready_find_impl(queue, task)
    if idx >= 0:
        return idx
    raise ValueError("task not in ready queue")


def ready_find_impl(
    queue: Deque[Handle],
    task: TaskAny,
) -> int:
    for i, handle in enumerate(reversed(queue)):
        found = get_task_from_handle_impl(handle)
        if found is task:
            return len(queue) - i - 1
    return -1
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
    handle = call_soon(loop, callback, *args, context=context)
    queue = loop._ready  # type: ignore
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
    if isinstance(task, TaskTypes):
        return cast(TaskAny, task)
    return None
