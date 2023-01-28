import asyncio
import sys
from typing import (
    Any,
    Coroutine,
    Generator,
    Optional,
    TypeVar,
    Union,
    Deque,
    List,
    TYPE_CHECKING,
)

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)

T = TypeVar("T")
CoroLike = Union[Coroutine[Any, Any, T], Generator[Any, Any, T]]

if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
else:
    _TaskAny = asyncio.Task

if PYTHON_38:
    # Ignore typing to remove warnings about different type signatures.
    def create_task(  # type: ignore
        coro: Coroutine[Any, Any, T],
        *,
        name: Optional[str] = None,
    ) -> _TaskAny:
        return asyncio.create_task(coro)

else:
    create_task = asyncio.create_task  # pragma: no cover


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


def task_from_handle(item: asyncio.Handle) -> Optional[_TaskAny]:
    """
    Runnable task objects exist as callbacks on the ready queue in the loop.
    Specifically, they are Handle objects, containing a Task bound method
    as the callback. Retrieve such a Task instance from a Handle if possible.
    Not everything on the queue are necessarily tasks, in which case we return None
    """

    try:
        task = item._callback.__self__  # type: ignore
    except AttributeError:
        return None
    if isinstance(task, asyncio.Task):
        return task
    return None
