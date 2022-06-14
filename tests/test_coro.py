import asyncio
import inspect
import pytest
import asynkit
import types


class TestEager:
    async def coro1(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)

    @asynkit.func_eager
    async def coro2(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)

    @asynkit.eager
    async def coro3(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)

    async def coro4(self, log):
        log.append(1)
        log.append(2)

    async def coro5(self, log):
        log.append(1)
        raise RuntimeError("foo")

    async def coro6(self, log):
        log.append(1)
        await asyncio.sleep(0)
        log.append(2)
        raise RuntimeError("foo")

    async def test_no_eager(self):
        log = []
        future = self.coro1(log)
        log.append("a")
        await future
        assert log == ["a", 1, 2]

    async def test_coro_eager(self):
        log = []
        future = asynkit.coro_eager(self.coro1(log))
        log.append("a")
        await future
        assert log == [1, "a", 2]

    async def test_func_eager(self):
        log = []
        future = self.coro2(log)
        log.append("a")
        await future
        assert log == [1, "a", 2]

    async def test_eager(self):
        """Test the `coro` helper, used both as wrapper and decorator"""
        log = []
        future = asynkit.eager(self.coro1(log))
        log.append("a")
        await future
        assert log == [1, "a", 2]
        log = []
        future = self.coro3(log)
        log.append("a")
        await future
        assert log == [1, "a", 2]

    async def test_eager_noblock(self):
        """Test `eager` when coroutine does not block"""
        log = []
        future = asynkit.eager(self.coro4(log))
        log.append("a")
        await future
        assert log == [1, 2, "a"]

    async def test_eager_future(self):
        log = []
        awaitable = asynkit.eager(self.coro4(log))
        assert inspect.isawaitable(awaitable)
        assert asyncio.isfuture(awaitable)
        await awaitable

    async def test_eager_exception_nonblocking(self):
        log = []
        awaitable = asynkit.eager(self.coro5(log))
        assert log == [1]
        with pytest.raises(RuntimeError):
            await awaitable

    async def test_eager_exception_blocking(self):
        log = []
        awaitable = asynkit.eager(self.coro6(log))
        assert log == [1]
        with pytest.raises(RuntimeError):
            await awaitable
        assert log == [1, 2]

    def test_eager_invalid(self):
        with pytest.raises(TypeError):
            asynkit.eager(self)

    async def test_coro_start(self):
        log = []
        cs = asynkit.CoroStart(self.coro1(log), auto_start=False)
        cs.start()
        assert cs.is_suspended()
        log.append("a")
        await cs.as_future()
        assert log == [1, "a", 2]

    async def test_coro_start_autostart(self):
        log = []
        cs = asynkit.CoroStart(self.coro1(log))
        assert cs.is_suspended()
        log.append("a")
        await cs.as_future()
        assert log == [1, "a", 2]


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
