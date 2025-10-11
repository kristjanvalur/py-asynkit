import asyncio
import sys
import threading
from asyncio import AbstractEventLoop, Handle, events
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, TypeVar
from weakref import ReferenceType

"""Compatibility routines for earlier asyncio versions"""

# Python version checks
PY_311 = sys.version_info >= (3, 11)

T = TypeVar("T")

# The following is needed because some generic types (like asyncio.Task and
# weakref.ReferenceType) cannot be subscripted at runtime, even in Python 3.10+.
# We use TYPE_CHECKING to provide subscripted types for mypy while using
# unsubscripted types at runtime to avoid TypeError.
if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
    FutureBool = asyncio.Future[bool]
    ReferenceTypeTaskAny = ReferenceType[_TaskAny]
else:
    _TaskAny = asyncio.Task
    FutureBool = asyncio.Future
    ReferenceTypeTaskAny = ReferenceType

# create_task() and loop.call_soon() have all features in Python 3.10+
create_task = asyncio.create_task


def call_soon(
    loop: AbstractEventLoop,
    callback: Callable[..., Any],
    *args: Any,
    context: Context | None = None,
) -> Handle:
    return loop.call_soon(callback, *args, context=context)


if sys.version_info >= (3, 10):  # pragma: no cover
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
