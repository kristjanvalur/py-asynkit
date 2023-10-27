import asyncio
import weakref
from abc import ABC, abstractmethod
from asyncio import Lock, Task
from typing import (
    Callable,
    Generic,
    Iterator,
    Optional,
    Set,
    Tuple,
    TypeVar,
)
from weakref import WeakSet

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

    def __init__(self, *, loop=None) -> None:  # type: ignore[no-untyped-def]
        if loop is not None:
            super().__init__(loop=loop)  # pragma: no cover
        else:
            super().__init__()
        # we use weakrefs to avoid reference cycles.  Tasks _own_ locks,
        # but locks don't own tasks. These are _backrefs_.
        self._waiting: WeakSet[TaskAny] = WeakSet()
        self._owning: Optional[weakref.ReferenceType[TaskAny]] = None

    async def acquire(self) -> Literal[True]:
        task = asyncio.current_task()
        assert task is not None
        self._waiting.add(task)
        try:
            # greedily reschedule a runnable owning task
            # in case its priority has changed
            owning = self._owning() if self._owning is not None else None
            if owning is not None:
                if task_is_runnable(owning):  # pragma: no branch
                    try:
                        owning.reschedule()  # type: ignore[attr-defined]
                    except AttributeError:
                        pass

            await super().acquire()

            assert self._owning is None
            self._owning = weakref.ref(task)
            try:
                task.add_owned_lock(self)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            return True
        finally:
            self._waiting.remove(task)

    def release(self) -> None:
        task = asyncio.current_task()
        assert task is not None
        assert self._owning is not None and self._owning() is task
        self._owning = None
        try:
            task.remove_owned_lock(self)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        super().release()

    def effective_priority(self) -> Optional[float]:
        # waiting tasks are either PriorityTasks or not.
        # regular tasks are given a priority of 0
        priorities = []
        for t in self._waiting:
            try:
                priorities.append(
                    t.effective_priority(),  # type: ignore[attr-defined]
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
        self._immediates = 0

    def __iter__(self) -> Iterator[T]:
        for _, obj in self._pq:
            yield obj

    def __len__(self) -> int:
        return len(self._pq)

    def __bool__(self) -> bool:
        return bool(self._pq)

    def clear(self) -> None:
        self._pq.clear()
        self._immediates = 0

    def append(self, obj: T) -> None:
        """
        Insert an item into its default place according to priority
        """
        self._pq.append((1, self._get_priority(obj)), obj)

    def append_pri(self, obj: T, priority: float) -> None:
        """
        Insert an item at a specific priority
        """
        self._pq.append((1, priority), obj)

    def insert(self, position: int, obj: T) -> None:
        """
        Insert an object to be scheduled at an immediate position.
        The position is typically 0 or 1, where 0 is the next object.
        """
        assert position >= 0
        # the immediate queue is one with priority key (0, 0)
        # reglar priority queues are (1, priority) and so the
        # immediate queue is always first.

        if position == self._immediates:
            # we can just add another immediate.
            self._pq.append((0, 0), obj)
            self._immediates += 1
            return

        # we must promote.  We must pop all immediates off and then regulars
        # to create the new list of immediates.  This is O(n) but we expect
        # n to be low, 0 or 1 most of the time.
        promoted: list[T] = []
        try:
            while self._immediates > 0 or position >= len(promoted):
                promoted.append(self.popleft())
        except IndexError:
            pass  # no more to promote
        promoted.insert(position, obj)
        for obj in promoted:
            self._pq.append((0, 0), obj)
        self._immediates = len(promoted)

    def popleft(self) -> T:
        pri, obj = self._pq.popleft()
        if self._immediates > 0:
            assert pri == (0, 0)
            self._immediates -= 1
        return obj

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
    ) -> Optional[T]:
        found = self._pq.find(key, remove)
        if found is not None:
            pri, obj = found
            if remove and pri == (0, 0):
                self._immediates -= 1
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
        for pri, obj in self._pq:
            if pri != (0, 0):
                pri = (1, self._get_priority(obj))
            newpri.append((pri, obj))
        self._pq.clear()
        self._pq.extend(newpri)
