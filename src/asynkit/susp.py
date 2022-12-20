
from typing import Coroutine, Tuple, Any, Optional
import types

class Suspender:
    __slots__ = ["coro", "suspended"]
    
    def __init__(self):
        self.coro: Optional[Coroutine] = None
        self.suspended = False

    async def call(self, coroutine: Coroutine) -> Tuple[bool, Any]:
        self.coro = coroutine
        return await self.resume(None)
        
    @types.coroutine
    def resume(self, message: Optional[Any] = None) -> Tuple[bool, Any]:
        try:
            out_value = self.coro.send(message)
        except StopIteration as exc:
            return (True, exc.value)

        # yield up the values
        # This is similar to how `yield from` is defined (see pep-380)
        # except that it uses a coroutines's send() and throw() methods.
        while True:
            if self.suspended:
                return (False, out_value)        
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
                    return (True, exc.value)
            else:
                try:
                    out_value = self.coro.send(in_value)
                except StopIteration as exc:
                    return (True, exc.value)
    

    @types.coroutine
    def suspend(self, message: Optional[Any] = None) -> Any:
        assert not self.suspended
        self.suspended = True
        try:
            return (yield message)
        finally:
            self.suspended = False
        