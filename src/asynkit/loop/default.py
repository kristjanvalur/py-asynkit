from __future__ import annotations

import asyncio
import asyncio.tasks
from asyncio import AbstractEventLoop, Handle, Task
from collections import deque
from collections.abc import Callable, Iterable
from contextvars import Context
from typing import Any, cast

from ..tools import deque_pop
from .schedulingloop import AbstractSchedulingLoop
from .types import QueueType, TaskAny

# asyncio by default uses a C implemented task from _asyncio module
TaskTypes: tuple[Any, ...]
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


class SchedulingLoopHelper(AbstractSchedulingLoop):
    """Helper class providing the scheduling methods
    for the default event loop
    """

    def __init__(self, loop: AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._queue: QueueType = loop._ready  # type: ignore

    def queue_len(self) -> int:
        return len(self._queue)

    def queue_items(self) -> Iterable[Handle]:
        """Enumerate the scheduled callbacks in the loop.
        The elements are returned in the order they will be called."""
        return self._queue

    def queue_find(
        self, key: Callable[[Handle], bool], remove: bool = False
    ) -> Handle | None:
        return queue_find(self._queue, key, remove)

    def queue_insert(self, handle: Handle) -> None:
        self._queue.append(handle)

    def queue_insert_pos(self, handle: Handle, pos: int) -> None:
        self._queue.insert(pos, handle)

    def queue_remove(self, in_handle: Handle) -> None:
        return queue_remove(self._queue, in_handle)

    def call_pos(
        self,
        pos: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> Handle:
        return call_pos(self._loop, pos, callback, *args, context=context)

    def task_from_handle(self, handle: Handle) -> TaskAny | None:
        return task_from_handle(handle)


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


def task_from_handle(
    handle: Handle,
) -> TaskAny | None:
    """
    Extract the runnable Task object
    from its scheduled __step() callback.  Returns None if the
    Handle does not represent a runnable Task.
    """
    # It would be _great_ if a Handle object contained meta information,
    # like the Task it was created for. But it doesn't.
    # it would be possible by replacing the callable with a custom class instance
    # with extra information, but it requires cooperation from the Task
    try:
        task = handle._callback.__self__  # type: ignore
    except AttributeError:
        return None
    if isinstance(task, TaskTypes):
        return cast(TaskAny, task)
    return None


def queue_find(
    queue: deque[Handle], key: Callable[[Handle], bool], remove: bool = False
) -> Handle | None:
    # search from the end of the queue since this is commonly
    # done for just-inserted callbacks
    for i, handle in enumerate(reversed(queue)):
        if key(handle):
            if remove:
                popped = deque_pop(queue, len(queue) - i - 1)
                assert popped is handle
            return handle
    return None


def queue_remove(queue: deque[Handle], in_handle: Handle) -> None:
    # search from the end
    for i, handle in enumerate(reversed(queue)):
        if in_handle is handle:
            deque_pop(queue, len(queue) - i - 1)
            break
    else:
        raise ValueError("handle not in queue")


def call_pos(
    loop: AbstractEventLoop,
    pos: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Context | None = None,
) -> Handle:
    """
    Arrange for a callback to be inserted at the head of the queue to be
    called later.
    """
    handle = loop.call_soon(callback, *args, context=context)
    queue = loop._ready  # type: ignore
    handle2 = queue.pop()
    assert handle2 is handle
    queue.insert(pos, handle)
    return handle
