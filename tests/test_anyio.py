from contextlib import nullcontext

import pytest
from anyio import Event, create_task_group, sleep

from asynkit import CoroStart
from asynkit.experimental.anyio import (
    EagerTaskGroup,
    TaskStatusForwarder,
    create_eager_task_group,
)

pytestmark = pytest.mark.anyio


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


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_eager_task_group_context(anyio_backend):
    """
    Test the async EagerTaskGroup object
    """
    # test only on asyncio, trio raises AssertionError which cannot be caught in testing
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
        with pytest.raises(EOFError):
            await tg.start(foo)


async def test_error_start_soon():
    async def foo():
        raise EOFError()

    with pytest.raises(EOFError):
        async with create_task_group() as tg:
            tg.start_soon(foo)


async def test_cancel_scope_corruption(anyio_backend_name):

    if anyio_backend_name == "trio":
        pytest.xfail("cancel weirness for a task")

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
        if block and eager and anyio_backend_name == "trio":
            pytest.xfail("cancel scope corruption")

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

        with nullcontext() if eager else pytest.raises(EOFError):
            async with group() as tg:
                with nullcontext() if not eager else pytest.raises(EOFError):
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
        if eager and block and anyio_backend_name == "trio":
            pytest.xfail("trio can't properly eager")

        result = []
        event, coro = self.get_coro_err2(block)

        with pytest.raises(EOFError) if not (eager and not block) else nullcontext():
            async with group() as tg:
                ctx = (
                    pytest.raises(EOFError) if (eager and not block) else nullcontext()
                )
                with ctx:
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


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
async def test_task_status_forwarder(block, anyio_backend):
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
        if block and eager:
            pytest.xfail("cancel scope corruption")
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
        if block and eager:
            pytest.xfail("cancel scope corruption")
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

        if eager and block and anyio_backend_name == "trio":
            pytest.xfail("trio can't properly eager")

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

        if eager and block and anyio_backend_name == "trio":
            pytest.xfail("trio can't properly eager")

        got_start = False
        with pytest.raises(EOFError):
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

        if eager and block and anyio_backend_name == "trio":
            pytest.xfail("trio can't properly eager")

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
