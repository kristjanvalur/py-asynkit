import asyncio
import contextlib
import weakref
from abc import ABC, abstractmethod
from asyncio import Handle, Lock, Task
from contextvars import Context
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Protocol,
    Set,
    Tuple,
    TypeVar,
    cast,
)

from typing_extensions import Literal

from asynkit.compat import LockHelper
from asynkit.loop.default import task_from_handle
from asynkit.loop.schedulingloop import AbstractSchedulingLoop
from asynkit.loop.types import TaskAny
from asynkit.scheduling import task_is_runnable
from asynkit.tools import PriorityQueue

T = TypeVar("T")


class BasePriorityObject(ABC):
    """
    The interface of a locking object which supports priority
    """

    @abstractmethod
    def effective_priority(self) -> Optional[float]:
        """
        Return the effective priority of this object.  For a task,
        this is the minimum of the task's priority and the effective
        priority of any held lock.  For a lock, this is the minimum
        effective priority of any waiting task.
        """
        ...


@contextlib.asynccontextmanager
async def _released(lock: Lock) -> AsyncIterator[None]:
    """Context manager to release a lock and reacquire it on exit"""
    lock.release()
    try:
        yield
    finally:
        err = None
        # retry as long as the error is CancelledError, then re-raise
        # the original error
        while True:
            try:
                await lock.acquire()
                break
            except asyncio.CancelledError as e:  # pragma: no cover
                err = e
        if err is not None:  # pragma: no cover
            try:
                raise err
            finally:
                err = None


class PriorityLock(Lock, BasePriorityObject, LockHelper):
    """
    A lock which supports keeping track of the waiting Task
    objects and can compute the highest effective priority
    of all waiting Tasks.
    """

    _waiters: Optional[
        PriorityQueue[
            float, Tuple[asyncio.Future[bool], weakref.ReferenceType[TaskAny]]
        ]
    ]

    def __init__(self) -> None:
        # we use weakrefs to avoid reference cycles.  Tasks _own_ locks,
        # but locks don't own tasks. These are _backrefs_.
        super().__init__()
        self._owning: Optional[weakref.ReferenceType[TaskAny]] = None

    async def acquire(self) -> Literal[True]:
        """Acquire a lock.

        This method blocks until the lock is unlocked, then sets it to
        locked and returns True.
        """
        task = asyncio.current_task()
        assert task is not None

        if not self._locked and not self._waiters:
            self._take_lock(task)
            return True

        # we are about to wait

        if self._waiters is None:
            self._waiters = PriorityQueue()
        try:
            priority = task.effective_priority()  # type: ignore[attr-defined]
        except AttributeError:
            priority = 0
        fut = self._get_loop().create_future()  # type: ignore[attr-defined]
        # tasks 'own' locks, but not the other way round.  Use weakref to make sure we
        # don't create refrerence cycles.
        entry = (fut, weakref.ref(task))
        self._waiters.add(priority, entry)

        # greedily reschedule a runnable owning task
        # in case its priority has changed
        owning = self._owning() if self._owning is not None else None
        if owning is not None:  # pragma: no branch
            if task_is_runnable(owning):  # pragma: no branch
                try:
                    owning.reschedule()  # type: ignore[attr-defined]
                except AttributeError:
                    pass

        try:
            try:
                await fut
            finally:
                self._waiters.remove(entry)
            self._take_lock(task)
            return True
        finally:
            if not self._locked:
                self._wake_up_first()

    def _take_lock(self, task: TaskAny) -> None:
        assert self._owning is None
        self._owning = weakref.ref(task)
        try:
            task.add_owned_lock(self)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        self._locked = True

    def release(self) -> None:
        if not self._locked:
            raise RuntimeError("Lock is not acquired.")  # pragma: no cover

        task = asyncio.current_task()
        assert task is not None
        assert self._owning is not None and self._owning() is task
        self._owning = None
        try:
            task.remove_owned_lock(self)  # type: ignore[attr-defined]
        except AttributeError:
            pass

        self._locked = False
        self._wake_up_first()

    def _wake_up_first(self) -> None:
        """Make sure the highest priorty waiter will run."""
        if not self._waiters:
            return
        fut, _ = self._waiters.peek()

        if not fut.done():  # pragma: no branch
            fut.set_result(True)

    def effective_priority(self) -> Optional[float]:
        # waiting tasks are either PriorityTasks or not.
        # regular tasks are given a priority of 0
        if not self._waiters:
            return None
        priorities = []
        for _, weak_task in self._waiters:
            task = weak_task()
            assert task is not None
            try:
                priorities.append(
                    task.effective_priority(),  # type: ignore[attr-defined]
                )
            except AttributeError:
                priorities.append(0)
        return min(priorities, default=None)


class PriorityCondition(asyncio.Condition, LockHelper):
    """A Condition variable which notifies waiters in priority order."""

    LockType = PriorityLock

    def __init__(self, lock: Optional[asyncio.Lock] = None) -> None:
        lock = lock or self.LockType()
        super().__init__(lock=lock)
        self._waiters: PriorityQueue[float, asyncio.Future[bool]] = PriorityQueue()

    async def wait(self) -> Literal[True]:
        if not self.locked():  # pragma: no cover
            raise RuntimeError("cannot wait on un-acquired lock")

        task = asyncio.current_task()
        assert task is not None
        try:
            priority = task.effective_priority()  # type: ignore[attr-defined]
        except AttributeError:
            priority = 0
        fut = self._get_loop().create_future()  # type: ignore[attr-defined]
        try:
            async with _released(self._lock):  # type: ignore[attr-defined]
                self._waiters.add(priority, fut)
                try:
                    await fut
                finally:
                    self._waiters.remove(fut)
                return True

        except BaseException:
            # must awaken a different waiter to avoid starvation, because
            # a notify() may have been lost.
            self._notify(1)
            raise

    def notify(self, n: int = 1) -> None:
        if not self.locked():  # pragma: no cover
            raise RuntimeError("cannot notify on un-acquired lock")
        self._notify(n)

    def _notify(self, n: int) -> None:
        count = 0
        ordereditems = self._waiters.ordereditems()
        try:
            for _, fut in ordereditems:
                if not fut.done():  # pragma: no branch
                    fut.set_result(True)
                    count += 1
                    if count >= n:  # pragma: no branch
                        break
        finally:
            ordereditems.close()


class PriorityTask(Task, BasePriorityObject):  # type: ignore[type-arg]
    def __init__(  # type: ignore[no-untyped-def]
        self,
        coro,
        *,
        loop=None,
        name=None,
        priority: float = 0,
    ) -> None:
        # Must initialize these attributes before calling parent init
        # because that will schedule the task.
        self.priority_value = priority
        self._holding_locks: Set[PriorityLock] = set()
        super().__init__(coro, loop=loop, name=name)

    def add_owned_lock(self, lock: PriorityLock) -> None:
        self._holding_locks.add(lock)

    def remove_owned_lock(self, lock: PriorityLock) -> None:
        self._holding_locks.remove(lock)

    def priority(self) -> float:
        return self.priority_value

    def effective_priority(self) -> float:
        p1 = (lock.effective_priority() for lock in self._holding_locks)
        lockmin = min((p for p in p1 if p is not None), default=None)
        if lockmin is None:
            return self.priority()
        return min(self.priority(), lockmin)

    def reschedule(self) -> None:
        """
        Ask the event loop to reschedule the task, if runnable,
        in case its effective priority has changed.
        """

    def propagate_priority(self) -> None:
        """Notify that someone has started waiting for this task, having it
        pass that notification onwards or reschedule itself if necessary.
        """
        # TODO: Have it propagate to any lock it is waiting for
        if task_is_runnable(self):
            loop = asyncio.get_running_loop()
            # if the loop supports it, ask for this task to be rescheduled
            try:
                loop.task_reschedule(self)  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover
                pass


class PosPriorityQueue(Generic[T]):
    """
    A simple priority queue for objects, which also allows scheduling
    at a fixed early position.  It respects floating point priority
    values of objects, but also allows positional scheduling when
    required.  Lower priority values are scheduled first.
    It supports "append" and "popleft" operations and as such can
    be directly plugged in as a deque to an event loop.
    """

    def __init__(self, get_priority: Callable[[T], float]) -> None:
        # the queues are stored in a dictionary, keyed by (priority-class, priority)
        # the priority-class is 1 for regular priority, 0 for immediate priority.
        self._pq: PriorityQueue[Tuple[int, float], T] = PriorityQueue()
        self._get_priority = get_priority

    def __iter__(self) -> Iterator[T]:
        """
        Iterate over the objects in the queue, in the order they would be popped.
        """
        self._pq.sort()
        yield from self._pq

    def __len__(self) -> int:
        return len(self._pq)

    def __bool__(self) -> bool:
        return bool(self._pq)

    def clear(self) -> None:
        self._pq.clear()

    def append(self, obj: T) -> None:
        """
        Insert an item into its default place according to priority
        """
        self._pq.add((1, self._get_priority(obj)), obj)

    def append_pri(self, obj: T, priority: float) -> None:
        """
        Insert an item at a specific priority
        """
        self._pq.add((1, priority), obj)

    def insert(self, position: int, obj: T) -> None:
        """
        Insert an object to be scheduled at an immediate position.
        The position is typically 0 or 1, where 0 is the next object.
        """
        assert position >= 0
        # the immediate queue is one with priority key (0, n)
        # reglar priority queues are (1, priority) and so the
        # immediate queue is always first.

        promoted: List[T] = []
        priority_val = 0.0
        try:
            while position > len(promoted):
                promoted.append(self.popleft())
            # are there other immediate objects in the queue?
            # if so, we select a one lower priority value for our
            # inserted objects.
            (priority_cls, val), _ = self._pq.peekitem()
            if priority_cls == 0:
                priority_val = val - 1
        except IndexError:
            pass
        promoted.append(obj)
        pri = (0, priority_val)
        for obj in promoted:
            self._pq.add(pri, obj)

    def popleft(self) -> T:
        return self._pq.pop()

    def remove(self, obj: T) -> None:
        """
        Remove an object from the queue.
        """
        self._pq.remove(obj)

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
    ) -> Optional[T]:
        found = self._pq.find(key, remove)
        if found is not None:
            pri, obj = found
            return obj
        return None

    def reschedule(
        self,
        key: Callable[[T], bool],
        new_priority: float,
    ) -> Optional[T]:
        """
        Reschedule an object which is already in the queue.
        """
        return self._pq.reschedule(key, (1, new_priority))

    def reschedule_all(self) -> None:
        """
        Reschedule all objects in the queue based on their priority,
        except the one in the immediate priority class which have
        a fixed ordering.
        """
        newpri = []
        for pri, obj in self._pq.items():
            if pri != (0, 0):
                pri = (1, self._get_priority(obj))
            newpri.append((pri, obj))
        self._pq.clear()
        self._pq.extend(newpri)


class EventLoopLike(Protocol):
    def call_soon(
        self,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        ...  # pragma: no cover


class PrioritySchedulingMixin(AbstractSchedulingLoop, EventLoopLike):
    def init(self) -> None:
        self.ready_queue: PosPriorityQueue[Handle] = PosPriorityQueue(self.get_priority)

    def get_priority(self, handle: Handle) -> float:
        task = self.task_from_handle(handle)
        if task is not None:
            try:
                priority = task.effective_priority()  # type: ignore[attr-defined]
                return cast(float, priority)
            except AttributeError:
                pass
        return 0.0

    def queue_len(self) -> int:
        return len(self.ready_queue)

    def queue_items(self) -> Iterable[Handle]:
        return iter(self.ready_queue)

    def queue_find(
        self, key: Callable[[Handle], bool], remove: bool = False
    ) -> Optional[Handle]:
        return self.ready_queue.find(key, remove)

    def queue_remove(self, handle: Handle) -> None:
        self.ready_queue.remove(handle)

    def queue_insert(self, handle: Handle) -> None:
        self.ready_queue.append(handle)

    def queue_insert_pos(self, handle: Handle, position: int) -> None:
        self.ready_queue.insert(position, handle)

    def call_pos(
        self,
        position: int,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        """Arrange for a callback to be inserted at position 'pos' near the the head of
        the queue to be called soon.  'position' is typically a low number, 0 or 1.
        This is effectively the same as calling
        `call_soon()`, `queue_remove()` and `queue_insert_pos()` in turn.
        """
        handle = self.call_soon(callback, *args, context=context)
        self.queue_remove(handle)
        self.queue_insert_pos(handle, position)
        return handle

    # helper to find tasks from handles and to find certain handles
    # in the queue
    def task_from_handle(self, handle: Handle) -> Optional[TaskAny]:
        """
        Extract the runnable Task object
        from its scheduled callback.  Returns None if the
        Handle does not represent a callback for a Task.
        """
        return task_from_handle(handle)

    def task_reschedule(self, task: TaskAny) -> None:
        """
        Ask the event loop to reschedule the task, if runnable,
        in case its effective priority has changed.
        """
        try:
            priority = task.effective_priority()  # type: ignore[attr-defined]
        except AttributeError:  # pragma: no cover
            return  # not a priority task, it already has the right priority of 0

        def key(handle: Handle) -> bool:
            return task is self.task_from_handle(handle)

        self.ready_queue.reschedule(key, priority)


class PrioritySelectorEventLoop(asyncio.SelectorEventLoop, PrioritySchedulingMixin):
    def __init__(self, arg: Any = None) -> None:
        super().__init__(arg)
        self.init()
        self._ready = self.ready_queue
