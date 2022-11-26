import asyncio
import inspect
import pytest
import asynkit
import types


@pytest.mark.parametrize("block", [True, False])
class TestEager:
    async def coro1(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)

    async def coro1_nb(self, log):
        log.append(1)
        log.append(2)

    def get_coro1(self, block):
        if block:
            return self.coro1, [1, "a", 2]
        else:
            return self.coro1_nb, [1, 2, "a"]

    @asynkit.func_eager
    async def coro2(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)

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
        coro, _ = self.get_coro1(block)
        log.append("a")
        await coro(log)
        assert log == ["a", 1, 2]

    async def test_coro_eager(self, block):
        log = []
        coro, expect = self.get_coro1(block)
        future = asynkit.coro_eager(coro(log))
        log.append("a")
        await future
        assert log == expect

    async def test_func_eager(self, block):
        log = []
        future = self.coro2(log)
        log.append("a")
        await future
        assert log == [1, "a", 2]

    async def test_eager(self, block):
        """Test the `coro` helper, used both as wrapper and decorator"""
        log = []
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

    async def test_eager_future(self, block):
        log = []
        awaitable = asynkit.eager(self.coro1_nb(log))
        assert inspect.isawaitable(awaitable)
        assert asyncio.isfuture(awaitable)
        await awaitable

    async def test_eager_exception(self, block):
        log = []
        awaitable = asynkit.eager(self.coro6(log, block))
        if block:
            assert log == [1]
        else:
            assert log == [1,2]
        with pytest.raises(RuntimeError):
            await awaitable
        assert log == [1, 2]

    def test_eager_invalid(self, block):
        with pytest.raises(TypeError):
            asynkit.eager(self)

    async def test_coro_start(self, block):
        log = []
        coro, expect = self.get_coro1(block)
        cs = asynkit.CoroStart(coro(log), auto_start=False)
        cs.start()
        assert cs.is_suspended() == block
        log.append("a")
        await cs.as_task_or_future()
        assert log == expect

    async def test_coro_start_autostart(self, block):
        log = []
        coro, expect = self.get_coro1(block)

        cs = asynkit.CoroStart(coro(log))
        assert cs.is_suspended() == block
        log.append("a")
        await cs.as_task_or_future()
        assert log == expect

    async def test_eager_coroutine(self, block):
        """
        Test that an eager coroutine can be passed to a Task creation api
        and the eagerness happens right away.
        """
        log = []
        coro, expect = self.get_coro1(block)
        task = asyncio.Task(asynkit.eager_coroutine(coro(log)))
        log.append("a")
        await task
        assert log == expect

    async def test_eager_awaitable(self, block):
        """
        Test that an eager awaitable can be passed to a Task creation api
        and the eagerness happens right away.
        """
        log = []
        coro, expect = self.get_coro1(block)

        def fake_api(awaitable):
            if asynkit.iscoroutine(awaitable):
                return asyncio.Task(awaitable)

            async def helper(awaitable):
                return await (awaitable)

            return asyncio.Task(helper(awaitable))

        async def helper(awaitable):
            return await awaitable

        task = fake_api(asynkit.eager_awaitable(coro(log)))
        log.append("a")
        await task
        assert log == expect

    async def test_eager_callable(self, block):
        """
        Test that an eager callable can be passed to a Task creation api which
        excepts callables, and eager execution is observed.
        """
        log = []
        coro, expect = self.get_coro1(block)

        async def helper(callable, *args, **kwargs):
            return await callable(*args, **kwargs)

        task = asyncio.Task(helper(asynkit.eager_callable(coro(log))))
        log.append("a")
        await task
        assert log == expect


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
        f = asynkit.coroutine.coro_get_frame(coro)

        # a running coroutine is neither new, suspended nor finished.
        assert not asynkit.coro_is_new(coro)
        assert not asynkit.coro_is_suspended(coro)
        assert not asynkit.coro_is_finished(coro)

    coro = foo()
    await coro
