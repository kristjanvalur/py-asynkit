import asyncio
import sys
from typing import Any, Coroutine, Generator, Optional, TypeVar, Union

_ver = sys.version_info[:2]

T = TypeVar("T")
CoroLike = Union[Coroutine[Any, Any, T], Generator[Any, Any, T]]


if _ver >= (3, 8):
    create_task = asyncio.create_task
else:  # pragma: no cover

    # can't really try to replicate the type definitions here.
    def create_task(  # type: ignore
        coro: CoroLike[T],
        *,
        name: Optional[str] = None,
    ) -> asyncio.Future[T]:
        return asyncio.create_task(coro)


def deque_pop(d, pos=-1):
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
    [].pop(pos)


def task_from_handle(item):
    """
    Runnable task objects exist as callbacks on the ready queue in the loop.
    Specifically, they are Handle objects, containing a Task bound method
    as the callback. Retrieve such a Task instance from a Handle if possible.
    Not everything on the queue are necessarily tasks, in which case we return None
    """

    try:
        task = item._callback.__self__
    except AttributeError:
        return None
    if isinstance(task, asyncio.Task):
        return task
