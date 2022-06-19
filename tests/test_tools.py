import asyncio
import contextlib
from collections import deque

import asynkit.tools
import pytest


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
        self.c = getattr(self, "c", [])
        self.l = getattr(self, "l", [])
        try:
            self.c.append(val)
            self.l.append("+" + val)
            yield val
        finally:
            assert self.c[-1] is val
            del self.c[-1]
            self.l.append("-" + val)

    @contextlib.asynccontextmanager
    async def acx(self, val):
        self.c = getattr(self, "c", [])
        self.l = getattr(self, "l", [])
        try:
            self.c.append(val)
            self.l.append("+" + val)
            yield val
        finally:
            assert self.c[-1] is val
            del self.c[-1]
            self.l.append("-" + val)

    @pytest.mark.parametrize("vals", [[], ["a"], ["a", "b", "c"]])
    def test_nested(self, vals):
        vals = ["a", "b", "c"]
        ctxs = [self.cx(c) for c in vals]
        with asynkit.nested(*ctxs) as v:
            assert v == tuple(vals)

    @pytest.mark.parametrize("vals", [[], ["a"], ["a", "b", "c", "d", "e"]])
    def test_nested_jit(self, vals):
        def get_ctxt(m):
            def ctxt():
                return self.cx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        with asynkit.nest, asynkit.nested_jit(*ctxs) as v:
            assert v == tuple(vals)

    @pytest.mark.parametrize(
        "vals", [[], ["a"], ["a", "b", "c", "d", "e"], ["ax", "b", "cx", "d", "ex"]]
    )
    async def test_anested(self, vals):
        def get_ctxt(m):
            if "x" in m:
                return self.cx(m)
            return self.acx(m)

        ctxs = [get_ctxt(c) for c in vals]
        async with asynkit.anested(*ctxs) as v:
            assert v == tuple(vals)

    @pytest.mark.parametrize(
        "vals", [[], ["a"], ["a", "b", "c", "d", "e"], ["ax", "b", "cx", "d", "ex"]]
    )
    async def test_anested_jit(self, vals):
        def get_ctxt(m):
            def ctxt():
                if "x" in m:
                    return self.cx(m)
                return self.acx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        async with asynkit.nest, asynkit.anested_jit(*ctxs) as v:
            assert v == tuple(vals)

    def test_nested_deprecation(self):
        """
        Test that this versionof nested doesn't have the problem causing "nested" to be deprectted from the standard library:

        "Secondly, if the __enter__() method of one of the inner context managers raises an exception that is caught and suppressed by the __exit__()
        method of one of the outer context managers, this construct will raise RuntimeError rather than skipping the body of the with statement."

        It is impossible to skip the body of a with statement with a single context manager, but possible with two.  So, we implement
        a ContextManagerExit exception and catch it at the top with a special `nest` context manager.
        """

        @contextlib.contextmanager
        def outer():
            try:
                yield
            except ZeroDivisionError:
                pass

        @contextlib.contextmanager
        def inner():
            1 / 0
            yield

        with pytest.raises(asynkit.ContextManagerExit):
            with asynkit.nested(outer(), inner()):
                assert False
        with asynkit.nest, asynkit.nested(outer(), inner()):
            assert False

    async def test_anested_deprecation(self):
        @contextlib.contextmanager
        def outer():
            try:
                yield
            except ZeroDivisionError:
                pass

        @contextlib.contextmanager
        def inner():
            1 / 0
            yield

        with pytest.raises(asynkit.ContextManagerExit):
            async with asynkit.anested(outer(), inner()):
                assert False
        async with asynkit.nest, asynkit.anested(outer(), inner()):
            assert False

    @pytest.mark.parametrize(
        "vals", [[], ["a"], ["a", "b", "c", "d", "e"], ["ax", "b", "cx", "d", "ex"]]
    )
    async def test_anested_jit_execution(self, vals):
        """
        Test that the context managers are instantiated just before they are entered
        """
        self.l = []

        def get_ctxt(m):
            def ctxt():
                self.l.append("*" + m)  # ctxt manager is instantiated
                if "x" in m:
                    return self.cx(m)
                return self.acx(m)

            return ctxt

        ctxs = [get_ctxt(c) for c in vals]
        async with asynkit.nest, asynkit.anested_jit(*ctxs) as v:
            assert v == tuple(vals)

        expect = []
        for c in vals:
            expect.append("*" + c)  # context manager instantiated
            expect.append("+" + c)  # context manager entered
        for c in reversed(vals):
            expect.append("-" + c)  # context manager exited

        assert self.l == expect


def test_skip_unless():
    with asynkit.nest, asynkit.skip_unless(False):
        assert False  # never run

    ran = False

    with asynkit.nest, asynkit.skip_unless(True) as flag:
        assert flag is True
        ran = True

    assert ran


async def test_as_asyncmgr():
    async with asynkit.nest, asynkit.as_asyncmgr(asynkit.skip_unless(False)):
        assert False  # never run
