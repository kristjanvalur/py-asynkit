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
    "task_switch",
    "task_is_blocked",
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
        handle = self.call_soon(callback, *args, context=context)
        handle2 = self.ready_pop(-1)
        assert handle2 is handle
        self.ready_insert(position, handle)
        return handle

    def ready_find_task(self, task):
        """
        Look for a runnable task in the ready queue.  Return its index if found,
        else -1
        """
        # we search in reverse, since the task is likely to have been
        # just appended to the queue
        for i, handle in enumerate(reversed(self._ready)):
            found = task_from_handle(handle)
            if found is task:
                return len(self._ready) - i - 1
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
    DefaultSchedulingEventLoop = SchedulingProactorEventLoop  # pragma: no coverage
else:
    DefaultSchedulingEventLoop = SchedulingSelectorEventLoop  # pragma: no coverage


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return DefaultSchedulingEventLoop()


@contextlib.contextmanager
def event_loop_policy(policy=None):
    policy = policy or SchedulingEventLoopPolicy()
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
    """
    loop = events.get_running_loop()

    def post_sleep():
        # move the task wakeup, currently at the end of list
        # to the right place
        loop.ready_insert(pos, loop.ready_pop())

    # make the callback execute right after the current task goes to sleep
    loop.call_insert(0, post_sleep)
    return await asyncio.sleep(0, result)


def task_reinsert(task, pos):
    """Place a just-created task at position 'pos' in the runnable queue."""
    loop = asyncio.get_running_loop()
    current_pos = loop.ready_find_task(task)
    if current_pos < 0:
        raise ValueError("task is not runnable")
    item = loop.ready_pop(current_pos)
    loop.ready_insert(pos, item)


async def task_switch(task, result=None, sleep_pos=None):
    """Switch immediately to the given task.
    The target task is moved to the head of the queue.  If 'sleep_pos'
    is None, then the current task is scheduled at the end of the
    queue, otherwise it is inserted at the given position, typically
    at position 1, right after the target task.
    """
    loop = asyncio.get_running_loop()
    pos = loop.ready_find_task(task)
    if pos < 0:
        raise ValueError("task is not runnable")
    # move the task to the head
    loop.ready_insert(0, loop.ready_pop(pos))
    if sleep_pos is None:
        # schedule ourselves to the end
        return await asyncio.sleep(0, result=result)
    else:
        # schedule ourselves at a given position, typically
        # position 1, right after the task.
        return await sleep_insert(sleep_pos, result=result)


def task_is_blocked(task):
    """
    Returns True if the task is blocked, as opposed to runnable.
    """
    # despite the comment in the Task implementation, a task on the
    # runnable queue can have a future which is done, e.g. when the
    # task was cancelled, or when the future it was waiting for
    # got done or cancelled.
    return task._fut_waiter is not None and not task._fut_waiter.done()


async def create_task_descend(coro, *, name=None):
    """Creates a task for the coroutine and starts it immediately.
    The current task is paused, to be resumed next when the new task
    initially blocks.  The new task is returned.
    This facilitates a depth-first task execution pattern.
    """
    task = create_task(coro, name=name)
    await task_switch(task, sleep_pos=1)
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
    result = set(t for (t, _) in tasks)
    assert all(not task_is_blocked(task) for task in result)
    return result


def blocked_tasks(loop=None):
    """Return a set of the blocked tasks for the loop."""
    if loop is None:
        loop = events.get_running_loop()
    result = asyncio.all_tasks(loop) - runnable_tasks(loop)
    # the current task is not blocked
    result.discard(asyncio.current_task(loop))
    assert all(task_is_blocked(task) for task in result)
    return result
