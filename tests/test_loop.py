from collections import deque
import asyncio
import pytest
import asynkit


class TestReadyRotate:
    """
    Test that tasks, ready to execute, can be rotated in the ready queue
    using the ready_rotate() loop method
    """

    async def simple(self, arg):
        self.log.append(arg)

    async def tasks(self, n=3):
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_len() == 0

        self.log = []
        self.tasks = [asyncio.create_task(self.simple(k)) for k in range(n)]
        return list(range(n))

    async def gather(self):
        await asyncio.gather(*self.tasks)
        return self.log

    def rotate(self, l, r):
        d = deque(l)
        d.rotate(r)
        return list(d)

    async def test_three_normal(self):
        log0 = await self.tasks()
        assert await self.gather() == log0

    async def test_two_shift_one(self):
        log0 = await self.tasks()
        asyncio.get_running_loop().ready_rotate(1)
        assert await self.gather() == self.rotate(log0, 1)

    @pytest.mark.parametrize("shift", [-3, -2, -1, 0, 1, 2, 3])
    async def test_five_multi(self, shift):
        log0 = await self.tasks(5)
        asyncio.get_running_loop().ready_rotate(shift)
        assert await self.gather() == self.rotate(log0, shift)


class TestCallInsertReady:
    """
    Test that we can insert callbacks at given places in the runnable
    queue.  Compare the order of execution with a list that has been
    similarly inserted into via list.insert()
    """

    def add_insert(self, pos, label):
        def callback():
            self.log.append(label)

        asyncio.get_running_loop().call_insert(pos, callback)

    def prepare(self, n=3):
        self.log = []
        self.tasks = [asyncio.create_task(self.simple(k)) for k in range(n)]
        return list(range(n))

    @pytest.mark.parametrize("count", [1, 2, 6])
    async def test_normal(self, count):
        self.log = []
        expect = []
        perm = list(range(count))
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect

    @pytest.mark.parametrize("count", [2, 6])
    async def test_reverse(self, count):
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_len() == 0

        self.log = []
        expect = []
        perm = list(range(count))
        perm.reverse()
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect

    @pytest.mark.parametrize("count", [2, 6])
    async def test_cut(self, count):
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_len() == 0
        self.log = []
        expect = []
        perm = list(range(count))
        perm = perm[len(perm) // 2 :] + perm[: len(perm) // 2]
        perm.reverse()
        for i, pos in enumerate(perm):
            self.add_insert(pos, i)
            expect.insert(pos, i)
        await asyncio.sleep(0)
        assert self.log == expect


@pytest.mark.parametrize("count", [2, 6])
async def test_ready_len(count):
    # proactor loop may start out with a propactor task in place.
    # flush it.
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0

    for i in range(count):

        async def foo():
            pass

        asyncio.create_task(foo())

    assert asyncio.get_running_loop().ready_len() == count
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0


@pytest.mark.parametrize("pos", [0, 1, 3])
async def test_sleep_insert(pos):
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0
    log = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        asyncio.create_task(foo(i))

    assert asyncio.get_running_loop().ready_len() == 6
    await asynkit.sleep_insert(pos)
    assert asyncio.get_running_loop().ready_len() == 6 - pos
    log.append("me")
    await asyncio.sleep(0)

    expect = list(range(6))
    expect.insert(pos, "me")
    assert log == expect


@pytest.mark.parametrize("pos", [0, 1, 6])
async def test_task_reinsert(pos):
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0
    log = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        asyncio.create_task(foo(i))

    asynkit.task_reinsert(pos)
    await asyncio.sleep(0)

    expect = list(range(6))
    p = expect.pop(-1)
    expect.insert(pos, p)
    assert log == expect


class TestReadyPopInsert:
    """
    Test popping from and inserting into the ready queue
    """

    async def simple(self, arg):
        self.log.append(arg)

    async def tasks(self, n=3):
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_len() == 0

        self.log = []
        self.tasks = [asyncio.create_task(self.simple(k)) for k in range(n)]
        return list(range(n))

    async def gather(self):
        await asyncio.gather(*self.tasks)
        return self.log

    @pytest.mark.parametrize("source,destination", [(0, 4), (-1, 2), (3, 3), (-2, 2)])
    async def test_pop_insert(self, source, destination):
        log0 = await self.tasks(5)
        loop = asyncio.get_running_loop()
        len = loop.ready_len()
        tmp = loop.ready_pop(source)
        assert loop.ready_len() == len - 1
        loop.ready_insert(destination, tmp)
        assert loop.ready_len() == len

        # manually manipulate our reference list
        log0.insert(destination, log0.pop(source))
        assert await self.gather() == log0


class TestRegularLoop:
    """
    Test that we get AttributeErrors when using scheduling functions on an eventloop that does
    not support scheduling
    """

    @pytest.fixture
    def event_loop(request):
        loop = asyncio.SelectorEventLoop()
        try:
            yield loop
        finally:
            loop.close()

    async def test_sleep_insert(self):
        with pytest.raises(AttributeError):
            await asynkit.sleep_insert(0)

    async def test_task_reinsert(self):
        async def foo():
            return None

        with pytest.raises(AttributeError):
            task = asyncio.create_task(foo())
            asynkit.task_reinsert(0)
            await task

    async def test_create_task_descend(self):
        async def foo():
            return None

        with pytest.raises(AttributeError):
            await asynkit.create_task_descend(foo())
