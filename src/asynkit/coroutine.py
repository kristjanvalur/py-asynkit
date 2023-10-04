import asyncio
import functools
import inspect
import types
from contextvars import Context, copy_context
from types import FrameType
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Iterator,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from typing_extensions import ParamSpec

from .tools import create_task

__all__ = [
    "CoroStart",
    "awaitmethod",
    "coro_await",
    "coro_eager",
    "func_eager",
    "eager",
    "coro_get_frame",
    "coro_is_new",
    "coro_is_suspended",
    "coro_is_finished",
    "coro_iter",
    "aiter_sync",
    "await_sync",
    "SynchronousError",
    "SynchronousAbort",
    "asyncfunction",
    "syncfunction",
]

T = TypeVar("T")
S = TypeVar("S")
P = ParamSpec("P")
T_co = TypeVar("T_co", covariant=True)
Suspendable = Union[Coroutine, Generator, AsyncGenerator]

"""
Tools and utilities for advanced management of coroutines
"""


class SynchronousError(RuntimeError):
    """
    An exception thrown when a coroutine does not complete
    synchronously.
    """


class SynchronousAbort(BaseException):
    """
    Exception thrown into coroutine to abort it.
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
        # async generators have an ag_await if they are suspended
        # ag_running() means that it is inside an anext() or athrow()
        # but it may be suspended.
        return (
            coro.ag_frame is not None and coro.ag_await is None and not coro.ag_running
        )
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
        return coro.ag_await is not None
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
        coro: Coroutine[Any, Any, T_co],
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
        Resume the execution of the started coroutine.  CoroStart is an
        _awaitable_.
        """
        if self.start_result is None:
            # exhausted coroutine, trigger the "cannot reuse" error
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

    @overload
    async def athrow(self, exc: Type[BaseException]) -> T_co:
        ...

    @overload
    async def athrow(self, exc: BaseException) -> T_co:
        ...

    async def athrow(self, exc: Union[Type[BaseException], BaseException]) -> T_co:
        """
        Throw an exception into a started coroutine if it is not done, instead
        of continuing it.
        """
        value = exc if isinstance(exc, BaseException) else exc()

        try:
            self.start_result = (
                self.context.run(self.coro.throw, type(value), value)
                if self.context
                else self.coro.throw(type(value), value)
            ), None
        except BaseException as exception:
            self.start_result = (None, exception)
        return await self

    @overload
    def throw(self, exc: Type[BaseException]) -> T_co:
        ...

    @overload
    def throw(self, exc: BaseException) -> T_co:
        ...

    def throw(
        self, exc: Union[Type[BaseException], BaseException], tries: int = 1
    ) -> T_co:
        """
        Throw an exception into the started coroutine. If the coroutine fails to
        exit, the exception will be re-thrown, up to 'tries' times.  If the coroutine
        handles the error and returns, the value is returned
        """
        value = exc if isinstance(exc, BaseException) else exc()
        for i in range(tries):
            try:
                self.coro.throw(type(value), value)
            except StopIteration as err:
                return cast(T_co, err.value)
        else:
            raise RuntimeError(f"coroutine ignored {type(value).__name__}")

    def close(self) -> None:
        """
        Close the coroutine.  It must immediately exit.
        """
        self.start_result = None
        self.coro.close()

    async def aclose(self) -> None:
        """
        Close the coroutine, throwing a GeneratorExit() into it if it is not done.
        It may perform async cleanup before exiting.
        """
        if self.start_result is None:
            return
        if self.done():
            self.start_result = None
            return
        try:
            await self.athrow(GeneratorExit())
        except GeneratorExit:
            pass

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
        Continue execution of the coroutine that was started by start().
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

    def as_awaitable(self) -> Awaitable[T_co]:
        """
        If `done()`, return `as_future()`, else `as_coroutine()`.
        This is a convenience function for use when the instance
        is to be passed directly to methods such as `asyncio.gather()`.
        In such cases, we want to avoid a `done()` instance to cause
        a `Task` to be created just to retrieve the result.
        """
        if self.done():
            return self.as_future()
        else:
            return self


async def coro_await(
    coro: Coroutine[Any, Any, T], *, context: Optional[Context] = None
) -> T:
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


def coro_iter(coro: Coroutine[Any, Any, T]) -> Generator[Any, Any, T]:
    """
    Helper to turn a coroutine into an iterator, which can then
    be used as the return of object's __await__ methods.
    """
    try:
        out_value = coro.send(None)
    except StopIteration as exc:
        return cast(T, exc.value)

    while True:
        try:
            in_value = yield out_value

        except GeneratorExit:
            coro.close()
            raise
        except BaseException as exc:
            try:
                out_value = coro.throw(exc)
            except StopIteration as exc:
                return cast(T, exc.value)
        else:
            try:
                out_value = coro.send(in_value)
            except StopIteration as exc:
                return cast(T, exc.value)


def awaitmethod(
    func: Callable[[S], Coroutine[Any, Any, T]]
) -> Callable[[S], Iterator[T]]:
    """
    Decorator to make a function return an awaitable.
    The function must be a coroutine function.
    Specifically intended to be used for __await__ methods.
    """

    @functools.wraps(func)
    def wrapper(self: S) -> Iterator[T]:
        return coro_iter(func(self))

    return wrapper


def await_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Runs a coroutine synchronously.  If the coroutine blocks, a
    SynchronousError is raised.
    """
    start = CoroStart[T](coro)
    if start.done():
        return start.result()
    # kill the coroutine
    try:
        # we can't use GeneratorExit because that gets special handling and
        # a traceback is not collected.
        start.throw(SynchronousAbort())
    except BaseException as err:
        raise SynchronousError("coroutine failed to complete synchronously") from err
    else:
        raise SynchronousError(
            "coroutine failed to complete synchronously (caught BaseException)"
        )
    finally:
        start.close()


def syncfunction(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, T]:
    """Make an async function synchronous, by invoking
    `await_sync()` on its coroutine.  Useful as a decorator.
    """

    @functools.wraps(func)
    def helper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await_sync(func(*args, **kwargs))

    return helper


def asyncfunction(func: Callable[P, T]) -> Callable[P, Coroutine[Any, Any, T]]:
    """Make a regular function async, so that its result needs to be awaited.
    Useful when providing synchronous callbacks to async code.
    """

    @functools.wraps(func)
    async def helper(*args: P.args, **kwargs: P.kwargs) -> T:
        return func(*args, **kwargs)

    return helper


def aiter_sync(async_iterable: AsyncIterable[T]) -> Generator[T, None, None]:
    """Iterate synchronously over an async iterable"""
    ai = async_iterable.__aiter__()

    # a helper ensures that we have a coroutine, not just an Awaitable
    async def helper() -> T:
        return await ai.__anext__()

    try:
        while True:
            yield await_sync(helper())
    except StopAsyncIteration:
        pass
