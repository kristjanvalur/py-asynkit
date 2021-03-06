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
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    asynkit.task_reinsert(tasks[-1], pos)
    await asyncio.sleep(0)

    expect = list(range(6))
    p = expect.pop(-1)
    expect.insert(pos, p)
    assert log == expect


async def test_task_reinsert_blocked():
    async def foo():
        await asyncio.sleep(0.1)

    task = asyncio.create_task(foo())
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        asynkit.task_reinsert(task, 0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("pos", [0, 1, 3, 5])
async def test_task_switch(pos):
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0
    log = []
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    assert len(log) == 0
    await asynkit.task_switch(tasks[pos])
    log.append("me")
    await asyncio.sleep(0)
    assert len(log) == 7

    expect = list(range(6))
    p = expect.pop(pos)
    expect.insert(0, pos)
    expect.append("me")
    assert log == expect


@pytest.mark.parametrize("pos", [0, 1, 3, 5])
async def test_task_switch_insert(pos):
    await asyncio.sleep(0)
    assert asyncio.get_running_loop().ready_len() == 0
    log = []
    tasks = []
    for i in range(6):

        async def foo(n):
            log.append(n)

        tasks.append(asyncio.create_task(foo(i)))

    assert len(log) == 0
    await asynkit.task_switch(tasks[pos], sleep_pos=1)
    log.append("me")
    await asyncio.sleep(0)
    assert len(log) == 7

    expect = list(range(6))
    p = expect.pop(pos)
    expect.insert(0, pos)
    expect.insert(1, "me")
    assert log == expect


async def test_task_switch_notfound():
    async def foo():
        pass

    task = asyncio.create_task(foo())
    loop = asyncio.get_running_loop()
    item = loop.ready_pop(loop.ready_find_task(task))
    with pytest.raises(ValueError):
        await asynkit.task_switch(task)
    loop.ready_append(item)


async def test_task_switch_blocked():
    async def foo():
        await asyncio.sleep(0.01)

    task = asyncio.create_task(foo())
    # make it settle on its sleep
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        await asynkit.task_switch(task)
    await task


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


class TestTasks:
    async def foo(self, sleeptime):
        await asyncio.sleep(sleeptime)

    def tasks(self, sleeptime=0):
        return [asyncio.create_task(self.foo(sleeptime)) for _ in range(4)]

    def identity(self, loop=None):
        all = asyncio.all_tasks(loop)
        all2 = (
            asynkit.runnable_tasks(loop)
            | asynkit.blocked_tasks(loop)
            | {asyncio.current_task(loop)}
        )
        assert all == all2

    async def test_find_task(self):
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        n = loop.ready_len()
        tasks = self.tasks()
        for i, t in enumerate(tasks):
            assert loop.ready_find_task(t) == i + n

        async def foo():
            pass

        task = asyncio.create_task(foo())
        item = loop.ready_pop(-1)
        assert loop.ready_find_task(task) == -1
        loop.ready_append(item)

    async def test_get_task(self):
        tasks = self.tasks()
        loop = asyncio.get_running_loop()
        tasks2 = loop.ready_get_tasks()

        # sort by position for safety
        tasks2.sort(key=lambda t: t[1])

        tasks3 = [t for t, _ in tasks2]
        assert tasks3 == tasks

    async def test_runnable_tasks(self):
        tasks = self.tasks()
        tasks2 = asynkit.runnable_tasks()
        assert set(tasks) == tasks2
        self.identity()

        # get them settled on their sleep
        await asyncio.sleep(0)
        assert set(tasks) == asynkit.runnable_tasks()
        self.identity()

        # make them return from sleep
        await asyncio.sleep(0)
        assert asynkit.runnable_tasks() == set()

    async def test_blocked_tasks(self):
        self.identity()
        tasks = self.tasks(0.1)
        self.identity()
        await asyncio.sleep(0)  # make our tasks blocked on the sleep
        tasks2 = asynkit.blocked_tasks()
        assert tasks2 == set(tasks)
        self.identity()
        assert asynkit.runnable_tasks() == set()
        self.identity()
        for task in tasks:
            task.cancel()
        self.identity()


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
            asynkit.task_reinsert(task, 0)
            await task

    async def test_create_task_descend(self):
        async def foo():
            return None

        with pytest.raises(AttributeError):
            await asynkit.create_task_descend(foo())


class TestTaskIsBlocked:
    async def test_blocked_sleep(self):
        async def foo():
            await asyncio.sleep(0.1)

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        assert asynkit.task_is_runnable(task)

        # settle on the sleep
        await asyncio.sleep(0)
        assert asynkit.task_is_blocked(task)
        assert not asynkit.task_is_runnable(task)
        task.cancel()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()
        assert not asynkit.task_is_blocked(task)
        assert not asynkit.task_is_runnable(task)

    async def test_blocked_future(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_find_task(task) == -1
        assert asynkit.task_is_blocked(task)

        task.cancel()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_blocked_future_result(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_find_task(task) == -1
        assert asynkit.task_is_blocked(task)

        fut.set_result(None)
        assert asyncio.get_running_loop().ready_find_task(task) >= 0
        assert not asynkit.task_is_blocked(task)
        await task

    async def test_blocked_future_exception(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_find_task(task) == -1
        assert asynkit.task_is_blocked(task)

        fut.set_exception(ZeroDivisionError())
        assert asyncio.get_running_loop().ready_find_task(task) >= 0
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(ZeroDivisionError):
            await task

    async def test_blocked_future_cancel(self):
        fut = asyncio.Future()

        async def foo():
            await fut

        task = asyncio.create_task(foo())
        assert not asynkit.task_is_blocked(task)
        # settle on the await
        await asyncio.sleep(0)
        assert asyncio.get_running_loop().ready_find_task(task) == -1
        assert asynkit.task_is_blocked(task)

        fut.cancel()
        assert asyncio.get_running_loop().ready_find_task(task) >= 0
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_blocked_await(self):
        # Test a task, blocked waiting for another blocked task
        async def foo():
            await asyncio.sleep(0.1)

        async def bar(task):
            await task

        task2 = asyncio.create_task(foo())
        task = asyncio.create_task(bar(task2))
        assert not asynkit.task_is_blocked(task)

        # settle on the sleep
        await asyncio.sleep(0)
        assert asynkit.task_is_blocked(task)
        assert asynkit.task_is_blocked(task2)
        # cancel the second task.  But the awaiting task doesn't become unblocked
        # befre the second task has had a chance to finish, by being run for a bit.
        task2.cancel()
        assert not asynkit.task_is_blocked(task2)
        assert not task2.done()
        # task is still blocked
        assert asynkit.task_is_blocked(task)
        assert asyncio.get_running_loop().ready_find_task(task) == -1

        # give task2 a chance to finish, unblocking task
        await asyncio.sleep(0)
        assert task2.done()
        assert not task.done()
        assert not asynkit.task_is_blocked(task)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()
        assert not asynkit.task_is_blocked(task)


def test_event_loop_policy_context():
    with asynkit.event_loop_policy() as a:
        assert isinstance(a, asynkit.SchedulingEventLoopPolicy)

        async def foo():
            assert isinstance(asyncio.get_running_loop(), asynkit.SchedulingMixin)

        asyncio.run(foo())
