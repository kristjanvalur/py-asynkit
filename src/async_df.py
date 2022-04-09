import sys
import asyncio
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
