import asyncio
import sys
import contextlib

__all__ = ["deque_pop", "nested", "nested_jit", "anested", "anested_jit"]

_ver = sys.version_info[:2]

if _ver >= (3, 8):
    create_task = asyncio.create_task
else:  # pragma: no cover

    def create_task(coro, name):
        return asyncio.create_task(coro)


def deque_pop(d, pos=-1):
    if pos == -1:
        return d.pop()
    elif pos == 0:
        return d.popleft()

    if pos >= 0:
        if pos < len(d):
            d.rotate(-pos)
            r = d.popleft()
            d.rotate(pos)
            return r
    elif pos >= -len(d):
        pos += 1
        d.rotate(-pos)
        r = d.pop()
        d.rotate(pos)
        return r
    # create exception
    [].pop(pos)


def task_from_handle(item):
    """
    Runnable task objects exist as callbacks on the ready queue in the loop.
    Specifically, they are Handle objects, containing a Task bound method
    as the callback.  Retrieve such a Task instance from a Handle if possible.
    Not everything on the queue are necessarily tasks, in which case we return None
    """

    try:
        task = item._callback.__self__
    except AttributeError:
        return None
    if isinstance(task, asyncio.Task):
        return task


@contextlib.contextmanager
def nested_jit(*callables):
    """
    Instantiate and invoke context managers in a nested way.  each argument is a callable which
    returns an instantiated context manager
    """
    if len(callables) > 1:
        mid = len(callables) // 2
        with nested_jit(*callables[:mid]) as a, nested_jit(*callables[mid:]) as b:
            yield a + b
    elif len(callables) == 1:
        with callables[0]() as a:
            yield (a,)
    else:
        yield ()


def nested(*managers):
    """
    Invoke preinstantiated context managers in a nested way
    """

    def helper(m):
        return lambda: m

    return nested_jit(*(helper(m) for m in managers))


@contextlib.asynccontextmanager
async def anested_jit(*callables):
    """
    Instantiate and invoke async context managers in a nested way.  each argument is a callable which
    returns an instantiated context manager
    """
    if len(callables) > 1:
        mid = len(callables) // 2
        async with anested_jit(*callables[:mid]) as a, anested_jit(
            *callables[mid:]
        ) as b:
            yield a + b
    elif len(callables) == 1:
        async with as_asynccontextmanager(callables[0]()) as a:
            yield (a,)
    else:
        yield ()


def as_asynccontextmanager(mgr):
    """
    Ensure a context manager has an asyn interface, wrapping
    it if necessary
    """
    if hasattr(mgr, "__aenter__"):
        return mgr

    @contextlib.asynccontextmanager
    async def wrapper():
        with mgr as result:
            yield result

    return wrapper()


def anested(*managers):
    """
    Invoke preinstantiated context managers in a nested way
    """

    def helper(m):
        return lambda: m

    return anested_jit(*(helper(m) for m in managers))
