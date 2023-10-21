import asyncio
import weakref
from abc import ABC, abstractmethod
from asyncio import Lock, Task
from typing import Optional, Set
from weakref import WeakSet

from typing_extensions import Literal

from asynkit.loop.types import TaskAny
from asynkit.scheduling import task_is_runnable


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
            super().__init__(loop=loop)
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
                if task_is_runnable(owning):
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
