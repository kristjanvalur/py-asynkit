import asyncio
from typing_extensions import Literal
from weakref import WeakSet

from asyncio import Lock, mixins, Task


def get_task_effective_priority(task: asyncio.Task) -> float:
    try:
        return task.effective_priority
    except AttributeError:
        return 0
    
class PriLock(Lock):
    """
    A lock which supports keeping track of the waiting Task
    objects and can compute the highest effective priority
    of all waiting Tasks.
    """

    def __init__(self, *, loop=mixins._marker):
        super().__init__(loop=loop)
        self._waiting = WeakSet()

    async def acquire(self) -> Literal[True]:
        task = asyncio.current_task()
        self._waiting.add(task)
        try:
            await super().acquire()
            try:
                task.add_owned_lock(self)
            except AttributeError:
                pass
            return True
        finally:
            self._waiting.remove(task)
    
    def release(self) -> None:
        task = asyncio.current_task()
        try:
            task.remove_owned_lock(self)
        except AttributeError:
            pass
        super().release()

    def get_waiting_priority(self):
        return min(get_task_effective_priority(t) for t in self._waiting)
        

class PriTask(Task):
    def __init__(self, coro, *, loop=None, name=None) -> None:
        super().__init__(coro, loop=loop, name=name)
        self.priority: float = 0
        self._holding_locks = WeakSet()

    @property
    def effective_priority(self) -> float:
        holding_pri = min(l.get_waiting_priority() for l in self._holding_locks)
        return min(self.priority, holding_pri)
