from __future__ import annotations

import asyncio
import heapq
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Deque,
    Generic,
    Iterable,
    Iterator,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
)

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)

T = TypeVar("T")


class Sortable(Protocol):
    """Objects that have the < operator defined"""

    def __lt__(self: T, other: T) -> bool:
        ...  # pragma: no cover


P = TypeVar("P", bound=Sortable)


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
    Popping and iterating returns (prioritt, object) typles, and iteration
    is in the order they would be popped.
    Identical priorites are returned in the order they were inserted.
    Also allows for searching, removing and rescheduling objects by key.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._pq: list[PriEntry[P, T]] = []

    def __len__(self) -> int:
        return len(self._pq)

    def __bool__(self) -> bool:
        return bool(self._pq)

    def __iter__(self) -> Iterator[Tuple[P, T]]:
        for entry in sorted(self._pq):
            yield entry.priority, entry.obj

    def clear(self) -> None:
        self._pq.clear()
        self._sequence = 0

    def append(self, pri: P, obj: T) -> None:
        heapq.heappush(self._pq, PriEntry(pri, self._sequence, obj))
        self._sequence += 1

    def extend(self, entries: Iterable[Tuple[P, T]]) -> None:
        # use this to add a lot of entries at once, since heapify is O(n)
        for pri, obj in entries:
            self._pq.append(PriEntry(pri, self._sequence, obj))
            self._sequence += 1
        heapq.heapify(self._pq)

    def popleft(self) -> Tuple[P, T]:
        entry = heapq.heappop(self._pq)
        if not self._pq:
            self._sequence = 0
        return entry.priority, entry.obj

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
    ) -> Optional[Tuple[P, T]]:
        # reversed is a heuristic because we are more likely to be looking for
        # more recently added items
        for i, entry in enumerate(reversed(self._pq)):
            if key(entry.obj):
                if remove:
                    # remove the entry. We replace the deleted item with the tail
                    # and heapify again, which disturbs the heap the least.
                    if i != 0:
                        i = len(self._pq) - i - 1
                        self._pq[i] = self._pq.pop()
                        heapq.heapify(self._pq)
                    else:
                        self._pq.pop()
                        if not self._pq:
                            self._sequence = 0
                return entry.priority, entry.obj
        return None

    def reschedule(
        self,
        key: Callable[[T], bool],
        new_priority: P,
    ) -> Optional[T]:
        """
        Reschedule an object which is already in the queue.
        """
        for entry in reversed(self._pq):
            if key(entry.obj):
                # use only the __lt__ operator to determine if priority has changed
                # since that is the one used to define priority for the heap
                if entry.priority < new_priority or new_priority < entry.priority:
                    # it retains its old squence number
                    # could mark the old entry as removed and re-add a new entry,
                    # that will be O(logn) instead of O(n) but lets not worry.
                    entry.priority = new_priority
                    heapq.heapify(self._pq)
                return entry.obj
        return None


class PriEntry(Generic[P, T]):
    sequence: int = 0

    def __init__(self, priority: P, sequence: int, obj: T) -> None:
        self.priority = priority
        self.sequence = sequence
        self.obj = obj

    def __lt__(self, other: PriEntry[P, T]) -> bool:
        # only use the __lt__ opeator on the priority object,
        # even in reverse to determine non-equality
        return (self.priority < other.priority) or (
            not (other.priority < self.priority) and self.sequence < other.sequence
        )
