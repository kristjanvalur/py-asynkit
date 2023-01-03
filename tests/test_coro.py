import asyncio
import inspect
import types
from contextvars import ContextVar, copy_context
from typing import Any
from unittest.mock import Mock

import pytest

import asynkit
import asynkit.tools

eager_var = ContextVar("eager_var")


@pytest.mark.parametrize("block", [True, False])
class TestEager:
    async def coro1(self, log):
        log.append(1)
        eager_var.set("a")
        await asyncio.sleep(0)
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
        await asyncio.sleep(0)
        log.append(2)
        assert eager_var.get() == "a"
        eager_var.set("b")

    @asynkit.eager
    async def coro3(self, log, block):
        log.append(1)
        if block:
            await asyncio.sleep(0)
        log.append(2)

    async def coro6(self, log, block):
        log.append(1)
        if block:
            await asyncio.sleep(0)
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


@pytest.mark.parametrize("block", [True, False], ids=["block", "noblock"])
class TestCoroStart:
    async def coro1(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)
        return log

    async def coro1_nb(self, log):
        log.append(1)
        log.append(2)
        return log

    async def coro2(self, log):
        1 / 0

    def get_coro1(self, block):
        if block:
            return self.coro1, [1, "a", 2]
        else:
            return self.coro1_nb, [1, 2, "a"]

    def test_auto_start(self, block):
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
            await asyncio.sleep(0)

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

    async def test_as_future(self, block):
        coro, expect = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        fut = cs.as_future()
        assert isinstance(fut, asyncio.Future)
        if block:
            assert isinstance(fut, asyncio.Task)
        else:
            assert not isinstance(fut, asyncio.Task)
            assert fut.done()

    async def test_as_future_custom(self, block):
        coro, expect = self.get_coro1(block)
        log = []
        cs = asynkit.CoroStart(coro(log))
        fut = cs.as_future(create_task=lambda t: t)
        if block:
            assert inspect.iscoroutine(fut)
            await fut
        else:
            assert not isinstance(fut, asyncio.Task)
            assert fut.done()

    async def test_task_factory(self, block):
        coro, expect = self.get_coro1(block)
        log = []
        mock = Mock()
        cs = asynkit.CoroStart(coro(log))
        fut = cs.as_future(create_task=mock)
        if block:
            assert isinstance(fut, Mock)
            mock.assert_called()
            assert len(mock.call_args[0]) == 1
            coro = mock.call_args[0][0]
            assert inspect.iscoroutine(coro)
            await coro
        else:
            assert isinstance(fut, asyncio.Future)
            mock.assert_not_called()

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


wrap = asynkit.coroutine.coro_await


class TestCoro:
    async def test_return_nb(self):
        async def func(a):
            return a

        d = ["foo"]
        assert await wrap(func(d)) is d

    async def test_exception_nb(self):
        async def func():
            1 / 0

        with pytest.raises(ZeroDivisionError):
            await wrap(func())

    async def test_coro_cancel(self):
        async def func():
            await asyncio.sleep(0)

        coro = wrap(func())
        task = asyncio.create_task(coro)
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_coro_handle_cancel(self):
        async def func(a):
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                return a

        d = ["a"]
        coro = wrap(func(d))
        task = asyncio.create_task(coro)
        await asyncio.sleep(0)
        task.cancel()
        assert await task is d


contextvar1: ContextVar = ContextVar("contextvar1")


@pytest.mark.parametrize("block", [True, False])
class TestContext:
    async def coro_block(self, var: ContextVar, val: Any):
        var.set(val)
        await asyncio.sleep(0)
        assert var.get() is val

    async def coro_noblock(self, var: ContextVar, val: Any):
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
    def get_coro(self, kind):
        if kind == "cr":

            async def coro(f):
                await f

        elif kind == "gi":

            @types.coroutine
            def coro(f):
                yield from f

        else:

            async def coro(f):
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
        f = asyncio.Future()
        f.set_result(True)
        coro = func(f)
        assert asynkit.coro_is_new(coro)
        assert not asynkit.coro_is_suspended(coro)
        assert not asynkit.coro_is_finished(coro)
        await self.wrap_coro(kind, coro)()

    async def test_coro_suspended(self, kind):
        func = self.get_coro(kind)
        f = asyncio.Future()
        coro = func(f)
        wrap = self.wrap_coro(kind, coro)
        t = asyncio.Task(wrap())
        await asyncio.sleep(0)
        assert not asynkit.coro_is_new(coro)
        assert asynkit.coro_is_suspended(coro)
        assert not asynkit.coro_is_finished(coro)
        f.set_result(True)
        await t

    async def test_coro_finished(self, kind):
        func = self.get_coro(kind)
        f = asyncio.Future()
        coro = func(f)
        wrap = self.wrap_coro(kind, coro)
        t = asyncio.Task(wrap())
        await asyncio.sleep(0)
        f.set_result(True)
        await t
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
