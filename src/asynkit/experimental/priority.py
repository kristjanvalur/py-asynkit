import asyncio
import weakref
from abc import ABC, abstractmethod
from asyncio import Lock, Task
from collections import defaultdict, deque
from typing import (
    Callable,
    DefaultDict,
    Deque,
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
from asynkit.tools import deque_pop

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


class PriorityQueue(Generic[T]):
    """
    A simple priority queue for objects, which also allows scheduling
    at a fixed early position.  It respects floating point priority
    values of objects, but also allows positional scheduling when
    required.  Lower priority values are scheduled first.
    """

    def __init__(self, get_priority: Callable[[T], float]) -> None:
        # the queues are stored in a dictionary, keyed by (priority-class, priority)
        # the priority-class is 1 for regular priority, 0 for immediate priority.
        self._queues: DefaultDict[Tuple[int, float], Deque[T]] = defaultdict(deque)
        self._get_priority = get_priority

    def clear(self) -> None:
        self._queues.clear()

    def append(self, obj: T) -> None:
        """
        Insert an item into its default place according to priority
        """
        priority = self._get_priority(obj)
        self._queues[(1, priority)].append(obj)

    def append_pri(self, obj: T, priority: float) -> None:
        """
        Insert an item at a specific priority
        """
        self._queues[(1, priority)].append(obj)

    def insert(self, position: int, obj: T) -> None:
        """
        Insert an object to be scheduled at an immediate position.
        The position is typically 0 or 1, where 0 is the next object.
        """
        assert position >= 0
        # the immediate queue is one with priority key (0, 0)
        # reglar priority queues are (1, priority) and so the
        # immediate queue is always first.

        # promote priority queue objects to the immediate queue
        # to place the new object in the right place.
        # must pop it from the dict so that it is not subject
        # to self.pop()
        immediate = self._queues.pop((0, 0), None)
        if immediate is None:
            immediate = deque()
        try:
            while len(immediate) < position:
                try:
                    promote = self.pop()
                    immediate.append(promote)
                except IndexError:
                    # just put it at the end
                    break
            immediate.insert(position, obj)
        finally:
            self._queues[(0, 0)] = immediate

    def __iter__(self) -> Iterator[T]:
        for _, queue in sorted(self._queues.items()):
            for obj in queue:
                yield obj

    def __len__(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def pop(self) -> T:
        if self._queues:
            pri, queue = min(self._queues.items())
            result = queue.popleft()
            if not queue:
                del self._queues[pri]
            return result
        raise IndexError("pop from empty queue")

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
        priority_hint: Optional[float] = None,
    ) -> Optional[T]:
        hint = (1, priority_hint) if priority_hint is not None else None
        r = self._find(key, remove, hint)
        return r[1]

    def _find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
        priority_hint: Optional[Tuple[int, float]] = None,
    ) -> Optional[Tuple[Tuple[int, float], T]]:
        # first look in the given queue
        if priority_hint is not None:
            priq = self._queues.get(priority_hint, None)
            if priq is not None:
                obj = self._deque_find(priq, key, remove)
                if obj is not None:
                    return priority_hint, obj
        else:
            priq = None

        # then look in the other queues
        for priority, queue in self._queues.items():
            if priq is queue:
                continue
            obj = self._deque_find(queue, key, remove)
            if obj is not None:
                return priority, obj
        raise ValueError("object not found")

    def _deque_find(
        self, queue: Deque[T], key: Callable[[T], bool], remove: bool = False
    ) -> Optional[T]:
        for i, obj in enumerate(reversed(queue)):
            if key(obj):
                if remove:
                    deque_pop(queue, len(queue) - i - 1)
                return obj
        return None

    def reschedule(
        self,
        key: Callable[[T], bool],
        new_priority: float,
        priority_hint: Optional[float] = None,
    ) -> None:
        """
        Reschedule an object which is already in the queue.
        """
        # look for it in the queues, with hint of priority
        hint = (1, priority_hint) if priority_hint is not None else None
        r = self._find(key, remove=False, priority_hint=hint)
        pri, obj = r
        if pri == (1, new_priority):
            return  # nothing needs to be done
        # remove it from the queue
        r = self._find(key, remove=True, priority_hint=pri)
        self.append_pri(obj, new_priority)

    def reschedule_all(self):
        """
        Reschedule all objects in the queue based on their priority,
        except the one in the immediate priority class which have
        a fixed ordering.
        """
        queues = self._queues
        self._queues = defaultdict(deque)
        for pri, queue in sorted(queues.items()):
            if pri[0] == 0:
                self._queues[pri] = queue
            else:
                for obj in queue:
                    self.append(obj)
