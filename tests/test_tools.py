import asyncio
import random
from collections import deque
from contextlib import closing

import pytest

import asynkit.tools
from asynkit.compat import PY_311
from asynkit.tools import PriorityQueue

from .conftest import SchedulingEventLoopPolicy, make_loop_factory

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend(request):
    policy = SchedulingEventLoopPolicy(request)
    return ("asyncio", {"loop_factory": make_loop_factory(policy)})


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

    def __lt__(self, other):
        return self.priority < other.priority


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
                queue.add(o.priority, o)

            assert len(queue) == 3
            assert queue.popitem() == (1, obj1)
            assert queue.popitem() == (2, obj2)
            assert queue.pop() is obj3
            pytest.raises(IndexError, queue.pop)

    def test_peek(self):
        queue = PriorityQueue()

        obj1 = PriorityObject(1)
        obj2 = PriorityObject(2)
        obj3 = PriorityObject(3)

        for i in range(5):
            obj = [obj1, obj2, obj3]
            random.shuffle(obj)
            for o in obj:
                queue.add(o.priority, o)

            assert len(queue) == 3
            assert queue.peekitem() == (1, obj1)
            assert queue.popitem() == (1, obj1)
            assert queue.peek() == obj2
            assert queue.popitem() == (2, obj2)
            assert queue.pop() is obj3
            pytest.raises(IndexError, queue.pop)
            pytest.raises(IndexError, queue.peek)

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
                queue.add(o.priority, o)

            obj = [obj1a, obj2a, obj3a]
            random.shuffle(obj)
            for o in obj:
                queue.add(o.priority, o)

            assert len(queue) == 6
            assert queue.popitem() == (1, obj1)
            assert queue.popitem() == (1, obj1a)
            assert queue.popitem() == (2, obj2)
            assert queue.popitem() == (2, obj2a)
            assert queue.popitem() == (3, obj3)
            assert queue.popitem() == (3, obj3a)
            pytest.raises(IndexError, queue.pop)

    def test_priority_iter(self):
        """Verify that iteration returns items in priority order"""
        queue = PriorityQueue()

        objs = [PriorityObject(i) for i in range(50)]

        for i in range(2):
            assert len(queue) == 0
            obj = list(objs)
            random.shuffle(obj)
            for o in obj:
                queue.add(o.priority, o)

            itered = list(queue)
            popped = [queue.popitem() for i in range(len(queue))]
            # these are not same order, queue was internally not fully sorted
            assert itered != popped

            assert not queue
            for o in obj:
                queue.add(o.priority, o)
            queue.sort()
            itered2 = list(queue.items())
            assert itered2 == popped
            queue.clear()

    def test_find(self):
        """Verify that we can find objects in the queue"""
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
                queue.add(o.priority, o)

            def getkey(obj):
                return lambda k: k is obj

            assert queue.find(getkey(obj1)) == (1, obj1)
            assert queue.find(getkey(obj2)) == (2, obj2)
            assert queue.find(getkey(obj3), remove=True) == (3, obj3)
            assert queue.find(lambda k: False) is None

            assert queue.find(getkey(obj3), remove=True) is None

            itered = list(queue.sorted().items())
            pris = [o.priority for (pri, o) in itered]
            expected = [1, 1, 2, 2, 3, 4, 4]
            assert pris == expected
            assert queue
            # empty the queye by removing objects in random order
            random.shuffle(itered)
            for pri, obj in itered:
                assert queue.find(getkey(obj), remove=True) == (obj.priority, obj)
                pris = [o.priority for (pri, o) in queue.sorted().items()]
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
                queue.add(o.priority, o)
            for o in obj:
                queue.add(o.priority, PriorityObject(o.priority))

            def getkey(obj):
                return lambda k: k is obj

            objs = list(queue.sorted())
            assert objs[4] is obj3

            queue.reschedule(getkey(obj3), 7)
            objs = list(queue.sorted())
            assert objs[-1] is obj3

            found = queue.reschedule(getkey(obj3), -1)
            assert found == obj3
            objs = list(queue.sorted())
            assert objs[0] is obj3

            queue.reschedule(getkey(obj3), 3)
            objs = list(queue.sorted())
            # don't define where it goes in the new priority
            assert obj3 in (objs[4], objs[5])
            pris = [o.priority for (pri, o) in queue.sorted().items()]
            assert pris == [1, 1, 2, 2, 3, 3, 4, 4]

            # reschedule to same priority
            queue.reschedule(getkey(obj3), 3)

            # pop first value and try to reschedule a popped value
            obj = queue.pop()
            found = queue.reschedule(getkey(obj), 3)
            assert found is None

    def test_remove(self):
        objs = [PriorityObject(random.random()) for i in range(50)]

        queue = PriorityQueue()
        for obj in objs:
            queue.add(obj.priority, obj)

        with pytest.raises(ValueError):
            queue.remove(PriorityObject(0))

        # remove the objects one by one and verify that the rest of the
        # objects pop out correctly
        for i, obj in enumerate(objs):
            queue.remove(obj)
            c = queue.copy()
            popped = [c.pop() for _ in range(len(c))]
            assert popped == sorted(objs[i + 1 :], key=priority_key)
        assert not queue

    def test_in(self):
        objs = [PriorityObject(random.random()) for i in range(10)]

        queue = PriorityQueue()
        for obj in objs:
            queue.add(obj.priority, obj)

        for obj in objs:
            assert obj in queue

        assert PriorityObject(0) not in queue

    def test_ordered(self):
        objs = [PriorityObject(random.random()) for i in range(50)]
        queue = PriorityQueue()
        assert len(list(queue.ordered())) == 0
        for obj in objs:
            queue.add(obj.priority, obj)

        q1 = queue.copy()
        for j in range(10, 60, 7):
            q2 = queue.copy()

            itered = []
            with closing(q1.ordered()) as o:
                for i in o:
                    itered.append(i)
                    if len(itered) == j:
                        break

            popped = []
            for _ in range(j):
                if not q2:
                    break
                popped.append(q2.pop())

            assert itered == popped

    def test_ordereditems(self):
        objs = [PriorityObject(random.random()) for i in range(50)]
        queue = PriorityQueue()
        assert len(list(queue.ordereditems())) == 0
        for obj in objs:
            queue.add(obj.priority, obj)

        q1 = queue.copy()
        for j in range(10, 60, 7):
            q2 = queue.copy()

            itered = []
            with closing(q1.ordereditems()) as o:
                for i in o:
                    itered.append(i)
                    if len(itered) == j:
                        break

            popped = []
            for _ in range(j):
                if not q2:
                    break
                popped.append(q2.popitem())

            assert itered == popped

    def test_refresh(self):
        objs = [PriorityObject(random.random()) for i in range(50)]
        queue = PriorityQueue()
        for obj in objs:
            queue.add(obj.priority, obj)

        q1 = queue.copy()
        q2 = queue.copy()

        q1._pq[0], q1._pq[-1] = q1._pq[-1], q1._pq[0]
        q1.refresh()

        assert list(q1.ordereditems()) == list(q2.ordereditems())


class TestCancelling:
    async def test_future(self):
        f = asyncio.Future()
        assert not f.cancelled()
        with asynkit.tools.cancelling(f, "hello") as c:
            assert not c.cancelled()
        assert f.cancelled()
        with pytest.raises(asyncio.CancelledError) as e:
            await f
        assert e.value.args == ("hello",)

        f = asyncio.Future()
        with pytest.raises(ValueError):
            with asynkit.cancelling(f) as c:
                assert not c.cancelled()
                raise ValueError
        assert f.cancelled()

        # it is ok to exit cancelling block with a finished future
        f = asyncio.Future()
        with asynkit.tools.cancelling(f) as c:
            assert not c.cancelled()
            f.set_result(None)
        assert f.result() is None
        assert not f.cancelled()

    async def test_task(self):
        async def coro():
            await asyncio.sleep(0.1)

        # task is cancelled if cancelling block is exited
        # without awaiting the task
        t = asyncio.create_task(coro())
        assert not t.cancelled()
        with asynkit.tools.cancelling(t, "hello") as c:
            assert not c.cancelled()
        with pytest.raises(asyncio.CancelledError) as e:
            await t
        if PY_311:
            assert e.match("hello")
        assert t.cancelled()

        # task is cancelled if an exception is raised
        t = asyncio.create_task(coro())
        with pytest.raises(ValueError):
            with asynkit.cancelling(t) as c:
                assert not c.cancelled()
                raise ValueError
        with pytest.raises(asyncio.CancelledError):
            await t
        assert t.cancelled()

        # it is ok to exit cancelling block with a finished task
        t = asyncio.create_task(coro())
        with asynkit.tools.cancelling(t) as c:
            assert not c.cancelled()
            await t
        assert not t.cancelled()
