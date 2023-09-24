import asyncio
import asyncio.tasks
import contextlib
import sys
from typing import Any, AsyncGenerator, Coroutine, Optional

from asynkit.loop.types import TaskAny
from asynkit.scheduling import get_scheduling_loop

__all__ = [
    "create_pytask",
    "task_interrupt",
    "task_throw",
    "task_timeout",
    "TimeoutInterrupt",
    "PyTask",
]

# Crate a python Task.  We need access to the __step method and this is hidden
# in the C implementation from _asyncio module
if hasattr(asyncio.tasks, "_PyTask"):
    PyTask = asyncio.tasks._PyTask
else:
    PyTask = asyncio.tasks.Task


def task_factory(loop, coro):  # type: ignore[no-untyped-def]
    task = PyTask(coro, loop=loop)
    return task


def create_pytask(
    coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None
) -> TaskAny:
    """Create a Python-implemented task for the given coroutine."""
    loop = asyncio.get_running_loop()
    old_factory = loop.get_task_factory()
    loop.set_task_factory(task_factory)
    try:
        task = loop.create_task(coro, name=name)
    finally:
        loop.set_task_factory(old_factory)
    return task


def task_throw(
    task: TaskAny, exception: BaseException, *, immediate: bool = False
) -> None:
    """Cause an exception to be raised on a task.  When the function returns, the
    task will be scheduled to run with the given exception."""

    # cannot interrupt a task which is finished
    if task.done():
        raise RuntimeError("cannot interrupt task which is done")

    # this only works on python tasks, which have the exposed __step method
    # because we need to insert it directly into the ready queue
    # have to defeat the name mangling:
    try:
        step_method = task._Task__step  # type: ignore[attr-defined]
    except AttributeError as error:
        raise RuntimeError(
            "cannot interrupt task which is not a python task"
        ) from error

    # get our scheduling loop, to perform the actual scheduling
    task_loop = task.get_loop()
    scheduling_loop = get_scheduling_loop(task_loop)

    # is the task blocked? If so, it is waiting for a future and
    # has the _fut_waiter attribute set.
    # note! the following comment from asyncio.tasks.py is wrong:
    ## - Either _fut_waiter is None, and _step() is scheduled;
    ## - or _fut_waiter is some Future, and _step() is *not* scheduled.
    # when a future is done, it schedules its done callbacks,
    # i.e. task.__wakeup will be "called soon".  but the task's
    # _fut_waiter is still set, albeit pointing to a 'done' future.

    fut_waiter = task._fut_waiter  # type: ignore[attr-defined]
    if fut_waiter and not fut_waiter.done():
        # we remove ourselves from the future's callback list.
        # this way, we can stop waiting for it, without cancelling it,
        # which would would have side effects.
        wakeup_method = task._Task__wakeup  # type: ignore[attr-defined]
        fut_waiter.remove_done_callback(wakeup_method)
    else:
        # it is in the ready queue (has __step / __wakeup shceduled)
        # or it is the running task..
        handle = scheduling_loop.ready_remove(task)

        if handle is None:
            # it is the running task
            assert task is asyncio.current_task()
            raise RuntimeError("cannot interrupt self")

    # now, we have to insert it
    task._fut_waiter = None  # type: ignore[attr-defined]
    if sys.version_info > (3, 8):
        task_loop.call_soon(
            step_method,
            exception,
            context=task._context,  # type: ignore[attr-defined]
        )
    else:
        task_loop.call_soon(
            step_method,
            exception,
        )

    if immediate:
        # Make sure it runs next.  This guarantees that the task doesn't
        # exist in a half-interrupted state for other tasks to see and perhaps
        # try to interrupt it again, which makes it easier to reason
        # about task behaviour.
        # Move target task to the head of the queue
        handle = scheduling_loop.ready_remove(task)
        assert handle is not None
        scheduling_loop.ready_insert(0, handle)


# interrupt a task.  We use much of the same mechanism used when cancelling a task,
# except that we don't actually cancel the task, we just raise an exception in it.
# Additionally, we need it to execute immediately, so we we switch to it.
async def task_interrupt(task: TaskAny, exception: BaseException) -> None:
    # We don't have a reliable way to detect if a task has been cancelled.
    # it may have been cancelled by cancelling its future, in which case
    # it just looks like a normal, runnable, task.
    # if task._must_cancel:
    #    raise RuntimeError("cannot interrupt task with pending cancellation")

    task_throw(task, exception, immediate=True)
    await asyncio.sleep(0)


class TimeoutInterrupt(BaseException):
    """A BaseException used to interrupt a task when a timeout occurs."""


@contextlib.asynccontextmanager
async def task_timeout(timeout: float) -> AsyncGenerator[None, None]:
    """Context manager to interrupt a task after a timeout."""
    task = asyncio.current_task()
    assert task is not None
    loop = task.get_loop()
    if not isinstance(task, PyTask):
        raise RuntimeError("cannot interrupt task which is not a python task")

    # create an interrupt instance, which we check for
    my_interrupt = TimeoutInterrupt()

    def trigger_timeout() -> None:
        if is_active:
            assert task is not None
            task_throw(task, my_interrupt, immediate=True)

    timeout_handle = loop.call_later(timeout, trigger_timeout)
    is_active = True
    try:
        yield
    except TimeoutInterrupt as err:
        if err is not my_interrupt:
            # This is some other timeout triggering
            raise
        raise asyncio.TimeoutError() from err
    finally:
        is_active = False
        timeout_handle.cancel()
