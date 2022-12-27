import types
from typing import Any, Coroutine, Optional, Tuple, Generator as GeneratorType

from .coroutine import coro_is_finished


class Monitor:
    __slots__ = [
        "coro",
        "is_oob",
    ]

    def __init__(self, coroutine: Optional[Coroutine] = None):
        self.coro = coroutine
        self.is_oob = False

    def init(self, coroutine: Coroutine):
        self.coro = coroutine
        return self

    @types.coroutine
    def oob_await(
        self, message: Optional[Any] = None
    ) -> GeneratorType[Tuple[bool, Any], Any, Any]:
        """
        Await with oob (Out Of Band data)
        returns a tuple `(is_oob, data)` where if `is_oob` is true, `data`
        is the data passed to the `oob()` method.
        Otherwise, it is the result of awaiting the function
        """

        try:
            out_value = self.coro.send(message)
        except StopIteration as exc:
            return (False, exc.value)
        return (yield from self.oob_continue(out_value))

    @types.coroutine
    def oob_continue(self, out_value):
        # yield up the values
        # This is similar to how `yield from` is defined (see pep-380)
        # except that it uses a coroutines's send() and throw() methods.
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
    def oob(self, message: Optional[Any] = None) -> Any:
        """
        Send Out Of Band data to a higher up caller which is using `oob_await()`
        """
        assert not self.is_oob
        self.is_oob = True
        try:
            return (yield message)
        finally:
            self.is_oob = False


class Generator(Monitor):
    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.asend(None)

    async def asend(self, value):
        if coro_is_finished(self.coro):
            raise StopAsyncIteration()
        is_oob, result = await self.oob_await(value)
        if not is_oob:
            raise StopAsyncIteration()
        return result

    async def athrow(self, type, value=None, traceback=None):
        if coro_is_finished(self.coro):
            return None
        is_oob, result = await self.oob_throw(type, value, traceback)
        if not is_oob:
            raise StopAsyncIteration()
        return result

    async def aclose(self):
        if coro_is_finished(self.coro):
            return
        try:
            is_oob, result = await self.oob_throw(GeneratorExit)
        except (GeneratorExit):
            return
        if is_oob:
            raise RuntimeError("async generator ignored GeneratorExit")

    async def ayield(self, value: Any) -> Any:
        """
        Asynchronously yield the value to the Generator object
        """
        return await self.oob(value)

    @types.coroutine
    def oob_throw(self, type, value=None, traceback=None):
        try:
            out_value = self.coro.throw(type, value, traceback)
        except StopIteration as exc:
            return (False, exc.value)
        return (yield from self.oob_continue(out_value))
