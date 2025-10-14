from __future__ import annotations

import asyncio
import contextlib
import random
import sys
import weakref
from abc import ABC, abstractmethod
from asyncio import Handle, Lock, Task
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from contextvars import Context
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Generic,
    Literal,
    Protocol,
    TypeVar,
    cast,
)

from asynkit.compat import (
    FutureBool,
    ReferenceTypeTaskAny,
)
from asynkit.loop.default import task_from_handle
from asynkit.loop.schedulingloop import AbstractSchedulingLoop
from asynkit.loop.types import TaskAny
from asynkit.scheduling import task_is_runnable
from asynkit.tools import PriorityQueue

__all__ = [
    "BasePriorityObject",
    "PriorityCondition",
    "PriorityLock",
    "PrioritySelectorEventLoop",
    "DefaultPriorityEventLoop",
    "PriorityTask",
    "PriorityEventLoopPolicy",
    "PrioritySchedulingMixin",
]

T = TypeVar("T")


class Priority(Enum):
    """standard prioriy values for tasks"""

    LOW = 10.0
    NORMAL = 0.0
    HIGH = -10.0


class BasePriorityObject(ABC):
    """
    The interface of a locking object which supports priority
    """

    @abstractmethod
    def effective_priority(self) -> float | None:
        """
        Return the effective priority of this object.  For a task,
        this is the minimum of the task's priority and the effective
        priority of any held lock.  For a lock, this is the minimum
        effective priority of any waiting task.
        """
        ...

    @abstractmethod
    def propagate_priority(self, from_obj: Any) -> None:
        """
        A task has begun waiting for a lock and we are propagating that
        up the chain of owning objects so that they can recompute their
        effective priority and reschedule themselves.
        """
        ...


@contextlib.contextmanager
def _waiting_on(task: TaskAny, target: Any) -> Iterator[None]:
    """Context manager to maintain a task's waiting_on attribute"""
    try:
        task.set_waiting_on(target)  # type: ignore[attr-defined]
        have_attr = True
    except AttributeError:
        have_attr = False
    try:
        yield
    finally:
        if have_attr:
            task.set_waiting_on(None)  # type: ignore[attr-defined]


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


class PriorityLock(Lock, BasePriorityObject):
    """
    A lock which supports keeping track of the waiting Task
    objects and can compute the highest effective priority
    of all waiting Tasks.
    """

    # Override base class _waiters to use priority queue instead of deque
    _waiters: PriorityQueue[float, tuple[FutureBool, ReferenceTypeTaskAny]] | None  # type: ignore[assignment]

    def __init__(self) -> None:
        # we use weakrefs to avoid reference cycles.  Tasks _own_ locks,
        # but locks don't own tasks. These are _backrefs_.
        super().__init__()
        self._owning: ReferenceTypeTaskAny | None = None

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
        # don't create reference cycles.
        entry = (fut, weakref.ref(task))
        with _waiting_on(task, self):
            self._waiters.add(priority, entry)

            try:
                # Propagate priority to any task owning this lock
                owning = self._owning() if self._owning is not None else None
                if owning is not None:  # pragma: no branch
                    try:
                        owning.propagate_priority(self)  # type: ignore[attr-defined]
                    except AttributeError:  # pragma: no cover
                        pass
                await fut
                self._take_lock(task)
                return True
            finally:
                self._waiters.remove(entry)
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

    def effective_priority(self) -> float | None:
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

    def propagate_priority(self, from_obj: Any) -> None:
        """A Task which is waiting for this lock has potentially had its priority
        changed.  We need to propagate that change to any other tasks waiting"""
        # propagate priority to any task owning this lock
        weak_owning = self._owning
        owning = weak_owning if weak_owning is None else weak_owning()
        if owning is not None:  # pragma: no branch
            try:
                owning.propagate_priority(self)  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover
                pass
        # Find the task in the waiting queue and reschedule it, since it may have
        # moved up in priority.
        try:
            priority = from_obj.effective_priority()
        except AttributeError:  # pragma: no cover
            return
        else:

            def key(
                entry: tuple[FutureBool, ReferenceTypeTaskAny],
            ) -> bool:
                fut, _ = entry
                return fut is from_obj

            if self._waiters:  # pragma: no branch
                self._waiters.reschedule(key, priority)


class PriorityCondition(asyncio.Condition):
    """A Condition variable which notifies waiters in priority order."""

    LockType = PriorityLock

    def __init__(self, lock: asyncio.Lock | None = None) -> None:
        lock = lock or self.LockType()
        super().__init__(lock=lock)
        # Override base class _waiters to use priority queue instead of deque
        self._waiters: PriorityQueue[float, FutureBool] = PriorityQueue()  # type: ignore[assignment]

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

    def propagate_priority(self, from_obj: Any) -> None:
        # we don't propagate priority and don't modify the
        # queue, since priority propagation is a protocol for
        # tasks/locks.  Condition variables don't participate
        # in the priority inversion mechanism directly.
        pass  # pragma: no cover


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
        self._holding_locks: set[PriorityLock] = set()
        self._waiting_on: Any | None = None
        super().__init__(coro, loop=loop, name=name)

    def add_owned_lock(self, lock: PriorityLock) -> None:
        self._holding_locks.add(lock)

    def remove_owned_lock(self, lock: PriorityLock) -> None:
        self._holding_locks.remove(lock)

    def set_waiting_on(self, obj: Any | None) -> None:
        if obj is not None:
            assert self._waiting_on is None
        else:
            assert self._waiting_on is not None
        self._waiting_on = obj

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

    def propagate_priority(self, from_obj: Any) -> None:
        """Notify that someone has started waiting for this task, having it
        pass that notification onwards or reschedule itself if necessary.
        """
        if task_is_runnable(self):
            loop = asyncio.get_running_loop()
            # if the loop supports it, ask for this task to be rescheduled
            try:
                loop.task_reschedule(self)  # type: ignore[attr-defined]
            except AttributeError:  # pragma: no cover
                pass
        elif self._waiting_on:
            # it is waiting for a lock
            try:
                self._waiting_on.propagate_priority(self)
            except AttributeError:  # pragma: no cover
                pass


@dataclass
class PriorityValue:
    """A priority value class, which allows
    for adding a priority boost value to the base priority.
    """

    base_priority: float  # the base priority, as reported by the object
    inserted_at: int  # the n_added when the object was added
    priority_boost: float = 0.0  # a boost value
    priority_class: int = 1  # 0 for immediate priority, 1 for regular

    def priority(self) -> float:
        return self.base_priority + self.priority_boost

    def __lt__(self, other: PriorityValue) -> bool:
        if self.priority_class != other.priority_class:
            return self.priority_class < other.priority_class
        return self.priority() < other.priority()


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
        self._pq: PriorityQueue[PriorityValue, T] = PriorityQueue()
        self._get_priority = get_priority
        self.last_maintenance = 0
        self.n_inserted = 0
        self.n_removed = 0
        self.priority_boost_factor = 1.2

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
        pv = PriorityValue(
            base_priority=self._get_priority(obj),
            inserted_at=self.n_inserted,
        )
        self._pq.add(pv, obj)
        self.update_counters(True)

    def update_counters(self, inserted: bool) -> None:
        if inserted:
            self.n_inserted += 1

            # do we need to perform queue maintenance?
            # compute througput, the lower of items added and
            # removed since the last time.  if it is equal to the
            # queue length, we can do a linear queue management which
            # still is amortized O(1) per entry.
            througput = min(self.n_inserted, self.n_removed)
            limit = max(10, len(self._pq)) + self.last_maintenance
            if througput > limit:
                self.do_maintenance()
                self.last_maintenance = througput
        else:
            if len(self._pq) > 0:
                self.n_removed += 1
            else:
                self.n_inserted = self.n_removed = 0

    def do_maintenance(self) -> None:
        """Iterate over the queue, gather priority information and boost
        priority of objects which have been waiting for a long time."""
        if not self.priority_boost_factor:
            return  # pragma: no cover
        pri, _ = self._pq.peekitem()
        min_pri = max_pri = pri.priority()
        stragglers = []
        limit = self.n_inserted - len(self._pq)
        for pri, obj in self._pq.items():
            if pri.priority_class == 0:
                continue
            base_pri = pri.priority()
            min_pri = min(min_pri, base_pri)
            max_pri = max(max_pri, base_pri)
            # we dermine long-waiting objects to be those inserted more than
            # queue len ago.
            if pri.inserted_at < limit:
                stragglers.append((pri, obj))

        if stragglers:
            self.boost_stragglers(stragglers, min_pri, max_pri)

    def boost_stragglers(
        self, stragglers: list[tuple[PriorityValue, T]], min_pri: float, max_pri: float
    ) -> None:
        n_boosted = 0
        for pri, _ in stragglers:
            # we boost the priority of long waiting objects by a random
            # factor to bring it below the min_pri.
            if pri.base_priority > min_pri:  # pragma: no branch
                pb = self.compute_priority_boost(pri.base_priority, min_pri, max_pri)
                if pb:  # pragma: no branch
                    pri.priority_boost = pb
                    n_boosted += 1
        if n_boosted > 0:  # pragma: no branch
            self._pq.refresh()

    def compute_priority_boost(
        self, priority: float, min_pri: float, max_pri: float
    ) -> float:
        # boost into a range scaled by the factor.  This gives it a chance of
        # being scheduled even before the currently highest priority object.
        range = (min_pri - priority) * self.priority_boost_factor
        r = random.random() * range
        return r

    def append_pri(self, obj: T, priority: float) -> None:
        """
        Insert an item at a specific priority
        """
        pv = PriorityValue(
            base_priority=priority,
            inserted_at=self.n_inserted,
        )
        self._pq.add(pv, obj)
        self.update_counters(True)

    def insert(self, position: int, obj: T) -> None:
        """
        Insert an object to be scheduled at an immediate position.
        The position is typically 0 or 1, where 0 is the next object.
        """
        assert position >= 0
        # the immediate queue is one with priority key (0, n)
        # reglar priority queues are (1, priority) and so the
        # immediate queue is always first.

        promoted: list[T] = []
        priority_val = 0.0
        try:
            while position > len(promoted):
                promoted.append(self.popleft())
            # are there other immediate objects in the queue?
            # if so, we select a one lower priority value for our
            # inserted objects.
            pv, _ = self._pq.peekitem()
            if pv.priority_class == 0:
                priority_val = pv.base_priority - 1
        except IndexError:
            pass
        promoted.append(obj)
        pv = PriorityValue(
            priority_class=0,
            base_priority=priority_val,
            inserted_at=self.n_inserted,
        )
        for obj in promoted:
            self._pq.add(pv, obj)
        self.update_counters(True)

    def popleft(self) -> T:
        result = self._pq.pop()
        self.update_counters(False)
        return result

    def remove(self, obj: T) -> None:
        """
        Remove an object from the queue.
        """
        self._pq.remove(obj)
        self.update_counters(False)

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
    ) -> T | None:
        found = self._pq.find(key, remove)
        if found is not None:
            pri, obj = found
            return obj
        return None

    def reschedule(
        self,
        key: Callable[[T], bool],
        new_priority: float,
    ) -> T | None:
        """
        Reschedule an object which is already in the queue.
        """
        pv = PriorityValue(
            base_priority=new_priority,
            inserted_at=self.n_inserted,
        )
        return self._pq.reschedule(key, pv)

    def reschedule_all(self) -> None:
        """
        Reschedule all objects in the queue based on their priority,
        except the one in the immediate priority class which have
        a fixed ordering.
        """
        newpri = []
        for pri, obj in self._pq.items():
            if pri.priority_class != 0:
                pri.base_priority = self._get_priority(obj)
            newpri.append((pri, obj))
        self._pq.clear()
        self._pq.extend(newpri)


class EventLoopLike(Protocol):  # pragma: no cover
    def call_soon(
        self,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> Handle: ...  # pragma: no cover


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
    ) -> Handle | None:
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
        context: Context | None = None,
    ) -> Handle:
        """Arrange for a callback to be inserted at position 'pos' near the head of
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
    def task_from_handle(self, handle: Handle) -> TaskAny | None:
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


class PrioritySelectorEventLoop(  # type: ignore[misc]
    asyncio.SelectorEventLoop,
    PrioritySchedulingMixin,
):
    def __init__(self, arg: Any = None) -> None:
        super().__init__(arg)
        self.init()
        self._ready = self.ready_queue


DefaultPriorityEventLoop = PrioritySelectorEventLoop

if hasattr(asyncio, "ProactorEventLoop"):  # pragma: no coverage

    class PriorityProactorEventLoop(asyncio.ProactorEventLoop, PrioritySchedulingMixin):  # type: ignore
        def __init__(self, arg: Any = None) -> None:
            super().__init__(arg)
            self.init()
            self._ready = self.ready_queue

    if sys.platform == "win32":  # pragma: no coverage
        DefaultPriorityEventLoop = PriorityProactorEventLoop  # type: ignore

    __all__.append("PriorityProactorEventLoop")


class PriorityEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return DefaultPriorityEventLoop()  # type: ignore
