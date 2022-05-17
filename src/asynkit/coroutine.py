import asyncio
import functools
import types

__all__ = [
    "coro_start",
    "coro_is_blocked",
    "coro_continue",
    "coro_await",
    "eager_task",
    "make_eager",
]

"""
Tools and utilities for advanced management of coroutines
"""


def coro_start(coro):
    """
    Start the coroutine execution.  It runs te coroutine to its first blocking point
    or until it raises an exception or returns a value, whichever comes first.
    returns a tuple, (future, exception), where either is always `None`.
    The tuple can be passed to `coro_continue` to continue execution, or if
    `exception is not none` it can be processed right away.
    If the exception is a `StopIteration` the `exception.value` can be returned,
    otherwise the exception can be raised directly.
    """
    try:
        future = coro.send(None)
    except BaseException as exception:
        # Coroutine returned without blocking
        return coro, None, exception
    else:
        return coro, future, None


def coro_is_blocked(coro_state):
    """
    Return True if coroutine started by coro_start() is in a blocked state,
    False, if it returned a value or raised an exception
    """
    return coro_state[2] is None


@types.coroutine
def coro_continue(coro_state):
    """
    Continue execution of the coroutine that was started by coro_start()
    """
    coro, out_value, out_exception = coro_state
    # process any exception generated by the initial start
    if out_exception:
        if isinstance(out_exception, StopIteration):
            return out_exception.value
        raise out_exception

    # yield up the initial future from `coro_start`.
    # This is similar to how `yield from` is defined (see pep-380)
    # except that it uses a coroutines's send() and throw() methods.
    while True:
        try:
            in_value = yield out_value
        except GeneratorExit:
            coro.close()
            raise
        except BaseException as e:
            try:
                out_value = coro.throw(e)
            except StopIteration as e:
                return e.value
        else:
            try:
                out_value = coro.send(in_value)
            except StopIteration as e:
                return e.value


async def coro_await(coro):
    """
    A simple await, using the partial run primitives, equivalent to
    `async def coro_await(coro): return await coro`
    """
    return await coro_continue(coro_start(coro))


def eager_task(coro):
    """
    Make the coroutine "eager":
    Start the coroutine.  If it blocks, create a task to continue
    execution and return immediately to the caller.
    The return value is either a non-blocking awaitable returning any
    result or exception, or a Task object.
    This implements a depth-first kind of Task execution.
    """

    # start the coroutine.  Run it to the first block, exception or return value.
    coro_state = coro_start(coro)
    if not coro_is_blocked(coro_state):
        # The coroutine didn't block, a result or exception is ready.
        # No need to create a Task.
        return coro_continue(coro_state)
    else:
        # otherwise, return a Task that runs the coroutine to completion
        return asyncio.create_task(coro_continue(coro_state))


def make_eager(func):
    """
    Decorator to ensure that the decorated coroutine function is always started
    eagerly and wrapped in a Task if it blocks.
    """

    @functools.wraps
    async def wrapper(*args, **kwargs):
        return eager_task(func(*args, **kwargs))

    return wrapper
