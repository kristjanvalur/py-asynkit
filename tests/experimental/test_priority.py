import asyncio
import random
from unittest.mock import Mock

import pytest

from asynkit.experimental.priority import FancyPriorityQueue, PriorityLock, PriorityTask

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_priority_lock():
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


class TestPriorityQueue:
    def test_append(self):
        queue = FancyPriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            assert len(queue) == 3
            assert queue.popleft() is obj1
            assert queue.popleft() is obj2
            assert queue.popleft() is obj3
            pytest.raises(IndexError, queue.popleft)

    def test_append_pri(self):
        """Test that we can specify priority when appending"""
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
        queue = FancyPriorityQueue(priority_key)

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
