import asyncio
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Coroutine,
    Deque,
    Optional,
    TypeVar,
)

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)

T = TypeVar("T")

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
