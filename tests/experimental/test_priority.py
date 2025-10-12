import asyncio
import random
from unittest.mock import Mock

import pytest

from asynkit.experimental.priority import (
    DefaultPriorityEventLoop,
    PosPriorityQueue,
    PriorityCondition,
    PriorityLock,
    PriorityTask,
)

from ..conftest import make_loop_factory

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    policy = asyncio.DefaultEventLoopPolicy()
    return "asyncio", {"loop_factory": make_loop_factory(policy)}


class TestPriorityLock:
    async def test_lock_effective_priority(self):
        """
        Test that a priority lock correctly assumes the priority of the waiting tasks
        """

        lock = PriorityLock()

        async def do_something():
            await lock.acquire()
            await asyncio.sleep(0.1)
            lock.release()

        async with lock:
            assert lock.effective_priority() is None

            task1 = asyncio.Task(do_something())
            await asyncio.sleep(0)
            assert lock.effective_priority() == 0

            task2 = PriorityTask(do_something())
            task2.priority_value = -1
            await asyncio.sleep(0)
            assert lock.effective_priority() == -1

            task3 = PriorityTask(do_something())
            task3.priority_value = -2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2

            task4 = PriorityTask(do_something())
            task4.priority_value = 2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2

        await asyncio.gather(task1, task2, task3, task4)
        assert lock.effective_priority() is None

    @pytest.mark.parametrize("tasktype", [PriorityTask, asyncio.Task])
    async def test_lock_scheduling(self, tasktype):
        """Test that tasks acquire lock in order of priority"""
        lock = PriorityLock()
        results = []

        async def doit(i):
            async with lock:
                results.append(i)

        async with lock:
            values = list(range(20))
            random.shuffle(values)
            if tasktype is PriorityTask:
                tasks = [PriorityTask(doit(i), priority=i) for i in values]
            else:
                tasks = [asyncio.Task(doit(i)) for i in values]
            await asyncio.sleep(0.001)
            assert results == []

        await asyncio.gather(*tasks)
        if tasktype is PriorityTask:
            assert results == list(range(20))
        else:
            assert results != list(range(20))

    async def test_lock_cancel(self):
        """Test that cancellation logic is correct"""
        lock = PriorityLock()
        results = []

        async def doit(i):
            try:
                async with lock:
                    results.append(i)
            except asyncio.CancelledError:
                pass

        async with lock:
            values = list(range(20))
            random.shuffle(values)
            tasks = [(PriorityTask(doit(i), priority=i), i) for i in values]
            await asyncio.sleep(0.001)
            assert results == []
            task1, i = tasks[8]
            task2, j = tasks[12]
            task1.cancel()
            await asyncio.sleep(0.001)
            task2.cancel()

        expect = list(range(20))
        expect.remove(i)
        expect.remove(j)
        await asyncio.gather(*(task for (task, i) in tasks))
        assert results == expect


class TestPriorityCondition:
    @pytest.mark.parametrize("tasktype", [PriorityTask, asyncio.Task])
    @pytest.mark.parametrize("locktype", [PriorityLock, asyncio.Lock])
    async def test_notify_scheduling(self, tasktype, locktype):
        """Test that tasks are notified in order of priority"""
        lock = locktype()
        cond = PriorityCondition(lock)
        results = []
        wake = False

        async def doit(i):
            async with cond:
                await cond.wait_for(lambda: wake)
                results.append(i)
                cond.notify(1)

        values = list(range(20))
        random.shuffle(values)
        if tasktype is PriorityTask:
            tasks = [PriorityTask(doit(i), priority=i) for i in values]
        else:
            tasks = [asyncio.Task(doit(i)) for i in values]
        await asyncio.sleep(0.001)
        assert results == []
        async with cond:
            wake = True
            cond.notify(1)

        await asyncio.gather(*tasks)
        if tasktype is PriorityTask:
            assert results == list(range(20))
        else:
            assert results != list(range(20))

    async def test_notify_cancel(self):
        """Test that cancellation logic is correct"""
        cond = PriorityCondition()
        results = []
        wake = False

        async def doit(i):
            try:
                async with cond:
                    await cond.wait_for(lambda: wake)
                    results.append(i)
                    cond.notify(1)
            except asyncio.CancelledError:
                pass

        values = list(range(20))
        random.shuffle(values)
        tasks = [(PriorityTask(doit(i), priority=i), i) for i in values]
        await asyncio.sleep(0.001)
        assert results == []
        async with cond:
            task, i = tasks[10]
            task.cancel()
            wake = True
            cond.notify()

        await asyncio.gather(*(task for (task, i) in tasks))
        expect = list(range(i)) + list(range(i + 1, 20))
        assert results == expect


async def test_priority_inheritance():
    """
    Test that a priority task correctly inherits the priority of a held
    lock.
    """

    lock = PriorityLock()

    async def do_something():
        await lock.acquire()
        await asyncio.sleep(0.1)
        lock.release()

    async def taskfunc():
        task = asyncio.current_task()
        assert task.effective_priority() == 1

        async with lock:
            assert lock.effective_priority() is None

            task1 = asyncio.Task(do_something())
            await asyncio.sleep(0)
            assert lock.effective_priority() == 0
            assert task.effective_priority() == 0

            task2 = PriorityTask(do_something())
            task2.priority_value = -1
            await asyncio.sleep(0)
            assert lock.effective_priority() == -1
            assert task.effective_priority() == -1

            task3 = PriorityTask(do_something())
            task3.priority_value = -2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2
            assert task.effective_priority() == -2

            task4 = PriorityTask(do_something())
            task4.priority_value = 2
            await asyncio.sleep(0)
            assert lock.effective_priority() == -2
            assert task.effective_priority() == -2

        await asyncio.gather(task1, task2, task3, task4)
        assert lock.effective_priority() is None
        assert task.effective_priority() == 1

    task = PriorityTask(taskfunc(), priority=1)
    await task


async def test_priority_reschedule():
    """
    Test that a holding task gets a reschedule call when a possibly
    higher priority task starts waiting
    """

    lock = PriorityLock()

    async def do_something():
        await lock.acquire()
        await asyncio.sleep(0.1)
        lock.release()

    async def taskfunc():
        task = asyncio.current_task()
        assert task.get_effective_priority() == 1

        async with lock:
            assert lock.effective_priority() is None

            with Mock.object(task, "reschedule") as mock:
                mock.return_value = True
                asyncio.Task(do_something())
                await asyncio.sleep(0)  # we remain runnable
                assert lock.effective_priority() == 0
                assert task.get_effective_priority() == 0

                assert mock.called


class PriorityObject:
    def __init__(self, priority):
        self.priority = priority

    def __repr__(self):
        return f"PriorityObject({self.priority})"


def priority_key(obj):
    return obj.priority


class TestPosPriorityQueue:
    def test_append(self):
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            assert not queue
            for o in obj:
                queue.append(o)
            assert queue

            assert len(queue) == 3
            assert queue.popleft() is obj1
            assert queue.popleft() is obj2
            assert queue.popleft() is obj3
            pytest.raises(IndexError, queue.popleft)

    def test_append_pri(self):
        """Test that we can specify priority when appending"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = list(enumerate(reversed([obj1, obj2, obj3])))
            random.shuffle(obj)
            for i, o in obj:
                queue.append_pri(o, i)

            assert len(queue) == 3
            assert queue.popleft() is obj3
            assert queue.popleft() is obj2
            assert queue.popleft() is obj1
            pytest.raises(IndexError, queue.popleft)

    def test_fifo(self):
        """Verify that same priority gets FIFO ordering"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj1a = PriorityObject(1)
        obj2a = PriorityObject(2)
        obj3a = PriorityObject(3)

        for i in range(5):
            assert len(queue) == 0
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            obj = [obj1a, obj2a, obj3a]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            assert len(queue) == 6
            assert queue.popleft() is obj1
            assert queue.popleft() is obj1a
            assert queue.popleft() is obj2
            assert queue.popleft() is obj2a
            assert queue.popleft() is obj3
            assert queue.popleft() is obj3a
            pytest.raises(IndexError, queue.popleft)

    def test_priority_iter(self):
        """Verify that iteration returns items in priority order"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            assert len(queue) == 0
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            itered = list(queue)
            popped = [queue.popleft() for i in range(3)]
            assert itered == popped

    def test_insert_pos(self):
        """Verify that we can insert at a specific position"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj4 = PriorityObject(4)

        for i in range(2):
            for pos in range(5):
                assert len(queue) == 0
                obj = [obj1, obj2, obj3]
                random.shuffle(obj)
                for o in obj:
                    queue.append(o)
                queue.insert(pos, obj4)

                itered = list(queue)
                queue.clear()
                expected = [obj1, obj2, obj3]
                expected.insert(pos, obj4)
                assert itered == expected

    def test_insert_pos2(self):
        """Verify that we can insert two at specific positions"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj4 = PriorityObject(4)
        obj5 = PriorityObject(5)

        for pos in range(5):
            for pos2 in range(6):
                assert len(queue) == 0
                obj = [obj1, obj2, obj3]
                random.shuffle(obj)
                for o in obj:
                    queue.append(o)
                queue.insert(pos, obj4)
                queue.insert(pos2, obj5)

                itered = list(queue)
                queue.clear()
                expected = [obj1, obj2, obj3]
                expected.insert(pos, obj4)
                expected.insert(pos2, obj5)
                assert itered == expected

    def test_find(self):
        """Verify that iteration returns items in priority order"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj4 = PriorityObject(4)

        for i in range(3):
            assert len(queue) == 0
            obj = [obj1, obj2, obj3, obj4]
            for i in range(1, 5):
                obj.append(PriorityObject(i))
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            def getkey(obj):
                return lambda k: k is obj

            assert queue.find(getkey(obj1)) is obj1
            assert queue.find(getkey(obj2)) is obj2
            assert queue.find(getkey(obj2)) is obj2
            assert queue.find(getkey(obj3), remove=True) is obj3

            assert queue.find(getkey(obj3), remove=True) is None

            pri5 = PriorityObject(5)
            queue.insert(1, pri5)
            pris = [o.priority for o in queue]
            expected = [1, 5]
            assert pris[:2] == expected

            assert queue.find(getkey(pri5), remove=True) is pri5

            itered = list(queue)
            pris = [o.priority for o in itered]
            expected = [1, 1, 2, 2, 3, 4, 4]
            assert pris == expected
            for obj in itered:
                assert queue.find(getkey(obj), remove=True) is obj
            assert len(queue) == 0

    def test_reschedule(self):
        """Verify that iteration returns items in priority order"""
        queue = PosPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj4 = PriorityObject(4)

        for i in range(3):
            queue.clear()
            assert len(queue) == 0
            obj = [obj1, obj2, obj3, obj4]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)
            for o in obj:
                queue.append(PriorityObject(o.priority))

            def getkey(obj):
                return lambda k: k is obj

            assert len(queue) == 8
            objs = list(queue)
            assert objs[4] is obj3

            assert len(queue) == 8
            queue.reschedule(getkey(obj3), 7)
            objs = list(queue)
            assert objs[-1] is obj3

            assert len(queue) == 8
            found = queue.reschedule(getkey(obj3), -1)
            assert found == obj3
            objs = list(queue)
            assert objs[0] is obj3

            assert len(queue) == 8
            pris = [o.priority for o in objs]
            assert pris == [3, 1, 1, 2, 2, 3, 4, 4]
            queue.reschedule(getkey(obj3), 3)
            objs = list(queue)
            # assert obj3 in (objs[4], objs[5]) # exact order within
            # the same priority level is not defined.
            pris = [o.priority for o in objs]
            assert pris == [1, 1, 2, 2, 3, 3, 4, 4]

            # reschedule to same priority
            queue.reschedule(getkey(obj3), 3)

            # pop first value and try to reschedule a popped value
            obj = queue.popleft()
            found = queue.reschedule(getkey(obj), 3)
            assert found is None

    def test_reschedule_all(self):
        """Verify that we can reschedule all items in a priority deque"""
        queue = PosPriorityQueue(priority_key)

        queue.clear()
        obj = [PriorityObject(random.randint(0, 5)) for i in range(50)]
        pris = [o.priority for o in obj]
        for o in obj:
            queue.append(o)

        objs = list(queue)
        pris2 = [o.priority for o in objs]
        assert pris2 == sorted(pris)

        # reverse the priorityes
        for o in obj:
            o.oldpri = o.priority
            o.priority = -o.oldpri

        objs = list(queue)
        pris2 = [-o.priority for o in objs]
        assert pris2 == sorted(pris)

        queue.reschedule_all()

        objs = list(queue)
        pris2 = [-o.priority for o in objs]
        assert pris2 == list(reversed(sorted(pris)))

        # add an immediate dude
        queue.insert(0, PriorityObject(100))
        objs = list(queue)
        pris2 = [-o.priority for o in objs]
        assert pris2 == [-100] + list(reversed(sorted(pris)))

        # reverse the priorites back
        for o in obj:
            o.oldpri = o.priority
            o.priority = -o.oldpri

        queue.reschedule_all()
        objs = list(queue)
        pris2 = [o.priority for o in objs]
        assert pris2 == [100] + (sorted(pris))

    def test_maintenance_rate(self):
        """Verify that mainenance kicks in and is roughly O(1)"""
        random.seed(0)
        nm = 0
        tm = 0

        def mock_maintenance():
            nonlocal nm, tm
            nm += 1
            tm += len(q._pq)

        q = PosPriorityQueue(priority_key)
        q.do_maintenance = mock_maintenance
        total = 0
        maxlen = 0
        for i in range(1000):
            for i in range(random.randrange(1, 20)):
                q.append(PriorityObject(random.random()))
                total += 1
                maxlen = max(maxlen, len(q))
            for i in range(random.randrange(1, 20)):
                if len(q):
                    q.popleft()
        while len(q):
            q.popleft()

        print(f"maxlen: {maxlen}, total: {total}, nm: {nm}, tm: {tm}")
        # assert that it is roughly O(1)
        assert total * 0.5 < tm < total * 1.5

    def test_priority_boost(self):
        """Test that priority boost works"""
        # We have a queue of 100 random priority items.  We pop and insert
        # items until we have seen all items.abs
        # without priority boost, we would always see the same item.  Priority
        # boost shoudl ensure that all items eventually pass through the queue.
        pris = set(PriorityObject(random.random()) for i in range(100))
        q = PosPriorityQueue(priority_key)
        for p in pris:
            q.append(p)

        found = set()
        for i in range(100000):
            popped = q.popleft()
            found.add(popped)
            if len(found) == len(pris):
                break
            q.append(popped)

        assert i < 100000
        assert found == pris


# loop policy for pytest-anyio plugin
class PriorityEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def __init__(self, request):
        super().__init__()
        self.request = request

    def new_event_loop(self):
        return DefaultPriorityEventLoop()


class TestPriorityScheduling:
    @pytest.fixture
    def anyio_backend(self, request):
        policy = PriorityEventLoopPolicy(request)
        return ("asyncio", {"loop_factory": make_loop_factory(policy)})

    async def await_tasks(self):
        async def nothing():
            pass

        final_task = PriorityTask(nothing(), priority=1000)
        await final_task

    async def test_create_event_loop(self):
        loop = asyncio.get_running_loop()
        assert isinstance(loop, DefaultPriorityEventLoop)
        assert loop._ready is loop.ready_queue

    async def test_simple_task(self):
        async def taskfunc():
            await asyncio.sleep(0.001)
            await asyncio.sleep(0)
            return 1

        task = asyncio.create_task(taskfunc())
        assert await task == 1

    async def test_priority_tasks(self):
        finished = []

        async def taskfunc(pri):
            finished.append(pri)

        for i in range(20):
            pri = random.randint(-5, 5)
            PriorityTask(taskfunc(pri), priority=pri)

        await self.await_tasks()
        assert len(finished) == 20
        assert finished == sorted(finished)

    async def test_priority_tasks_same(self):
        """Test that same priority tasks are scheduled in FIFO order"""

        finished = []

        async def taskfunc(pri, i):
            finished.append((pri, i))

        for i in range(40):
            pri = random.randint(-5, 5)
            PriorityTask(taskfunc(pri, i), priority=pri)

        await self.await_tasks()
        assert len(finished) == 40
        assert finished == sorted(finished)

    async def test_priority_tasks_reschedule(self):
        """Test that we can reschedule a task to be ahead of others"""
        finished = []
        alltasks = []

        async def taskfunc(pri, i):
            finished.append((pri, i))

        for i in range(40):
            pri = random.randint(-5, 5)
            t = PriorityTask(taskfunc(pri, i), priority=pri)
            alltasks.append((t, pri, i))

        # make the first task have lowest priority, and the last task highest
        alltasks[0][0].priority_value = 10
        alltasks[0][0].propagate_priority(None)
        alltasks[-1][0].priority_value = -10
        alltasks[-1][0].propagate_priority(None)

        await self.await_tasks()
        assert len(finished) == 40
        first = finished.pop(0)
        last = finished.pop(-1)
        assert first[1] == 39
        assert last[1] == 0

        assert finished == sorted(finished)

    async def test_priority_inversion(self):
        """Test that a high priority task can run before a low priority task"""

        finished = []
        priorities = []

        lock = PriorityLock()
        event = asyncio.Event()

        async def lowpri():
            # get lock and wait
            async with lock:
                await event.wait()
                finished.append("low")
                priorities.append(asyncio.current_task().effective_priority())

        async def highpri():
            # wait for the event and then get the lock
            await event.wait()
            async with lock:
                finished.append("high")
                priorities.append(asyncio.current_task().effective_priority())

        async def medpri():
            # just wait for the event
            await event.wait()
            finished.append("med")
            priorities.append(asyncio.current_task().effective_priority())

        # test without the high priority task
        t1 = PriorityTask(lowpri(), priority=1)
        t2 = PriorityTask(medpri(), priority=0)
        await self.await_tasks()
        event.set()
        await asyncio.gather(t1, t2)
        # medium priority task will run first
        assert finished == ["med", "low"]
        assert priorities == [0, 1]

        # now the same, but with the high priority task waitint thfor the lock that
        # "low" awaits:
        event.clear()
        finished = []
        priorities = []
        t1 = PriorityTask(lowpri(), priority=1)
        t2 = PriorityTask(highpri(), priority=-1)
        t3 = PriorityTask(medpri(), priority=0)
        await self.await_tasks()
        event.set()
        await asyncio.gather(t1, t2, t3)
        # low priority task now runs first (inherits priority of the high pri task)
        assert finished == ["low", "high", "med"]
        assert priorities == [-1, -1, 0]

    async def test_priority_inversion2(self):
        """Test that a high priority task can run before a low priority task.
        An extra lock is involved."""

        finished = []
        priorities = []

        lock1 = PriorityLock()
        lock2 = PriorityLock()
        event = asyncio.Event()

        async def lowpri1():
            # get lock and wait
            async with lock2:
                await event.wait()
                finished.append("low1")
                priorities.append(asyncio.current_task().effective_priority())

        async def lowpri2():
            # get lock and wait
            async with lock1:
                # lock2 is blocked by lowpri1
                async with lock2:
                    finished.append("low2")
                    priorities.append(asyncio.current_task().effective_priority())

        async def highpri():
            # wait for the event and then get the lock
            await event.wait()
            async with lock1:
                finished.append("high")
                priorities.append(asyncio.current_task().effective_priority())

        async def medpri():
            # just wait for the event
            await event.wait()
            finished.append("med")
            priorities.append(asyncio.current_task().effective_priority())

        # test without the high priority task
        t1 = PriorityTask(lowpri1(), priority=1)
        t2 = PriorityTask(lowpri2(), priority=1)
        t3 = PriorityTask(medpri(), priority=0)
        await self.await_tasks()
        event.set()
        await asyncio.gather(t1, t2, t3)
        # medium priority task will run first
        assert finished == ["med", "low1", "low2"]
        assert priorities == [0, 1, 1]

        # now the same, but with the high priority task waitint thfor the lock that
        # "low2" holds.  "low2" is awaiting al lock held by "low1".  priority propagates
        # from 'high' to lock1 to low1 to lock2 to low2.
        event.clear()
        finished = []
        priorities = []
        # test without the high priority task
        t1 = PriorityTask(lowpri1(), priority=1)
        t2 = PriorityTask(lowpri2(), priority=1)
        t3 = PriorityTask(medpri(), priority=0)
        t4 = PriorityTask(highpri(), priority=-1)
        await self.await_tasks()
        event.set()
        await asyncio.gather(t1, t2, t3, t4)
        # low priority task now runs first (inherits priority of the high pri task)
        assert finished == ["low1", "low2", "high", "med"]
        assert priorities == [-1, -1, -1, 0]
