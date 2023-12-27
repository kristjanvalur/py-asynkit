import asyncio
import sys
import threading
from asyncio import AbstractEventLoop, Handle, events
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, TypeVar
from weakref import ReferenceType

"""Compatibility routines for earlier asyncio versions"""

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)
PYTHON_39 = sys.version_info[:2] <= (3, 9)

T = TypeVar("T")

# The following is needed for mypy to work with Python 3.8
# which doesn't allow subscripting many types
if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
    FutureBool = asyncio.Future[bool]
    ReferenceTypeTaskAny = ReferenceType[_TaskAny]
else:
    _TaskAny = asyncio.Task
    FutureBool = asyncio.Future
    ReferenceTypeTaskAny = ReferenceType

# create_task() got the name argument in 3.8

if PYTHON_38:  # pragma: no cover

    def create_task(
        coro: Coroutine[Any, Any, T],
        *,
        name: Optional[str] = None,
    ) -> _TaskAny:
        return asyncio.create_task(coro)

else:  # pragma: no cover
    create_task = asyncio.create_task  # type: ignore


# loop.call_soon got the context argument in 3.9.10 and 3.10.2
if PYTHON_39:  # pragma: no cover

    def call_soon(
        loop: AbstractEventLoop,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        return loop.call_soon(callback, *args, context=context)

else:  # pragma: no cover

    def call_soon(
        loop: AbstractEventLoop,
        callback: Callable[..., Any],
        *args: Any,
        context: Optional[Context] = None,
    ) -> Handle:
        return loop.call_soon(callback, *args)


if not PYTHON_39:  # pragma: no cover
    from asyncio.mixins import _LoopBoundMixin  # type: ignore[import]

    LoopBoundMixin = _LoopBoundMixin

    class LockHelper:
        # derived locks should inherit from this class
        # since they already inherit from LoopBoundMixin
        pass

else:  # pragma: no cover

    _global_lock = threading.Lock()

    # Used as a sentinel for loop parameter
    _marker = object()

    class LoopBoundMixin:  # type: ignore[no-redef]
        _loop = None

        def __init__(self, *, loop: Any = _marker) -> None:
            if loop is not _marker:
                raise TypeError(
                    f"As of 3.10, the *loop* parameter was removed from "
                    f"{type(self).__name__}() since it is no longer necessary"
                )

        def _get_loop(self) -> AbstractEventLoop:
            loop = events._get_running_loop()

            if self._loop is None:
                with _global_lock:
                    if self._loop is None:
                        self._loop = loop
            if loop is not self._loop:
                raise RuntimeError(f"{self!r} is bound to a different event loop")
            return loop

    LockHelper = LoopBoundMixin  # type: ignore
