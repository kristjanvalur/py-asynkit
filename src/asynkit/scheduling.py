import asyncio
from typing import Any, Coroutine, Optional, Set

from .loop.extensions import (
    get_ready_queue_instance,
    ready_tasks,
)
from .loop.schedulingloop import ReadyQueueBase, SchedulingLoopBase
from .loop.types import FutureAny, TaskAny

"""
This module contains functions which extend the task scheduling
features of asyncio
"""

__all__ = [
    "blocked_tasks",
    "create_task_descend",
    "create_task_start",
    "runnable_tasks",
    "sleep_insert",
    "task_reinsert",
    "task_switch",
    "task_is_blocked",
    "task_is_runnable",
]


async def sleep_insert(pos: int) -> None:
    """Coroutine that completes after `pos` other callbacks have been run.

    This effectively pauses the current coroutine and places it at position `pos`
    in the ready queue. This position may subsequently change due to other
    scheduling operations
    """
    await _sleep_insert(get_ready_queue_instance(), pos)


async def _sleep_insert(queue: ReadyQueueBase, pos: int) -> None:
    queue = get_ready_queue_instance()

    def post_sleep() -> None:
        # move the task wakeup, currently at the end of list
        # to the right place
        queue.ready_insert(pos, queue.ready_pop())

    queue.call_insert(0, post_sleep)
    await asyncio.sleep(0)


def task_reinsert(task: TaskAny, pos: int) -> None:
    """Place a just-created task at position 'pos' in the runnable queue."""
    queue = get_ready_queue_instance()
    current_pos = queue.ready_index(task)
    item = queue.ready_pop(current_pos)
    queue.ready_insert(pos, item)


async def task_switch(task: TaskAny, insert_pos: Optional[int] = None) -> Any:
    """Switch immediately to the given task.
    The target task is moved to the head of the queue. If 'insert_pos'
    is None, then the current task is scheduled at the end of the
    queue, otherwise it is inserted at the given position, typically
    at position 1, right after the target task.
    """
    queue = get_ready_queue_instance()

    # Move target task to the head of the queue
    pos = queue.ready_index(task)
    queue.ready_insert(0, queue.ready_pop(pos))

    # go to sleep so that target runs
    if insert_pos is None:
        # schedule ourselves to the end
        await asyncio.sleep(0)
    else:
        # schedule ourselves at a given position, typically
        # position 1, right after the task.
        await _sleep_insert(queue, insert_pos)


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


def runnable_tasks(loop: Optional[asyncio.AbstractEventLoop] = None) -> Set[TaskAny]:
    """Return a set of the runnable tasks for the loop."""
    loop = loop or asyncio.get_running_loop()
    if isinstance(loop, SchedulingLoopBase):
        result = loop.ready_tasks()
    else:
        result = ready_tasks(loop=loop)
    assert all(not task_is_blocked(task) for task in result)
    return result


def blocked_tasks(loop: Optional[asyncio.AbstractEventLoop] = None) -> Set[TaskAny]:
    """Return a set of the blocked tasks for the loop."""
    loop = loop or asyncio.get_running_loop()
    result = asyncio.all_tasks(loop) - runnable_tasks(loop)
    # the current task is not blocked
    current = asyncio.current_task()
    if current:
        result.discard(current)
    assert all(task_is_blocked(task) for task in result)
    return result
