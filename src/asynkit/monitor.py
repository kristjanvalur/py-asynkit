from __future__ import annotations

import sys
import types
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
)
from enum import IntEnum
from typing import (
    Any,
    Generic,
    TypeVar,
    cast,
    overload,
)

from .coroutine import coro_is_finished, coro_is_new

__all__ = [
    "GeneratorObject",
    "GeneratorObjectIterator",
    "Monitor",
    "BoundMonitor",
    "OOBData",
]

T = TypeVar("T")
V = TypeVar("V")
T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


class MonitorState(IntEnum):
    """State of a Monitor object."""

    INACTIVE = 0  # Monitor is not active
    ACTIVE = 1  # Monitor is actively running
    OOB = -1  # Monitor is yielding out-of-band data


class OOBData(Exception):
    """
    An exception representing OutOfBound data sent to a Monitor.
    The `data` member contains any actual data being sent.
    """

    __slots__ = ["data"]

    def __init__(self, data: Any | None = None):
        self.data = data


class Monitor(Generic[T]):
    """
    A class to await a coroutine while receiving and sending OOB (out of band)
    data to the coroutine.  The called coroutine can thus suspend operation while
    the caller handles and responds to the OOB data.
    """

    __slots__ = [
        "state",
    ]

    def __init__(self) -> None:
        self.state: MonitorState = MonitorState.INACTIVE

    @types.coroutine
    def _asend(
        self,
        coro: Coroutine[Any, Any, T],
        callable: Callable[..., Any],
        args: tuple[Any, ...],
    ) -> Generator[Any, Any, T]:
        """
        Await a coroutine after an initial "send" call which is either
        `send()` or `throw()`, while handling the OOB data protocol.
        """

        if self.state != MonitorState.INACTIVE:
            raise RuntimeError("Monitor cannot be re-entered")
        self.state = MonitorState.ACTIVE
        try:
            try:
                out_value = callable(*args)
            except StopIteration as exc:
                return cast(T, exc.value)
            except OOBData:
                raise RuntimeError("coroutine raised OOBData")

            while True:
                if self.state == MonitorState.OOB:
                    self.state = MonitorState.ACTIVE
                    raise OOBData(out_value)
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
        finally:
            self.state = MonitorState.INACTIVE

    async def aawait(
        self,
        coro: Coroutine[Any, Any, T],
        data: Any | None = None,
    ) -> T:
        """
        Asynchronously await the coroutine result.  If the coroutine calls `oob()`
        the function will throw a `OOBData` exception with the data in the `data`
        attribute.  The caller must then re-try the `aawait`.
        `data` must be None for the first time it is called, but can be used
        to pass data as the return value for the `oob()` call for a subsequent call.
        """
        return await self._asend(coro, coro.send, (data,))

    def __call__(
        self,
        coro: Coroutine[Any, Any, T],
    ) -> Awaitable[T]:
        """
        Return a `BoundMonitor` object which can be used without always
        specifying a `coro` argument, and can be awaited directly.`
        """
        return BoundMonitor(self, coro)

    async def athrow(
        self,
        coro: Coroutine[Any, Any, T],
        exc: BaseException | type[BaseException],
    ) -> T:
        """
        Similar to `aawait()` but throws an exception into the coroutine at the
        point where it is suspended.
        """
        # Pass directly to coro.throw() - it handles both classes and instances
        return await self._asend(coro, coro.throw, (exc,))

    @types.coroutine
    def oob(self, data: Any | None = None) -> Generator[Any, Any, Any]:
        """
        Send Out Of Band data to a higher up caller which is awaiting `aawait()` or
        `athrow()`.  It will cause a `OOBData` exception to be generated for the caller
        of those functions.  The return value once awaited will be whatever `data`
        is passed in by a subsequent `aawait()` call.
        """
        if self.state != MonitorState.ACTIVE:
            raise RuntimeError("Monitor not active")
        # signal OOB data being yielded
        self.state = MonitorState.OOB
        return (yield data)

    async def aclose(
        self,
        coro: Coroutine[Any, Any, T],
    ) -> None:
        """Close the coroutine, by sending a GeneratorExit exception into it."""
        if coro_is_finished(coro):
            return  # already closed
        try:
            await self.athrow(coro, GeneratorExit)
        except GeneratorExit:
            pass
        except OOBData:
            raise RuntimeError("Monitor coroutine ignored GeneratorExit")

    async def start(self, coro: Coroutine[Any, Any, T]) -> Any:
        """
        Start the Monitor.  This is a convenience function to call `aawait()`
        with no arguments, catching an expected OOBData exception and
        returning its `data` member.
        """
        try:
            await self.aawait(coro)
        except OOBData as oob:
            return oob.data
        raise RuntimeError("Coroutine did not await Monitor.oob()")

    async def try_await(
        self,
        coro: Coroutine[Any, Any, T],
        data: Any | None = None,
        sentinel: Any = None,
    ) -> Any:
        """
        A convenience function to call `aawait()`, returning a sentinel if
        an OOBData exception was raised.
        The `sentinel` value defaults to None.  The OOBData
        exception is discarded.
        """
        try:
            return await self.aawait(coro, data)
        except OOBData:
            return sentinel


class BoundMonitor(Generic[T]):
    """
    An awaitable helper class which can be awaited to invoke a
    `await Monitor.aawait(coroutine)`
    """

    def __init__(self, monitor: Monitor[T], coro: Coroutine[Any, Any, T]) -> None:
        self.monitor = monitor
        self.coro = coro

    def __await__(self) -> Generator[Any, Any, T]:
        return self.monitor.aawait(self.coro, None).__await__()

    async def aawait(self, data: Any | None = None) -> T:
        return await self.monitor.aawait(self.coro, data)

    async def athrow(
        self,
        exc: BaseException | type[BaseException],
    ) -> T:
        """
        Similar to `aawait()` but throws an exception into the coroutine at the
        point where it is suspended.
        """
        return await self.monitor.athrow(self.coro, exc)

    async def aclose(self) -> None:
        await self.monitor.aclose(self.coro)

    async def start(self) -> Any:
        return await self.monitor.start(self.coro)

    async def try_await(self, data: Any | None = None, sentinel: Any = None) -> Any:
        return await self.monitor.try_await(self.coro, data, sentinel)


class GeneratorObject(Generic[T, V]):
    __slots__ = ["monitor"]

    def __init__(
        self,
    ) -> None:
        self.monitor: Monitor[Any] = Monitor()

    def __call__(self, coro: Coroutine[Any, Any, Any]) -> GeneratorObjectIterator[T, V]:
        return GeneratorObjectIterator(self.monitor, coro)

    async def ayield(self, value: T) -> Any:
        """
        Asynchronously yield the value to the Generator object
        """
        return await self.monitor.oob(value)


class GeneratorObjectIterator(AsyncGenerator[T_co, T_contra]):
    __slots__ = ["monitor", "coro", "ag_running", "finalizer", "__weakref__"]

    def __init__(self, monitor: Monitor[Any], coro: Coroutine[Any, Any, Any]) -> None:
        self.monitor = monitor
        self.coro = coro
        # Mypy thinks ag_running is read-only
        self.ag_running = False
        self.finalizer: Callable[[Any], None] | None = None

    def __aiter__(self) -> AsyncIterator[T_co]:
        return self

    async def __anext__(self) -> T_co:
        return await self.asend(None)

    def __del__(self) -> None:
        if self.finalizer:
            self.finalizer(self)

    def _first_iter(self) -> None:
        hooks = sys.get_asyncgen_hooks()
        if hooks.firstiter is not None:
            hooks.firstiter(self)
        self.finalizer = cast(Callable[[Any], None] | None, hooks.finalizer)

    async def asend(self, value: T_contra | None) -> T_co:
        if self.ag_running:
            raise RuntimeError("asend(): asynchronous generator is already running")
        if coro_is_finished(self.coro):
            raise StopAsyncIteration()
        elif coro_is_new(self.coro):
            self._first_iter()
        self.ag_running = True
        try:
            await self.monitor.aawait(self.coro, value)
        except OOBData as oob:
            return cast(T_co, oob.data)
        except StopAsyncIteration as err:
            # similar to pep479, StopAsyncIteration must not bubble out
            # the case for StopIteration is already handled by coro.send()
            # but raises a different "coroutine raised ..." RuntimeError.
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        else:
            raise StopAsyncIteration()
        finally:
            self.ag_running = False

    @overload
    async def athrow(
        self, typ: type[BaseException], val: object = ..., tb: object = ..., /
    ) -> T_co: ...

    @overload
    async def athrow(
        self, typ: BaseException, val: None = ..., tb: object = ..., /
    ) -> T_co: ...

    async def athrow(
        self,
        exc: BaseException | type[BaseException],
        val: object = None,
        tb: object = None,
    ) -> T_co:
        # Ignore val and tb parameters - they're only for AsyncGenerator compatibility
        return cast(T_co, await self._athrow(exc))

    async def aclose(self) -> None:
        await self._athrow(None)

    # shared implementation for aclose() and athrow()
    async def _athrow(
        self,
        exc: BaseException | type[BaseException] | None,
    ) -> T_co | None:
        if self.ag_running:
            raise RuntimeError(
                ("athrow" if exc is not None else "aclose")
                + "(): asynchronous generator is already running"
            )
        if coro_is_finished(self.coro):
            return None
        elif coro_is_new(self.coro):
            self._first_iter()
        self.ag_running = True
        try:
            if exc is not None:
                # athrow()
                await self.monitor.athrow(self.coro, exc)
            else:
                # aclose()
                await self.monitor.athrow(self.coro, GeneratorExit)
        except OOBData as oob:
            if exc is None:
                # aclose() - There should be no generated value
                raise RuntimeError("async generator ignored GeneratorExit")
            # athrow() - return the generated value
            return cast(T_co, oob.data)
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        except GeneratorExit:
            # special handling for GeneratorExit if this was an aclose() call
            if exc is None:
                return None  # aclose()
            raise  # otherwise, pass the error along
        else:
            if exc is None:
                return None  # aclose() resulted in coroutine exit
            raise StopAsyncIteration()
        finally:
            self.ag_running = False
