import asyncio
import functools
import inspect
import sys
import types

from . import tools

__all__ = [
    "CoroStart",
    "coro_await",
    "coro_eager",
    "func_eager",
    "eager",
    "eager_awaitable",
    "eager_callable",
    "eager_coroutine",
    "coro_get_frame",
    "coro_is_new",
    "coro_is_suspended",
    "coro_is_finished",
    "iscoroutine",
]

PYTHON_37 = sys.version_info.major == 3 and sys.version_info.minor == 7

"""
Tools and utilities for advanced management of coroutines
"""


# Helpers to find if a coroutine (or a generator as created by types.coroutine)
# has started or finished


def iscoroutine(coro):
    """
    a lenient inspection function to recognize a coroutine which
    has been defined with the generator syntax.
    """
    return inspect.iscoroutine(coro) or inspect.isgenerator(coro)


def _coro_getattr(coro, suffix):
    """
    Get an attribute of a coroutine or coroutine like object
    """
    # look for
    # 1. coroutine
    # 2. legacy coroutine (even wrapped with types.coroutine())
    # 3. async generator
    for prefix in ("cr_", "gi_", "ag_"):
        if hasattr(coro, prefix + suffix):
            if prefix == "ag_" and suffix == "running":
                return False  # async generators are shown as ag_running=True, even when the code is not executiong.  Override that.
            # coroutine (async function)
            return getattr(coro, prefix + suffix)
    raise TypeError(
        f"a coroutine or coroutine like object is required. Got: {type(coro)}"
    )


def coro_get_frame(coro):
    """
    Get the current frame of a coroutine or coroutine like object (generator, legacy coroutines)
    """
    return _coro_getattr(coro, "frame")


def coro_is_new(coro):
    """
    Returns True if the coroutine has just been created and
    never not yet started
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_CREATED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_CREATED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:
            return coro.ag_frame and coro.ag_frame.f_lasti < 0
        else:
            return coro.ag_frame and not coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_suspended(coro):
    """
    Returns True if the coroutine has started but not exited
    """
    if inspect.iscoroutine(coro):
        return inspect.getcoroutinestate(coro) == inspect.CORO_SUSPENDED
    elif inspect.isgenerator(coro):
        return inspect.getgeneratorstate(coro) == inspect.GEN_SUSPENDED
    elif inspect.isasyncgen(coro):
        if PYTHON_37:
            # frame is None if it has already exited
            # the currently running coroutine is also not suspended by definition.
            return coro.ag_frame and coro.ag_frame.f_lasti >= 0
        else:
            return coro.ag_running
    else:
        raise TypeError(
            f"a coroutine or coroutine like object is required. Got: {type(coro)}"
        )


def coro_is_finished(coro):
    """
    Returns True if the coroutine has finished execution, either by
    returning or throwing an exception
    """
    return coro_get_frame(coro) is None


class CoroStart:
    """
    A class to encapsulate the state of a coroutine which is manually started
    until its first suspension point, and then resumed.  This facilitates
    later execution of coroutines, encapsulating them in Tasks only at the point when
    they initially become suspended.
    """

    __slots__ = ["coro", "start_result", "wrapped"]

    def __init__(self, coro, auto_start=True):
        self.coro = coro
        self.start_result = None  # the (future, exception) tuple
        self.wrapped = False
        if auto_start:
            self.start()

    def started(self):
        return self.start_result is not None

    def done(self):
        """returns true if the coroutine finished without blocking"""
        return self.start_result and self.start_result[1]

    def start(self):
        """
        Start the coroutine execution.  It runs the coroutine to its first suspension point
        or until it raises an exception or returns a value, whichever comes first.
        """
        if self.start_result:
            raise RuntimeError("CoroStart already started")
        try:
            self.start_result = (self.coro.send(None), None)
        except BaseException as exception:
            # Coroutine returned without blocking
            self.start_result = (None, exception)
            return True
        return False

    def result(self):
        if not self.done():
            raise asyncio.InvalidStateError("CoroStart: coroutine not done()")
        exc = self.start_result[1]
        if isinstance(exc, StopIteration):
            return exc.value
        raise exc

    def as_coroutine(self):
        """
        Continue execution of the coroutine that was started by start()
        Returns a coroutine which can be awaited
        """
        if self.wrapped:
            raise RuntimeError("CoroStart: coroutine already wrapped")
        self.wrapped = True

        async def wrap():
            return await self._resume()

        return wrap()

    @types.coroutine
    def _resume(self):
        if not self.start_result:
            raise RuntimeError("CoroStart: not started while resuming")
        out_value, exc = self.start_result
        # process any exception generated by the initial start
        if exc:
            if isinstance(exc, StopIteration):
                return exc.value
            raise exc

        # yield up the initial future from `coro_start`.
        # This is similar to how `yield from` is defined (see pep-380)
        # except that it uses a coroutines's send() and throw() methods.
        while True:
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
                    return exc.value
            else:
                try:
                    out_value = self.coro.send(in_value)
                except StopIteration as exc:
                    return exc.value

    def as_awaitable(self, *, create_task=tools.create_task):
        """
        Convert the continuation of the coroutine to an awaitable.
        This is either a coroutine, if the task finished, or a Task,
        created using the provided `create_task` function.
        """
        # if task isn't started, or it didn't finish early, create the task
        if create_task and not self.done():
            return create_task(self.as_coroutine())
        return self.as_coroutine()

    def as_callable(self):
        """
        A helper method which returns a callable, which when called, returns `as_coroutine`.
        Used for APIs which expect async callables.
        """

        def helper():
            return self.as_coroutine()

        return helper


async def coro_await(coro):
    """
    A simple await, using the partial run primitives, equivalent to
    `async def coro_await(coro): return await coro`.  Provided for
    testing purposes.
    """
    cs = CoroStart(coro)
    return await cs.as_coroutine()


def eager_callable(coro):
    """
    Eagerly start the coroutine, then return a callable which can be passed
    to other apis which expect a callable for Task creation
    """
    cs = CoroStart(coro)
    return cs.as_callable()


def eager_awaitable(coro):
    """
    Eagerly start the coroutine, then return an awaitable which can be passed
    to other apis which expect an awaitable for Task creation.  Use only
    if your API can accept a Future
    """
    cs = CoroStart(coro)
    return cs.as_awaitable(create_task=None)


def eager_coroutine(coro):
    """
    Eagerly start the coroutine, then return an coroutine which can be passed
    to other apis which expect an coroutine for Task creation
    """
    cs = CoroStart(coro)
    return cs.as_awaitable(create_task=None)


def coro_eager(coro):
    """
    Make the coroutine "eager":
    Start the coroutine.  If it blocks, create a task to continue
    execution and return immediately to the caller.
    The return value is either a non-blocking awaitable returning any
    result or exception, or a Task object.
    This implements a depth-first kind of Task execution.
    """

    # start the coroutine.  Run it to the first block, exception or return value.
    cs = CoroStart(coro)
    return cs.as_awaitable()


def func_eager(func):
    """
    Decorator to automatically apply the `coro_eager` to the
    coroutine generated by invoking the given async function
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return coro_eager(func(*args, **kwargs))

    return wrapper


def eager(arg):
    """
    Convenience function invoking either `coro_eager` or `func_eager`
    to either decorate an async function or convert a coroutine returned by
    invoking an async function.
    """
    if isinstance(arg, types.CoroutineType):
        # A coroutine
        return coro_eager(arg)
    if isinstance(arg, types.FunctionType):
        return func_eager(arg)
    raise TypeError("need coroutine or function")
