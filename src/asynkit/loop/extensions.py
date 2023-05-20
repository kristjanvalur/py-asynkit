import asyncio
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from types import ModuleType
from typing import Any, Callable, Deque, Optional, Set

from . import default
from .schedulingloop import SchedulingLoopBase
from .types import TaskAny

"""
This module contains extensions to the asyncio loop API.
These are primarily aimed at doing better scheduling, and
achieving specific scheduling goals.

If the current loop is an SchedulingLoopBase, then the
extensions are implemented directly on the loop.
Otherwise, we call special extensions that work for the
default loop implementation.
"""

def loop_helpers(loop: AbstractEventLoop) -> ModuleType:
    """
    get the helpers module for the given loop
    """
    return default  # currently only support this

# loop extensions
# functions which extend the loop API
def call_insert(
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
        return loop_helpers(loop).call_insert(
            position, callback, *args, context=context, loop=loop
        )


def ready_len(
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_len()
    else:
        return loop_helpers(loop).ready_len(loop=loop)


def ready_pop(
    position: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> Any:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_pop(position)
    else:
        return loop_helpers(loop).ready_pop(position, loop=loop)


def ready_index(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_index(task)
    else:
        return loop_helpers(loop).ready_index(task, loop=loop)


def ready_append(
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_append(item)
    else:
        loop_helpers(loop).ready_append(item, loop=loop)


def ready_insert(
    position: int,
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_insert(position, item)
    else:
        loop_helpers(loop).ready_insert(position, item, loop=loop)


def ready_rotate(
    n: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        loop.ready_rotate(n)
    else:
        loop_helpers(loop).ready_rotate(n, loop=loop)


def ready_tasks(
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        return loop.ready_tasks()
    else:
        return loop_helpers(loop).ready_tasks(loop=loop)


def get_ready_queue(
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
        return loop_helpers(loop).get_ready_queue(loop=loop)


def get_task_from_handle(
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
        return loop_helpers(loop).get_task_from_handle(handle, loop=loop)
