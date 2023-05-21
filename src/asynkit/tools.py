import asyncio
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Coroutine,
    Deque,
    List,
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
    if pos == -1:
        return d.pop()
    elif pos == 0:
        return d.popleft()

    if pos >= 0:
        if pos < len(d):
            d.rotate(-pos)
            r = d.popleft()
            d.rotate(pos)
            return r
    elif pos >= -len(d):
        pos += 1
        d.rotate(-pos)
        r = d.pop()
        d.rotate(pos)
        return r
    # create exception
    empty: List[T] = []
    return empty.pop(pos)
