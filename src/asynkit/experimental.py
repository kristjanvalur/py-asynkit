import asyncio
import types
import sys
import traceback


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
def signals(coro):
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
    def execute_callback(self, callback, *args, **kwargs):

        signal = TaskCallbackSignal.new(callback, *args, **kwargs)
        return self.send_signal(signal)

    def send_signal(self, signal):

        # find the coro
        coro = self.get_pending_coro()

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

    def get_pending_coro(self):
        """
        return the coroutine object, if the task is
        either blocked or runnable.
        """
        if self._coro and self._fut_waiter:
            return self._coro
        if self._coro and not self._fut_waiter:
            raise ValueError("task is not pending")
        else:
            raise ValueError("task has no coroutine")

    def get_stack(self, *, limit=None, trim=None):
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
            return []
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


class MyTask(TaskMixin, asyncio.Task):
    pass
