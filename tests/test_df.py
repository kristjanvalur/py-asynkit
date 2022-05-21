import asyncio
import inspect
import pytest

import asynkit


@pytest.fixture
def event_loop():
    loop = asynkit.DefaultSchedulingEventLoop()
    yield loop
    loop.close()


@pytest.mark.parametrize("method", ["nostart", "start", "descend", "eager"])
class TestCreateTask:

    delay = 0.01
    error = False

    # three async methods to "start" the coroutine in various ways
    async def nostart(self, coro):
        return coro

    async def start(self, coro):
        return await asynkit.create_task_start(coro)

    async def descend(self, coro):
        return await asynkit.create_task_descend(coro)

    async def eager(self, coro):
        return asynkit.coro_eager(coro)

    def setup(self, method):
        self.method = method
        if method == "nostart":
            self.convert = self.nostart
            self.getlog = self.normal_log
        elif method == "start":
            self.convert = self.start
            self.getlog = self.df_log
        elif method == "descend":
            self.convert = self.descend
            self.getlog = self.df_log
        elif method == "eager":
            self.convert = self.eager
            self.getlog = self.df_log

    # generate logs based on normal, and depth-first behaviour
    def normal_log(self, max_depth, log, depth=0, label="0"):
        """
        The log as it would appear if the tasks are just awaited
        normally and no Tasks created.
        """
        log.append(label + "a")
        if depth == max_depth:
            log.append(label + "B")
            log.append(label + "c")
        else:
            log.append(label + "b")
            self.normal_log(max_depth, log, depth + 1, label + ":0")
            self.normal_log(max_depth, log, depth + 1, label + ":1")
            log.append(label + "c")

    def df_log(self, max_depth, log, depth=0, label="0", part=0):
        if part == 0:
            log.append(label + "a")
            if depth == max_depth:
                log.append(label + "B")
            else:
                self.df_log(max_depth, log, depth + 1, label + ":0")
                self.df_log(max_depth, log, depth + 1, label + ":1")
                log.append(label + "b")
        if part == 1:
            log.append(label + "c")
        if depth == 0:
            self.df_log(max_depth, log, depth + 1, label + ":1", part=1)
            self.df_log(max_depth, log, depth + 1, label + ":0", part=1)
            log.append(label + "c")

    def splitlog(self, log):
        """
        return just the first part of log, down to the part
        where the top level starts awating for low levels.
        this avoids testing the latter part of the logs which
        is subject to scheduling randomness.
        """
        return log[0 : log.index("0b") + 1]

    async def recursive(self, max_depth, log, depth=0, label="0"):
        """
        A faux task, recursively creating two new tasks, converting them
        and waiting for them.  At the bottom, the tasks sleep for a bit.
        They append their execution order to a log.
        """
        log.append(label + "a")
        try:
            if depth == max_depth:
                log.append(label + "B")
                await asyncio.sleep(self.delay)
                if self.error:
                    1 / 0
                else:
                    return [label]
            else:
                # create two child requests and "convert" them
                a = self.recursive(max_depth, log, depth + 1, label + f":0")
                a = await self.convert(a)
                b = self.recursive(max_depth, log, depth + 1, label + f":1")
                b = await self.convert(b)

                # we don't use gather here, because the use case is to do processing
                # and use the results from a or b only when actually needed.
                log.append(label + "b")
                return await a + await b
        finally:
            log.append(label + "c")

    async def test_okay_one(self, method):
        self.setup(method)
        log = []
        r = await self.recursive(1, log)
        log2 = []
        self.getlog(1, log2)
        assert self.splitlog(log) == self.splitlog(log2)

    async def test_okay_two(self, method):
        self.setup(method)
        log = []
        r = await self.recursive(2, log)
        log2 = []
        self.getlog(2, log2)
        if method != "start":
            assert self.splitlog(log) == self.splitlog(log2)
        else:
            # for start, the log order is neither 'normal' nor 'depth-first'
            log2 = []
            assert self.splitlog(log) != self.normal_log(2, log2)
            log2 = []
            assert self.splitlog(log) != self.df_log(2, log2)


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
        