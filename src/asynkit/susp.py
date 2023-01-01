import sys
import types
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Generator,
    Generic,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from typing_extensions import Literal

from .coroutine import coro_is_finished, coro_is_new

T = TypeVar("T")
V = TypeVar("V")


class Monitor(Generic[T, V]):
    """
    A class to await a coroutine while receiving and sending OOB (out of band)
    data to the coroutine and leaving it suspended.
    """

    # return type of the await
    S = TypeVar("S")
    OOB = Union[Tuple[Literal[True], S], Tuple[Literal[False], Any]]

    __slots__ = [
        "state",
    ]

    def __init__(self) -> None:
        self.state: int = 0

    @types.coroutine
    def _oob_generic(
        self,
        coro: Coroutine[Any, Any, Any],
        callable: Callable[..., Any],
        args: Tuple[Any, ...],
    ) -> Generator[Any, Any, OOB[T]]:
        if self.state != 0:
            raise RuntimeError("Monitor cannot be re-entered")
        self.state = 1
        try:
            try:
                out_value = callable(*args)
            except StopIteration as exc:
                return (False, exc.value)

            while True:
                if self.state == -1:
                    self.state = 1
                    return (True, out_value)
                try:
                    in_value = yield out_value
                except GeneratorExit:  # pragma: no coverage
                    # asyncio lib does not appear to ever close coroutines.
                    coro.close()
                    raise
                except BaseException as exc:
                    try:
                        out_value = coro.throw(exc)
                    except StopIteration as exc:
                        return (False, exc.value)
                else:
                    try:
                        out_value = coro.send(in_value)
                    except StopIteration as exc:
                        return (False, exc.value)
        finally:
            self.state = 0

    @types.coroutine
    async def oob_await(
        self,
        coro: Coroutine[Any, Any, Any],
        data: Optional[V],
    ) -> OOB[T]:
        """
        Await with oob (Out Of Band data)
        returns a tuple `(is_oob, data)` where if `is_oob` is true, `data`
        is the data passed to the `oob()` method.
        Otherwise, it is the result of awaiting the function
        """
        return await self._oob_generic(coro, coro.send, (data,))

    @overload
    async def oob_throw(
        self,
        coro: Coroutine[Any, Any, Any],
        type: Type[BaseException],
        value: Union[BaseException, object] = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> OOB[T]:
        ...

    @overload
    async def oob_throw(
        self,
        coro: Coroutine[Any, Any, Any],
        type: BaseException,
        value: None = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> OOB[T]:
        ...

    async def oob_throw(
        self,
        coro: Coroutine[Any, Any, Any],
        type: Union[BaseException, Type[BaseException]],
        value: Union[BaseException, object] = None,
        traceback: Optional[TracebackType] = None,
    ) -> OOB[T]:
        return await self._oob_generic(coro, coro.throw, (type, value, traceback))

    @types.coroutine
    def oob(self, data: T) -> Generator[T, V, V]:
        """
        Send Out Of Band data to a higher up caller which is using `oob_await()`
        """
        if self.state != 1:
            raise RuntimeError("Monitor not active")
        # signal OOB data being yielded
        self.state = -1
        return (yield data)


class GeneratorObject(AsyncIterator[T]):
    __slots__ = ["monitor", "coro", "running", "finalizer", "__weakref__"]

    def __init__(self, coro: Optional[Coroutine[Any, Any, Any]] = None) -> None:
        self.monitor: Monitor[T, Any] = Monitor()
        self.coro = coro
        self.running = False
        self.finalizer: Optional[Callable[[Any], None]] = None

    def init(self, coro: Coroutine[Any, Any, Any]) -> "GeneratorObject[T]":
        self.coro = coro
        return self

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        return await self.asend(None)

    def __del__(self) -> None:
        if self.finalizer:
            self.finalizer(self)

    def _first_iter(self) -> None:
        hooks = sys.get_asyncgen_hooks()
        if hooks.firstiter is not None:
            cast(Callable[[Any], None], hooks.firstiter)(self)
        self.finalizer = cast(Optional[Callable[[Any], None]], hooks.finalizer)

    async def asend(self, value: Any) -> T:
        if self.running:
            raise RuntimeError("asend(): asynchronous generator is already running")
        assert self.coro is not None
        if coro_is_finished(self.coro):
            raise StopAsyncIteration()
        elif coro_is_new(self.coro):
            self._first_iter()
        self.running = True
        try:
            is_oob, result = await self.monitor.oob_await(self.coro, value)
        except StopAsyncIteration as err:
            # similar to pep479, StopAsyncIteration must not bubble out
            # the case for StopIteration is already handled by coro.send()
            # but raises a different "coroutine raised ..." RuntimeError.
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        finally:
            self.running = False
        if not is_oob:
            raise StopAsyncIteration()
        return cast(T, result)

    @overload
    async def athrow(
        self,
        type: Type[BaseException],
        value: Union[BaseException, object] = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> Optional[T]:
        ...

    @overload
    async def athrow(
        self,
        type: BaseException,
        value: None = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> Optional[T]:
        ...

    async def athrow(
        self,
        type: Union[BaseException, Type[BaseException]],
        value: Union[BaseException, object] = None,
        traceback: Optional[TracebackType] = None,
    ) -> Optional[T]:
        if self.running:
            raise RuntimeError("athrow(): asynchronous generator is already running")
        assert self.coro is not None
        if coro_is_finished(self.coro):
            return None
        elif coro_is_new(self.coro):
            self._first_iter()
        self.running = True
        try:
            is_oob, result = await self.monitor.oob_throw(
                self.coro, cast(Type[BaseException], type), value, traceback
            )
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        finally:
            self.running = False
        if not is_oob:
            raise StopAsyncIteration()
        return cast(T, result)

    async def aclose(self) -> None:
        assert self.coro is not None
        if coro_is_finished(self.coro):
            return
        if self.running:
            raise RuntimeError("aclose(): asynchronous generator is already running")
        self.running = True
        try:
            is_oob, result = await self.monitor.oob_throw(self.coro, GeneratorExit)
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        except (GeneratorExit):
            return
        finally:
            self.running = False
        if is_oob:
            raise RuntimeError("async generator ignored GeneratorExit")

    async def ayield(self, value: Any) -> Any:
        """
        Asynchronously yield the value to the Generator object
        """
        return await self.monitor.oob(value)
