import asyncio
import functools
import inspect
import sys
import types
from contextvars import Context, copy_context
from types import FrameType
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

from typing_extensions import ParamSpec

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

T = TypeVar("T")
P = ParamSpec("P")
T_co = TypeVar("T_co", covariant=True)
CoroLike = Union[Coroutine[Any, Any, T], Generator[Any, Any, T]]
Suspendable = Union[Coroutine, Generator, AsyncGenerator]

"""
Tools and utilities for advanced management of coroutines
"""


# Helpers to find if a coroutine (or a generator as created by types.coroutine)
# has started or finished


def _coro_getattr(coro: Suspendable, suffix: str) -> Any:
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


def coro_get_frame(coro: Suspendable) -> FrameType:
    """
    Get the current frame of a coroutine or coroutine like object
    (generator, legacy coroutines)
    """
    return cast(FrameType, _coro_getattr(coro, "frame"))


def coro_is_new(coro: Suspendable) -> bool:
    """
    Returns True if the coroutine has just been created and
    never not yet started
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_CREATED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_CREATED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:
            return coro.ag_frame is not None and coro.ag_frame.f_lasti < 0
        else:
            return coro.ag_frame is not None and not coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_suspended(coro: Suspendable) -> bool:
    """
    Returns True if the coroutine has started but not exited
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_SUSPENDED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_SUSPENDED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:
            # frame is None if it has already exited
            # the currently running coroutine is also not suspended by definition.
            return coro.ag_frame is not None and coro.ag_frame.f_lasti >= 0
        else:
            # This is true only if we are inside an anext() or athrow(), not if the
            # inner coroutine is itself doing an await before yielding a value.
            return coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_finished(coro: Suspendable) -> bool:
    """
    Returns True if the coroutine has finished execution, either by
    returning or throwing an exception
    """
    return coro_get_frame(coro) is None


class CoroStart(Awaitable[T_co]):
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
        coro: CoroLike[T_co],
        *,
        context: Optional[Context] = None,
    ):
        self.coro = coro
        self.context = context
        self.start_result: Optional[Tuple[Any, Optional[BaseException]]] = self._start()

    def _start(self) -> Tuple[Any, Optional[BaseException]]:
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

    def __await__(self) -> Generator[Any, Any, T_co]:
        """
        Resume the excecution of the started coroutine.  CoroStart is an
        _awaitable_.
        """
        if self.start_result is None:
            # exhausted coroutine, triger the "cannot reuse" error
            self.coro.send(None)
            assert False, "unreachable"

        out_value, exc = self.start_result
        self.start_result = None
        # process any exception generated by the initial start
        if exc:
            if isinstance(exc, StopIteration):
                return cast(T_co, exc.value)
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
                        self.context.run(self.coro.throw, exc)  # type: ignore
                        if self.context
                        else self.coro.throw(exc)
                    )
                except StopIteration as exc:
                    return cast(T_co, exc.value)
            else:
                try:
                    out_value = (
                        self.context.run(self.coro.send, in_value)
                        if self.context
                        else self.coro.send(in_value)
                    )
                except StopIteration as exc:
                    return cast(T_co, exc.value)

    def close(self) -> None:
        self.coro.close()
        self.start_result = None

    def done(self) -> bool:
        """returns true if the coroutine finished without blocking"""
        return self.start_result is not None and self.start_result[1] is not None

    def result(self) -> T_co:
        """
        Returns the result or raises the exception
        """
        exc = self.start_result and self.start_result[1]
        if not exc:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return cast(T_co, exc.value)
        raise exc

    def exception(self) -> Optional[BaseException]:
        """
        Returns the exception or None
        """
        exc = self.start_result and self.start_result[1]
        if exc is None:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return None
        return exc

    async def as_coroutine(self) -> T_co:
        """
        Continue execution of the coroutine that was started by start()
        Returns a coroutine which can be awaited
        """
        return await self

    def as_future(self) -> Awaitable[T_co]:
        """
        if `done()` convert the result of the coroutine into a `Future`
        and return it.  Otherwise raise a `RuntimeError`
        """
        if not self.done():
            raise RuntimeError("CoroStart: coroutine not done()")
        assert self.start_result is not None
        exc = self.start_result[1]
        assert exc
        future = asyncio.get_running_loop().create_future()
        if isinstance(exc, StopIteration):
            future.set_result(exc.value)
        else:
            future.set_exception(exc)
        return future


async def coro_await(coro: CoroLike[T], *, context: Optional[Context] = None) -> T:
    """
    A simple await, using the partial run primitives, equivalent to
    `async def coro_await(coro): return await coro`
    `context` can be provided for the coroutine to run in instead
    of the currently active context.
    """
    cs = CoroStart(coro, context=context)
    return await cs


def coro_eager(
    coro: Coroutine[Any, Any, T],
    *,
    task_factory: Optional[Callable[[Coroutine[Any, Any, T]], Awaitable[T]]] = None,
) -> Awaitable[T]:
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

    if task_factory:
        return task_factory(cs.as_coroutine())
    return create_task(cs.as_coroutine(), name="eager_task")


def func_eager(
    func: Callable[P, Coroutine[Any, Any, T]],
    *,
    task_factory: Optional[Callable[[Coroutine[Any, Any, T]], Awaitable[T]]] = None,
) -> Callable[P, Awaitable[T]]:
    """
    Decorator to automatically apply the `coro_eager` to the
    coroutine generated by invoking the given async function
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Awaitable[T]:
        return coro_eager(func(*args, **kwargs), task_factory=task_factory)

    return wrapper


@overload
def eager(
    arg: Coroutine[Any, Any, T],
    *,
    task_factory: Optional[Callable[[Coroutine[Any, Any, T]], Awaitable[T]]] = None,
) -> Awaitable[T]:
    ...


@overload
def eager(
    arg: Callable[P, Coroutine[Any, Any, T]],
    *,
    task_factory: Optional[Callable[[Coroutine[Any, Any, T]], Awaitable[T]]] = None,
) -> Callable[P, Awaitable[T]]:
    ...


def eager(
    arg: Union[Coroutine[Any, Any, T], Callable[P, Coroutine[Any, Any, T]]],
    *,
    task_factory: Optional[Callable[[Coroutine[Any, Any, T]], Awaitable[T]]] = None,
) -> Union[Awaitable[T], Callable[P, Awaitable[T]]]:
    """
    Convenience function invoking either `coro_eager` or `func_eager`
    to either decorate an async function or convert a coroutine returned by
    invoking an async function.
    """
    if isinstance(arg, types.CoroutineType):
        # A coroutine
        return coro_eager(arg, task_factory=task_factory)
    if isinstance(arg, types.FunctionType):
        return func_eager(arg, task_factory=task_factory)
    raise TypeError("need coroutine or function")
