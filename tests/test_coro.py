import asyncio
import inspect
import sys
import types
from contextlib import asynccontextmanager
from contextvars import ContextVar, copy_context
from typing import Any
from unittest.mock import Mock

import pytest
from anyio import Event, create_task_group, sleep

import asynkit
import asynkit.tools

try:
    from contextlib import aclosing  # type: ignore[attr-defined]
except ImportError:

    @asynccontextmanager  # type: ignore[no-redef]
    async def aclosing(obj):
        try:
            yield obj
        finally:
            await obj.aclose()


eager_var: ContextVar[str] = ContextVar("eager_var")

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("block", [True, False])
class TestEager:
    @pytest.fixture
    def anyio_backend(self):
        """
        eager behaviour creates Tasks and thus does not work directly with Trio
        """
        return "asyncio"

    async def coro1(self, log):
        log.append(1)
        eager_var.set("a")
        await sleep(0)
        log.append(2)
        assert eager_var.get() == "a"
        eager_var.set("b")

    async def coro1_nb(self, log):
        log.append(1)
        eager_var.set("a")
        log.append(2)
        assert eager_var.get() == "a"
        eager_var.set("b")

    def get_coro1(self, block):
        if block:
            return self.coro1, [1, "a", 2]
        else:
            return self.coro1_nb, [1, 2, "a"]

    @asynkit.func_eager
    async def coro2(self, log):
        log.append(1)
        eager_var.set("a")
        await sleep(0)
        log.append(2)
        assert eager_var.get() == "a"
        eager_var.set("b")

    @asynkit.eager
    async def coro3(self, log, block):
        log.append(1)
        if block:
            await sleep(0)
        log.append(2)

    async def coro6(self, log, block):
        log.append(1)
        if block:
            await sleep(0)
        log.append(2)
        raise RuntimeError("foo")

    async def test_no_eager(self, block):
        log = []
        eager_var.set("X")
        coro, _ = self.get_coro1(block)
        log.append("a")
        await coro(log)
        assert log == ["a", 1, 2]
        assert eager_var.get() == "b"

    async def test_coro_eager(self, block):
        log = []
        eager_var.set("X")
        coro, expect = self.get_coro1(block)
        future = asynkit.coro_eager(coro(log))
        log.append("a")
        await future
        assert log == expect
        assert eager_var.get() == "X"

    async def test_coro_eager_create_task(self, block):
        log = []
        eager_var.set("X")
        coro, expect = self.get_coro1(block)

        def factory(coro):
            return asynkit.tools.create_task(coro, name="bob")

        m = Mock()
        m.side_effect = factory
        future = asynkit.coro_eager(coro(log), create_task=m)
        if block:
            m.assert_called_once()
        log.append("a")
        await future
        assert log == expect
        assert eager_var.get() == "X"

    async def test_func_eager(self, block):
        log = []
        eager_var.set("X")
        future = self.coro2(log)
        log.append("a")
        await future
        assert log == [1, "a", 2]
        assert eager_var.get() == "X"

    async def test_eager(self, block):
        """Test the `coro` helper, used both as wrapper and decorator"""
        log = []
        eager_var.set("X")
        coro, expect = self.get_coro1(block)
        future = asynkit.eager(coro(log))
        log.append("a")
        await future
        assert log == expect
        log = []
        future = self.coro3(log, block)
        log.append("a")
        await future
        assert log == expect
        assert eager_var.get() == "X"

    async def test_eager_future(self, block):
        log = []
        awaitable = asynkit.eager(self.coro1_nb(log))
        assert inspect.isawaitable(awaitable)
        await awaitable

    async def test_eager_exception(self, block):
        log = []
        awaitable = asynkit.eager(self.coro6(log, block))
        if block:
            assert log == [1]
        else:
            assert log == [1, 2]
        with pytest.raises(RuntimeError):
            await awaitable
        assert log == [1, 2]

    def test_eager_invalid(self, block):
        with pytest.raises(TypeError):
            asynkit.eager(self)

    async def test_eager_ctx(self, block):
        log = []
        coro, expect = self.get_coro1(block)
        with asynkit.eager_ctx(coro(log)) as c:
            log.append("a")
            await c

        assert log == expect

    async def test_eager_ctx_noawait(self, block: bool) -> None:
        log: list[Any] = []
        coro, expect = self.get_coro1(block)
        with asynkit.eager_ctx(coro(log)) as c:
            log.append("a")

        if block:
            with pytest.raises(asyncio.CancelledError):
                await c
            assert c.cancelled()
        else:
            assert log == expect


@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
class TestCoroStart:
    async def coro1(self, log):
        self.gen_exit = False
        log.append(1)
        try:
            await sleep(0.01)
        except GeneratorExit:
            self.gen_exit = True
            raise
        log.append(2)
        return log

    async def coro1_nb(self, log):
        self.gen_exit = False
        log.append(1)
        log.append(2)
        return log

    async def coro2(self, log):
        self.gen_exit = False
        1 / 0

    def get_coro1(self, block):
        if block:
            return self.coro1, [1, "a", 2]
        else:
            return self.coro1_nb, [1, 2, "a"]

    async def test_auto_start(self, block, anyio_backend):
        corofn, expect = self.get_coro1(block)
        log = []
        coro = corofn(log)
        cs = asynkit.CoroStart(coro)
        if block:
            assert not cs.done()
            assert asynkit.coro_is_suspended(coro)
            assert not asynkit.coro_is_finished(coro)
            assert log == [1]
        else:
            assert cs.done()
            assert not asynkit.coro_is_suspended(coro)
            assert asynkit.coro_is_finished(coro)
            assert log == [1, 2]

    async def test_await(self, block):
        corofn, expect = self.get_coro1(block)
        log = []
        coro = corofn(log)
        cs = asynkit.CoroStart(coro)
        log.append("a")
        assert await cs == expect
        assert log == expect

    async def test_await_twice(self, block):
        corofn, expect = self.get_coro1(block)
        log = []
        coro = corofn(log)
        cs = asynkit.CoroStart(coro)
        log.append("a")
        assert await cs == expect
        assert log == expect
        with pytest.raises(RuntimeError) as err:
            await cs
        assert err.match("cannot reuse already awaited")

    async def test_close(self, block):
        # first test regular coroutine
        async def normal():
            await sleep(0)

        coro = normal()
        coro.send(None)
        coro.close()
        coro.close()
        with pytest.raises(RuntimeError) as err:
            await coro
        assert err.match("cannot reuse already")

        # and now our own
        corofn, expect = self.get_coro1(block)
        log = []
        coro = corofn(log)
        cs = asynkit.CoroStart(coro)
        log.append("a")
        cs.close()
        cs.close()
        with pytest.raises(RuntimeError) as err:
            await cs
        assert err.match("cannot reuse already")

    async def test_start_err(self, block):
        log = []
        cs = asynkit.CoroStart(self.coro2(log))
        assert cs.done()
        with pytest.raises(ZeroDivisionError):
            await cs.as_coroutine()

    async def test_as_coroutine(self, block):
        coro, expect = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        cr = cs.as_coroutine()
        assert inspect.iscoroutine(cr)
        log.append("a")
        await cr
        assert log == expect

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_as_future(self, block, anyio_backend):
        coro, expect = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        log.append("a")
        if block:
            with pytest.raises(RuntimeError) as err:
                fut = cs.as_future()
            assert err.match(r"not done")
            assert await cs == expect
        else:
            fut = cs.as_future()
            assert isinstance(fut, asyncio.Future)
            assert await fut == expect

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_as_awaitable(self, block, anyio_backend):
        coro, expect = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        log.append("a")
        awaitable = cs.as_awaitable()
        if block:
            assert inspect.isawaitable(awaitable)
        else:
            assert isinstance(awaitable, asyncio.Future)
        assert await awaitable == expect

    async def test_result(self, block):
        coro, _ = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        if block:
            assert not cs.done()
            with pytest.raises(asyncio.InvalidStateError):
                cs.result()
        else:
            assert cs.result() is log
        cs = asynkit.CoroStart(self.coro2(log))
        assert cs.done()
        with pytest.raises(ZeroDivisionError):
            cs.result()

    async def test_exception(self, block):
        async def coro():
            if block:
                await sleep(0.01)
            1 / 0

        cs = asynkit.CoroStart(coro())
        if block:
            assert not cs.done()
            with pytest.raises(asyncio.InvalidStateError):
                cs.exception()
        else:
            assert isinstance(cs.exception(), ZeroDivisionError)

    async def test_low_level_close(self, block):
        coro, _ = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        cont = cs.as_coroutine()
        if not block:
            with pytest.raises(StopIteration) as err:
                cont.send(None)
            assert err.value.value == [1, 2]
        else:
            cont.send(None)
        cont.close()
        if block:
            assert self.gen_exit is True

    async def test_closing(self, block):
        coro, _ = self.get_coro1(block)
        async with aclosing(asynkit.CoroStart(coro([]))) as cs:
            return await cs

    async def test_closing_abort(self, block):
        coro, _ = self.get_coro1(block)
        async with aclosing(asynkit.CoroStart(coro([]))) as cs:
            assert not self.gen_exit
            if cs.done():
                return await cs
        if block:
            #  Assert that a generator exit was sent into the coroutine
            assert self.gen_exit


class TestCoroStartClose:
    # A separate test class to test close semantics
    # with no parametrization

    stage = [0]

    async def sleep(self, t):
        # for synchronous tests use asyncio version
        if getattr(self, "sync", False):
            await asyncio.sleep(t)
        else:
            await sleep(t)

    async def cleanupper(self):
        """A an async function which does async cleanup when interrupted"""
        try:
            self.stage[0] = 1
            await self.sleep(0)
        except ZeroDivisionError:
            pass
        finally:
            self.stage[0] = 2
            await self.sleep(0)
            self.stage[0] = 3
        self.stage[0] = 4
        return "result"

    async def simple(self):
        return "simple"

    async def handler(self):
        try:
            await self.sleep(0)
        except ZeroDivisionError:
            pass
        return "handler"

    def test_close(self):
        self.sync = True
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert not starter.done()
        assert self.stage[0] == 1
        with pytest.raises(RuntimeError) as err:
            starter.close()
        assert err.match("coroutine ignored GeneratorExit")
        assert self.stage[0] == 2

    async def test_aclose(self):
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert self.stage[0] == 1
        assert not starter.done()
        await starter.aclose()
        assert self.stage[0] == 3

    async def test_athrow(self):
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert self.stage[0] == 1
        assert not starter.done()
        with pytest.raises(RuntimeError) as err:
            await starter.athrow(RuntimeError("slap face"))
        assert self.stage[0] == 3
        assert err.match("face")

    async def test_athrow_handled(self):
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert self.stage[0] == 1
        assert not starter.done()
        result = await starter.athrow(ZeroDivisionError)
        assert self.stage[0] == 4
        assert result == "result"

    def test_throw_handled(self):
        self.sync = True
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert self.stage[0] == 1
        assert not starter.done()
        with pytest.raises(RuntimeError) as err:
            starter.throw(asyncio.CancelledError())
        assert err.match("coroutine ignored")
        assert self.stage[0] == 2

    def test_throw_handled_2(self):
        self.sync = True
        self.stage[0] = 0
        c = self.cleanupper()
        starter = asynkit.CoroStart(c)
        assert self.stage[0] == 1
        assert not starter.done()
        with pytest.raises(asyncio.CancelledError):
            starter.throw(asyncio.CancelledError, tries=2)
        assert self.stage[0] == 2

    def test_throw_simple(self):
        self.sync = True
        c = self.simple()
        starter = asynkit.CoroStart(c)
        assert starter.done()
        with pytest.raises(RuntimeError) as err:
            starter.throw(asyncio.CancelledError())
        assert err.match("cannot reuse already awaited coroutine")

    def test_throw_handled_return(self):
        self.sync = True
        c = self.handler()
        starter = asynkit.CoroStart(c)
        assert not starter.done()
        assert starter.throw(ZeroDivisionError()) == "handler"

    async def test_close_simple(self):
        starter = asynkit.CoroStart(self.simple())
        assert starter.done()
        starter.close()

        starter = asynkit.CoroStart(self.simple())
        assert await starter == "simple"
        starter.close()

    async def test_aclose_simple(self):
        starter = asynkit.CoroStart(self.simple())
        assert starter.done()
        await starter.aclose()

        starter = asynkit.CoroStart(self.simple())
        assert await starter == "simple"
        await starter.aclose()

    async def test_athrow_simple(self):
        starter = asynkit.CoroStart(self.simple())
        assert starter.done()
        with pytest.raises(RuntimeError) as err:
            await starter.athrow(ZeroDivisionError())
        assert err.match("cannot reuse")

        starter = asynkit.CoroStart(self.simple())
        assert await starter == "simple"
        with pytest.raises(RuntimeError) as err:
            await starter.athrow(ZeroDivisionError())
        assert err.match("cannot reuse")


class TestCoroRun:
    sync = True

    async def sleep(self, t):
        # for synchronous tests use asyncio version
        if getattr(self, "sync", False):
            await asyncio.sleep(t)
        else:
            await sleep(t)

    async def cleanupper(self):
        try:
            await self.sleep(0)
        finally:
            await self.sleep(0)

    async def genexit(self):
        """A an async function which does async cleanup when interrupted"""
        try:
            await self.sleep(0)
        except BaseException:
            pass

    async def noexit(self):
        while True:
            try:
                await self.sleep(0)
            except GeneratorExit:
                raise  # sent by asyncio
            except BaseException:
                # ignore our SyncronousAbort error
                pass

    async def simple(self):
        return "simple"

    @asynkit.syncfunction
    async def sync_simple(self):
        return await self.simple()

    @asynkit.syncfunction
    async def sync_cleanup(self):
        return await self.cleanupper()

    @asynkit.syncfunction
    async def sync_genexit(self):
        return await self.genexit()

    def test_simple(self):
        assert asynkit.await_sync(self.simple()) == "simple"

    def test_sync_simple(self):
        assert self.sync_simple() == "simple"

    def test_cleanup(self):
        with pytest.raises(asynkit.SynchronousError) as err:
            self.sync_cleanup()
        assert err.match("failed to complete synchronously")

    def test_genexit(self):
        with pytest.raises(asynkit.SynchronousError) as err:
            self.sync_genexit()
        assert err.match("failed to complete synchronously")
        assert err.match("caught BaseException")

    def test_noexit(self):
        with pytest.raises(asynkit.SynchronousError) as err:
            asynkit.await_sync(self.noexit())
        assert err.match("failed to complete synchronously")


def test_aiter_sync():
    async def agen():
        for i in range(5):
            yield i

    gen = asynkit.aiter_sync(agen())
    assert list(gen) == list(range(5))


class TestCoroAwait:
    """
    These tests test the behaviour of a coroutine wrapped in `coro_await`
    """

    def wrap(self, coro):
        return asynkit.coroutine.coro_await(coro)

    @pytest.fixture(
        params=[
            pytest.param("regular", id="regular"),
            pytest.param("eager", id="eager", marks=pytest.mark.eager_tasks),
        ]
    )
    def anyio_backend(self, request):
        if request.param == "eager":
            if sys.version_info < (3, 12):
                pytest.skip("Eager task factory requires Python 3.12+")

            # Use default event loop with eager task factory
            def loop_factory():
                loop = asyncio.new_event_loop()
                loop.set_task_factory(asyncio.eager_task_factory)
                return loop

            return ("asyncio", {"loop_factory": loop_factory})
        else:
            return "asyncio"

    def is_eager_mode(self, request):
        """Check if test is running with eager task factory"""
        return any(mark.name == "eager_tasks" for mark in request.node.iter_markers())

    async def test_return_nb(self):
        async def func(a):
            return a

        d = ["foo"]
        assert await self.wrap(func(d)) is d

    async def test_exception_nb(self):
        async def func():
            1 / 0

        with pytest.raises(ZeroDivisionError):
            await self.wrap(func())

    async def test_coro_cancel(self, request):
        # Skip for eager mode - task completes synchronously before cancellation
        if self.is_eager_mode(request):
            pytest.skip(
                "Cancellation timing test not applicable with eager task factory"
            )

        async def func():
            await sleep(0)

        coro = self.wrap(func())
        task = asyncio.create_task(coro)
        await sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_coro_handle_cancel(self, request):
        # Skip for eager mode - task completes synchronously before cancellation
        if self.is_eager_mode(request):
            pytest.skip(
                "Cancellation timing test not applicable with eager task factory"
            )

        async def func(a):
            try:
                await sleep(0)
            except asyncio.CancelledError:
                return a

        d = ["a"]
        coro = self.wrap(func(d))
        task = asyncio.create_task(coro)
        await sleep(0)
        task.cancel()
        assert await task is d


contextvar1: ContextVar[Any] = ContextVar("contextvar1")


@pytest.mark.parametrize("block", [True, False])
class TestContext:
    async def coro_block(self, var: ContextVar[Any], val: Any) -> None:
        var.set(val)
        await sleep(0)
        assert var.get() is val

    async def coro_noblock(self, var: ContextVar[Any], val: Any) -> None:
        var.set(val)
        assert var.get() is val

    def get_coro(self, block):
        return self.coro_block if block else self.coro_noblock

    async def test_no_context(self, block):
        coro = self.get_coro(block)
        contextvar1.set("bar")
        await asynkit.coro_await(coro(contextvar1, "foo"))

        assert contextvar1.get() == "foo"

    async def test_private_context(self, block):
        coro = self.get_coro(block)
        contextvar1.set("bar")
        context = copy_context()
        await asynkit.coro_await(coro(contextvar1, "foo"), context=context)
        assert contextvar1.get() == "bar"

        def check():
            assert contextvar1.get() == "foo"

        context.run(check)


@pytest.mark.parametrize("kind", ["cr", "gi", "ag"])
class TestCoroState:
    def get_coro(self, kind):  # type: ignore[misc]
        # Intentionally defines different coroutine types based on kind
        if kind == "cr":

            async def coro(f):  # type: ignore[misc]
                await f

        elif kind == "gi":

            @types.coroutine
            def coro(f):  # type: ignore[misc]
                yield from f

        else:

            async def coro(f):  # type: ignore[misc]
                await f
                yield f

        return coro

    def wrap_coro(self, kind, coro):
        if kind == "ag":

            async def wrap():
                async for _ in coro:
                    pass

        else:

            async def wrap():
                await coro

        return wrap

    async def test_coro_new(self, kind):
        func = self.get_coro(kind)
        e = Event()
        e.set()
        coro = func(e.wait())
        assert asynkit.coro_is_new(coro)
        assert not asynkit.coro_is_suspended(coro)
        assert not asynkit.coro_is_finished(coro)
        await self.wrap_coro(kind, coro)()

    async def test_coro_suspended(self, kind):
        func = self.get_coro(kind)
        e = Event()
        coro = func(e.wait())
        wrap = self.wrap_coro(kind, coro)
        async with create_task_group() as tg:
            tg.start_soon(wrap)
            await sleep(0.01)  # need a non-zero wait for trio
            assert not asynkit.coro_is_new(coro)
            assert asynkit.coro_is_suspended(coro)
            assert not asynkit.coro_is_finished(coro)
            e.set()

    async def test_coro_finished(self, kind):
        func = self.get_coro(kind)
        e = Event()
        coro = func(e.wait())
        wrap = self.wrap_coro(kind, coro)
        async with create_task_group() as tg:
            tg.start_soon(wrap)
            await sleep(0)
            e.set()
        assert not asynkit.coro_is_new(coro)
        assert not asynkit.coro_is_suspended(coro)
        assert asynkit.coro_is_finished(coro)


def test_coro_is_new_invalid():
    with pytest.raises(TypeError):
        asynkit.coro_is_new("string")


async def test_current():
    coro = None

    async def foo():
        asynkit.coroutine.coro_get_frame(coro)

        # a running coroutine is neither new, suspended nor finished.
        assert not asynkit.coro_is_new(coro)
        assert not asynkit.coro_is_suspended(coro)
        assert not asynkit.coro_is_finished(coro)

    coro = foo()
    await coro


async def test_coro_get_frame():
    async def coroutine():
        await sleep(0)

    c = coroutine()
    assert asynkit.coroutine.coro_get_frame(c) is not None
    await c

    @types.coroutine
    def generator():
        yield from sleep(0)

    c = generator()
    assert asynkit.coroutine.coro_get_frame(c) is not None
    await c

    async def asyncgen():
        yield 1

    c = asyncgen()
    assert asynkit.coroutine.coro_get_frame(c) is not None
    await c.aclose()

    with pytest.raises(TypeError):
        asynkit.coroutine.coro_get_frame("str")


async def test_coro_is_suspended():
    async def coroutine():
        await sleep(0)

    c = coroutine()
    assert not asynkit.coroutine.coro_is_suspended(c)
    c.send(None)
    assert asynkit.coroutine.coro_is_suspended(c)
    c.close()

    @types.coroutine
    def generator():
        yield from sleep(0)

    c = generator()
    assert not asynkit.coroutine.coro_is_suspended(c)
    c.send(None)
    assert asynkit.coroutine.coro_is_suspended(c)
    c.close()

    async def asyncgen():
        await sleep(0)
        yield 1

    c = asyncgen()
    assert not asynkit.coroutine.coro_is_suspended(c)
    cs = asynkit.CoroStart(c.__anext__())
    assert asynkit.coroutine.coro_is_suspended(c)
    assert await cs == 1
    await c.aclose()

    with pytest.raises(TypeError):
        asynkit.coroutine.coro_is_suspended("str")


class TestCoroIter:
    async def coroutine1(self, val):
        await sleep(0)
        return "foo" + val

    async def coroutine2(self, val):
        await sleep(0)
        raise RuntimeError("foo" + val)

    class Awaiter:
        def __init__(self, coro, args=None):
            self.coro = coro
            self.args = args or ["bar1", "bar2"]

        def __await__(self):
            # manually create a coroutine object
            return asynkit.coro_iter(self.coro(self.args.pop(0)))

    class Awaiter2(Awaiter):
        """
        Test the awaitmethod decorator
        """

        @asynkit.awaitmethod_iter
        async def __await__(self):
            return await self.coro(self.args.pop(0))

    class Awaiter3(Awaiter):
        """
        Test the awaitmethod decorator
        """

        @asynkit.awaitmethod
        async def __await__(self):
            return await self.coro(self.args.pop(0))

    class Awaiter4:
        """
        Test the awaitmethod classmethod
        """

        @classmethod
        @asynkit.awaitmethod
        async def __await__(cls) -> str:
            return "Awaiter4"

    class Awaiter5:
        """
        Test the awaitmethod staticmethod
        """

        @staticmethod
        @asynkit.awaitmethod
        async def __await__() -> str:
            return "Awaiter5"

    @pytest.mark.parametrize("awaiter", [Awaiter, Awaiter2, Awaiter3])
    async def test_await(self, awaiter):
        a = awaiter(self.coroutine1, ["bar1"])
        assert await a == "foobar1"

    @pytest.mark.parametrize("awaiter", [Awaiter, Awaiter2, Awaiter3])
    async def test_await_again(self, awaiter):
        a = awaiter(self.coroutine1, ["bar2", "bar3"])
        assert await a == "foobar2"
        assert await a == "foobar3"  # it can be awaited again

    @pytest.mark.parametrize("awaiter", [Awaiter, Awaiter2, Awaiter3])
    async def test_await_exception(self, awaiter):
        a = awaiter(self.coroutine2)
        with pytest.raises(RuntimeError) as err:
            await a
        assert err.value.args[0] == "foobar1"
        with pytest.raises(RuntimeError) as err:
            await a
        assert err.value.args[0] == "foobar2"

    @pytest.mark.parametrize("awaiter", [Awaiter, Awaiter2, Awaiter3])
    async def test_await_immediate(self, awaiter):
        async def coroutine(arg):
            return "coro" + arg

        a = awaiter(coroutine)
        assert await a == "corobar1"

    async def test_raw_generator_exit(self):
        step = 0

        async def coroutine():
            nonlocal step
            with pytest.raises(GeneratorExit):
                step = 1
                await sleep(0)
            step = 2

        @types.coroutine
        def helper():
            yield from asynkit.coro_iter(coroutine())

        c = helper()
        c.send(None)
        assert step == 1
        with pytest.raises(GeneratorExit):
            c.throw(GeneratorExit)
        assert step == 2
        c.close()

    async def test_raw_exception(self):
        step = 0

        async def coroutine():
            nonlocal step
            with pytest.raises(ZeroDivisionError):
                step = 1
                await sleep(0)
            step = 2
            return "foo"

        @types.coroutine
        def helper():
            return (yield from asynkit.coro_iter(coroutine()))

        c = helper()
        c.send(None)
        assert step == 1
        with pytest.raises(StopIteration) as err:
            c.throw(ZeroDivisionError)
        assert step == 2
        assert err.value.value == "foo"
        c.close()

    @pytest.mark.parametrize("awaiter", [Awaiter4, Awaiter5])
    async def test_await_static(self, awaiter):
        a = awaiter()
        if awaiter == self.Awaiter4:
            assert await a == "Awaiter4"
        else:
            assert await a == "Awaiter5"


async def test_async_function():
    def sync_method():
        return "foo"

    @asynkit.asyncfunction
    def sync_method2():
        return "bar"

    assert await asynkit.asyncfunction(sync_method)() == "foo"
    assert await sync_method2() == "bar"


async def test_sync_function():
    async def async_method():
        return "foo"

    @asynkit.syncfunction
    async def async_method2():
        return "bar"

    assert asynkit.syncfunction(async_method)() == "foo"
    assert async_method2() == "bar"
