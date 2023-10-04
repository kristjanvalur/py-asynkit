import asyncio
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from typing import Any, Callable, Deque, Optional, Set, cast

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
        return cast(AbstractSchedulingLoop, helpers.SchedulingHelper(loop))


# loop extensions
# functions which extend the loop API
def call_insert(
    position: int,
    callback: Callable[..., Any],
    *args: Any,
    context: Optional[Context] = None,
    loop: Optional[AbstractEventLoop] = None,
) -> Handle:
    return get_scheduling_loop(loop).call_insert(
        position, callback, *args, context=context
    )


def ready_len(
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    return get_scheduling_loop(loop).ready_len()


def ready_pop(
    position: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> Any:
    return get_scheduling_loop(loop).ready_pop(position)


def ready_remove(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
) -> Optional[Handle]:
    return get_scheduling_loop(loop).ready_remove(task)


def ready_index(
    task: TaskAny,
    loop: Optional[AbstractEventLoop] = None,
) -> int:
    return get_scheduling_loop(loop).ready_index(task)


def ready_append(
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    get_scheduling_loop(loop).ready_append(item)


def ready_insert(
    position: int,
    item: Any,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    get_scheduling_loop(loop).ready_insert(position, item)


def ready_rotate(
    n: int = -1,
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    get_scheduling_loop(loop).ready_rotate(n)


def ready_tasks(
    loop: Optional[AbstractEventLoop] = None,
) -> Set[TaskAny]:
    return get_scheduling_loop(loop).ready_tasks()


def get_ready_queue(
    loop: Optional[AbstractEventLoop] = None,
) -> Deque[Handle]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    return get_scheduling_loop(loop).get_ready_queue()


def get_task_from_handle(
    handle: Handle,
    loop: Optional[AbstractEventLoop] = None,
) -> Optional[TaskAny]:
    """
    Low level routine, mostly used for testing.  May
    raise NotImplementedError if not supported.
    """
    return get_scheduling_loop(loop).get_task_from_handle(handle)
