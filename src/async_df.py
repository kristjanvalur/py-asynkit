from lib2to3.pytree import Base
import sys
import types
import asyncio
import functools
from asyncio import events


if sys.version_info[1] == 7:

    def _start_task(coro, loop, name):
        return asyncio.Task(coro, loop=loop)

else:

    def _start_task(coro, loop, name):
        return asyncio.Task(coro, loop=loop, name=name)


class EventLoopMixin:
    """
    A mixin class adding features to the base event loop.
    """

    def rotate_ready(self, n: int):
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called nex.

        A negative value will rotate the queue to the left, placing the next entry at the end.
        A Positive values will move callbacks from the end to the front, making them next in line.
        """
        self._ready.rotate(n)

    def call_insert(self, position, callback, *args, context=None):
        """Arrange for a callback to be inserted at `position` in the queue to be
        called later.

        This operates on the ready queue.  A value of 0 will insert it at the front
        to be called next, a value of 1 will insert it after the first element.

        Negative values will insert before the entries counting from the end.  A value of -1 will place
        it in the next-to-last place.  use `call_soon` to place it _at_ the end.
        """
        self._check_closed()
        if self._debug:
            self._check_thread()
            self._check_callback(callback, "call_insert")
        handle = events.Handle(callback, args, self, context)
        if handle._source_traceback:
            del handle._source_traceback[-1]
        self._ready.insert(position, handle)
        return handle


class DepthFirstSelectorEventLoop(asyncio.SelectorEventLoop, EventLoopMixin):
    pass


if hasattr(asyncio, "ProactorEventLoop"):

    class DepthFirstProactorEventLoop(asyncio.ProactorEventLoop, EventLoopMixin):
        pass


class DepthFirstEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    if sys.platform == "win32":
        _loop_factory = DepthFirstProactorEventLoop
    else:
        _loop_factory = DepthFirstSelectorEventLoop


async def sleep_insert(pos, result=None):
    """Coroutine that completes after `pos` other callbacks have been run.

    This effectively pauses the current coroutine and places it at position `pos`
    in the ready queue.

    In case the current event loop doesn't support the `call_insert` method, it
    behaves the same as sleep(0)
    """
    loop = events.get_running_loop()
    try:
        call_insert = loop.call_insert
    except AttributeError:
        return await asyncio.sleep(0, result)

    future = loop.create_future()
    h = call_insert(pos, futures._set_result_unless_cancelled, future, result)
    try:
        return await future
    finally:
        h.cancel()


async def descend(coro, *, loop=None, name=None):
    """Starts the coroutine immediately.
    The current coroutine is paused, to be resumed immediatelly when the called coroutine
    first pauses.  A future is returned.
    """

    loop = loop or asyncio.get_event_loop()
    task = _start_task(coro, loop=loop, name=name)
    try:
        # the task was previously at the end.  Make it the next runnable task
        loop.rotate_ready(1)
        # sleep, placing us at the second place
        await sleep_insert(1)
    except AttributeError:
        # event loop doesn't support it.  Just sleep and return the task
        await asyncio.sleep(0)
    return task


async def start(coro, *, loop=None, name=None):
    """Starts the coroutine _soon_.
    A Task is created and the current coroutine
    **yields** allowing the other to commence.
    """
    loop = loop or asyncio.get_event_loop()
    task = _start_task(coro, loop, name)
    await asyncio.sleep(0)
    return task


async def nostart(coro):
    """Same signature as `start` and `descend` but does
    nothing.  Useful do invoke default behaviour.
    """
    return coro


# Functions for running coroutimes
#


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


def make_eager(coro):
    """
    Decorator to ensure that the decorated coroutine is always started
    eagerly and wrapped in a Task if it blocks.
    """

    @functools.wraps
    async def wrapper(*args, **kwargs):
        return eager_task(coro(*args, **kwargs))

    return wrapper
