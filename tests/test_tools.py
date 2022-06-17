import asyncio
from collections import deque
import pytest
import contextlib
import asynkit.tools


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


async def test_task_from_handle():
    async def foo():
        pass

    task = asyncio.create_task(foo())

    item = asyncio.get_running_loop().ready_pop()
    asyncio.get_running_loop().ready_append(item)
    assert isinstance(item, asyncio.Handle)
    task2 = asynkit.tools.task_from_handle(item)
    assert task2 is task

    assert asynkit.tools.task_from_handle(foo) is None


async def test_task_from_handle_notask():
    # test that a bogus member callback results in a None
    class Foo:
        def bar(self):
            pass

    h = asyncio.Handle(Foo().bar, (), asyncio.get_running_loop())
    assert asynkit.tools.task_from_handle(h) is None


class TestNested:
    @contextlib.contextmanager
    def cx(self, val):
        try:
            if not hasattr(self, "c"):
                self.c = []
            self.c.append(val)
            yield val
        finally:
            assert self.c[-1] is val
            del self.c[-1]

    @contextlib.asynccontextmanager
    async def acx(self, val):
        try:
            if not hasattr(self, "c"):
                self.c = []
            self.c.append(val)
            yield val
        finally:
            assert self.c[-1] is val
            del self.c[-1]

    def test_nested_1(self):
        with asynkit.nested(self.cx("a")) as v:
            assert v == ("a",)

    def test_nested_3(self):
        vals = ["a", "b", "c"]
        ctxs = [self.cx(c) for c in vals]
        with asynkit.nested(*ctxs) as v:
            assert v == tuple(vals)

    def test_nested_delayed_1(self):
        vals = ["a"]

        def get_ctxt(m):
            def ctxt():
                return self.cx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        with asynkit.nested_jit(*ctxs) as v:
            assert v == tuple(vals)

    def test_nested_delayed_5(self):
        vals = ["a", "b", "c", "d", "e"]

        def get_ctxt(m):
            def ctxt():
                return self.cx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        with asynkit.nested_jit(*ctxs) as v:
            assert v == tuple(vals)

    async def test_anested_delayed_5(self):
        vals = ["a", "b", "c", "d", "e"]

        def get_ctxt(m):
            def ctxt():
                return self.acx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        async with asynkit.anested_jit(*ctxs) as v:
            assert v == tuple(vals)

    async def test_anested_delayed_mixed_5(self):
        vals = ["a", "b", "cx", "d", "e"]

        def get_ctxt(m):
            def ctxt():
                if "x" in m:
                    return self.cx(m)
                return self.acx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        async with asynkit.anested_jit(*ctxs) as v:
            assert v == tuple(vals)
