import asyncio
import inspect
import pytest
import asynkit


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
