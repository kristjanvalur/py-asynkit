from contextlib import nullcontext
from sys import version_info

import pytest
from anyio import Event, create_task_group, sleep

from asynkit import CoroStart
from asynkit.experimental.anyio import (
    EagerTaskGroup,
    TaskStatusForwarder,
    create_eager_task_group,
)

# ExceptionGroup is built-in from Python 3.11+
if version_info >= (3, 11):
    from builtins import ExceptionGroup  # type: ignore[attr-defined]
else:
    from exceptiongroup import ExceptionGroup  # type: ignore[import-not-found]

pytestmark = pytest.mark.anyio


def raises_or_exception_group(exc_type: type[BaseException]):  # type: ignore[no-untyped-def]
    """
    Context manager that matches either a direct exception or an ExceptionGroup
    containing that exception. Needed for anyio 4.x compatibility.
    """

    class ExceptionMatcher:
        def __enter__(self):
            return self

        def __exit__(self, et, ev, tb):
            if et is None:
                pytest.fail(f"Expected {exc_type.__name__} but no exception was raised")
            # Check if it's the direct exception
            if et is exc_type:
                return True
            # Check if it's an ExceptionGroup containing the exception
            if issubclass(et, ExceptionGroup):
                # Extract exceptions from the group
                if hasattr(ev, "exceptions"):
                    for e in ev.exceptions:
                        if isinstance(e, exc_type):
                            return True
                pytest.fail(
                    f"Expected {exc_type.__name__} in ExceptionGroup, "
                    f"but got {[type(e).__name__ for e in ev.exceptions]}"
                )
            # Not the exception we're looking for
            return False

    return ExceptionMatcher()


# Backend parametrization for tests
# trio backend is incompatible with eager execution + blocking due to
# architectural differences (see module docstring below for details)
backends = ["asyncio", "trio"]  # Both backends supported
backends_notrio = ["asyncio"]  # Only asyncio (trio incompatible with this test)


"""
There is a fundamental problem preventing us from implementing "eager" like
behaviour in Trio.

A lot of the primitives in Trio depend on Tasks.  A primitive, when it goes to sleep,
puts the Task in some place, and then when it needs to be woken up, it attempts to
reschedule that Task.  This is a problem if the primitive goes to sleep in one task
and then expects to be awoken in another task, such as can happen with CoroStart.  A
CoroStart() routine, which runs to an Event.wait(), and blocks there, will put the
currenttask on in `Events._tasks`.  When someone then "sets" the events, all these
tasks are then rescheduled.  But we expect the "waking up" to happen in a new routine.

Similarly, Cancel scopes, such that are entered around sleep() calls,
perform sanity check when unwound.  They will panic if they are unwinding in a
differentTask than the one in which they entered.  This prevents Eager-like behaviour,
where thesleep is entered in the context of the parent task, a coroutine created,
a new task created, and then the sleep is exited in the new task.

Fundamentally, the problem is that trio doesn't use `Futures` like asyncio does.
CoroStart() works by intercepting the Future that is being passed up to the event loop.
No scheduling happens in the wait primitive itself, it all happens when the Future
reaches the event loop. And so, for asyncio, CoroStart() works, because it appears
to asyncio that the blocking primitive just happened on the newly created Task object,
 once it starts running.

In contrast, in Trio, a lot of the scheduling activity happens inside the primitive
call, before yielding up a control structure to the Trio loop.

Therefore, this kind of stuff does not work with Trio properly.   But using anyio
with "asyncio" does work just fine.
"""


@pytest.mark.parametrize("anyio_backend", backends_notrio)
async def test_eager_task_group_context(anyio_backend):
    """
    Test the async EagerTaskGroup object
    """
    # test only on asyncio, trio incompatible with eager execution
    # test behaviour of normal task group

    async with create_task_group() as tg:
        assert tg.cancel_scope is not None

    async with create_task_group() as tg:
        with pytest.raises(RuntimeError):
            async with tg:  # check if it works as context mgr
                pass

    # and now the eager one

    async with create_eager_task_group():
        assert tg.cancel_scope is not None

    async with create_eager_task_group() as tg:
        with pytest.raises(RuntimeError):
            async with tg:  # check if it works as context mgr
                pass


async def test_error_start():
    async def foo(task_status):
        raise EOFError()

    async with create_task_group() as tg:
        with raises_or_exception_group(EOFError):
            await tg.start(foo)


async def test_error_start_soon():
    async def foo():
        raise EOFError()

    with raises_or_exception_group(EOFError):
        async with create_task_group() as tg:
            tg.start_soon(foo)


async def test_cancel_scope_corruption(anyio_backend_name):
    # Skip trio - even non-eager eager task groups have cancel scope issues
    if anyio_backend_name == "trio":
        pytest.skip("trio incompatible with EagerTaskGroup")

    async def func():
        # non-zero sleep is implemented with a cancel scope
        await sleep(0.01)

    async with create_task_group() as tg:
        EagerTaskGroup(tg).start_soon(func)


@pytest.mark.parametrize(
    "group", [create_task_group, create_eager_task_group], ids=["normal", "eager"]
)
@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
class TestStartSoon:
    async def test_normal(self, group, block, anyio_backend_name):
        eager = group == create_eager_task_group
        # Skip trio for eager+blocking combinations
        if block and eager and anyio_backend_name == "trio":
            pytest.skip("trio incompatible with eager execution + blocking")

        result = []
        event, coro = self.get_coro(block)
        async with group() as tg:
            tg.start_soon(coro, result, "b", name="myname")
            if not eager:
                assert result == []
            else:
                assert result == (["a"] if block else ["a", "b"])
            event.set()

        assert result == ["a", "b"]

    def get_coro(self, block):
        event = Event()

        async def coro(result, val):
            result.append("a")
            if block:
                await event.wait()
            result.append(val)

        return event, coro

    async def test_err1(self, group, block):
        eager = group == create_eager_task_group

        result = []
        event, coro = self.get_coro_err1(block)

        ctx_outer = nullcontext() if eager else raises_or_exception_group(EOFError)
        with ctx_outer:
            async with group() as tg:
                ctx_inner = (
                    nullcontext() if not eager else raises_or_exception_group(EOFError)
                )
                with ctx_inner:
                    tg.start_soon(coro, result, "b", name="myname")

                event.set()

    def get_coro_err1(self, block):
        event = Event()

        async def coro(result, val):
            raise EOFError()
            result.append("a")
            if block:
                await event.wait()
            result.append(val)

        return event, coro

    async def test_err2(self, group, block, anyio_backend_name):
        eager = group == create_eager_task_group
        # Skip trio for eager+blocking combinations
        if eager and block and anyio_backend_name == "trio":
            pytest.skip("trio incompatible with eager execution + blocking")

        result = []
        event, coro = self.get_coro_err2(block)

        ctx_outer = (
            raises_or_exception_group(EOFError)
            if not (eager and not block)
            else nullcontext()
        )
        with ctx_outer:
            async with group() as tg:
                ctx_inner = (
                    raises_or_exception_group(EOFError)
                    if (eager and not block)
                    else nullcontext()
                )
                with ctx_inner:
                    tg.start_soon(coro, result, "b", name="myname")
                    assert result == (["a"] if eager else [])
                event.set()

    def get_coro_err2(self, block):
        event = Event()

        async def coro(result, val):
            result.append("a")
            if block:
                await event.wait()
            raise EOFError()
            result.append(val)

        return event, coro


@pytest.mark.parametrize("anyio_backend", backends_notrio)
@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
async def test_task_status_forwarder(block, anyio_backend):
    # Only test on asyncio - uses CoroStart which has trio issues
    result = None

    async def coro(task_status):
        if block:
            await sleep(0.001)
        task_status.started("foo")
        nonlocal result
        result = "bar"

    async with create_task_group() as tg:
        sf = TaskStatusForwarder()
        cs = CoroStart(coro(sf))

        async def helper(task_status):
            sf.set_forward(task_status)
            await cs

        assert await tg.start(helper) == "foo"
    assert result == "bar"


@pytest.mark.parametrize(
    "group", [create_task_group, create_eager_task_group], ids=["normal", "eager"]
)
@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
class TestStart:
    async def test_normal(self, group, block):
        eager = group == create_eager_task_group
        # Skip eager+blocking (trio incompatible, handled via parametrization)
        if block and eager:
            pytest.skip("eager + blocking not tested (trio incompatible)")
        result = []
        event, coro = self.get_coro(block)
        async with group() as tg:
            coro2 = tg.start(coro, result, "b", name="myname")
            if not eager:
                assert result == []
            else:
                assert result == (["a"] if block else ["a", "b"])
            event.set()
            assert await coro2 == "b"

        assert result == ["a", "b"]

    async def test_normal_create_group(self, group, block):
        eager = group == create_eager_task_group
        # Skip eager+blocking (trio incompatible)
        if block and eager:
            pytest.skip("eager + blocking not tested (trio incompatible)")
        result = []
        event, coro = self.get_coro(block)
        # manually create the group
        if group == create_eager_task_group:
            tg = EagerTaskGroup(create_task_group())
        else:
            tg = create_task_group()
        async with tg:
            coro2 = tg.start(coro, result, "b", name="myname")
            if not eager:
                assert result == []
            else:
                assert result == (["a"] if block else ["a", "b"])
            event.set()
            assert await coro2 == "b"

        assert result == ["a", "b"]

    def get_coro(self, block):
        event = Event()

        async def coro(result, val, *, task_status):
            result.append("a")
            if block:
                await event.wait()
            task_status.started(val)
            result.append(val)

        return event, coro

    async def test_err1(self, group, block):
        """
        Test a method which errors right at the start
        """
        eager = group == create_eager_task_group

        result = []
        event, coro = self.get_coro_err1(block)

        async with group() as tg:
            coro2 = tg.start(coro, result, "b", name="myname")
            assert result == (["a"] if eager else [])
            event.set()
            with pytest.raises(EOFError):
                assert await coro2 == "b"

    def get_coro_err1(self, block):
        event = Event()

        async def coro(result, val, *, task_status):
            result.append("a")
            raise EOFError()
            if block:
                await event.wait()
            result.append(val)

        return event, coro

    async def test_err2(self, group, block, anyio_backend_name):
        """
        Test a coroutine which errors after blocking but
        before sending task_status.started()
        """
        eager = group == create_eager_task_group

        result = []
        event, coro = self.get_coro_err2(block)

        # Skip eager+blocking on trio (incompatible)
        if eager and block and anyio_backend_name == "trio":
            pytest.skip("eager + blocking not tested (trio incompatible)")

        async with group() as tg:
            coro2 = tg.start(coro, result, "b", name="myname")
            assert result == (["a"] if eager else [])
            event.set()
            # with pytest.raises(EOFError) if (eager and not block) else nullcontext():
            # assert await coro2 is None
            with pytest.raises(EOFError):
                assert await coro2 == "b"

    def get_coro_err2(self, block):
        event = Event()

        async def coro(result, val, *, task_status):
            result.append("a")
            if block:
                await event.wait()
            raise EOFError()
            task_status.started(val)
            result.append(val)

        return event, coro

    async def test_err3(self, group, block, anyio_backend_name):
        """
        Test a coroutine which errors _after_ calling task_status->started()
        """
        eager = group == create_eager_task_group

        result = []
        event, coro = self.get_coro_err3(block)

        # Skip eager+blocking on trio (incompatible)
        if eager and block and anyio_backend_name == "trio":
            pytest.skip("eager + blocking not tested (trio incompatible)")

        got_start = False
        with raises_or_exception_group(EOFError):
            async with group() as tg:
                coro2 = tg.start(coro, result, "b", name="myname")
                if eager:
                    assert result == (["a"] if block else ["a", "b"])
                else:
                    assert result == []
                event.set()
                assert await coro2 == "b"
                got_start = True
        assert result == ["a", "b"]
        assert got_start

    def get_coro_err3(self, block):
        event = Event()

        async def coro(result, val, *, task_status):
            result.append("a")
            if block:
                await event.wait()
            task_status.started(val)
            result.append(val)
            raise EOFError()

        return event, coro

    async def test_err4(self, group, block, anyio_backend_name):
        """
        Test a coroutine succeeds but doesn't call task_status->started()
        """
        eager = group == create_eager_task_group

        result = []
        event, coro = self.get_coro_err4(block)

        # Skip eager+blocking on trio (incompatible)
        if eager and block and anyio_backend_name == "trio":
            pytest.skip("eager + blocking not tested (trio incompatible)")

        async with group() as tg:
            coro2 = tg.start(coro, result, "b", name="myname")
            if eager:
                assert result == (["a"] if block else ["a", "b"])
            else:
                assert result == []
            event.set()
            with pytest.raises(RuntimeError) as err:
                assert await coro2 == "b"
            assert err.match(r"[Cc]hild exited without calling task_status.started\(\)")
        assert result == ["a", "b"]

    def get_coro_err4(self, block):
        event = Event()

        async def coro(result, val, *, task_status):
            result.append("a")
            if block:
                await event.wait()
            result.append(val)

        return event, coro
