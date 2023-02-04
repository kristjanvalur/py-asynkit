"""
drop-in replacement for uvloop, but providing scheduling primitives
"""
import asyncio
from .eventloop import SchedulingMixin


try:
    import uvloop as _uvloop

    # make sure the loop can be used
    _loop = _uvloop.Loop()
    if not hasattr(_loop, "_ready") and not hasattr(_loop, "get_ready_queue"):
        _uvloop = None
    del _loop
except ImportError:
    _uvloop = None

if _uvloop:

    class Loop(_uvloop.Loop, SchedulingMixin):
        def get_loop_ready_queue(self):
            #  Invoke the special queue getter function on _uvloop.Loop
            return self.get_ready_queue()

        def get_task_from_handle(self, handle: asyncio.Handle):
            # uvloop.loop.Handle objects have this method
            # note that uvloop type hints claim that methods return
            # asyncio.Handle objects, but in fact they return
            # uvloop.loop.Handle methods which are unrelated.
            cb = handle.get_callback()  # type: ignore
            if cb:
                try:
                    task = cb[0].__self__  # type: ignore
                except AttributeError:
                    return None
                if isinstance(task, asyncio.Task):
                    return task

            return None

    def new_event_loop():
        return Loop()

    class EventLoopPolicy(_uvloop.EventLoopPolicy):
        def _loop_factory(self) -> Loop:
            return new_event_loop()
