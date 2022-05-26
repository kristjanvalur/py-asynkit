import asyncio
import contextlib
import sys
from asyncio import events

from .tools import deque_pop, create_task, task_from_handle

__all__ = [
    "SchedulingMixin",
    "SchedulingSelectorEventLoop",
    "SchedulingEventLoopPolicy",
    "DefaultSchedulingEventLoop",
    "event_loop_policy",
    "sleep_insert",
    "task_reinsert",
    "create_task_start",
    "create_task_descend",
    "runnable_tasks",
    "blocked_tasks",
]


class SchedulingMixin:
    """
    A mixin class adding features to the base event loop.
    """

    def ready_len(self):
        """Get the length of the runnable queue"""
        return len(self._ready)

    def ready_rotate(self, n: int):
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called next.

        A negative value will rotate the queue to the left, placing the next entry at the end.
        A Positive values will move callbacks from the end to the front, making them next in line.
        """
        self._ready.rotate(n)

    def ready_pop(self, pos=-1):
        """Pop an element off the ready list at the given position."""
        return deque_pop(self._ready, pos)

    def ready_insert(self, pos, element):
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        self._ready.insert(pos, element)

    def ready_append(self, element):
        """Append a previously popped `element` to the end of the queue."""
        self._ready.append(element)

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

    def ready_find_task(self, task):
        """
        Look for a runnable task in the ready queue.  Return its index if found,
        else -1
        """
        for i, handle in enumerate(self._ready):
            task = task_from_handle(handle)
            if task:
                return i
        return -1

    def ready_get_tasks(self):
        """
        Find all runnable tasks in the ready queue.  Return a list of
        (task, index) tuples.
        """
        result = []
        for i, handle in enumerate(self._ready):
            task = task_from_handle(handle)
            if task:
                result.append((task, i))
        return result


class SchedulingSelectorEventLoop(asyncio.SelectorEventLoop, SchedulingMixin):
    pass


if hasattr(asyncio, "ProactorEventLoop"):

    class SchedulingProactorEventLoop(asyncio.ProactorEventLoop, SchedulingMixin):
        pass

    __all__.append("SchedulingProactorEventLoop")


if sys.platform == "win32" and globals().get("SchedulingProactorEventLoop"):
    DefaultSchedulingEventLoop = SchedulingProactorEventLoop
else:
    DefaultSchedulingEventLoop = SchedulingSelectorEventLoop


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return DefaultSchedulingEventLoop()


@contextlib.contextmanager
def event_loop_policy(policy=SchedulingEventLoopPolicy):
    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(policy)
    try:
        yield policy
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

    def post_sleep():
        # move the task wakeup, currently at the end of list
        # to the right place
        loop.ready_insert(pos, loop.ready_pop())

    # make the callback execute right after the current task goes to sleep
    loop.call_insert(0, post_sleep)
    return await asyncio.sleep(0, result)


def task_reinsert(pos):
    """Place a just-created task at position 'pos' in the runnable queue."""
    loop = asyncio.get_running_loop()
    if pos == 0:
        # simply rotate it from the endo to the beginning
        loop.ready_rotate(1)
    else:
        task = loop.ready_pop()
        try:
            loop.ready_insert(pos, task)
        except:
            # in case of error, put it back where it was
            loop.ready_insert(loop.ready_len(), task)
            raise


async def create_task_descend(coro, *, name=None):
    """Creates a task for the coroutine and starts it immediately.
    The current task is paused, to be resumed next when the new task
    initially blocks.  The new task is returned.
    This facilitates a depth-first task execution pattern.
    """
    loop = asyncio.get_running_loop()
    task = create_task(coro, name=name)
    # the task was previously at the end.  Make it the next runnable task
    task_reinsert(0)
    # sleep, placing us at the second place, to be resumed when the task blocks.
    await sleep_insert(1)
    return task


async def create_task_start(coro, *, name=None):
    """Creates a task for the coroutine and starts it soon.
    The current task is paused for one round of the event loop, giving the new task a chance
    to eventually run, before control is returned. The new task is returned.
    """
    task = create_task(coro, name=name)
    await asyncio.sleep(0)
    return task


def runnable_tasks(loop=None):
    """Return a set of the runnable tasks for the loop."""
    if loop is None:
        loop = events.get_running_loop()
    tasks = loop.ready_get_tasks()
    return set(t for (t, _) in tasks)


def blocked_tasks(loop=None):
    """Return a set of the blocked tasks for the loop."""
    if loop is None:
        loop = events.get_running_loop()
    result = asyncio.all_tasks(loop) - runnable_tasks(loop)
    # the current task is not blocked
    result.discard(asyncio.current_task(loop))
    return result
