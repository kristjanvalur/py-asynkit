import asyncio
import sys
from collections import defaultdict, deque
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    DefaultDict,
    Deque,
    Generic,
    Iterator,
    Optional,
    Tuple,
    TypeVar,
)

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)

T = TypeVar("T")
P = TypeVar("P")

if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
else:
    _TaskAny = asyncio.Task

if PYTHON_38:  # pragma: no cover

    def create_task(
        coro: Coroutine[Any, Any, T],
        *,
        name: Optional[str] = None,
    ) -> _TaskAny:
        return asyncio.create_task(coro)

else:  # pragma: no cover
    create_task = asyncio.create_task  # type: ignore


def deque_pop(d: Deque[T], pos: int = -1) -> T:
    """
    Allows popping from an arbitrary position in a deque.
    The `pos` argument has the same meaning as for
    `list.pop()`
    """
    ld = len(d)
    if pos < 0:
        pos += ld  # convert to positive index
        if pos < 0:
            raise IndexError("pop index out of range")
    if pos < ld >> 2:  # closer to head
        d.rotate(-pos)
        r = d.popleft()
        d.rotate(pos)
        return r
    if pos < ld:  # pop of the tail end
        pos -= ld - 1
        d.rotate(-pos)
        r = d.pop()
        d.rotate(pos)
        return r
    raise IndexError("pop index out of range")


class PriorityQueue(Generic[P, T]):
    """
    A simple priority queue for objects.  Allows 'append' at thend
    and 'popleft'.  The objects are sorted by priority, which is provided.
    Identical priorites are returned in the order they were inserted.
    Also allows for searching and removing objects by key.
    """

    def __init__(self) -> None:
        # the queues are stored in a dictionary, keyed by (priority-class, priority)
        # the priority-class is 1 for regular priority, 0 for immediate priority.
        self._queues: DefaultDict[P, Deque[T]] = defaultdict(deque)

    def clear(self) -> None:
        self._queues.clear()

    def __len__(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def __bool__(self) -> bool:
        return bool(self._queues)

    def __iter__(self) -> Iterator[Tuple[P, T]]:
        for pri, queue in sorted(self._queues.items()):
            for obj in queue:
                yield pri, obj

    def append(self, pri: P, obj: T) -> None:
        """
        Insert an item into its default place according to priority
        """
        self._queues[pri].append(obj)

    def popleft(self) -> Tuple[P, T]:
        if self._queues:
            pri, queue = min(self._queues.items())
            result = queue.popleft()
            if not queue:
                del self._queues[pri]
            return pri, result
        raise IndexError("pop from empty queue")

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
        priority_hint: Optional[P] = None,
    ) -> Optional[Tuple[P, T]]:
        # first look in the given queue
        if priority_hint is not None:
            priq = self._queues.get(priority_hint, None)
            if priq is not None:
                obj = self._deque_find(priq, key, remove)
                if obj is not None:
                    if remove and not priq:
                        del self._queues[priority_hint]
                    return priority_hint, obj
        else:
            priq = None

        # then look in the other queues
        for priority, queue in self._queues.items():
            if priq is queue:
                continue
            obj = self._deque_find(queue, key, remove)
            if obj is not None:
                if remove and not queue:
                    del self._queues[priority]
                return priority, obj
        return None  # not found

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
        new_priority: P,
        priority_hint: Optional[P] = None,
    ) -> Optional[T]:
        """
        Reschedule an object which is already in the queue.
        """
        # look for it in the queues, with hint of priority
        r = self.find(key, remove=False, priority_hint=priority_hint)
        if r is None:
            return None  # not found
        pri, obj = r
        if pri == new_priority:
            return obj  # nothing needs to be done
        # remove it from the queue
        r = self.find(key, remove=True, priority_hint=pri)
        assert r is not None
        self.append(new_priority, obj)
        return obj
