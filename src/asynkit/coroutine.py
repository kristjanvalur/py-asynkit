import asyncio
import functools
import inspect
import sys
import types
import typing
from contextvars import Context, copy_context
from types import FrameType
from typing import AsyncGenerator, Optional, Union

from .tools import create_task

__all__ = [
    "CoroStart",
    "coro_await",
    "coro_eager",
    "func_eager",
    "eager",
    "coro_get_frame",
    "coro_is_new",
    "coro_is_suspended",
    "coro_is_finished",
]

PYTHON_37 = sys.version_info.major == 3 and sys.version_info.minor == 7

Coroutine = Union[typing.Coroutine, typing.Generator]
CoroutineLike = Union[typing.Coroutine, typing.Generator, AsyncGenerator]

"""
Tools and utilities for advanced management of coroutines
"""


# Helpers to find if a coroutine (or a generator as created by types.coroutine)
# has started or finished


def _coro_getattr(coro, suffix):
    """
    Get an attribute of a coroutine or coroutine like object
    """
    # look for
    # 1. coroutine
    # 2. legacy coroutine (even wrapped with types.coroutine())
    # 3. async generator
    for prefix in ("cr_", "gi_", "ag_"):
        if hasattr(coro, prefix + suffix):
            # coroutine (async function)
            return getattr(coro, prefix + suffix)
    raise TypeError(
        f"a coroutine or coroutine like object is required. Got: {type(coro)}"
    )


def coro_get_frame(coro: CoroutineLike) -> FrameType:
    """
    Get the current frame of a coroutine or coroutine like object
    (generator, legacy coroutines)
    """
    return _coro_getattr(coro, "frame")


def coro_is_new(coro: CoroutineLike):
    """
    Returns True if the coroutine has just been created and
    never not yet started
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_CREATED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_CREATED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:  # pragma: no cover
            return coro.ag_frame and coro.ag_frame.f_lasti < 0
        else:
            return coro.ag_frame and not coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_suspended(coro: CoroutineLike):
    """
    Returns True if the coroutine has started but not exited
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_SUSPENDED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_SUSPENDED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:  # pragma: no cover
            # frame is None if it has already exited
            # the currently running coroutine is also not suspended by definition.
            return coro.ag_frame and coro.ag_frame.f_lasti >= 0
        else:
            # This is true only if we are inside an anext() or athrow(), not if the
            # inner coroutine is itself doing an await before yielding a value.
            return coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_finished(coro: CoroutineLike) -> bool:
    """
    Returns True if the coroutine has finished execution, either by
    returning or throwing an exception
    """
    return coro_get_frame(coro) is None


class CoroStart:
    """
    A class to encapsulate the state of a coroutine which is manually started
    until its first suspension point, and then resumed. This facilitates
    later execution of coroutines, encapsulating them in Tasks only at the point when
    they initially become suspended.
    `context`: A context object to run the coroutine in
    """

    __slots__ = ["coro", "context", "start_result"]

    def __init__(
        self,
        coro: Coroutine,
        *,
        context: Optional[Context] = None,
    ):
        self.coro: Coroutine = coro
        self.context = context
        self.start_result = self._start()

    def _start(self):
        """
        Start the coroutine execution. It runs the coroutine to its first suspension
        point or until it raises an exception or returns a value, whichever comes
        first. Returns `True` if the coroutine finished without blocking.
        """
        try:
            return (
                self.context.run(self.coro.send, None)
                if self.context
                else self.coro.send(None)
            ), None
        except BaseException as exception:
            # Coroutine returned without blocking
            return (None, exception)

    def __await__(self):
        """
        Resume the excecution of the started coroutine.  CoroStart is an
        _awaitable_.
        """
        if not self.start_result:
            # exhausted coroutine, triger the "cannot reuse" error
            self.coro.send(None)

        out_value, exc = self.start_result
        self.start_result = None
        # process any exception generated by the initial start
        if exc:
            if isinstance(exc, StopIteration):
                return exc.value
            raise exc

        # yield up the initial future from `coro_start`.
        # This is similar to how `yield from` is defined (see pep-380)
        # except that it uses a coroutines's send() and throw() methods.
        while True:
            try:
                in_value = yield out_value
            except GeneratorExit:
                self.coro.close()
                raise
            except BaseException as exc:
                try:
                    out_value = (
                        self.context.run(self.coro.throw, exc)
                        if self.context
                        else self.coro.throw(exc)
                    )
                except StopIteration as exc:
                    return exc.value
            else:
                try:
                    out_value = (
                        self.context.run(self.coro.send, in_value)
                        if self.context
                        else self.coro.send(in_value)
                    )
                except StopIteration as exc:
                    return exc.value

    def close(self):
        self.coro.close()
        self.start_result = None

    def done(self):
        """returns true if the coroutine finished without blocking"""
        return self.start_result[1] is not None

    def result(self):
        """
        Returns the result or raises the exception
        """
        exc = self.start_result[1]
        if exc is None:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return exc.value
        raise exc

    def exception(self) -> Optional[BaseException]:
        """
        Returns the exception or None
        """
        exc = self.start_result[1]
        if exc is None:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return None
        return exc

    async def as_coroutine(self):
        """
        Continue execution of the coroutine that was started by start()
        Returns a coroutine which can be awaited
        """
        return await self

    def as_future(self):
        """
        if `done()` convert the result of the coroutine into a `Future`
        and return it.  Otherwise raise a `RuntimeError`
        """
        if not self.done():
            raise RuntimeError("CoroStart: coroutine not done()")
        future = asyncio.get_running_loop().create_future()
        exc = self.start_result[1]
        if isinstance(exc, StopIteration):
            future.set_result(exc.value)
        else:
            future.set_exception(exc)
        return future


async def coro_await(coro: Coroutine, *, context: Optional[Context] = None):
    """
    A simple await, using the partial run primitives, equivalent to
    `async def coro_await(coro): return await coro`
    `context` can be provided for the coroutine to run in instead
    of the currently active context.
    """
    cs = CoroStart(coro, context=context)
    return await cs


def coro_eager(coro, *, create_task=create_task, name="eager"):
    """
    Make the coroutine "eager":
    Start the coroutine. If it blocks, create a task to continue
    execution and return immediately to the caller.
    The return value is either a non-blocking awaitable returning any
    result or exception, or a Task object.
    This implements a depth-first kind of Task execution.
    """

    # start the coroutine. Run it to the first block, exception or return value.
    cs = CoroStart(coro, context=copy_context())
    if cs.done():
        return cs.as_future()
    return create_task(cs.as_coroutine(), name=name)


def func_eager(func, *, create_task=create_task, name="eager"):
    """
    Decorator to automatically apply the `coro_eager` to the
    coroutine generated by invoking the given async function
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return coro_eager(func(*args, **kwargs), create_task=create_task, name=name)

    return wrapper


def eager(arg, *, create_task=create_task, name="eager"):
    """
    Convenience function invoking either `coro_eager` or `func_eager`
    to either decorate an async function or convert a coroutine returned by
    invoking an async function.
    """
    if isinstance(arg, types.CoroutineType):
        # A coroutine
        return coro_eager(arg, create_task=create_task, name=name)
    if isinstance(arg, types.FunctionType):
        return func_eager(arg, create_task=create_task, name=name)
    raise TypeError("need coroutine or function")
