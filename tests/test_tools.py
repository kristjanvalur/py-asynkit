import random
from collections import deque

import pytest

import asynkit.tools
from asynkit.tools import PriorityQueue

from .conftest import SchedulingEventLoopPolicy

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend(request):
    return ("asyncio", {"policy": SchedulingEventLoopPolicy(request)})


def test_deque_pop():
    """
    Test that our pop for a deque has same semantics as that for a list
    """

    for i in range(-7, 7):
        ref = list(range(5))
        deq = deque(range(5))

        try:
            refpop = ref.pop(i)
            ok = True
        except IndexError:
            ok = False

        if ok:
            pop = asynkit.tools.deque_pop(deq, i)
            assert pop == refpop
            assert list(deq) == ref
        else:
            with pytest.raises(IndexError):
                asynkit.tools.deque_pop(deq, i)


class PriorityObject:
    def __init__(self, priority):
        self.priority = priority

    def __repr__(self):
        return f"PriorityObject({self.priority})"


def priority_key(obj):
    return obj.priority


class TestPriorityQueue:
    def test_append(self):
        queue = PriorityQueue()

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o.priority, o)

            assert len(queue) == 3
            assert queue.popleft() == (1, obj1)
            assert queue.popleft() == (2, obj2)
            assert queue.popleft() == (3, obj3)
            pytest.raises(IndexError, queue.popleft)

    def test_fifo(self):
        """Verify that same priority gets FIFO ordering"""
        queue = PriorityQueue()

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
                queue.append(o.priority, o)

            obj = [obj1a, obj2a, obj3a]
            random.shuffle(obj)
            for o in obj:
                queue.append(o.priority, o)

            assert len(queue) == 6
            assert queue.popleft() == (1, obj1)
            assert queue.popleft() == (1, obj1a)
            assert queue.popleft() == (2, obj2)
            assert queue.popleft() == (2, obj2a)
            assert queue.popleft() == (3, obj3)
            assert queue.popleft() == (3, obj3a)
            pytest.raises(IndexError, queue.popleft)

    def test_priority_iter(self):
        """Verify that iteration returns items in priority order"""
        queue = PriorityQueue()

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            assert len(queue) == 0
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.append(o.priority, o)

            itered = list(queue)
            popped = [queue.popleft() for i in range(3)]
            assert itered == popped

    def test_find(self):
        """Verify that iteration returns items in priority order"""
        queue = PriorityQueue()

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
                queue.append(o.priority, o)

            def getkey(obj):
                return lambda k: k is obj

            assert queue.find(getkey(obj1)) == (1, obj1)
            assert queue.find(getkey(obj2)) == (2, obj2)
            assert queue.find(getkey(obj3), remove=True) == (3, obj3)
            assert queue.find(lambda k: False) is None

            assert queue.find(getkey(obj3), remove=True) is None

            itered = list(queue)
            pris = [o.priority for (pri, o) in itered]
            expected = [1, 1, 2, 2, 3, 4, 4]
            assert pris == expected
            assert queue
            # empty the queye by removing objects in random order
            random.shuffle(itered)
            for pri, obj in itered:
                assert queue.find(getkey(obj), remove=True) == (obj.priority, obj)
                pris = [o.priority for (pri, o) in queue]
                assert pris == sorted(pris)
            assert len(queue) == 0
            assert not queue

    def test_reschedule(self):
        """Verify that iteration returns items in priority order"""
        queue = PriorityQueue()

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
                queue.append(o.priority, o)
            for o in obj:
                queue.append(o.priority, PriorityObject(o.priority))

            def getkey(obj):
                return lambda k: k is obj

            objs = list(queue)
            assert objs[4][1] is obj3

            queue.reschedule(getkey(obj3), 7)
            objs = list(queue)
            assert objs[-1][1] is obj3

            found = queue.reschedule(getkey(obj3), -1)
            assert found == obj3
            objs = list(queue)
            assert objs[0][1] is obj3

            queue.reschedule(getkey(obj3), 3)
            objs = list(queue)
            # don't define where it goes in the new priority
            assert obj3 in (objs[4][1], objs[5][1])
            pris = [o.priority for (pri, o) in objs]
            assert pris == [1, 1, 2, 2, 3, 3, 4, 4]

            # reschedule to same priority
            queue.reschedule(getkey(obj3), 3)

            # pop first value and try to reschedule a popped value
            pri, obj = queue.popleft()
            found = queue.reschedule(getkey(obj), 3)
            assert found is None
