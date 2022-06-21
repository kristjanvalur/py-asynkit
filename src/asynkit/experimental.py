import asyncio
import types
import sys

from .eventloop import task_is_blocked, task_is_runnable
from .coroutine import coro_is_suspended, coro_get_frame

_sentinel = object()


class TaskSignal(BaseException):
    """An exception used to signal an awaiting coroutine"""


class TaskCallbackSignal(TaskSignal):
    """Cause a callback to be called in the context of the task.
    the callback is args[0], invoked with args[1:]
    """

    @classmethod
    def new(cls, func, *args, **kwargs):
        return cls(func, args, kwargs)

    @property
    def func(self):
        return self.args[0]

    @property
    def posargs(self):
        return self.args[1] if len(self.args) > 1 else ()

    @property
    def kwargs(self):
        return self.args[2] if len(self.args) > 2 else {}

    def __call__(self):
        return self.func(*self.posargs, **self.kwargs)


@types.coroutine
def await_with_signals(coro):
    """
    awaits a coroutine manually, processing any incoming TaskSignal exceptions
    coming from outside.  Similar to the "yield from" template from pep-380
    but uses coroutine methods and containe additional logic for the TaskSignal.
    """
    try:
        out_value = coro.send(None)
    except StopIteration as out_exception:
        return out_exception.value
    while True:
        try:
            in_value = yield out_value
        except GeneratorExit:  # pragma: no coverage
            # asyncio lib does not appear to ever close coroutines.
            coro.close()
            raise
        except TaskSignal as in_exception:
            # Note, because of some weirdness with coroutines resumed by exceptions,
            # we don't have a fully valid frame stack.  So, this protocol just acknowledges
            # that it _can_ handle TaskSignal, by yielding the exception back out.  It is
            # then sent in again, but as a value.
            # out_value = handle_task_signal(in_exception)
            out_value = in_exception
        except BaseException as in_exception:
            try:
                out_value = coro.throw(in_exception)
            except StopIteration as out_exception:
                return out_exception.value
        else:
            if isinstance(in_value, TaskSignal):
                # we handle the TaskSignal as a propertly sent 'value' rather
                # than an exception, to have a fully valid call chain stack.
                out_value = handle_task_signal(in_value)
            else:
                try:
                    out_value = coro.send(in_value)
                except StopIteration as out_exception:
                    return out_exception.value


def yield_with_signals(final_value):
    # a wrapper around a final yield, such as the final yield of a future
    out_value = final_value
    while True:
        try:
            in_value = yield out_value
        except TaskSignal as in_exception:
            out_value = in_exception
        else:
            if isinstance(in_value, TaskSignal):
                out_value = handle_task_signal(in_value)
            else:
                break


@types.coroutine
def __sleep0():
    """Skip one event loop run cycle.

    This is a private helper for 'asyncio.sleep()', used
    when the 'delay' is set to 0.  It uses a bare 'yield'
    expression (which Task.__step knows how to handle)
    instead of creating a Future object.
    """
    yield from yield_with_signals(None)


async def sleep_ex(delay, result=None):
    if delay == 0:
        await __sleep0()
        return result
    return await await_with_signals(asyncio.sleep(delay, result=result))


class FutureMixin:
    def __await__(self):
        """
        Special version which can
        """
        if not self.done():
            self._asyncio_future_blocking = True
            yield from yield_with_signals(
                self
            )  # This tells Task to wait for completion.
        if not self.done():
            raise RuntimeError("await wasn't used with future")
        return self.result()  # May raise too.

    __iter__ = __await__


class FutureEx(FutureMixin, asyncio.Future):
    pass


def handle_task_signal(e):
    # the result is wrapped in a completed future, to easily
    # send exceptions up as well, without causing everything to break
    def handler(e):
        if isinstance(e, TaskCallbackSignal):
            return e()

    fut = asyncio.Future()
    try:
        fut.set_result(handler(e))
    except BaseException as e:
        fut.set_exception(e)
    return fut


class TaskMixin:
    def is_blocked(self):
        return task_is_blocked(self)

    def is_runnable(self):
        return task_is_runnable(self)

    def is_suspended(self):
        """
        A task is suspended if it isn't the current task, if it isn't in the initial state and
        it isn't done
        """
        # checking for the initial state is hard, because the default Task object makes no state transition
        # when it first
        return self._coro is not None and coro_is_suspended(self._coro)

    def execute_callback(self, callback, *args, **kwargs):

        signal = TaskCallbackSignal.new(callback, *args, **kwargs)
        return self.send_signal(signal)

    def send_signal(self, signal):

        # find the coro
        coro = self.get_suspended_coro()

        try:
            # first try sending the exception by throw.
            # if we get the exception out, we know that there is
            # a signal handler down there, and we can retry via send.
            out_value = coro.throw(signal)
        except TaskSignal as error:
            # No handler was present.
            # we effectively killed the task.  Need to do something here
            # to mark it as such..
            super(asyncio.Task, self).set_exception(error)
            raise ValueError("task didn't handle TaskSignal") from error
        else:
            out_value = coro.send(signal)
        # The result value was wrapped in a future to be able to
        # handle exceptions by the handler.
        assert out_value.done()
        return out_value.result()

    def get_suspended_coro(self):
        """
        return the coroutine object, if the task is
        either blocked or runnable.
        """
        if self.is_suspended():
            return self._coro
        if self._coro:
            print(self._coro, self._coro.cr_frame, self._coro.cr_frame.f_lasti)
            raise ValueError("task is not suspended")
        else:
            raise ValueError("task has no coroutine")

    def _get_suspended_stack(self, *, limit=None, trim=None):
        def capture_stack(top):
            r = []
            f = sys._getframe()
            while f:
                r.append(f)
                if not f.f_back:
                    print(f)
                if f is top:
                    break
                f = f.f_back
            return r

        here = sys._getframe()
        try:
            stack = self.execute_callback(capture_stack, here)
        except ValueError:
            return []  # no pending coroutine
        # trim our end of the stack
        if stack[-1] is here:
            del stack[-3:]
        # trim stack-capturing code and signal handler
        if trim is None:
            trim = 5  # adjust to trim away the signal handling function
            del stack[:trim]  # remove the stack grabbing functions
        stack.reverse()
        if limit is not None:
            if limit > 0:
                stack = stack[-limit:]
            else:
                stack = stack[:-limit]
        return stack

    def _get_exception_stack(self):
        frames = []
        if not frames and self._exception is not None:
            tb = self._exception.__traceback__
            while tb is not None:
                if limit is not None:
                    if limit <= 0:
                        break
                    limit -= 1
                frames.append(tb.tb_frame)
                tb = tb.tb_next
        return frames

    def get_stack(self, *, limit=None, trim=None):
        frames = self._get_suspended_stack(limit=limit, trim=trim)
        if not frames:
            frames = self._get_exception_stack()
        return frames


class TaskEx(TaskMixin, asyncio.Task):
    pass


def coro_walk_down(coro):
    """
    Walk down the chain of suspended coroutines as far as possible, yielding
    each one in turn, ever more deeply nested.
    Regular coroutines have a property holding any coroutine it is
    "awating" on and so it may be possible do descend a certain
    amount.  Many awaitables do not allow any such introspection, though,
    such as the iterators for async generators.
    """
    next = coro
    while next:
        yield next
        coro = next
        # Find any inner coroutine, whatever this one is "awaiting"

        # common case: async function
        try:
            next = coro.cr_await
            continue
        except AttributeError:
            pass
        # async generator:
        try:
            next = coro.ag_await
            continue
        except AttributeError:
            pass
        # generator-iterator (old-style coroutine, or types.coroutine)
        try:
            next = coro.gi_yieldfrom
            if next is None:
                # This could be one of our "manual yield from" methods.  Look into the frame and get
                # the 'coro' local variable
                f = coro_get_frame(coro)
                next = f.f_locals.get("coro")
        except AttributeError:
            # we have reached something we don't know what is.  For example, an async_generator_asend object.
            # Give up
            return


def coro_walk_stack(coro):
    """
    Generate a sequence of stack frames from coroutines by walking down
    the chain of awaiting coroutines as well as it is possible.
    Yields the most-recently called (deeply nested) frame last.
    """
    for c in coro_walk_down(coro):
        try:
            frame = coro_get_frame(c)
        except TypeError:
            # this coroutine has no frame
            frame = None
        if frame is not None:
            yield frame
