import asyncio
import gc
import sys

import pytest
from anyio import sleep

from asynkit import BoundMonitor, GeneratorObject, Monitor, OOBData

PYPY = sys.implementation.name == "pypy"

pytestmark = pytest.mark.anyio


# Most tests here are just testing coroutine behaviour.
# some need to explicitly start tasks
@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestMonitor:
    async def test_monitor(self):
        """
        Test basic monitor functionality
        """

        async def helper(m):
            back = await m.oob("foo")
            await sleep(0)
            back = await m.oob(back + "foo")
            await sleep(0)
            return back + "foo"

        m = Monitor()
        c = helper(m)
        with pytest.raises(OOBData) as data:
            await m.aawait(c)
        assert data.value.data == "foo"
        with pytest.raises(OOBData) as data:
            await m.aawait(c, "hoo")
        assert data.value.data == "hoofoo"
        back = await m.aawait(c, "how")
        assert back == "howfoo"

    async def test_bound_monitor_await(self):
        """
        Test basic BoundMonitor object
        """

        async def helper(m):
            back = await m.oob("foo")
            await sleep(0)
            back = await m.oob(str(back) + "foo")
            await sleep(0)
            return str(back) + "foo"

        m = Monitor()
        b = m(helper(m))
        with pytest.raises(OOBData) as data:
            await b
        assert data.value.data == "foo"
        with pytest.raises(OOBData) as data:
            await b
        assert data.value.data == "Nonefoo"
        back = await b
        assert back == "Nonefoo"

        # create the BoundMonitor directly
        b = BoundMonitor(m, helper(m))
        with pytest.raises(OOBData) as data:
            await b
        assert data.value.data == "foo"
        with pytest.raises(OOBData) as data:
            await b
        assert data.value.data == "Nonefoo"
        back = await b
        assert back == "Nonefoo"

    async def test_bound_monitor_aawait(self):
        """
        Test basic BoundMonitor object
        """

        async def helper(m):
            back = await m.oob("foo")
            await sleep(0)
            back = await m.oob(str(back) + "foo")
            await sleep(0)
            return str(back) + "foo"

        m = Monitor()
        b = m(helper(m))
        with pytest.raises(OOBData) as data:
            await b.aawait()
        assert data.value.data == "foo"
        with pytest.raises(OOBData) as data:
            await b.aawait()
        assert data.value.data == "Nonefoo"
        back = await b.aawait("hello")
        assert back == "hellofoo"

    async def test_bound_monitor_athrow(self):
        """
        Test basic BoundMonitor object
        """

        async def helper(m):
            back = await m.oob("foo")
            await sleep(0)
            back = await m.oob(str(back) + "foo")
            await sleep(0)
            return str(back) + "foo"

        m = Monitor()
        b = m(helper(m))
        with pytest.raises(OOBData) as data:
            await b.aawait()
        assert data.value.data == "foo"
        with pytest.raises(OOBData) as data:
            await b.aawait()
        assert data.value.data == "Nonefoo"
        with pytest.raises(EOFError):
            await b.athrow(EOFError())

    async def test_bound_monitor_aclose(self):
        """
        Test closing a BoundMonitor object
        """

        finished = False

        async def helper(m):
            nonlocal finished
            try:
                await m.oob("foo")
            finally:
                finished = True

        m = Monitor()
        a = m(helper(m))
        with pytest.raises(OOBData):
            await a
        assert not finished
        await a.aclose()
        assert finished

    async def test_throw(self):
        """
        Assert that throwing an error into the coroutine after the first OOB
        value works.
        """

        async def helper(m):
            with pytest.raises(EOFError):
                await m.oob("foo")
            return "bar"

        m = Monitor()
        c = helper(m)
        with pytest.raises(OOBData) as oob:
            await m.aawait(c)
        assert oob.value.data == "foo"
        assert await m.athrow(c, EOFError()) == "bar"

    async def test_throw_new(self):
        """
        Assert that throwing an error into the un-run coroutine works
        """

        async def helper(m):
            assert False
            return m

        m = Monitor()
        c = helper(m)
        with pytest.raises(EOFError):
            await m.athrow(c, EOFError())

    async def test_monitor_detached(self):
        """
        Test that we get an error if no one is listening
        """

        async def helper(m):
            back = await m.oob(1)
            assert back is None
            await sleep(0)
            back = await m.oob(2)
            assert back is None

        m = Monitor()
        c = helper(m)
        with pytest.raises(RuntimeError) as err:
            await c
        assert err.match(r"not active")

    async def test_monitor_re_enter(self):
        """
        Verify that we get an error if trying to re-enter the monitor
        """

        async def helper(m, final=0):
            if final:
                return
            c = helper(m, final=1)
            with pytest.raises(RuntimeError) as err:
                await m.aawait(c)
            assert err.match(r"cannot be re-entered")
            await c  # to avoid warnings, must await all coroutines
            return 3

        m = Monitor()
        c = helper(m)
        t = await m.aawait(c, None)
        assert t == 3

    async def test_monitor_raise_oob(self):
        """
        Verify that we get an error if raising OOB error out of monitor
        """

        async def helper(m):
            raise OOBData("foo")

        m = Monitor()
        c = helper(m)
        with pytest.raises(RuntimeError) as err:
            await m.aawait(c, None)
        assert err.match("raised OOBData")

    async def test_monitor_close(self):
        """
        Test low-level close() handling of our coroutine, for coverage
        """

        async def helper(m):
            await sleep(0)

        m = Monitor()
        c = helper(m)
        cc = m.aawait(c, None)
        cc.send(None)
        cc.close()

    async def test_monitor_throw(self):
        """
        Test low-level throw() handling of our coroutine, for coverage
        """

        async def helper(m):
            await sleep(0)

        m = Monitor()
        c = helper(m)
        cc = m.aawait(c, None)
        cc.send(None)
        with pytest.raises(EOFError):
            cc.throw(EOFError())
        cc.close()

    async def test_monitor_throw2(self):
        """
        Test low-level throw() handling of our coroutine, for coverage
        """

        async def helper(m):
            try:
                await sleep(0)
            except EOFError:
                return 1

        m = Monitor()
        c = helper(m)
        cc = m.aawait(c, None)
        cc.send(None)
        with pytest.raises(StopIteration) as err:
            cc.throw(EOFError())
        assert err.value.value == 1
        cc.close()

    async def test_monitor_aclose(self):
        """
        Test aclose of a coroutine suspended with oob()
        """
        finished = False

        async def helper(m):
            nonlocal finished
            try:
                await m.oob()
            finally:
                finished = True

        m = Monitor()
        c = helper(m)
        try:
            await m.aawait(c)
        except OOBData:
            pass
        assert not finished
        await m.aclose(c)
        assert finished

    async def test_monitor_aclose_finished(self):
        """
        Test aclose of a coroutine that has finished
        """

        async def helper(m):
            pass

        m = Monitor()
        c = helper(m)
        await m.aawait(c)
        await m.aclose(c)

    async def test_monitor_aclosed_new(self):
        """
        Test aclose of a coroutine that has not been started
        """

        async def helper(m):
            pass

        m = Monitor()
        c = helper(m)
        await m.aclose(c)

    async def test_monitor_aclose_ignore(self):
        """
        test aclose of couritine which ignores
        GeneratorExit and continues to send oob
        """

        async def helper(m):
            try:
                await m.oob()
            except GeneratorExit:
                await m.oob()

        m = Monitor()
        b = m(helper(m))
        with pytest.raises(OOBData):
            await b

        with pytest.raises(RuntimeError) as err:
            await b.aclose()
        assert "ignored GeneratorExit" in str(err)

    async def test_start(self):
        """
        Test starting a coroutine
        """

        started = False

        async def helper(m):
            nonlocal started
            started = True
            await m.oob("foo")
            return 1

        m = Monitor()
        b = m(helper(m))
        assert not started
        assert await b.start() == "foo"
        assert started
        await b.aclose()

    async def test_failed_start(self):
        """
        Test starting a coroutine which fails
        """

        async def helper(m):
            return 1

        m = Monitor()
        b = m(helper(m))
        with pytest.raises(RuntimeError) as err:
            await b.start()
            assert err.match("did not await")

    async def test_try_await(self):
        """
        Test try_await
        """

        async def helper(m):
            assert await m.oob() == 1
            assert await m.oob() == 2
            return 3

        m = Monitor()
        b = m(helper(m))
        assert await b.try_await() is None
        sentinel = object()
        assert await b.try_await(1, sentinel) is sentinel
        assert await b.try_await(2, "foo") == 3


async def top(g):
    v = await bottom(g, 10)
    await sleep(0)
    return await bottom(g, 20, v)


async def bottom(g, i, v=None):
    v = await g.ayield(i + 1 + (v or 0))
    await sleep(0)
    v = await g.ayield(i + 2 + (v or 0))
    await sleep(0)
    v = await g.ayield(i + 3 + (v or 0))
    await sleep(0)
    return v


async def topfail(g):
    v = await bottomfail(g, 10)
    await sleep(0)
    return await bottomfail(g, 20, v)


async def bottomfail(g, i, v=None):
    v = await g.ayield(i + 1 + (v or 0))
    await sleep(0)
    raise ZeroDivisionError()
    v = await g.ayield(i + 2 + (v or 0))
    await sleep(0)
    v = await g.ayield(i + 3 + (v or 0))
    await sleep(0)
    return v


async def standard():
    v = 0
    for i in [11, 12, 13, 21, 22, 23]:
        v = yield i + (v or 0)


async def standardfail():
    yield 11
    raise ZeroDivisionError()
    v = 0
    for i in [12, 13, 21, 22, 23]:
        v = yield i + (v or 0)


async def assert_exhausted(g):
    with pytest.raises(StopAsyncIteration):
        r = await g.asend(None)
    with pytest.raises(StopAsyncIteration):
        r = await g.__anext__()
    # but throw just works for cpython
    if not PYPY:
        # pypy athrow raises the thrown error on
        # exhausted generators
        r = await g.athrow(EOFError)
        assert r is None


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def normalgen(request):
    if request.param == "std":
        return standard()
    else:
        g = GeneratorObject()
        return g(top(g))


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def failgen(request):
    if request.param == "std":
        return standardfail()
    else:
        g = GeneratorObject()
        return g(topfail(g))


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def catchgen1(request):
    if request.param == "std":

        async def gen():
            try:
                yield 1
            except EOFError:
                yield 2

        return gen()
    else:
        g = GeneratorObject()

        async def gen():
            try:
                await g.ayield(1)
            except EOFError:
                await g.ayield(2)

        return g(gen())


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def catchgen2(request):
    if request.param == "std":

        async def gen():
            try:
                yield 1
            except EOFError:
                pass

        return gen()
    else:
        g = GeneratorObject()

        async def gen():
            try:
                await g.ayield(1)
            except EOFError:
                pass

        return g(gen())


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def closegen1(request):
    if request.param == "std":

        async def gen():
            try:
                yield 1
            except GeneratorExit:
                yield 2
                raise

        return gen()
    else:
        g = GeneratorObject()

        async def gen():
            try:
                await g.ayield(1)
            except GeneratorExit:
                await g.ayield(2)
                raise

        return g(gen())


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def closegen2(request):
    if request.param == "std":

        async def gen():
            try:
                for i in range(10):
                    yield i
            except GeneratorExit:
                pass

        return gen()
    else:
        g = GeneratorObject()

        async def gen():
            try:
                for i in range(10):
                    await g.ayield(i)
            except GeneratorExit:
                pass

        return g(gen())


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def gen479(request):
    if request.param == "std":

        async def gen(err):
            for i in range(2):
                try:
                    yield i
                except (EOFError, GeneratorExit):
                    pass
                raise err()

        return gen
    else:
        g = GeneratorObject()

        async def gen(err):
            for i in range(2):
                try:
                    await g.ayield(i)
                except (EOFError, GeneratorExit):
                    pass
                raise err()

        return lambda e: g(gen(e))


class TestGenerator:
    async def test_generator_none(self):
        "create a generator but don't iterate"

        async def foo():
            pass

        coro = foo()
        # create and destroy that GeneratorIterator
        GeneratorObject()(coro)
        await coro  # to avoid warnings

    async def test_generator_no_firstiter(self):
        "create a generator but don't iterate"

        async def foo():
            pass

        i = GeneratorObject()(foo())
        old = sys.get_asyncgen_hooks()
        sys.set_asyncgen_hooks(None, None)
        try:
            assert [e async for e in i] == []
        finally:
            sys.set_asyncgen_hooks(*old)

    async def test_generator_iter(self, normalgen):
        g = normalgen
        results = [f async for f in g]
        assert results == [11, 12, 13, 21, 22, 23]

    async def test_generator_send(self, normalgen):
        g = normalgen
        r = await g.asend(None)
        assert r == 11
        r = await g.asend(0)
        assert r == 12
        r = await g.asend(100)
        assert r == 113

    async def test_send_to_new(self, normalgen):
        # test send to new generator
        g = normalgen
        with pytest.raises(TypeError):
            await g.asend("foo")
        # but it should be iterable
        assert await g.__anext__() == 11

    async def test_send_exhausted(self, normalgen):
        # test exhausted generator
        g = normalgen
        [f async for f in g]
        # generator should now be exhausted
        await assert_exhausted(g)

    async def test_throw(self, normalgen):
        # test exhaustion after throw
        g = normalgen
        with pytest.raises(ZeroDivisionError):
            await g.athrow(ZeroDivisionError)
        await assert_exhausted(g)

    async def test_throw_catch1(self, catchgen1):
        # test exhaustion after throw
        g = catchgen1
        n = await g.__anext__()
        assert n == 1
        n = await g.athrow(EOFError())
        assert n == 2

    async def test_throw_catch2(self, catchgen2):
        # test exhaustion after throw
        g = catchgen2
        n = await g.__anext__()
        assert n == 1
        with pytest.raises(StopAsyncIteration):
            n = await g.athrow(EOFError())

    async def test_throw_live(self, normalgen):
        # test exhaustion after throw while live
        g = normalgen
        await g.__anext__()
        with pytest.raises(ZeroDivisionError):
            await g.athrow(ZeroDivisionError)
        await assert_exhausted(g)

    async def test_fail(self, failgen):
        # test generator which throws an error
        g = failgen
        with pytest.raises(ZeroDivisionError):
            [f async for f in g]
        await assert_exhausted(g)

    async def test_close_on_exhausted(self, normalgen):
        g = normalgen
        [f async for f in g]
        n = await g.aclose()
        assert n is None

    async def test_close_on_failed(self, failgen):
        g = failgen
        with pytest.raises(ZeroDivisionError):
            [f async for f in g]
        n = await g.aclose()
        assert n is None

    async def test_close_on_active(self, normalgen):
        g = normalgen
        n = await g.__anext__()
        assert n == 11
        n = await g.aclose()
        assert n is None
        with pytest.raises(StopAsyncIteration):
            await g.__anext__()

    async def test_close_twice_on_active(self, normalgen):
        g = normalgen
        n = await g.__anext__()
        assert n == 11
        n = await g.aclose()
        assert n is None
        await g.aclose()
        with pytest.raises(StopAsyncIteration):
            await g.__anext__()

    async def test_close_yield(self, closegen1):
        g = closegen1
        n = await g.__anext__()
        assert n == 1
        with pytest.raises(RuntimeError) as err:
            await g.aclose()
        assert "ignored GeneratorExit" in str(err)
        # generator is still active and will continue now
        with pytest.raises(GeneratorExit):
            await g.__anext__()

    async def test_close_exit(self, closegen2):
        g = closegen2
        n = await g.__anext__()
        assert n == 0
        await g.aclose()
        # and again
        await g.aclose()
        # generator is clos
        with pytest.raises(StopAsyncIteration):
            await g.__anext__()

    async def test_throw_generatorexit(self, normalgen):
        g = normalgen
        n = await g.__anext__()
        assert n == 11
        with pytest.raises(GeneratorExit):
            n = await g.athrow(GeneratorExit)
            await g.__anext__()

    async def test_pep_479(self, gen479):
        for et in (StopIteration, StopAsyncIteration):
            g = gen479(et)
            n = await g.__anext__()
            assert n == 0
            with pytest.raises(RuntimeError) as err:
                await g.__anext__()
            assert isinstance(err.value.__cause__, et)
            assert err.match(r"(async generator|coroutine) raised " + et.__name__)

            g = gen479(et)
            await g.__anext__()
            with pytest.raises(RuntimeError) as err:
                await g.athrow(EOFError())
            assert isinstance(err.value.__cause__, et)
            assert err.match(r"(async generator|coroutine) raised " + et.__name__)

            g = gen479(et)
            await g.__anext__()
            with pytest.raises(RuntimeError) as err:
                await g.aclose()
            assert isinstance(err.value.__cause__, et)
            assert err.match(r"(async generator|coroutine) raised " + et.__name__)

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    @pytest.mark.parametrize("gentype", ["std", "oob"], ids=["async gen", "Generator"])
    async def test_issue_74956(self, gentype, anyio_backend):
        # simultanous use of generator by different coroutines is not
        # allowed.
        # https://github.com/python/cpython/issues/74956

        if PYPY:
            pytest.skip("pypy does not have this fix")

        if gentype == "std":

            async def consumer():
                while True:
                    await sleep(0)
                    if (yield) is None:
                        break

        else:

            async def gf(g):
                while True:
                    await sleep(0)
                    if await g.ayield(None) is None:
                        break

            def consumer():
                g = GeneratorObject()
                return g(gf(g))

        for op, args in [("asend", ["A"]), ("athrow", [EOFError]), ("aclose", [])]:
            agenerator = consumer()
            await agenerator.asend(None)  # start it
            # fa will hit sleep and then fb will run
            fa = asyncio.create_task(agenerator.asend("A"))
            coro = getattr(agenerator, op)(*args)
            fb = asyncio.create_task(coro)
            await fa
            with pytest.raises(RuntimeError) as err:
                await fb
            assert err.match("already running")
            with pytest.raises(StopAsyncIteration):
                await agenerator.asend(None)  # close it

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    @pytest.mark.parametrize("gentype", ["std", "oob"], ids=["async gen", "Generator"])
    async def test_loop_cleanup(self, gentype, anyio_backend):
        closed = False
        if gentype == "std":

            async def generator():
                nonlocal closed
                for i in range(10):
                    try:
                        yield i
                    except GeneratorExit:
                        closed = True
                        raise

        else:

            async def genfunc(go):
                nonlocal closed
                for i in range(10):
                    try:
                        await go.ayield(i)
                    except GeneratorExit:
                        closed = True
                        raise

            def generator():
                go = GeneratorObject()
                return go(genfunc(go))

        # Test that cleanup occurs by GC
        g = generator()
        async for i in g:
            break
        assert i == 0
        assert not closed
        g = None
        gc.collect()  # needed, e.g. for PyPy
        await sleep(0.01)
        assert closed

        # test that cleanup occurs with explicit gen shutdown
        closed = False
        g = generator()
        async for i in g:
            break
        assert i == 0
        assert not closed
        await asyncio.get_running_loop().shutdown_asyncgens()
        assert closed

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    @pytest.mark.parametrize("gentype", ["std", "oob"], ids=["async gen", "Generator"])
    async def test_ag_running(self, gentype, anyio_backend):
        """
        Verify that as_running transitions correctly in
        an async generator
        """
        state = 0

        if gentype == "std":
            if PYPY:
                pytest.skip("pypy does not implemente ag_running correctly")

            async def generator():
                nonlocal state
                state = 1
                await asyncio.sleep(0)
                state = 2
                value = yield "foo"
                state = value

        else:

            async def genfunc(go):
                nonlocal state
                state = 1
                await asyncio.sleep(0)
                state = 2
                value = await go.ayield("foo")
                state = value

            def generator():
                go = GeneratorObject()
                return go(genfunc(go))

        a = generator()
        coro = a.asend(None)
        assert state == 0
        coro.send(None)
        assert state == 1
        assert a.ag_running is True
        try:
            coro.send(None)
        except StopIteration as v:
            assert v.value == "foo"
        assert state == 2
        assert a.ag_running is False

        # finish it
        coro = a.asend("bar")
        pytest.raises(StopAsyncIteration, coro.send, None)
        assert a.ag_running is False
        assert state == "bar"
