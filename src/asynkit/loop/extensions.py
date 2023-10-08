import asyncio
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from typing import Any, Callable, Iterable, Optional, cast

from . import default
from .schedulingloop import AbstractSchedulingLoop as AbstractSchedulingLoop
from .types import TaskAny

"""
This module contains extensions to the asyncio loop API.
These are primarily aimed at doing better scheduling, and
achieving specific scheduling goals.

If the current loop is an AbstractSchedulingLoop, then the
extensions are implemented directly on the loop.
Otherwise, we call special extensions that work for the
default loop implementation.
"""


def get_scheduling_loop(
    loop: Optional[AbstractEventLoop] = None,
) -> AbstractSchedulingLoop:
    """
    get the AbstractSchedulingLoop for the given loop
    """
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, AbstractSchedulingLoop):
        return loop
    else:
        # in future, select other loop types here
        helpers = default
        return cast(AbstractSchedulingLoop, helpers.SchedulingLoopHelper(loop))


# loop extensions
# functions which extend the loop API for extended Task scheduling


def call_pos(
    position: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Optional[Context] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    """Arrange for a callback to be made at position 'pos' near the the head of
    the callable queue.  'position' is typically a low number, 0 or 1, where 0
    means that the callback will be called __immediately__ after the currently
    running callback.
    """
    return get_scheduling_loop(loop).call_pos(
        position, callback, *args, context=context
    )


def ready_len(
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    """Returns the length of the ready queue.  This is the number
    of Handles in there, which may not all represent ready Tasks.
    """
    return get_scheduling_loop(loop).queue_len()


def ready_remove(
    handle: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> Optional[Handle]:
    """Removes a handle from the ready queue.
    Raises ValueError if not found."""
    sl = get_scheduling_loop(loop)
    return sl.queue_remove(handle)


def ready_find(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
    remove: bool = False,
) -> Optional[Handle]:
    """Finds a task in the ready queue, and returns its handle,
    optionally removing it from the queue.
    Returns None if not found."""
    sl = get_scheduling_loop(loop)
    return sl.queue_find(key=lambda h: task is sl.task_from_handle(h), remove=remove)


def ready_insert(
    item: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """Inserts a handle in the default position on the ready queue"""
    get_scheduling_loop(loop).queue_insert(item)


def ready_tasks(
    loop: Optional[AbstractEventLoop] = None,
) -> Iterable[TaskAny]:
    """Returns all the Tasks in the ready queue"""
    sl = get_scheduling_loop(loop)
    for handle in sl.queue_items():
        task = sl.task_from_handle(handle)
        if task is not None:
            yield task


def get_ready_queue(
    loop: Optional[AbstractEventLoop] = None,
) -> Iterable[Handle]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    return get_scheduling_loop(loop).queue_items()


def task_from_handle(
    handle: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> Optional[TaskAny]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    return get_scheduling_loop(loop).task_from_handle(handle)
