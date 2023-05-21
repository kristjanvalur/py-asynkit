import asyncio
import sys
from asyncio import AbstractEventLoop, Handle
from contextvars import Context
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, TypeVar

"""Compatibility routines for earlier asyncio versions"""

# 3.8 or earlier
PYTHON_38 = sys.version_info[:2] <= (3, 8)
PYTHON_39 = sys.version_info[:2] <= (3, 9)

T = TypeVar("T")

if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
else:
    _TaskAny = asyncio.Task

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
