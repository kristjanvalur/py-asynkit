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
    TYPE_CHECKING,
    Any,
    Generic,
    TypeAlias,
    TypeVar,
    cast,
    overload,
)

from typing_extensions import ParamSpec, Protocol

from .compat import PY_311, swap_current_task
from .tools import Cancellable, cancelling
from .tools import create_task as _create_task

# Try to import C extension for performance-critical components
try:
    from ._cext import CoroStartBase as _CCoroStartBase  # type: ignore[attr-defined]
    from ._cext import get_build_info as _get_c_build_info  # type: ignore[attr-defined]

    _HAVE_C_EXTENSION = (
        True  # Re-enabled - C extension now has continued/pending methods
    )
except ImportError:
    _CCoroStartBase = None
    _get_c_build_info = None
    _HAVE_C_EXTENSION = False


def get_implementation_info() -> dict[str, Any]:
    """Return information about which coroutine implementation is active.

    Returns:
        Dictionary with implementation details including:
        - implementation: "C extension" or "Pure Python"
        - performance_info: Description of expected performance
        - build_info: For C extension, compiler and optimization details

    Example:
        >>> info = get_implementation_info()
        >>> print(f"Using {info['implementation']}")
        >>> if 'build_info' in info:
        ...     print(f"Build: {info['build_info']}")
    """
    if _HAVE_C_EXTENSION:
        build_info = {}
        if _get_c_build_info:
            try:
                build_info = _get_c_build_info()
            except Exception:
                build_info = {"status": "available but info unavailable"}

        return {
            "implementation": "C extension",
            "performance_info": "4-5x faster than pure Python",
            "build_info": build_info,
            "c_extension_available": True,
        }
    else:
        return {
            "implementation": "Pure Python",
            "performance_info": (
                "Baseline performance (install with build tools for 4x boost)"
            ),
            "build_info": {},
            "c_extension_available": False,
        }


__all__ = [
    "CoroStart",
    "PyCoroStart",
    "awaitmethod",
    "awaitmethod_iter",
    "coro_await",
    "coro_eager",
    "func_eager",
    "eager",
    "eager_ctx",
    "get_implementation_info",
    "create_eager_task_factory",
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


class CoroStartBase(Awaitable[T_co]):
    """
    Base class for CoroStart with only synchronous methods.

    A class to encapsulate the state of a coroutine which is manually started
    until its first suspension point, and then resumed. This facilitates
    later execution of coroutines, encapsulating them in Tasks only at the point when
    they initially become suspended.

    **Usage Pattern:**

    By default (autostart=True), CoroStart immediately executes the coroutine to its
    first suspension point upon construction. This is the typical usage::

        cs = CoroStart(my_coroutine())  # Starts immediately
        if cs.done():
            result = cs.result()
        else:
            result = await cs

    For advanced use cases, you can defer execution by setting autostart=False.
    This allows creating a Task before starting execution::

        cs = CoroStart(my_coroutine(), autostart=False)
        task = asyncio.create_task(cs.as_coroutine())  # Create task before starting
        cs.start()  # Now start execution
        result = await task

    **Important:** When autostart=False, methods like `done()`, `result()`,
    `exception()`, etc. have undefined behavior until `start()` is called.

    Parameters:
        coro: The coroutine to wrap
        context: Optional context to run the coroutine in.  If autostarted, it will be
            used for both phases of the run.  If not autostarted, it will be used
            only for the continuation phase.
        autostart: If True, automatically call start() during initialization (default True).
    """

    __slots__ = ["coro", "context", "_start_result"]

    def __init__(
        self,
        coro: Coroutine[Any, Any, T_co],
        *,
        context: Context | None = None,
        autostart: bool = True,
    ):
        self.coro = coro
        self.context = context
        self._start_result: tuple[Any, BaseException | None] | None = (
            self._start(context) if autostart else None
        )

    def start(self, context: Context | None = None) -> bool:
        """
        Start the coroutine execution (only needed when autostart=False).

        When autostart=False was used in __init__, this method **must be called**
        before awaiting the CoroStart or using methods like `done()`, `result()`,
        or `exception()`. It runs the coroutine to its first suspension point or
        until it completes (by returning or raising an exception), whichever comes
        first.

        This method can only be called once. Calling it multiple times will raise
        an error.

        Parameters:
            context: The context to be used for the initial execution phase only.
                    This is independent of the context passed to __init__ (which is
                    used for the continuation phase). If None, the coroutine runs
                    in the current context.

        Returns:
            True if the coroutine completed during the initial execution (done()),
            False if it suspended and will need to be awaited.
        """
        # context parameter is independent - doesn't use self.context as fallback
        ctx = context
        self._start_result = self._start(ctx)
        return self._start_result[1] is not None

    def _start(self, context: Context | None) -> tuple[Any, BaseException | None]:
        """
        Start the coroutine execution. It runs the coroutine to its first suspension
        point or until it raises an exception or returns a value, whichever comes
        first. Returns a tuple of (result, exception) for the initial execution.
        """
        try:
            return (
                context.run(self.coro.send, None)
                if context is not None
                else self.coro.send(None)
            ), None
        except BaseException as exception:
            # Coroutine returned without blocking
            return (None, exception)

    def __await__(self) -> Generator[Any, Any, T_co]:
        """
        Resume the execution of the started coroutine.  CoroStartBase is an
        _awaitable_.
        """
        if self._start_result is None:
            # continued coroutine, trigger the "cannot reuse" error
            self.coro.send(None)
            assert False, "unreachable"

        out_value, exc = self._start_result
        self._start_result = None
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
                        if self.context is not None
                        else self.coro.throw(exc)
                    )
                except StopIteration as exc:
                    return cast(T_co, exc.value)
            else:
                try:
                    out_value = (
                        self.context.run(self.coro.send, in_value)
                        if self.context is not None
                        else self.coro.send(in_value)
                    )
                except StopIteration as exc:
                    return cast(T_co, exc.value)

    def _throw(self, exc: type[BaseException] | BaseException) -> Any:
        """
        Core logic for throw operations - throws exception into coroutine,
        and makes the CoroStart either pending() or done() as appropriate,
        to be awaited later.
        """
        value = exc if isinstance(exc, BaseException) else exc()
        try:
            self._start_result = (
                (
                    self.context.run(self.coro.throw, value)
                    if self.context is not None
                    else self.coro.throw(value)
                ),
                None,
            )
        except BaseException as exception:
            self._start_result = (None, exception)

    def close(self) -> None:
        """
        Close the coroutine.  It must immediately exit.
        Respects context if provided.
        """
        # Always close the underlying coroutine
        if self.context is not None:
            self.context.run(self.coro.close)
        else:
            self.coro.close()
        # Transition to continued() state so that subsequent await attempts
        # trigger the "cannot reuse already awaited coroutine" error in __await__
        self._start_result = None

    def done(self) -> bool:
        """returns true if the coroutine finished synchronously during initial start"""
        return self._start_result is not None and self._start_result[1] is not None

    def continued(self) -> bool:
        """Returns true if the coroutine has been continued (awaited) after
        initial start.
        """
        return self._start_result is None

    def pending(self) -> bool:
        """returns true if the coroutine is pending, waiting for async operation"""
        return self._start_result is not None and self._start_result[1] is None

    def result(self) -> T_co:
        """
        Returns the result or raises the exception
        """
        exc = self._start_result and self._start_result[1]
        if not exc:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return cast(T_co, exc.value)
        raise exc

    def exception(self) -> BaseException | None:
        """
        Returns the exception or None
        """
        exc = self._start_result and self._start_result[1]
        if exc is None:
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        if isinstance(exc, StopIteration):
            return None
        return exc


class CoroStartMixin(Generic[T_co]):
    """
    Mixin providing async methods for CoroStart.

    This mixin adds async convenience methods on top of a CoroStartBase.
    It should be mixed with either the Python CoroStartBase or the C extension
    CoroStartBase to provide the full CoroStart functionality.

    This mixin uses only the public API of CoroStartBase to ensure compatibility
    with both Python and C extension implementations.
    """

    if TYPE_CHECKING:
        # Abstract methods expected from base class - only for type checking
        def _throw(self, exc: type[BaseException] | BaseException) -> None: ...
        def done(self) -> bool: ...
        def result(self) -> T_co: ...
        def pending(self) -> bool: ...
        def __await__(self) -> Generator[Any, Any, T_co]: ...

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
        for _ in range(tries):
            self._throw(exc)
            if self.done():
                return self.result()
        else:
            raise RuntimeError(f"coroutine ignored {type(exc).__name__}")

    # Type hints for attributes from CoroStartBase (public interface only)
    coro: Coroutine[Any, Any, T_co]
    context: Context | None
    # Note: No reference to private _start_result - use public methods instead

    @overload
    async def athrow(self, exc: type[BaseException]) -> T_co: ...

    @overload
    async def athrow(self, exc: BaseException) -> T_co: ...

    async def athrow(self, exc: type[BaseException] | BaseException) -> T_co:
        """
        Throw an exception into a started coroutine if it is not done, instead
        of continuing it.
        """
        self._throw(exc)
        return await self

    async def aclose(self) -> None:
        """
        Close the coroutine, throwing a GeneratorExit() into it if it is not done.
        It may perform async cleanup before exiting.

        Uses only public API - no direct access to private state.
        """
        # If coroutine is already done or continued, nothing to close
        if not self.pending():
            return

        # For pending coroutines, use athrow to send GeneratorExit
        # This will handle the transition from pending() to continued() properly
        try:
            await self.athrow(GeneratorExit())
        except GeneratorExit:
            # Expected - coroutine closed cleanly
            pass

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

        future = asyncio.get_running_loop().create_future()
        try:
            result = self.result()
            future.set_result(result)
        except BaseException as exc:
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


class CoroStart(CoroStartBase[T_co], CoroStartMixin[T_co]):
    """
    Complete CoroStart implementation combining base functionality with async methods.

    This is the main user-facing class that provides both sync and async methods
    for managing eager coroutine execution.
    """

    pass


# C Extension Integration
# Use C implementation of CoroStartBase when available for performance
# The C version eliminates Python generator overhead in the suspend/resume hot path
_PyCoroStartBase = CoroStartBase  # Keep reference to Python implementation
_PyCoroStart = CoroStart  # Keep reference to Python implementation

# Simple multiple inheritance approach for C extension integration

if _HAVE_C_EXTENSION and _CCoroStartBase is not None:
    # Pure C implementation with Python mixin via multiple inheritance
    class _CCoroStart(_CCoroStartBase, CoroStartMixin[T_co]):  # type: ignore[misc]
        """C CoroStartBase + Python CoroStartMixin via multiple inheritance"""

        pass

    # Public API uses C implementation when available (follows asyncio convention)
    CoroStart = _CCoroStart  # type: ignore[misc]

else:
    # Python implementation only
    _CCoroStart = None  # type: ignore[assignment,misc]
    CoroStart = _PyCoroStart  # type: ignore[misc]

# Always export Python implementation for advanced use cases
# (follows asyncio convention)
PyCoroStart = _PyCoroStart


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

    Initialized from an object that has the Future interface (done(), result(), etc.),
    """

    def __init__(
        self,
        future: Any | None = None,
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> None:
        super().__init__()
        self._name: str | None = name
        self._context: Context | None = context

        # Copy state from existing future if provided
        # future can be a Future or a CoroStart (which has done(), result(), exception())
        if future is not None:
            if future.done():
                # optimize for the common case:
                try:
                    self.set_result(future.result())
                except BaseException as exc:
                    self.set_exception(exc)

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


def create_eager_task_factory(
    custom_task_constructor: Callable[..., Task[Any]],
) -> Callable[..., Any]:
    """
    Create a task factory that applies eager execution to all coroutines.

    This function creates a task factory that can be set on an event loop to make
    all coroutines created via `asyncio.create_task()` execute eagerly. Eager
    execution means the coroutine starts immediately and runs until it blocks,
    potentially completing synchronously without creating a Task.

    The signature matches Python 3.12+'s asyncio.create_eager_task_factory().

    Args:
        custom_task_constructor: A callable used to create tasks when coroutines
            don't complete synchronously. Typically asyncio.Task or a Task subclass.
            This matches the signature of Python 3.12's implementation.

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

        # Create eager task factory (standard signature)
        factory = asynkit.create_eager_task_factory(asyncio.Task)
        loop = asyncio.get_running_loop()
        loop.set_task_factory(factory)

        # Now all tasks created will execute eagerly
        async def sync_coro():
            return "completed"  # No await - completes immediately

        task = asyncio.create_task(sync_coro())
        assert task.done()  # True - completed synchronously!
        result = await task  # "completed"
        ```

    Notes:
        - This implementation works on all Python versions but may not always create
          a real Task - synchronous coroutines get a TaskLikeFuture instead.
        - All kwargs from asyncio.create_task() are properly forwarded to the
          custom_task_constructor when delegation occurs.

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

        def real_task_factory(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
            # this inner factory must not be eager!
            kwargs.pop("eager_start", None)  # remove incompatible eager_start
            return custom_task_constructor(coro, loop=loop, **kwargs)

        return coro_eager_task_helper(loop, coro, name, context, real_task_factory)

    return factory


#: Pre-created eager task factory instance for easy use.
#:
#: This is equivalent to ``create_eager_task_factory(asyncio.Task)`` and can be used
#: directly with ``loop.set_task_factory()`` for the same behavior as Python 3.12's
#: ``asyncio.eager_task_factory``.
#:
#: Example:
#:     >>> import asyncio
#:     >>> import asynkit
#:     >>> loop = asyncio.get_running_loop()
#:     >>> loop.set_task_factory(asynkit.eager_task_factory)
eager_task_factory = create_eager_task_factory(asyncio.Task)


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
          synchronous completion, similar to create_eager_task_factory behavior
        - Provides compatibility with Python 3.12+ asyncio.create_task() API
        - Works on all Python versions, not just 3.12+
    """

    def real_task_factory(coro_arg: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        if PY_311:
            return _create_task(coro_arg, name=name, context=context, **kwargs)  # type: ignore[call-arg]
        else:
            return _create_task(coro_arg, name=name, **kwargs)

    if eager_start:
        return coro_eager_task_helper(
            asyncio.get_running_loop(),
            coro,
            name,
            context,
            real_task_factory,
        )

    else:
        return real_task_factory(coro)


class GhostTaskHelper:
    """
    Helper class to create and manage ghost tasks, used to provide a
    temporary task contexts if creating eager tasks in a non-task context.
    """

    # this could be a WeakKeyDictionary but we want maximum performance here
    # and there are unlikely to be many event loops in practice.
    tasks: dict[asyncio.AbstractEventLoop, asyncio.Task[Any]] = {}

    @classmethod
    def get(
        cls,
        loop: asyncio.AbstractEventLoop,
        raw_create: Callable[[Coroutine[Any, Any, Any]], asyncio.Task[Any]],
    ) -> asyncio.Task[Any]:
        """
        Get the GhostTaskHelper instance for the given event loop.
        """
        try:
            return cls.tasks[loop]
        except KeyError:
            cls.tasks[loop] = raw_create(cls.task_coro())
        return cls.tasks[loop]

    @classmethod
    async def task_coro(cls) -> None:
        pass


_get_ghost_task = GhostTaskHelper.get  # for easier access


def coro_eager_task_helper(
    loop: asyncio.AbstractEventLoop,
    coro: Coroutine[Any, Any, T],
    name: str | None,
    context: Context | None,
    real_task_factory: Callable[[Coroutine[Any, Any, T]], asyncio.Task[T]],
) -> asyncio.Task[T] | TaskLikeFuture[T]:
    """
    Create a task with eager execution.

    If there is no current task, we temporarily swap in a reusable "ghost task"
    to provide task context during eager execution. This allows libraries like
    anyio/sniffio to detect the async framework via asyncio.current_task().

    The coroutine is started immediately. If it blocks, we create a real Task
    to continue execution. If it completes synchronously, we return a
    TaskLikeFuture wrapping the result.

    This ensures all parts of the execution run in the correct task context.
    """

    # if the loop is different from the current loop, we cannot run eager.
    try:
        # is task meant for a different loop?
        no_eager = loop is not asyncio.get_running_loop()
    except RuntimeError:
        no_eager = True  # no running loop yet
    if no_eager:
        return real_task_factory(coro)

    # In Python < 3.11, context parameter doesn't exist for create_task()
    # so we ignore any provided context and let CoroStart manage its own
    if sys.version_info < (3, 11):
        context = None

    cs: CoroStart[T]
    current_task = asyncio.current_task(loop)
    if current_task is not None:
        if context is None:
            cs = CoroStart(coro, context=copy_context())
        else:
            # Enter the context only for the initial start, then use None for CoroStart
            # This way the continuation won't try to re-enter the context
            cs = context.run(lambda: CoroStart(coro, context=None))
    else:
        # if there is no current task, then we need a fake task to run it in
        # this is so that asyncio.get_current_task() returns a valid task during
        # eager start.  This is not the same task as will be created later. This
        # is purely to satisfy get_current_task() calls during eager start, such
        # as for anyio that wants to detect the current async framework.
        old = swap_current_task(loop, _get_ghost_task(loop, real_task_factory))
        try:
            if context is None:
                cs = CoroStart(coro, context=copy_context())
            else:
                # Enter the context only for the initial start, then use None for CoroStart
                # This way the continuation won't try to re-enter the context
                cs = context.run(lambda: CoroStart(coro, context=None))
        finally:
            swap_current_task(loop, old)

    # if the coroutine is not done, set it as the awaitable for the helper and
    # return the task
    if not cs.done():
        return real_task_factory(cs.as_coroutine())
    else:
        return TaskLikeFuture(cs, name=name, context=context)


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
