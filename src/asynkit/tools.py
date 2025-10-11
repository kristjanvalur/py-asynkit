from __future__ import annotations

import asyncio
import contextlib
import heapq
from collections import deque
from collections.abc import Callable, Generator, Iterable, Iterator
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
)

from typing_extensions import Protocol

T = TypeVar("T")


class Sortable(Protocol):
    """Objects that have the < operator defined"""

    def __lt__(self: T, other: T) -> bool: ...  # pragma: no cover


P = TypeVar("P", bound=Sortable)


if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
else:
    _TaskAny = asyncio.Task

create_task = asyncio.create_task


def deque_pop(d: deque[T], pos: int = -1) -> T:
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

    def __iter__(self) -> Iterator[T]:
        """
        Iterate over the queue.  The order is undefined
        unless sort() has been called.
        """
        for entry in self._pq:
            yield entry.obj

    def items(self) -> Iterator[tuple[P, T]]:
        """Iterate over the queue, returning (priority, object) tuples. The order
        is undefined unless sort() has been called.
        """
        for entry in self._pq:
            yield entry.priority, entry.obj

    def refresh(self) -> None:
        """Refresh the queue state.  Can be used if any of the objects
        have had their priority changed.
        """
        heapq.heapify(self._pq)

    def sort(self) -> None:
        """Sort the queue in priority order.  Can be used to ensure that
        iteration is in priority order.
        """
        self._pq.sort()

    def sorted(self) -> PriorityQueue[P, T]:
        """convenience function which returns a sorted copy of itself"""
        c = self.copy()
        c.sort()
        return c

    def ordered(self) -> Generator[T, None, None]:
        """Iterate over the queue in the same order as it would be popped.
        The generator must be exhausted or closed after use."""
        items = self.ordereditems()
        try:
            for _, obj in items:
                yield obj
        finally:
            items.close()

    def ordereditems(self) -> Generator[tuple[P, T], None, None]:
        """Iterate over the queue in the same order as it would be popped,
        returning (priority, object) tuples.
        The generator must be exhausted or closed after use."""
        popped = []
        try:
            while self._pq:
                head = self._pq[0]
                yield head.priority, head.obj
                # only pop after the yield, which means that the caller
                # wants to move to the next object
                popped.append(heapq.heappop(self._pq))
        finally:
            # heuristic for the fastest method to restore the heap
            lp, lq = len(popped), len(self._pq)
            if lp >= lq:
                # we can just merge them and don't need to heapify
                popped.extend(self._pq)
                self._pq = popped
            elif lp >= lq >> 1:
                popped.extend(self._pq)
                heapq.heapify(popped)
                self._pq = popped
            else:
                # for relatively few items, it is faster to push them back
                for entry in popped:
                    heapq.heappush(self._pq, entry)

    def clear(self) -> None:
        self._pq.clear()
        self._sequence = 0

    def add(self, pri: P, obj: T) -> None:
        heapq.heappush(self._pq, PriEntry(pri, self._sequence, obj))
        self._sequence += 1

    def pop(self) -> T:
        entry = heapq.heappop(self._pq)
        if not self._pq:
            self._sequence = 0
        return entry.obj

    def popitem(self) -> tuple[P, T]:
        entry = heapq.heappop(self._pq)
        if not self._pq:
            self._sequence = 0
        return entry.priority, entry.obj

    def extend(self, entries: Iterable[tuple[P, T]]) -> None:
        # use this to add a lot of entries at once, since heapify is O(n)
        for pri, obj in entries:
            self._pq.append(PriEntry(pri, self._sequence, obj))
            self._sequence += 1
        heapq.heapify(self._pq)

    def peek(self) -> T:
        entry = self._pq[0]
        return entry.obj

    def peekitem(self) -> tuple[P, T]:
        entry = self._pq[0]
        return entry.priority, entry.obj

    def remove(self, obj: T) -> P:
        """
        Remove an object from the queue.  The object must be in the queue.
        comparison is based on object equality.
        """
        for i, entry in enumerate(self._pq):
            if entry.obj == obj:
                break
        else:
            raise ValueError(f"{obj!r} not in queue")
        if i == 0:
            e = heapq.heappop(self._pq)
        elif i == len(self._pq) - 1:
            e = self._pq.pop()
        else:
            e = self._pq[i]
            self._pq[i] = self._pq.pop()
            heapq.heapify(self._pq)
        if not self._pq:
            self._sequence = 0
        return e.priority

    def copy(self) -> PriorityQueue[P, T]:
        """Create a shallow copy of the priority queue"""
        new = type(self)()
        new._pq[:] = self._pq[:]
        new._sequence = self._sequence
        return new

    def find(
        self,
        key: Callable[[T], bool],
        remove: bool = False,
    ) -> tuple[P, T] | None:
        # reversed is a heuristic because we are more likely to be looking for
        # more recently added items
        for i, entry in enumerate(reversed(self._pq)):
            if key(entry.obj):
                break
        else:
            return None

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

    def reschedule(
        self,
        key: Callable[[T], bool],
        new_priority: P,
    ) -> T | None:
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

    def __repr__(self) -> str:  # pragma: no cover
        return f"PriEntry({self.priority!r}, {self.sequence!r}, {self.obj!r})"

    def __lt__(self, other: PriEntry[P, T]) -> bool:
        # only use the __lt__ opeator on the priority object,
        # even in reverse to determine non-equality
        return (self.priority < other.priority) or (
            not (other.priority < self.priority) and self.sequence < other.sequence
        )


class Cancellable(Protocol):
    def cancel(self, msg: str | None = None) -> Any: ...

    def cancelled(self) -> bool: ...


CA = TypeVar("CA", bound=Cancellable)


@contextlib.contextmanager
def cancelling(target: CA, msg: str | None = None) -> Generator[CA, None, None]:
    """Ensure that the target is cancelled"""
    try:
        yield target
    finally:  # pragma: no cover
        target.cancel(msg)
