
import pytest
from anyio import create_task_group, sleep

from asynkit.experimental.anyio import EagerTaskGroup, create_eager_task_group

pytestmark = pytest.mark.anyio


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


"""
There is a fundamental problem preventing us from implementing "eager" like
behaviour in Trio.  Cancel scopse, such that are entered around sleep() calls,
perform sanity check when unwound.  They will panic if they are unwinding in a different
Task than the one in which they entered.  This prevents Eager-like behaviour, where the
sleep is entered in the context of the parent task, a coroutine created, a new task 
creeated, and then the sleep is exited in the new task.
"""


async def test_cancel_scope_corruption(anyio_backend_name):

    if anyio_backend_name == "trio":
        pytest.xfail("cancel weirness for a task")

    async def func():
        await sleep(0.01)

    async with create_task_group() as tg:
        EagerTaskGroup(tg).start_soon(func)


@pytest.mark.parametrize(
    "group", [create_task_group, create_eager_task_group], ids=["normal", "eager"]
)
@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
class TestStartSoon:
    def get_coro(self, block):
        async def coro(result, val):
            result.append("a")
            if block:
                await sleep(0.01)
            result.append(val)

        return coro

    async def test_one(self, group, block):
        if block and group == create_eager_task_group:
            pytest.xfail("cancel scope corruption")
        result = []
        coro = self.get_coro(block)
        # async with group() as tg:
        async with create_task_group() as tg:
            if group is create_eager_task_group:
                tg = EagerTaskGroup(tg)
            tg.start_soon(coro, result, "b", name="myname")
            if group is create_task_group:
                assert result == []
            else:
                assert result == ["a"] if block else ["a", "b"]

        assert result == ["a", "b"]
