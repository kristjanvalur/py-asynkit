import asyncio
import sys

import pytest

from asynkit.susp import GeneratorObject, Monitor


class TestMonitor:
    async def test_monitor(self):
        """
        Test basic monitor functionality
        """

        async def helper(m):
            back = await m.oob("foo")
            await asyncio.sleep(0)
            back = await m.oob(back + "foo")
            await asyncio.sleep(0)
            return back + "foo"

        m = Monitor()
        c = helper(m)
        is_oob, back = await m.oob_await(c, None)
        assert is_oob
        assert back == "foo"
        is_oob, back = await m.oob_await(c, "hoo")
        assert is_oob
        assert back == "hoofoo"
        is_oob, back = await m.oob_await(c, "how")
        assert not is_oob
        assert back == "howfoo"

    async def test_throw(self):
        async def helper(m):
            return m

        m = Monitor()
        c = helper(m)
        with pytest.raises(EOFError):
            await m.oob_throw(c, EOFError())

    async def test_monitor_detached(self):
        """
        Test that we get an error if no one is listening
        """

        async def helper(m):
            back = await m.oob(1)
            assert back is None
            await asyncio.sleep(0)
            back = await m.oob(2)
            assert back is None

        m = Monitor()
        c = helper(m)
        with pytest.raises(RuntimeError) as err:
            await c
        assert err.match(r"not active")

    async def test_monitor_re_enter(self):
        """
        Test that the closest monitor listener receives
        the messages
        """

        async def helper(m):
            with pytest.raises(RuntimeError) as err:
                await m.aawait(helper(m))
            assert err.match(r"cannot be re-entered")
            return 3

        m = Monitor()
        c = helper(m)
        t = await m.aawait(c, None)
        assert t == (False, 3)


async def top(g):
    v = await bottom(g, 10)
    await asyncio.sleep(0)
    return await bottom(g, 20, v)


async def bottom(g, i, v=None):
    v = await g.ayield(i + 1 + (v or 0))
    await asyncio.sleep(0)
    v = await g.ayield(i + 2 + (v or 0))
    await asyncio.sleep(0)
    v = await g.ayield(i + 3 + (v or 0))
    await asyncio.sleep(0)
    return v


async def topfail(g):
    v = await bottomfail(g, 10)
    await asyncio.sleep(0)
    return await bottomfail(g, 20, v)


async def bottomfail(g, i, v=None):
    v = await g.ayield(i + 1 + (v or 0))
    await asyncio.sleep(0)
    raise ZeroDivisionError()
    v = await g.ayield(i + 2 + (v or 0))
    await asyncio.sleep(0)
    v = await g.ayield(i + 3 + (v or 0))
    await asyncio.sleep(0)
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
    # but throw just works (weird)
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

    @pytest.mark.parametrize("gentype", ["std", "oob"], ids=["async gen", "Generator"])
    async def test_issue_74956(self, gentype):
        # simultanous use of generator by different coroutines is not
        # allowed.
        # https://github.com/python/cpython/issues/74956
        # skipped for std generator in 3.7 version
        if gentype == "std":
            if sys.version_info < (3, 8):
                pytest.skip("broken prior to 3.8")

            async def consumer():
                while True:
                    await asyncio.sleep(0)
                    yield
                    # print('received', message)

        else:

            async def gf(g):
                while True:
                    await asyncio.sleep(0)
                    await g.ayield(None)
                    # print('received', message)

            def consumer():
                g = GeneratorObject()
                return g(gf(g))

        agenerator = consumer()
        await agenerator.asend(None)
        fa = asyncio.create_task(agenerator.asend("A"))
        fb = asyncio.create_task(agenerator.asend("B"))
        await fa
        with pytest.raises(RuntimeError) as err:
            await fb
        assert err.match("already running")

        agenerator = consumer()
        await agenerator.asend(None)
        fa = asyncio.create_task(agenerator.asend("A"))
        fb = asyncio.create_task(agenerator.athrow(EOFError))
        await fa
        with pytest.raises(RuntimeError) as err:
            await fb
        assert err.match("already running")

        await agenerator.asend(None)
        fa = asyncio.create_task(agenerator.asend("A"))
        fb = asyncio.create_task(agenerator.aclose())
        await fa
        with pytest.raises(RuntimeError) as err:
            await fb
        assert err.match("already running")

    @pytest.mark.parametrize("gentype", ["std", "oob"], ids=["async gen", "Generator"])
    async def test_loop_cleanup(self, gentype):

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
        await asyncio.sleep(0.01)
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
