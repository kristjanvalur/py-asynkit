import asyncio
import contextlib
import sys
import types
from asyncio import events, AbstractEventLoop
from typing import Optional


class SchedulingMixin:
    """
    A mixin class adding features to the base event loop.
    """

    def num_ready(self):
        """Get the length of the runnable queue"""
        return len(self._ready)

    def rotate_ready(self, n: int):
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called next.

        A negative value will rotate the queue to the left, placing the next entry at the end.
        A Positive values will move callbacks from the end to the front, making them next in line.
        """
        self._ready.rotate(n)

    def ready_pop(self, pos=-1):
        """Pop an element off the ready list at the given position."""
        if pos == -1:
            return self._ready.pop()
        # move the element to the head
        self._ready.rotate(-pos)
        r = self._ready.popleft()
        self._ready.rotate(pos)
        return r

    def ready_insert(self, pos, element):
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        self._ready.insert(pos, element)

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


class SchedulingSelectorEventLoop(asyncio.SelectorEventLoop, SchedulingMixin):
    pass


if hasattr(asyncio, "ProactorEventLoop"):

    class SchedulingProactorEventLoop(asyncio.ProactorEventLoop, SchedulingMixin):
        pass


if sys.platform == "win32" and globals().get("SchedulingProactorEventLoop"):
    DefaultSchedulingEventLoop = SchedulingProactorEventLoop
else:
    DefaultSchedulingEventLoop = SchedulingSelectorEventLoop


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> AbstractEventLoop:
        return DefaultSchedulingEventLoop()


@contextlib.contextmanager
def event_loop_policy(policy=SchedulingEventLoopPolicy):
    previous = asyncio.get_event_loop_policy()
    try:
        asyncio.set_event_loop_policy(policy)
    finally:
        asyncio.set_event_loop_policy(previous)


async def sleep_insert(pos, result=None):
    """Coroutine that completes after `pos` other callbacks have been run.

    This effectively pauses the current coroutine and places it at position `pos`
    in the ready queue.  This position may subsequently change due to other
    scheduling operations

    In case the current event loop doesn't support the `call_insert` method, it
    behaves the same as sleep(0)
    """
    loop = events.get_running_loop()
    try:
        call_insert = loop.call_insert
    except AttributeError:
        pass
    else:

        def post_sleep():
            # move the task wakeup, currently at the end of list
            # to the right place
            loop.ready_insert(pos, loop.ready_pop())

        # make the callback execute right after the current task goes to sleep
        call_insert(0, post_sleep)

    return await asyncio.sleep(0, result)


async def create_task_descend(
    coro: types.coroutine, *, name: Optional[str] = None
) -> asyncio.Task:
    """Creates a task for the coroutine and starts it immediately.
    The current task is paused, to be resumed immediately when the new coroutine
    initially blocks.  The new task is returned.
    This facilitates a depth-first task execution pattern.
    """

    loop = loop or asyncio.get_event_loop()
    task = asyncio.create_task(coro, name=name)
    # the task was previously at the end.  Make it the next runnable task
    loop.rotate_ready(1)
    # sleep, placing us at the second place, to be resumed when the task blocks.
    await sleep_insert(1)
    return task


async def create_task_start(
    coro: types.coroutine, *, name: Optional[str] = None
) -> asyncio.Task:
    """Creates a task for the coroutine and starts it soon.
    The current task is paused for one round of the event loop, giving the new task a chance
    to eventually run, before control is returned. The new task is returned.
    """
    task = asyncio.create_task(coro, name=name)
    await asyncio.sleep(0)
    return task
