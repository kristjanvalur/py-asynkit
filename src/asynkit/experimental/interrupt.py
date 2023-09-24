import asyncio
import asyncio.tasks
from typing import Any, Coroutine, Optional, TypeVar

from asynkit.loop.types import TaskAny
from asynkit.scheduling import get_scheduling_loop

# Crate a python Task.  We need access to the __step method and this is hidden
# in the C implementation from _asyncio module
if hasattr(asyncio.tasks, "_PyTask"):
    PyTask = asyncio.tasks._PyTask
else:
    PyTask = asyncio.tasks.Task

T = TypeVar("T")


def task_factory(loop, coro):  # type: ignore[no-untyped-def]
    task = PyTask(coro, loop=loop)
    return task


def create_pytask(
    coro: Coroutine[Any, Any, T], *, name: Optional[str] = None
) -> asyncio.Task[T]:
    """Create a Python-implemented task for the given coroutine."""
    loop = asyncio.get_running_loop()
    old_factory = loop.get_task_factory()
    loop.set_task_factory(task_factory)
    try:
        task = loop.create_task(coro, name=name)
    finally:
        loop.set_task_factory(old_factory)
    return task


# interrupt a task.  We use much of the same mechanism used when cancelling a task,
# except that we don't actually cancel the task, we just raise an exception in it.
# Additionally, we need it to execute immediately, so we we switch to it.
async def task_interrupt(task: TaskAny, exception: BaseException) -> None:
    # We don't have a reliable way to detect if a task has been cancelled.
    # it may have been cancelled by cancelling its future, in which case
    # it just looks like a normal, runnable, task.
    # if task._must_cancel:
    #    raise RuntimeError("cannot interrupt task with pending cancellation")

    # cannot interrupt a task which is finished
    if task.done():
        raise RuntimeError("cannot interrupt task which is done")

    task_loop = task.get_loop()
    if task_loop != asyncio.get_running_loop():
        # we cannot interrupt a task from a different loop
        raise RuntimeError("cannot interrupt task from different loop")

    # this only works on python tasks, which have the exposed __step method
    # because we need to insert it directly into the ready queue
    # have to defeat the name mangling:
    try:
        step_method = task._Task__step  # type: ignore[attr-defined]
    except AttributeError as error:
        raise RuntimeError(
            "cannot interrupt task which is not a python task"
        ) from error

    # secondly, the task is either waiting for a future, or it is
    # the queue alreay.

    # is the task in the running queue?
    loop = get_scheduling_loop()
    try:
        index = loop.ready_index(task)
    except ValueError:
        # it is either blocked on a future, or it is ourselves!
        # verify that we are not trying to cancel ourselves
        if task._fut_waiter is None:  # type: ignore[attr-defined]
            assert task is asyncio.current_task()
            raise RuntimeError("cannot interrupt self") from None

        # ok, it must be waiting on a future
        # we remove ourselves from the future's callback list.
        # this way, we can stop waiting for it, without cancelling it,
        # which would would have side effects.
        wakeup_method = task._Task__wakeup  # type: ignore[attr-defined]
        task._fut_waiter.remove_done_callback(wakeup_method)
        task._fut_waiter = None  # type: ignore[attr-defined]
    else:
        # it was alread scheduled to run, just pop it.
        loop.ready_pop(index)

    # now, we have to insert it
    task_loop.call_soon(
        step_method,
        exception,
        context=task._context,  # type: ignore[attr-defined]
    )
    # and make sure it runs next.  This guarantees that the task doesn't
    # exist in a half-interrupted state for other tasks to see and perhaps
    # try to interrupt it again.

    # Move target task to the head of the queue
    pos = loop.ready_index(task)
    if pos != 0:
        loop.ready_insert(0, loop.ready_pop(pos))

    # now sleep
    await asyncio.sleep(0)
