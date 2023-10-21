import asyncio
import random
from unittest.mock import Mock

import pytest

from asynkit.experimental.priority import PriorityLock, PriorityQueue, PriorityTask

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
        queue = PriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o)

            assert len(queue) == 3
            assert queue.pop() is obj1
            assert queue.pop() is obj2
            assert queue.pop() is obj3
            pytest.raises(IndexError, queue.pop)

    def test_append_pri(self):
        """Test that we can specify priority when appending"""
        queue = PriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = list(enumerate(reversed([obj1, obj2, obj3])))
            random.shuffle(obj)
            for i, o in obj:
                queue.append_pri(o, i)

            assert len(queue) == 3
            assert queue.pop() is obj3
            assert queue.pop() is obj2
            assert queue.pop() is obj1
            pytest.raises(IndexError, queue.pop)

    def test_fifo(self):
        """Verify that same priority gets FIFO ordering"""
        queue = PriorityQueue(priority_key)

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
            assert queue.pop() is obj1
            assert queue.pop() is obj1a
            assert queue.pop() is obj2
            assert queue.pop() is obj2a
            assert queue.pop() is obj3
            assert queue.pop() is obj3a
            pytest.raises(IndexError, queue.pop)

    def test_priority_iter(self):
        """Verify that iteration returns items in priority order"""
        queue = PriorityQueue(priority_key)

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
            popped = [queue.pop() for i in range(3)]
            assert itered == popped

    def test_insert_pos(self):
        """Verify that we can insert at a specific position"""
        queue = PriorityQueue(priority_key)

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
        queue = PriorityQueue(priority_key)

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)
        obj4 = PriorityObject(4)
        obj5 = PriorityObject(5)

        for i in range(2):
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
        queue = PriorityQueue(priority_key)

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
            assert queue.find(getkey(obj2), priority_hint=2) is obj2
            assert queue.find(getkey(obj2), priority_hint=1) is obj2
            assert queue.find(getkey(obj2), priority_hint=7) is obj2
            assert queue.find(getkey(obj3), priority_hint=3, remove=True) is obj3
            with pytest.raises(ValueError):
                queue.find(getkey(obj3), remove=True)

            itered = list(queue)
            pris = [o.priority for o in itered]
            queue.clear()
            expected = [1, 1, 2, 2, 3, 4, 4]
            assert pris == expected
