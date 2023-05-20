import asyncio
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from typing import Any, Callable, Coroutine, Deque, Optional, Set, cast

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
from .types import FutureAny, TaskAny

"""
This module contains extensions to the asyncio loop API.
These are primarily aimed at doing better scheduling, and
achieving specific scheduling goals.
"""


async def sleep_insert(pos: int) -> None:
    """Coroutine that completes after `pos` other callbacks have been run.

    This effectively pauses the current coroutine and places it at position `pos`
    in the ready queue. This position may subsequently change due to other
    scheduling operations
    """
    loop = asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):

        def post_sleep() -> None:
            # move the task wakeup, currently at the end of list
            # to the right place
            sloop = cast(SchedulingLoopBase, loop)  # mypy fails to infer this
            sloop.ready_insert(pos, sloop.ready_pop())

        # make the callback execute right after the current task goes to sleep
        loop.call_insert(0, post_sleep)
    else:

        def post_sleep() -> None:
            # move the task wakeup, currently at the end of list
            # to the right place
            queue = loop_get_ready_queue(loop)
            ready_insert(pos, ready_pop(queue=queue), queue=queue)

        call_insert(0, post_sleep, loop=loop)
    await asyncio.sleep(0)


def task_reinsert(task: TaskAny, pos: int) -> None:
    """Place a just-created task at position 'pos' in the runnable queue."""
    loop = asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        current_pos = loop.ready_index(task)
        item = loop.ready_pop(current_pos)
        loop.ready_insert(pos, item)
    else:
        queue = loop_get_ready_queue(loop)
        current_pos = ready_index(task, queue=queue)
        item = ready_pop(current_pos, queue=queue)
        ready_insert(pos, item, queue=queue)


async def task_switch(task: TaskAny, insert_pos: Optional[int] = None) -> Any:
    """Switch immediately to the given task.
    The target task is moved to the head of the queue. If 'insert_pos'
    is None, then the current task is scheduled at the end of the
    queue, otherwise it is inserted at the given position, typically
    at position 1, right after the target task.
    """
    # Move target task to the head of the queue
    loop = asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        pos = loop.ready_index(task)
        # move the task to the head
        loop.ready_insert(0, loop.ready_pop(pos))
    else:
        pos = ready_index(task)
        # move the task to the head
        queue = loop_get_ready_queue(loop)
        ready_insert(0, ready_pop(pos, queue=queue), queue=queue)

    # go to sleep so that target runs
    if insert_pos is None:
        # schedule ourselves to the end
        await asyncio.sleep(0)
    else:
        # schedule ourselves at a given position, typically
        # position 1, right after the task.
        await sleep_insert(insert_pos)


# Task helpers


def task_is_blocked(task: TaskAny) -> bool:
    """
    Returns True if the task is blocked, as opposed to runnable.
    """
    # despite the comment in the Task implementation, a task on the
    # runnable queue can have a future which is done, e.g. when the
    # task was cancelled, or when the future it was waiting for
    # got done or cancelled.
    # So we check the future directly.
    future: Optional[FutureAny] = task._fut_waiter  # type: ignore
    return future is not None and not future.done()


def task_is_runnable(task: TaskAny) -> bool:
    """
    Returns True if the task is ready.
    """
    # we don't actually check for the task's presence in the ready queue,
    # it must be either, blocked, runnable or done.
    return not (task_is_blocked(task) or task.done())


async def create_task_descend(
    coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None
) -> TaskAny:
    """Creates a task for the coroutine and starts it immediately.
    The current task is paused, to be resumed next when the new task
    initially blocks. The new task is returned.
    This facilitates a depth-first task execution pattern.
    """
    task = asyncio.create_task(coro, name=name)
    await task_switch(task, insert_pos=1)
    return task


async def create_task_start(
    coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None
) -> TaskAny:
    """Creates a task for the coroutine and starts it soon.
    The current task is paused for one round of the event loop, giving the
    new task a chance to eventually run, before control is returned.
    The new task is returned.
    """
    task = asyncio.create_task(coro, name=name)
    await asyncio.sleep(0)
    return task


def runnable_tasks(loop: Optional[AbstractEventLoop] = None) -> Set[TaskAny]:
    """Return a set of the runnable tasks for the loop."""
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        result = loop.ready_tasks()
    else:
        result = ready_tasks(loop=loop)
    assert all(not task_is_blocked(task) for task in result)
    return result


def blocked_tasks(loop: Optional[AbstractEventLoop] = None) -> Set[TaskAny]:
    """Return a set of the blocked tasks for the loop."""
    loop = loop or asyncio.get_running_loop()
    result = asyncio.all_tasks(loop) - runnable_tasks(loop)
    # the current task is not blocked
    current = asyncio.current_task()
    if current:
        result.discard(current)
    assert all(task_is_blocked(task) for task in result)
    return result


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
