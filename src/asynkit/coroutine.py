from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import sys
import types
from asyncio import Future, Task
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Iterator,
)
from contextvars import Context, copy_context
from types import FrameType
from typing import (
    Any,
    TypeAlias,
    TypeVar,
    cast,
    overload,
)

from typing_extensions import ParamSpec, Protocol

from .tools import Cancellable, cancelling
from .tools import create_task as _create_task

__all__ = [
    "CoroStart",
    "awaitmethod",
    "awaitmethod_iter",
    "coro_await",
    "coro_eager",
    "func_eager",
    "eager",
    "eager_ctx",
    "create_eager_factory",
    "eager_task_factory",
    "create_task",
    "TaskLikeFuture",
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
Suspendable = (
    Coroutine[Any, Any, Any] | Generator[Any, Any, Any] | AsyncGenerator[Any, Any]
)


class CAwaitable(Awaitable[T_co], Cancellable, Protocol):
    pass


Future_Type: TypeAlias = Future


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
        context: Context | None = None,
    ):
        self.coro = coro
        self.context = context
        self.start_result: tuple[Any, BaseException | None] | None = self._start()

    def _start(self) -> tuple[Any, BaseException | None]:
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
        # except that it uses a coroutine's send() and throw() methods.
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
    async def athrow(self, exc: type[BaseException]) -> T_co: ...

    @overload
    async def athrow(self, exc: BaseException) -> T_co: ...

    async def athrow(self, exc: type[BaseException] | BaseException) -> T_co:
        """
        Throw an exception into a started coroutine if it is not done, instead
        of continuing it.
        """
        value = exc if isinstance(exc, BaseException) else exc()

        try:
            self.start_result = (
                (
                    self.context.run(self.coro.throw, value)
                    if self.context
                    else self.coro.throw(value)
                ),
                None,
            )
        except BaseException as exception:
            self.start_result = (None, exception)
        return await self

    @overload
    def throw(self, exc: type[BaseException]) -> T_co: ...

    @overload
    def throw(self, exc: BaseException) -> T_co: ...

    def throw(self, exc: type[BaseException] | BaseException, tries: int = 1) -> T_co:
        """
        Throw an exception into the started coroutine. If the coroutine fails to
        exit, the exception will be re-thrown, up to 'tries' times.  If the coroutine
        handles the error and returns, the value is returned
        """
        value = exc if isinstance(exc, BaseException) else exc()
        for i in range(tries):
            try:
                self.coro.throw(value)
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

    def exception(self) -> BaseException | None:
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

    def as_future(self) -> Future_Type[T_co]:
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
        If `done()`, return `as_future()`, else return self.
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
    coro: Coroutine[Any, Any, T], *, context: Context | None = None
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
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
    context: Context | None = None,
) -> CAwaitable[T]:
    """
    Make the coroutine "eager":
    Start the coroutine. If it blocks, create a task to continue
    execution and return immediately to the caller.
    The return value is either a non-blocking awaitable returning any
    result or exception, or a Task object.
    This implements a depth-first kind of Task execution.
    """

    # start the coroutine. Run it to the first block, exception or return value.
    cs = CoroStart(coro, context=context if context is not None else copy_context())
    if cs.done():
        return cs.as_future()

    if create_task:
        return create_task(cs.as_coroutine())
    return _create_task(cs.as_coroutine(), name="eager_task")


def func_eager(
    func: Callable[P, Coroutine[Any, Any, T]],
    *,
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
) -> Callable[P, CAwaitable[T]]:
    """
    Decorator to automatically apply the `coro_eager` to the
    coroutine generated by invoking the given async function
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> CAwaitable[T]:
        return coro_eager(func(*args, **kwargs), create_task=create_task)

    return wrapper


@overload
def eager(
    arg: Coroutine[Any, Any, T],
    *,
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
) -> CAwaitable[T]: ...


@overload
def eager(
    arg: Callable[P, Coroutine[Any, Any, T]],
    *,
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
) -> Callable[P, CAwaitable[T]]: ...


def eager(
    arg: Coroutine[Any, Any, T] | Callable[P, Coroutine[Any, Any, T]],
    *,
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
) -> CAwaitable[T] | Callable[P, CAwaitable[T]]:
    """
    Convenience function invoking either `coro_eager` or `func_eager`
    to either decorate an async function or convert a coroutine returned by
    invoking an async function.
    """
    if isinstance(arg, types.CoroutineType):
        # A coroutine
        return coro_eager(arg, create_task=create_task)
    if isinstance(arg, types.FunctionType):
        return func_eager(arg, create_task=create_task)
    raise TypeError("need coroutine or function")


def eager_ctx(
    coro: Coroutine[Any, Any, T],
    *,
    create_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]] | None = None,
    msg: str | None = None,
) -> contextlib.AbstractContextManager[CAwaitable[T]]:
    """Create an eager task and return a context manager that will cancel it on exit."""
    e = coro_eager(coro, create_task=create_task)
    return cancelling(e, msg=msg)


class TaskLikeFuture(Future[T]):
    """A Future subclass that supports Task-like methods for asyncio compatibility.

    This is used when eager execution completes synchronously but asyncio expects
    a Task-like object that supports set_name(), get_name(), etc.
    """

    def __init__(
        self,
        future: Future[T] | None = None,
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> None:
        super().__init__()
        self._name: str | None = name
        self._context: Context | None = context

        # Copy state from existing future if provided
        if future is not None:
            if future.done():
                if future.cancelled():
                    self.cancel()
                elif future.exception() is not None:
                    exc = future.exception()
                    assert exc is not None  # we just checked it's not None
                    self.set_exception(exc)
                else:
                    self.set_result(future.result())

    def set_name(self, value: str) -> None:
        """Set the task name (Task compatibility method)."""
        self._name = value

    def get_name(self) -> str:
        """Get the task name (Task compatibility method)."""
        return self._name or f"TaskLikeFuture-{id(self)}"

    def get_context(self) -> Context:
        """Get the task context (Task compatibility method)."""
        return self._context or Context()

    def set_context(self, context: Context) -> None:
        """Set the task context (Task compatibility method)."""
        self._context = context


def create_eager_factory(
    inner_factory: Callable[..., Task[Any]] | None = None,
) -> Callable[..., Any]:
    """
    Create a task factory that applies eager execution to all coroutines.

    This function creates a task factory that can be set on an event loop to make
    all coroutines created via `asyncio.create_task()` execute eagerly. Eager
    execution means the coroutine starts immediately and runs until it blocks,
    potentially completing synchronously without creating a Task.

    Args:
        inner_factory: Optional task factory to delegate to when coroutines
            actually need to be scheduled. If None, falls back to creating
            asyncio.Task instances directly.

    Returns:
        A task factory function with signature (loop, coro, **kwargs) ->
        Task | TaskLikeFuture. The returned factory can be passed to
        `loop.set_task_factory()`.

        - If the coroutine completes synchronously: returns TaskLikeFuture
        - If the coroutine blocks: returns Task (via inner_factory or asyncio.Task)

    Example:
        ```python
        import asyncio
        import asynkit

        # Option 1: Simple usage (replaces any existing factory)
        factory = asynkit.create_eager_factory()
        loop = asyncio.get_running_loop()
        loop.set_task_factory(factory)

        # Option 2: Preserve existing factory by chaining
        old_factory = loop.get_task_factory()
        factory = asynkit.create_eager_factory(old_factory)
        loop.set_task_factory(factory)

        # Now all tasks created will execute eagerly
        async def sync_coro():
            return "completed"  # No await - completes immediately

        task = asyncio.create_task(sync_coro())
        assert task.done()  # True - completed synchronously!
        result = await task  # "completed"
        ```

    Notes:
        - This is a different mechanism from Python 3.12's native eager execution
          feature. Python 3.12 provides `eager_start=True` parameter for
          `asyncio.create_task()` and `asyncio.eager_task_factory()`. Our
          implementation works on all Python versions but may not always create
          a real Task - synchronous coroutines get a TaskLikeFuture instead.
        - All kwargs from asyncio.create_task() are properly forwarded to the
          inner factory when delegation occurs.
        - This is experimental functionality that modifies global task creation
          behavior for the entire event loop.
        - If you want to preserve an existing task factory, explicitly pass it
          as inner_factory rather than relying on automatic detection.

    See Also:
        - `eager()`: Apply eager execution to individual coroutines
        - `coro_eager()`: Lower-level eager execution function
        - `TaskLikeFuture`: Future subclass with Task-like methods
    """

    def factory(
        loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, Any], **kwargs: Any
    ) -> Any:
        # an actual task_factory, corresponding to the signature of
        # AbstractEventLoop.set_task_factory()
        # however, it will not always return a Task, it may return a future.
        # we hope that the event loop that calls it won't mind.
        # kwargs.pop("eager_start", None)  # incompatible with the standard eager.

        # Extract context and name parameters for coro_eager and TaskLikeFuture
        context = kwargs.get("context")
        name = kwargs.get("name")

        def create_task(coro: Coroutine[Any, Any, T]) -> CAwaitable[T]:
            # when creating the task for the coro continuation, use the inner factory
            # with the original kwargs from the task factory call
            if inner_factory is not None:
                return inner_factory(loop, coro, **kwargs)
            else:
                return asyncio.Task(coro, loop=loop, **kwargs)

        # Use the refactored function that handles both eager execution and wrapping
        return coro_eager_task_helper(
            coro, construct_task=create_task, context=context, name=name
        )

    return factory


#: Pre-created eager task factory instance for easy use.
#:
#: This is equivalent to ``create_eager_factory()`` and can be used directly
#: with ``loop.set_task_factory()`` for the same behavior as Python 3.12's
#: ``asyncio.eager_task_factory``.
#:
#: Example:
#:     >>> import asyncio
#:     >>> import asynkit
#:     >>> loop = asyncio.get_running_loop()
#:     >>> loop.set_task_factory(asynkit.eager_task_factory)
eager_task_factory = create_eager_factory()


def create_task(
    coro: Coroutine[Any, Any, T],
    *,
    name: str | None = None,
    context: Context | None = None,
    eager_start: bool | None = None,
    **kwargs: Any,
) -> CAwaitable[T]:
    """
    Create a task with optional eager execution, compatible with Python 3.12+ API.

    This function provides the same interface as Python 3.12's asyncio.create_task()
    including the eager_start parameter, but works on all Python versions using
    asynkit's eager execution implementation.

    Args:
        coro: The coroutine to wrap in a task
        name: Optional name for the task
        context: Optional context to run the coroutine in
        eager_start: If True, apply eager execution. If False or None,
            delegate to standard asyncio.create_task()
        **kwargs: Additional arguments passed to asyncio.create_task()

    Returns:
        Task or TaskLikeFuture: Returns asynkit's eager implementation when
        eager_start=True, otherwise returns standard asyncio.Task

    Example:
        ```python
        import asynkit

        # Use eager execution (asynkit implementation)
        task = asynkit.create_task(my_coro(), eager_start=True)

        # Use standard asyncio behavior
        task = asynkit.create_task(my_coro(), eager_start=False)
        task = asynkit.create_task(my_coro())  # same as eager_start=False
        ```

    Notes:
        - When eager_start=True, may return TaskLikeFuture instead of Task for
          synchronous completion, similar to create_eager_factory behavior
        - Provides compatibility with Python 3.12+ asyncio.create_task() API
        - Works on all Python versions, not just 3.12+
    """
    if eager_start:
        # Use our enhanced eager implementation with Task compatibility
        def continuation_factory(c: Coroutine[Any, Any, T]) -> CAwaitable[T]:
            # Pass the context to the continuation task
            try:
                return _create_task(c, name=name, context=context, **kwargs)  # type: ignore[call-arg]
            except TypeError:
                # Fallback for Python < 3.11 which doesn't support context parameter
                # Note: The coroutine is already running in the correct context from
                # coro_eager_task_helper, so we don't need to pass context here
                return _create_task(c, name=name, **kwargs)

        # Use the refactored function that handles both eager execution and wrapping
        return coro_eager_task_helper(
            coro, construct_task=continuation_factory, context=context, name=name
        )
    else:
        # Delegate to standard asyncio.create_task()
        # Handle context parameter compatibility (added in Python 3.11)
        try:
            return _create_task(coro, name=name, context=context, **kwargs)  # type: ignore[call-arg]
        except TypeError:
            # Fallback for Python < 3.11 which doesn't support context parameter
            if context is not None:
                # For older Python versions, we can't pass context to create_task
                # This is a limitation of the older asyncio API
                pass
            return _create_task(coro, name=name, **kwargs)


def coro_eager_task_helper(
    coro: Coroutine[Any, Any, T],
    *,
    construct_task: Callable[[Coroutine[Any, Any, T]], CAwaitable[T]],
    context: Context | None = None,
    name: str | None = None,
) -> CAwaitable[T]:
    """
    Internal helper for eager execution with Task compatibility and context handling.

    This function combines eager execution with TaskLikeFuture wrapping for
    synchronous completion, making it suitable for use in task factories and
    create_task implementations.

    Args:
        coro: The coroutine to execute eagerly
        construct_task: Factory for creating continuation tasks when coroutine blocks
        context: Optional context to run the coroutine in
        name: Optional name for the task (applied to TaskLikeFuture for sync completion)

    Returns:
        Task, TaskLikeFuture, or CAwaitable depending on execution path:
        - Sync completion: TaskLikeFuture with Task-like methods
        - Async completion: Result from construct_task (usually asyncio.Task)
    """

    # In Python < 3.11, context parameter doesn't exist for create_task()
    # so we ignore any provided context and let CoroStart manage its own
    if sys.version_info < (3, 11):
        context = None

    if context is not None:
        # Enter the context only for the initial start, then use None for CoroStart
        # This way the continuation won't try to re-enter the context
        def start_in_context() -> CoroStart[T]:
            return CoroStart(coro, context=None)

        cs = context.run(start_in_context)
    else:
        # No explicit context - use copy_context() as before
        cs = CoroStart(coro, context=copy_context())

    if cs.done():
        # Sync completion - wrap in TaskLikeFuture for Task compatibility
        return TaskLikeFuture(cs.as_future(), name=name, context=context)

    # Async completion - delegate to task construction factory
    return construct_task(cs.as_coroutine())


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


def awaitmethod(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Iterator[T]]:
    """
    Decorator to make a function return an awaitable.
    The function must be a coroutine function.
    Specifically intended to be used for __await__ methods.
    Can also be used for class or static methods.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Iterator[T]:
        return func(*args, **kwargs).__await__()

    return wrapper


def awaitmethod_iter(
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Iterator[T]]:
    """
    Same as above, but implemented using the coro_iter helper.
    Only included for completeness, it is better to use the
    builtin coroutine.__await__() method.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Iterator[T]:
        return coro_iter(func(*args, **kwargs))

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
