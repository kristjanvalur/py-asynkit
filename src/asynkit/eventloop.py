import asyncio
import asyncio.base_events
import contextlib
import sys
from asyncio import Handle, Task, AbstractEventLoopPolicy, AbstractEventLoop, Future
from contextvars import Context
from typing import (
    TYPE_CHECKING,
    Deque,
    Callable,
    Optional,
    Any,
    Generator,
    TypeVar,
    cast,
    Coroutine,
    Set,
)

from .tools import create_task, deque_pop, task_from_handle

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
    "task_is_runnable",
    "create_task_start",
    "create_task_descend",
    "runnable_tasks",
    "blocked_tasks",
]

if TYPE_CHECKING:
    TaskAny = Task[Any]
    FutureAny = Future[Any]

    class _Base(asyncio.base_events.BaseEventLoop):
        _ready: Deque[Handle]

else:
    TaskAny = Task
    FutureAny = Future
    _Base = object

T = TypeVar("T")


class SchedulingMixin(_Base):
    """
    A mixin class adding features to the base event loop.
    """

    def ready_len(self) -> int:
        """Get the length of the runnable queue"""
        return len(self._ready)

    def ready_rotate(self, n: int) -> None:
        """Rotate the ready queue.

        The leftmost part of the ready queue is the callback called next.

        A negative value will rotate the queue to the left, placing the next
        entry at the end. A Positive values will move callbacks from the end
        to the front, making them next in line.
        """
        self._ready.rotate(n)

    def ready_pop(self, pos: int = -1) -> Handle:
        """Pop an element off the ready list at the given position."""
        return deque_pop(self._ready, pos)

    def ready_insert(self, pos: int, element: Handle) -> None:
        """Insert a previously popped `element` back into the
        ready queue at `pos`"""
        self._ready.insert(pos, element)

    def ready_append(self, element: Handle) -> None:
        """Append a previously popped `element` to the end of the queue."""
        self._ready.append(element)

    def call_insert(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None
    ) -> Handle:
        """Arrange for a callback to be inserted at `position` in the queue to be
        called later.
        """
        handle = self.call_soon(callback, *args, context=context)
        handle2 = self.ready_pop(-1)
        assert handle2 is handle
        self.ready_insert(position, handle)
        return handle

    def ready_index(self, task: TaskAny) -> int:
        """
        Look for a runnable task in the ready queue. Return its index if found
        or raise a ValueError
        """
        # we search in reverse, since the task is likely to have been
        # just appended to the queue
        for i, handle in enumerate(reversed(self._ready)):
            found = task_from_handle(handle)
            if found is task:
                return len(self._ready) - i - 1
        raise ValueError("task not in ready queue")

    def ready_tasks(self) -> Set[TaskAny]:
        """
        Return a set of all all runnable tasks in the ready queue.
        """
        result = set()
        for handle in self._ready:
            task = task_from_handle(handle)
            if task:
                result.add(task)
        return result


class SchedulingSelectorEventLoop(asyncio.SelectorEventLoop, SchedulingMixin):
    pass


if not TYPE_CHECKING and hasattr(asyncio, "ProactorEventLoop"):  # pragma: no coverage

    class SchedulingProactorEventLoop(asyncio.ProactorEventLoop, SchedulingMixin):
        pass

    __all__.append("SchedulingProactorEventLoop")


if sys.platform == "win32" and globals().get(
    "SchedulingProactorEventLoop"
):  # pragma: no coverage

    DefaultSchedulingEventLoop = globals().get("SchedulingProactorEventLoop")
else:  # pragma: no coverage
    DefaultSchedulingEventLoop = SchedulingSelectorEventLoop


class SchedulingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> AbstractEventLoop:
        return DefaultSchedulingEventLoop()


@contextlib.contextmanager
def event_loop_policy(
    policy: Optional[AbstractEventLoopPolicy] = None,
) -> Generator[AbstractEventLoopPolicy, Any, None]:
    policy = policy or SchedulingEventLoopPolicy()
    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(policy)
    try:
        yield policy
    finally:
        asyncio.set_event_loop_policy(previous)


def get_running_scheduling_loop() -> SchedulingMixin:
    return cast(SchedulingMixin, asyncio.get_running_loop())


async def sleep_insert(pos: int) -> None:
    """Coroutine that completes after `pos` other callbacks have been run.

    This effectively pauses the current coroutine and places it at position `pos`
    in the ready queue. This position may subsequently change due to other
    scheduling operations
    """
    loop = get_running_scheduling_loop()

    def post_sleep() -> None:
        # move the task wakeup, currently at the end of list
        # to the right place
        loop.ready_insert(pos, loop.ready_pop())

    # make the callback execute right after the current task goes to sleep
    loop.call_insert(0, post_sleep)
    await asyncio.sleep(0)


def task_reinsert(task: TaskAny, pos: int) -> None:
    """Place a just-created task at position 'pos' in the runnable queue."""
    loop = get_running_scheduling_loop()
    current_pos = loop.ready_index(task)
    item = loop.ready_pop(current_pos)
    loop.ready_insert(pos, item)


async def task_switch(task: TaskAny, insert_pos: Optional[int] = None) -> Any:
    """Switch immediately to the given task.
    The target task is moved to the head of the queue. If 'insert_pos'
    is None, then the current task is scheduled at the end of the
    queue, otherwise it is inserted at the given position, typically
    at position 1, right after the target task.
    """
    loop = get_running_scheduling_loop()
    pos = loop.ready_index(task)
    # move the task to the head
    loop.ready_insert(0, loop.ready_pop(pos))
    if insert_pos is None:
        # schedule ourselves to the end
        await asyncio.sleep(0)
    else:
        # schedule ourselves at a given position, typically
        # position 1, right after the task.
        await sleep_insert(insert_pos)


def task_is_blocked(task: TaskAny) -> bool:
    """
    Returns True if the task is blocked, as opposed to runnable.
    """
    # despite the comment in the Task implementation, a task on the
    # runnable queue can have a future which is done, e.g. when the
    # task was cancelled, or when the future it was waiting for
    # got done or cancelled.
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
    task = create_task(coro, name=name)
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
    task = create_task(coro, name=name)
    await asyncio.sleep(0)
    return task


def runnable_tasks(loop: Optional[SchedulingMixin] = None) -> Set[TaskAny]:
    """Return a set of the runnable tasks for the loop."""
    if loop is None:
        loop = get_running_scheduling_loop()
    result = loop.ready_tasks()
    assert all(not task_is_blocked(task) for task in result)
    return result


def blocked_tasks(loop: Optional[SchedulingMixin] = None) -> Set[TaskAny]:
    """Return a set of the blocked tasks for the loop."""
    if loop is None:
        loop = get_running_scheduling_loop()
    result = asyncio.all_tasks(loop) - runnable_tasks(loop)
    # the current task is not blocked
    current = asyncio.current_task()
    if current:
        result.discard(current)
    assert all(task_is_blocked(task) for task in result)
    return result
