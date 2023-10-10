import asyncio
import asyncio.tasks
import contextlib
import logging
import sys
from asyncio import AbstractEventLoop
from typing import Any, AsyncGenerator, Coroutine, Optional

from asynkit.loop.extensions import AbstractSchedulingLoop, get_scheduling_loop
from asynkit.loop.types import FutureAny, TaskAny
from asynkit.scheduling import task_switch

__all__ = [
    "create_pytask",
    "task_interrupt",
    "task_throw",
    "task_timeout",
    "TimeoutInterrupt",
    "PyTask",
]

_have_context = sys.version_info > (3, 8)

# Crate a python Task.  We need access to the __step method and this is hidden
# in the C implementation from _asyncio module
if hasattr(asyncio.tasks, "_PyTask"):
    PyTask = asyncio.tasks._PyTask
else:  # pragma: no cover
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


def task_throw(task: TaskAny, exception: BaseException) -> None:
    """Cause an exception to be raised on a task.  When the function returns, the
    task will be scheduled to run with the given exception.  Note that
    this function can override a previously thrown error, which has not
    got the chance to be delivered yet. Use with caution."""

    if not isinstance(exception, BaseException):
        raise TypeError("exception must be an instance deriving from BaseException")

    # cannot interrupt a task which is finished
    if task.done():
        raise RuntimeError("cannot interrupt task which is done")

    # For Python tasks, we can access the __step method to send an
    # exception.  For C implemented tasks, it becomes more complicated,
    # since the actual __step and __wakeup methods are hidden.  We need
    # more complex and hacky code to re-use already scheduled callbacks
    # in this case.
    step_method = getattr(task, "_Task__step", None)

    # get our scheduling loop, to perform the actual scheduling
    task_loop = task.get_loop()
    scheduling_loop = get_scheduling_loop(task_loop)

    # tasks.py mentions that the only way to transition from waiting
    # for a future and being runnable is via the __wakeup() method.
    # Well, we change that here.  task_throw() makes a task stop waiting
    # for a future and transitions it to the runnable state directly.

    # is the task blocked? If so, it is waiting for a future and
    # has the _fut_waiter attribute set, and _fut_waiter.done() is False.
    # note! the following comment from asyncio.tasks.py is wrong:
    # # - Either _fut_waiter is None, and _step() is scheduled;
    # # - or _fut_waiter is some Future, and _step() is *not* scheduled.
    # The key is that _fut_waiter _can_ be not None, with done() == True.
    # in which case __step() (or __wakeup()) _is_ scheduled.
    # When a future is done, it schedules its "done" callbacks to be called
    # "soon".  __wakeup() is one such callback which calls __step().
    # Until __wakeup()/__step() runs, _fut_waiter
    # is left in place.

    # Cancellation: We need to detect if the task is cancelled.
    # because we don't want to deliver a second exception to a task.
    # Cancellation is asynchronous, a task may be in a cancelled state,
    # yet, not yet have the exception delivered to it.
    # when a task is cancelled, it is done by cancelling its future.
    # A `cancelled()` future is also `done()`.
    # if there is no future (the task was in the ready queue),
    # the _must_cancel flag is set on the task instead.

    fut_waiter = task._fut_waiter  # type: ignore[attr-defined]

    if step_method is None:
        # special super hack for C tasks
        callback, arg, ctx = c_task_reschedule(
            task_loop, scheduling_loop, task, fut_waiter, exception
        )
    else:
        # regular code for Python tasks.  We can use the __step method directly.

        if fut_waiter and not fut_waiter.done():
            # it is blocked on a future.
            # we remove ourselves from the future's callback list.
            # this way, we can stop waiting for it, without cancelling it,
            # which would would have side effects.
            wakeup_method = task._Task__wakeup  # type: ignore[attr-defined]
            fut_waiter.remove_done_callback(wakeup_method)
        else:
            # it is not blocked but it could be cancelled
            if task._must_cancel or (  # type: ignore[attr-defined]
                fut_waiter and fut_waiter.cancelled()
            ):
                raise RuntimeError("cannot interrupt a cancelled task")

            # it is in the ready queue (has __step / __wakeup scheduled)
            # or it is the running task..
            handle = scheduling_loop.ready_remove(task)
            if handle is None:
                # it is the running task
                assert task is asyncio.current_task()
                raise RuntimeError("cannot interrupt self")

        callback, arg = step_method, exception
        ctx = task._context if _have_context else None  # type: ignore[attr-defined]

    # clear the future waiter, and re-insert it.  fut_waiter is not necessarily
    # done.
    if step_method:
        # only possible for Py-Tasks!
        # for C tasks, we cannot clear it.  but it is fine, it will be cleared
        # later by the task's __step method, and we are no longer in its callback list
        # however in the mean time, the invariant that _fut_waiter is None or done()
        # while the task is blocked, no longer holds!  so we should really make
        # sure this task is switched to immediately!
        task._fut_waiter = None  # type: ignore[attr-defined]
    if _have_context:
        task_loop.call_soon(  # type: ignore[call-arg]
            callback,
            arg,
            context=ctx,
        )
    else:  # pragma: no cover
        task_loop.call_soon(
            callback,
            arg,
        )


def c_task_reschedule(
    task_loop: AbstractEventLoop,
    scheduling_loop: AbstractSchedulingLoop,
    task: TaskAny,
    fut_waiter: FutureAny,
    exception: BaseException,
) -> Any:
    # because we don't have access to the __step method or __wakeup methods
    # in c tasks, we need to fish out the already existing callbacks
    # in the system and _reuse_ those.

    # first, find the callback on the future, if any.  Similar to
    # Future.remove_done_callback()
    # but filters for the task, and returns the single callback found.
    if fut_waiter and not fut_waiter.done():
        callback, ctx = future_find_task_callback(fut_waiter, task)
        fut_waiter.remove_done_callback(callback)
        handle = None

    else:
        # it is not blocked but it could be cancelled
        if task._must_cancel or (  # type: ignore[attr-defined]
            fut_waiter and fut_waiter.cancelled()
        ):
            raise RuntimeError("cannot interrupt a cancelled task")

        # it is in the ready queue (has __step / __wakeup scheduled)
        # or it is the running task..
        handle = scheduling_loop.ready_remove(task)
        if handle is None:
            # it is the running task
            assert task is asyncio.current_task()
            raise RuntimeError("cannot interrupt self")
        callback = handle._callback  # type: ignore[attr-defined]
        ctx = handle._context if _have_context else None  # type: ignore[attr-defined]

    # we now have a callback, a bound method.  We must re-use this method
    # because we have no way to create a new bound method for the internal
    # __step and __wakeup methods of C tasks.  Find out which we have.
    # for C tasks, this can either be the
    # "TaskStepMethWrapper" for __step, or the "task_wakeup" for __wakeup.
    # (for Py tasks, it is just a Task.__step or Task.__wakeup bound method.
    # We check for both)
    arg: Any
    cbname = str(callback)
    # CTasks have a TaskStepMethWrapper
    if "TaskStep" in cbname or "__step" in cbname:  # pragma: no cover
        # we can re-use this directly
        arg = exception

        # BUT! TaskStepMethWrapper cannot take arguments when called.  And we cannot
        # cannot create one.  So, CTasks which have a plain __step scheduled
        # cannot be interrupted.  So, we have to give up here.  There is no way for us
        # into the pesky C implementation, we cannot modify the wrapped args, nothing.
        # bummer.
        if "TaskStepMethWrapper" in cbname:
            assert handle is not None
            scheduling_loop.ready_insert(-1, handle)  # re-insert it somewhere
            raise RuntimeError(
                "cannot interrupt a c-task with a plain __step scheduled"
            )
    else:
        # this is a TaskWakeupMethWrapper in 3.9 and earlier, 'task_wakeup()' after.
        assert "wakeup" in cbname or "TaskWakeup" in cbname
        # we need to create a cancelled future and pass that as arg to this one.
        f: FutureAny = task._loop.create_future()  # type: ignore[attr-defined]
        f.set_exception(exception)
        arg = f

    return callback, arg, ctx


def future_find_task_callback(fut_waiter: FutureAny, task: TaskAny) -> Any:
    """
    Look for the correct callback on the future to remove, by finding the
    one associated with a task.
    """
    if _have_context:
        found = [
            (f, ctx)
            for (f, ctx) in fut_waiter._callbacks  # type: ignore[attr-defined]
            if getattr(f, "__self__", None) is task
        ]
    else:  # pragma: no cover
        found = [
            f
            for f in fut_waiter._callbacks  # type: ignore[attr-defined]
            if getattr(f, "__self__", None) is task
        ]
    assert len(found) == 1
    cb = found[0]
    if _have_context:
        callback, ctx = cb
    else:  # pragma: no cover
        callback, ctx = cb, None  # type: ignore[assignment]
    return callback, ctx


# interrupt a task.  We use much of the same mechanism used when cancelling a task,
# except that we don't actually cancel the task, we just raise an exception in it.
# Additionally, we need it to execute immediately, so we we switch to it.
async def task_interrupt(task: TaskAny, exception: BaseException) -> None:
    # We don't have a reliable way to detect if a task has been cancelled.
    # it may have been cancelled by cancelling its future, in which case
    # it just looks like a normal, runnable, task.
    # if task._must_cancel:
    #    raise RuntimeError("cannot interrupt task with pending cancellation")

    task_throw(task, exception)
    await task_switch(task)


class TimeoutInterrupt(BaseException):
    """A BaseException used to interrupt a task when a timeout occurs."""


@contextlib.asynccontextmanager
async def task_timeout(timeout: Optional[float]) -> AsyncGenerator[None, None]:
    """Context manager to interrupt a task after a timeout."""
    if timeout is None:
        yield
        return

    task = asyncio.current_task()
    assert task is not None
    loop = task.get_loop()

    # create an interrupt instance, which we check for
    my_interrupt = TimeoutInterrupt()

    def trigger_timeout() -> None:
        # we want to interrupt the task, but not from a
        # loop callback (using task_throw()), because hypothetically many
        # such callbacks could run, and they could then
        # preempt each other.  Instead, we interrupt from
        # a task, so that only one interrupt can be active.
        async def interruptor() -> None:
            try:
                if is_active:  # pragma: no branch
                    assert task is not None  # typing
                    await task_interrupt(task, my_interrupt)
            except Exception:  # pragma: no cover
                logging.exception("task_timeout: interruptor failed")

        loop.create_task(interruptor())

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
