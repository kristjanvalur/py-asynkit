import asyncio
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from typing import Any, Callable, Deque, Optional, Set

from .default import (
    call_insert,
    get_ready_queue,
    get_task_from_handle,
    ready_append,
    ready_index,
    ready_insert,
    ready_len,
    ready_pop,
    ready_rotate,
    ready_tasks,
)
from .schedulingloop import SchedulingLoopBase
from .types import TaskAny

"""
This module contains extensions to the asyncio loop API.
These are primarily aimed at doing better scheduling, and
achieving specific scheduling goals.
"""

# loop extensions
# functions which extend the loop API
def loop_call_insert(
    position: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Optional[Context] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.call_insert(position, callback, *args, context=context)
    else:
        return call_insert(position, callback, *args, context=context, loop=loop)


def loop_ready_len(
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_len()
    else:
        return ready_len(loop=loop)


def loop_ready_pop(
    position: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> Any:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_pop(position)
    else:
        return ready_pop(position, loop=loop)


def loop_ready_index(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_index(task)
    else:
        return ready_index(task, loop=loop)


def loop_ready_append(
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_append(item)
    else:
        ready_append(item, loop=loop)


def loop_ready_insert(
    position: int,
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_insert(position, item)
    else:
        ready_insert(position, item, loop=loop)


def loop_ready_rotate(
    n: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_rotate(n)
    else:
        ready_rotate(n, loop=loop)


def loop_ready_tasks(
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_tasks()
    else:
        return ready_tasks(loop=loop)


def loop_get_ready_queue(
    loop: Optional[AbstractEventLoop] = None,
) -> Deque[Handle]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.get_ready_queue()
    else:
        return get_ready_queue(loop=loop)


def loop_get_task_from_handle(
    handle: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> Optional[TaskAny]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.get_task_from_handle(handle)
    else:
        return get_task_from_handle(handle, loop=loop)
