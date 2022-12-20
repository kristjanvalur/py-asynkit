
from asynkit.susp import Suspender
import asyncio


async def test_suspend():

    async def helper(s):
        back = await s.suspend("foo")
        await asyncio.sleep(0)
        back = await s.suspend(back + "foo")
        await asyncio.sleep(0)
        return back+"foo"

    s = Suspender()
    finished, back = await s.call(helper(s))
    assert not finished
    assert back == "foo"
    finished, back = await s.resume("hoo")
    assert not finished
    assert back == "hoofoo"
    finished, back = await s.resume("how")
    assert finished
    assert back == "howfoo"
    
    
