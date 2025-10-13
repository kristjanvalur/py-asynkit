import asyncio

import pytest

import asynkit

from .conftest import SchedulingEventLoopPolicy, make_loop_factory

"""
Test depth-first coroutine execution behaviour, both with create_task_descend and eager
"""

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend(request):
    policy = SchedulingEventLoopPolicy(request)
    return ("asyncio", {"loop_factory": make_loop_factory(policy)})


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

    def setup_method(self, method):
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

    def splitlog(self, log, item="0b"):
        """
        return just the first part of log, down to the part
        where the top level starts awating for low levels.
        this avoids testing the latter part of the logs which
        is subject to scheduling randomness.
        """
        return log[0 : log.index(item) + 1]

    async def recursive(self, max_depth, log, depth=0, label="0"):
        """
        A faux task, recursively creating two new tasks, converting them
        and waiting for them. At the bottom, the tasks sleep for a bit.
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
                a = self.recursive(max_depth, log, depth + 1, label + ":0")
                a = await self.convert(a)
                b = self.recursive(max_depth, log, depth + 1, label + ":1")
                b = await self.convert(b)

                # we don't use gather here, because the use case is to do processing
                # and use the results from a or b only when actually needed.
                log.append(label + "b")
                return await a + await b
        finally:
            log.append(label + "c")

    async def test_okay_one(self, method):
        self.setup_method(method)
        log = []
        await self.recursive(1, log)
        log2 = []
        self.getlog(1, log2)
        assert self.splitlog(log) == self.splitlog(log2)

    async def test_okay_two(self, method):
        self.setup_method(method)
        log = []
        await self.recursive(2, log)
        log2 = []
        self.getlog(2, log2)
        if method == "descend":
            # task order becomes uncertain on unwind,
            # split by 0:1:1B until we understand why
            item = "0:1:1B"
            assert self.splitlog(log, item) == self.splitlog(log2, item)
        elif method != "start":
            assert self.splitlog(log) == self.splitlog(log2)
        else:
            # for start, the log order is neither 'normal' nor 'depth-first'
            log2 = []
            assert self.splitlog(log) != self.normal_log(2, log2)
            log2 = []
            assert self.splitlog(log) != self.df_log(2, log2)
