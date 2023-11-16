import asyncio
import weakref
from abc import ABC, abstractmethod
from asyncio import Lock, Task
from typing import (
    Callable,
    Generic,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

from typing_extensions import Literal

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


class PriorityLock(Lock, BasePriorityObject):
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
        if owning is not None:
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
            raise RuntimeError("Lock is not acquired.")

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

        if not fut.done():
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


class PriorityTask(Task, BasePriorityObject):  # type: ignore[type-arg]
    def __init__(  # type: ignore[no-untyped-def]
        self,
        coro,
        *,
        loop=None,
        name=None,
        priority: float = 0,
    ) -> None:
        super().__init__(coro, loop=loop, name=name)
        self.priority_value = priority
        self._holding_locks: Set[PriorityLock] = set()

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


class FancyPriorityQueue(Generic[T]):
    """
    A simple priority queue for objects, which also allows scheduling
    at a fixed early position.  It respects floating point priority
    values of objects, but also allows positional scheduling when
    required.  Lower priority values are scheduled first.
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
