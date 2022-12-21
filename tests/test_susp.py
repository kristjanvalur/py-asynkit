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
    is_oob, back = await m.init(helper(m)).oob_await()
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


@pytest.mark.parametrize("gen_type", ["std", "oob"], ids=["async gen", "Generator"])
class TestGenerator:
    async def test_generator_iter(self, gen_type):
        g = self.normal(gen_type)
        results = [f async for f in g]
        assert results == [11, 12, 13, 21, 22, 23]

    async def test_generator_send(self, gen_type):
        g = self.normal(gen_type)
        r = await g.asend(None)
        assert r == 11
        r = await g.asend(0)
        assert r == 12
        r = await g.asend(100)
        assert r == 113

    def normal(self, gen_type):
        if gen_type == "std":
            return standard()
        g = Generator()
        return g.init(top(g))

    def fail(self, gen_type):
        if gen_type == "std":
            return standardfail()
        g = Generator()
        return g.init(topfail(g))

    async def test_send_to_new(self, gen_type):
        # test send to new generator
        g = self.normal(gen_type)
        with pytest.raises(TypeError):
            await g.asend("foo")
        # but it should be iterable
        assert await g.__anext__() == 11

    async def test_send_exhausted(self, gen_type):
        # test exhausted generator
        g = self.normal(gen_type)
        [f async for f in g]
        # generator should now be exhausted
        await assert_exhausted(g)

    async def test_throw(self, gen_type):
        # test exhaustion after throw
        g = self.normal(gen_type)
        with pytest.raises(ZeroDivisionError):
            await g.athrow(ZeroDivisionError)
        await assert_exhausted(g)

    async def test_throw_live(self, gen_type):
        # test exhaustion after throw while live
        g = self.normal(gen_type)
        await g.__anext__()
        with pytest.raises(ZeroDivisionError):
            await g.athrow(ZeroDivisionError)
        await assert_exhausted(g)

    async def test_fail(self, gen_type):
        # test generator which throws an error
        g = self.fail(gen_type)
        with pytest.raises(ZeroDivisionError):
            [f async for f in g]
        await assert_exhausted(g)
