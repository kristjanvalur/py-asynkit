"""
drop-in replacement for uvloop, but providing scheduling primitives
"""
import asyncio
from types import ModuleType
from typing import TYPE_CHECKING, Any, Deque, Optional, cast

from .eventloop import SchedulingMixin

if TYPE_CHECKING:
    _TaskAny = asyncio.Task[Any]
else:
    _TaskAny = asyncio.Task

_uvloop: Optional[ModuleType]
try:
    import uvloop as __uvloop  # type: ignore

    _uvloop = __uvloop

    # make sure the loop can be used
    assert _uvloop
    _loop = _uvloop.Loop()
    if not hasattr(_loop, "_ready") and not hasattr(_loop, "get_ready_queue"):
        _uvloop = None
    del _loop
except ImportError:
    _uvloop = None

if _uvloop:

    # uvloop.Loop is type-incompatible with AbstractEventLoop, so
    # we must ignore typing for this class.
    class Loop(_uvloop.Loop, SchedulingMixin):  # type: ignore
        def get_loop_ready_queue(self) -> Deque[asyncio.Handle]:
            #  Invoke the special queue getter function on _uvloop.Loop
            return cast(Deque[asyncio.Handle], self.get_ready_queue())

        def get_task_from_handle(self, handle: asyncio.Handle) -> Optional[_TaskAny]:
            # uvloop.loop.Handle objects have this method
            # note that uvloop type hints claim that methods return
            # asyncio.Handle objects, but in fact they return
            # uvloop.loop.Handle methods which are unrelated.
            cb = handle.get_callback()  # type: ignore
            if cb:
                try:
                    task = cb[0].__self__
                except AttributeError:
                    return None
                if isinstance(task, asyncio.Task):
                    return task

            return None

    def new_event_loop() -> Loop:
        return Loop()

    class EventLoopPolicy(_uvloop.EventLoopPolicy):  # type: ignore
        def _loop_factory(self) -> Loop:
            return new_event_loop()

    def install() -> None:
        """A helper function to install uvloop policy."""
        asyncio.set_event_loop_policy(EventLoopPolicy())

    __all__ = ["new_event_loop", "install", "EventLoopPolicy"]

else:
    __all__ = []
