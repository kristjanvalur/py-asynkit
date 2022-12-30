import asyncio

import pytest

from asynkit.susp import Generator, Monitor


async def test_monitor():
    async def helper(m):
        back = await m.oob("foo")
        await asyncio.sleep(0)
        back = await m.oob(back + "foo")
        await asyncio.sleep(0)
        return back + "foo"

    m = Monitor()
    is_oob, back = await m.init(helper(m)).oob_await(None)
    assert is_oob
    assert back == "foo"
    is_oob, back = await m.oob_await("hoo")
    assert is_oob
    assert back == "hoofoo"
    is_oob, back = await m.oob_await("how")
    assert not is_oob
    assert back == "howfoo"


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
        g = Generator()
        return g.init(top(g))


@pytest.fixture(params=["std", "oob"], ids=["async gen", "Generator"])
def failgen(request):
    if request.param == "std":
        return standardfail()
    else:
        g = Generator()
        return g.init(topfail(g))


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
        g = Generator()

        async def gen():
            try:
                await g.ayield(1)
            except EOFError:
                await g.ayield(2)

        return g.init(gen())


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
        g = Generator()

        async def gen():
            try:
                await g.ayield(1)
            except EOFError:
                pass

        return g.init(gen())


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
        g = Generator()

        async def gen():
            try:
                await g.ayield(1)
            except GeneratorExit:
                await g.ayield(2)
                raise

        return g.init(gen())


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
        g = Generator()

        async def gen():
            try:
                for i in range(10):
                    await g.ayield(i)
            except GeneratorExit:
                pass

        return g.init(gen())


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
        g = Generator()

        async def gen(err):
            for i in range(2):
                try:
                    await g.ayield(i)
                except (EOFError, GeneratorExit):
                    pass
                raise err()

        return lambda e: g.init(gen(e))


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
