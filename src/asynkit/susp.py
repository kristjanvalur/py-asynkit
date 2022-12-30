import types
from types import TracebackType
from typing import Any, AsyncIterator, Coroutine
from typing import Generator as GeneratorType
from typing import (Generic, Optional, Tuple, Type, TypeVar, Union, cast,
                    overload)

from typing_extensions import Literal

from .coroutine import coro_is_finished

T = TypeVar("T")
V = TypeVar("V")


class Monitor(Generic[T, V]):

    # return type of the await
    S = TypeVar("S")
    OOB = Union[Tuple[Literal[True], S], Tuple[Literal[False], Any]]

    __slots__ = [
        "coro",
        "is_oob",
    ]

    def __init__(self, coroutine: Optional[Coroutine[Any, Any, Any]] = None):
        self.coro = coroutine
        self.is_oob = False

    def init(self, coroutine: Coroutine[Any, Any, Any]) -> "Monitor[T, V]":
        self.coro = coroutine
        return self

    @types.coroutine
    def _oob_continue(self, out_value: Any) -> GeneratorType[Any, Any, OOB[T]]:
        # yield up the values
        # This is similar to how `yield from` is defined (see pep-380)
        # except that it uses a coroutines's send() and throw() methods.
        assert self.coro is not None
        while True:
            if self.is_oob:
                return (True, out_value)
            try:
                in_value = yield out_value
            except GeneratorExit:  # pragma: no coverage
                # asyncio lib does not appear to ever close coroutines.
                self.coro.close()
                raise
            except BaseException as exc:
                try:
                    out_value = self.coro.throw(exc)
                except StopIteration as exc:
                    return (False, exc.value)
            else:
                try:
                    out_value = self.coro.send(in_value)
                except StopIteration as exc:
                    return (False, exc.value)

    @types.coroutine
    async def oob_await(
        self,
        message: Optional[V],
    ) -> OOB[T]:
        """
        Await with oob (Out Of Band data)
        returns a tuple `(is_oob, data)` where if `is_oob` is true, `data`
        is the data passed to the `oob()` method.
        Otherwise, it is the result of awaiting the function
        """

        assert self.coro is not None
        try:
            out_value = self.coro.send(message)
        except StopIteration as exc:
            return (False, exc.value)
        return await self._oob_continue(out_value)

    @overload
    async def oob_throw(
        self,
        type: Type[BaseException],
        value: Union[BaseException, object] = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> OOB[T]:
        ...

    @overload
    async def oob_throw(
        self,
        type: BaseException,
        value: None = ...,
        traceback: Optional[TracebackType] = ...,
    ) -> OOB[T]:
        ...

    async def oob_throw(
        self,
        type: Union[BaseException, Type[BaseException]],
        value: Union[BaseException, object] = None,
        traceback: Optional[TracebackType] = None,
    ) -> OOB[T]:
        assert self.coro is not None
        try:
            out_value = self.coro.throw(
                cast(Type[BaseException], type), value, traceback
            )
        except StopIteration as exc:
            return (False, exc.value)
        return await self._oob_continue(out_value)

    @types.coroutine
    def oob(self, message: T) -> GeneratorType[T, V, V]:
        """
        Send Out Of Band data to a higher up caller which is using `oob_await()`
        """
        assert not self.is_oob
        self.is_oob = True
        try:
            return (yield message)
        finally:
            self.is_oob = False


class Generator(Monitor[T, Any], AsyncIterator[T]):
    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        return await self.asend(None)

    async def asend(self, value: Any) -> T:
        assert self.coro is not None
        if coro_is_finished(self.coro):
            raise StopAsyncIteration()
        try:
            is_oob, result = await self.oob_await(value)
        except StopAsyncIteration as err:
            # similar to pep479, StopAsyncIteration must not bubble out
            # the case for StopIteration is already handled by coro.send()
            # but raises a different "coroutine raised ..." RuntimeError.
            raise RuntimeError("async generator raised StopAsyncIteration") from err
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
        assert self.coro is not None
        if coro_is_finished(self.coro):
            return None
        try:
            is_oob, result = await self.oob_throw(
                cast(Type[BaseException], type), value, traceback
            )
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        if not is_oob:
            raise StopAsyncIteration()
        return cast(T, result)

    async def aclose(self) -> None:
        assert self.coro is not None
        if coro_is_finished(self.coro):
            return
        try:
            is_oob, result = await self.oob_throw(GeneratorExit)
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        except (GeneratorExit):
            return
        if is_oob:
            raise RuntimeError("async generator ignored GeneratorExit")

    async def ayield(self, value: Any) -> Any:
        """
        Asynchronously yield the value to the Generator object
        """
        return await self.oob(value)
